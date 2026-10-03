"""External official SDK client for a fresh synthetic Slicer acceptance process."""

import asyncio
import hashlib
import importlib.metadata
import json
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

import httpx
import jsonschema
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def acceptance(url, output):
    if urlparse(url).hostname != "127.0.0.1":
        raise ValueError("Acceptance connects only to its owned loopback host")
    state = {"sdk_version": importlib.metadata.version("mcp"), "transcript": []}
    schemas = {}
    async with httpx.AsyncClient(trust_env=False, timeout=150) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                state["initialize"] = (await session.initialize()).model_dump(mode="json")

                async def call(name, args=None):
                    raw = await session.call_tool(name, args or {})
                    if raw.isError and raw.structuredContent is None:
                        data = {"success": False, "isError": True, "message": raw.content[0].text}
                    else:
                        data = raw.structuredContent or json.loads(raw.content[0].text)
                    state["transcript"].append(
                        {"tool": name, "arguments": args or {}, "response": raw.model_dump(mode="json")}
                    )
                    (output / "sdk-transcript.json").write_text(json.dumps(state["transcript"], indent=2))
                    return data

                async def operation(tool_name, expect=True, **args):
                    data = await call(tool_name, args)
                    if not expect and (data.get("success") is False or data.get("isError")):
                        return data
                    jsonschema.validate(data, schemas[tool_name]["output_schema"])
                    if "job_id" in data:
                        deadline = time.monotonic() + 150
                        job_id = data["job_id"]
                        while time.monotonic() < deadline:
                            status = await call("jobs_get_status", {"job_id": job_id, "include_result": True})
                            if status.get("status") not in {"pending", "running"}:
                                break
                            await asyncio.sleep(0.05)
                        assert status["status"] == "completed", status
                        data = status["result"]
                        jsonschema.validate(data, schemas[tool_name]["output_schema"])
                    assert data["success"] is expect, data
                    if expect and tool_name != "capabilities":
                        assert data["context"]["execution_thread_id"] == data["context"]["main_thread_id"]
                    return data

                state["search"] = await call("search_skills", {"query": "synthetic slicer"})
                state["load"] = await call("load_skill", {"skill_name": "slicer-scene"})
                listed = []
                cursor = None
                while True:
                    page = await session.list_tools(cursor=cursor)
                    listed.extend(page.tools)
                    cursor = page.nextCursor
                    if not cursor:
                        break
                state["listed_tools"] = [tool.model_dump(mode="json") for tool in listed]
                described = await call("get_skill_info", {"skill_name": "slicer-scene"})
                schemas.update({tool["name"]: tool for tool in described["tools"]})
                assert len(schemas) == 12
                for tool in schemas.values():
                    assert tool["input_schema"]["additionalProperties"] is False
                    jsonschema.Draft202012Validator.check_schema(tool["output_schema"])
                state["capabilities"] = await operation("capabilities")
                assert (await operation("scene_info"))["context"]["count"] == 0
                sphere = (await operation("create_sphere", name="Synthetic SDK sphere", radius=14))["context"]["node"]
                volume = (await operation("create_phantom", size=64))["context"]["node"]
                state["toy_volume"] = await operation("create_volume", size=16)
                edited = await operation(
                    "edit_sphere", node_id=sphere["node_id"], expected_revision=sphere["revision"], radius=16
                )
                state["stale_rejected"] = await operation(
                    "edit_sphere", expect=False, node_id=sphere["node_id"], expected_revision=sphere["revision"]
                )
                assert "stale" in state["stale_rejected"]["message"]
                state["camera"] = await operation(
                    "configure_camera", node_id=sphere["node_id"], direction="anterior", zoom=1.2
                )
                state["slice"] = await operation(
                    "configure_slice", node_id=volume["node_id"], view="Red", orientation="axial"
                )
                state["png_3d"] = await operation(
                    "export_view", filename="sphere-view.png", view="3D", width=640, height=480
                )
                state["png_slice"] = await operation(
                    "export_view", filename="slice-view.png", view="Red", width=640, height=480
                )
                for key in ("png_3d", "png_slice"):
                    info = state[key]["context"]
                    assert info["scalar_range"][1] > info["scalar_range"][0], info
                    assert info["aspect_ratio_preserved"] is True
                    source_width, source_height = info["source_dimensions"][:2]
                    fitted_width, fitted_height = info["content_dimensions"]
                    assert abs(fitted_width / source_width - fitted_height / source_height) <= 1 / min(
                        source_width, source_height
                    )
                state["export_volume"] = await operation(
                    "export_node", node_id=volume["node_id"], filename="phantom.nrrd"
                )
                state["export_sphere"] = await operation(
                    "export_node",
                    node_id=sphere["node_id"],
                    filename="sphere.stl",
                    expected_revision=edited["context"]["node"]["revision"],
                )
                state["overwrite_rejected"] = await operation(
                    "export_node", expect=False, node_id=sphere["node_id"], filename="sphere.stl"
                )
                cancel_launch = await call("export_node", {"node_id": sphere["node_id"], "filename": "cancelled.stl"})
                jsonschema.validate(cancel_launch, schemas["export_node"]["output_schema"])
                job_id = cancel_launch["job_id"]
                deadline = time.monotonic() + 15
                while not (output / "cancel-staged.json").exists():
                    assert time.monotonic() < deadline, "Native staging did not reach cancellation barrier"
                    await asyncio.sleep(0.02)
                cancellation = await http.delete(url.rsplit("/mcp", 1)[0] + "/v1/jobs/" + job_id)
                assert cancellation.is_success, cancellation.text
                (output / "cancel-release").write_text("continue into the real cancellation checkpoint")
                while True:
                    cancelled = await call("jobs_get_status", {"job_id": job_id, "include_result": True})
                    if cancelled["status"] in {"cancelled", "interrupted"}:
                        break
                    assert time.monotonic() < deadline, cancelled
                    await asyncio.sleep(0.02)
                # This read traverses the same native lane after the cancelled callback.
                after_cancel = await operation("scene_info")
                assert after_cancel["context"]["count"] == 3
                assert (output / "cancel-callback-exited").exists()
                assert not (output / "cancelled.stl").exists()
                assert not list(output.glob(".dcc-mcp-export-*"))
                state["wire_cancellation"] = {
                    "job_id": job_id,
                    "terminal_status": cancelled["status"],
                    "http_status": cancellation.status_code,
                    "native_staging": json.loads((output / "cancel-staged.json").read_text()),
                    "same_native_lane_read_completed": True,
                    "final_file_absent": True,
                    "staging_removed": True,
                }
                state["oversize_rejected"] = await operation("create_volume", expect=False, size=129)
                state["unknown_node_rejected"] = await operation("edit_sphere", expect=False, node_id="missing")
                state["save"] = await operation("save_scene", filename="synthetic-scene.mrb")
                state["reopen"] = await operation("reopen_scene", filename="synthetic-scene.mrb")
                assert (await operation("scene_info"))["context"]["count"] == 6
                state["camera_after_reopen"] = await operation("configure_camera", node_id=sphere["node_id"])
                # Concurrent read calls must all observe a bounded consistent scene.
                concurrent = await asyncio.gather(*[operation("scene_info") for _ in range(8)])
                assert all(item["context"]["count"] == 6 for item in concurrent)
                state["concurrent_read_calls"] = len(concurrent)
                state["artifacts"] = {
                    path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in output.iterdir()
                    if path.is_file() and path.suffix in {".png", ".stl", ".nrrd", ".mrb"}
                }
                assert not list(output.glob(".dcc-mcp-*"))
                state["status"] = "PASS"
    return state


def main():
    url, directory = sys.argv[1:]
    output = Path(directory)
    try:
        state = asyncio.run(acceptance(url, output))
    except BaseException:
        state = {"status": "FAIL", "traceback": traceback.format_exc()}
    (output / "sdk-result.json").write_text(json.dumps(state, indent=2))
    return 0 if state["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
