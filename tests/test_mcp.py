"""Real Core HTTP lifecycle with a fake Qt timer; no Slicer dependency."""

import json
import urllib.request
from types import SimpleNamespace

from test_dispatcher import Timer

from dcc_mcp_slicer.dispatcher import SlicerDispatcher
from dcc_mcp_slicer.server import SlicerMcpServer


def test_mcp_discovery_load_metadata_call_and_unload():
    dispatch = SlicerDispatcher(qt_module=SimpleNamespace(QTimer=Timer))
    server = SlicerMcpServer(host_version="5.10.0", dispatcher=dispatch, enable_checkpoint_persistence=False)
    handle = server.start()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }

    def request(method, params):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        req = urllib.request.Request(handle.mcp_url(), data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.headers.get("Mcp-Session-Id"):
                headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
            result = json.loads(response.read())
        assert "error" not in result, result
        return result["result"]

    def tool(name, arguments):
        result = request("tools/call", {"name": name, "arguments": arguments})
        return result.get("structuredContent") or json.loads(result["content"][0]["text"])

    try:
        assert handle.mcp_url().startswith("http://127.0.0.1:")
        request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "adapter-test", "version": "1"},
            },
        )
        assert request("tools/list", {})["tools"]
        search = tool("search_skills", {"query": "slicer synthetic"})
        assert any(skill["name"] == "slicer-scene" for skill in search["skills"])
        load = tool("load_skill", {"skill_name": "slicer-scene"})
        assert "slicer_scene__capabilities" in load["registered_tools"]
        result = tool("slicer_scene__capabilities", {})
        assert result["success"] is True
        assert result["context"]["patient_data"] is False
        tool("unload_skill", {"skill_name": "slicer-scene"})
    finally:
        server.stop()
    assert not server.is_running
