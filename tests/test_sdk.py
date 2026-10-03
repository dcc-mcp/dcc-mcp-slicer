"""Official Python MCP SDK against a real Core listener, host-free metadata path."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import jsonschema
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from test_dispatcher import Timer

from dcc_mcp_slicer.dispatcher import SlicerDispatcher
from dcc_mcp_slicer.server import SlicerMcpServer


def test_official_sdk_schema_and_malformed_requests():
    server = SlicerMcpServer(
        host_version="5.10.0", dispatcher=SlicerDispatcher(qt_module=SimpleNamespace(QTimer=Timer))
    )
    server.start()

    async def run():
        async with httpx.AsyncClient(trust_env=False) as http:
            async with streamable_http_client(server.mcp_url, http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "dcc-mcp-slicer"
                    loaded = await session.call_tool("load_skill", {"skill_name": "slicer-scene"})
                    assert not loaded.isError
                    listed = []
                    cursor = None
                    while True:
                        page = await session.list_tools(cursor=cursor)
                        listed.extend(page.tools)
                        cursor = page.nextCursor
                        if not cursor:
                            break
                    assert len(listed) >= 12
                    described = await session.call_tool("get_skill_info", {"skill_name": "slicer-scene"})
                    info = described.structuredContent or json.loads(described.content[0].text)
                    capability = next(tool for tool in info["tools"] if tool["name"] == "capabilities")
                    advertised = next(tool for tool in listed if tool.name == "capabilities")
                    assert advertised.outputSchema == capability["output_schema"]
                    assert capability["input_schema"]["additionalProperties"] is False
                    result = await session.call_tool("capabilities", {})
                    data = result.structuredContent or json.loads(result.content[0].text)
                    jsonschema.validate(data, capability["output_schema"])
                    assert data["success"] is True
                    for name, arguments in [
                        ("capabilities", {"unexpected": True}),
                        ("create_volume", {"size": 129}),
                        ("create_volume", {"size": "64"}),
                        ("create_volume", {"name": "a" * 10000}),
                        ("export_view", {"filename": "../escape.png"}),
                    ]:
                        rejected = await session.call_tool(name, arguments)
                        if not rejected.isError:
                            data = rejected.structuredContent or json.loads(rejected.content[0].text)
                            if "job_id" in data:
                                for _ in range(100):
                                    status = await session.call_tool(
                                        "jobs_get_status", {"job_id": data["job_id"], "include_result": True}
                                    )
                                    status_data = status.structuredContent or json.loads(status.content[0].text)
                                    if status_data["status"] not in {"pending", "running"}:
                                        break
                                    await asyncio.sleep(0.01)
                                assert (
                                    status_data["status"] == "failed"
                                    or status_data.get("result", {}).get("success") is False
                                )
                            else:
                                assert data.get("success") is False, data
                    assert server.host_dispatcher.pending_count() == 0

    async def pumped():
        task = asyncio.create_task(run())
        while not task.done():
            server.host_dispatcher._tick()
            await asyncio.sleep(0.001)
        await task

    try:
        asyncio.run(pumped())
    finally:
        server.stop()
