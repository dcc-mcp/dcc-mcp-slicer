"""Run with Slicer --no-main-window --python-script scripts/live_smoke.py.

Use a fresh process. No existing GUI state is accessed. Environment configuration
is documented in docs/validation.md. HTTP client runs on a worker; all scene
calls must report the host main thread. Generated artifacts stay in TEST_DIR.
"""

import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

# Test bootstrap only: production installs into the host interpreter.
if os.environ.get("DCC_MCP_SLICER_TEST_SITE"):
    sys.path.insert(0, os.environ["DCC_MCP_SLICER_TEST_SITE"])
if os.environ.get("DCC_MCP_SLICER_TEST_INSTALLED") != "1":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dcc_mcp_core
import qt
import slicer

import dcc_mcp_slicer
from dcc_mcp_slicer import start_server

OUT = Path(os.environ["DCC_MCP_SLICER_WORKSPACE"])
OUT.mkdir(parents=True, exist_ok=True)
STATE = {"adapter_module_file": dcc_mcp_slicer.__file__, "core_module_file": dcc_mcp_core.__file__}


class Client:
    def __init__(self, url):
        self.url = url
        self.session = None
        self.counter = 0
        self.call(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "slicer-live-smoke", "version": "0.1.0"},
            },
        )

    def call(self, method, params):
        self.counter += 1
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        body = {"jsonrpc": "2.0", "id": self.counter, "method": method, "params": params}
        request = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.headers.get("Mcp-Session-Id"):
                self.session = response.headers["Mcp-Session-Id"]
            result = json.loads(response.read())
        assert result.get("id") == self.counter, result
        assert "error" not in result, result
        return result["result"]

    def tool(self, name, arguments=None):
        raw = self.call("tools/call", {"name": name, "arguments": arguments or {}})
        result = raw.get("structuredContent")
        if result is None:
            try:
                result = json.loads(raw["content"][0]["text"])
            except (ValueError, KeyError):
                result = raw
        return result

    def operation(self, tool_name, expect_success=True, **arguments):
        result = self.tool("slicer_scene__" + tool_name, arguments)
        if result.get("status") in {"pending", "running"}:
            job_id = result["job_id"]
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                result = self.tool("jobs_get_status", {"job_id": job_id, "include_result": True})
                if result.get("status") not in {"pending", "running"}:
                    break
                time.sleep(0.05)
            assert result["status"] == "completed", result
            result = result["result"]
        if not expect_success:
            assert result.get("success") is False or result.get("isError") is True, result
            return result
        assert result.get("success"), result
        if tool_name != "capabilities":
            assert result["context"]["execution_thread_id"] == MAIN_THREAD, result
            assert result["context"]["main_thread_id"] == MAIN_THREAD, result
        return result


def run_client(url):
    try:
        client = Client(url)
        listing = client.call("tools/list", {})
        STATE["initial_tools"] = [tool["name"] for tool in listing["tools"]]
        STATE["search"] = client.tool("search_skills", {"query": "synthetic slicer"})
        STATE["load"] = client.tool("load_skill", {"skill_name": "slicer-scene"})
        STATE["loaded_tools"] = [tool["name"] for tool in client.call("tools/list", {})["tools"]]
        assert "slicer_scene__create_volume" in STATE["load"]["registered_tools"]
        STATE["capabilities"] = client.operation("capabilities")
        STATE["initial_scene"] = client.operation("scene_info")
        assert STATE["initial_scene"]["context"]["count"] == 0
        volume = client.operation("create_volume", name="Synthetic mathematical phantom", size=32)
        sphere = client.operation("create_sphere", name="Synthetic edited sphere", radius=10, resolution=32)
        STATE["phantom"] = client.operation("create_phantom", size=64)
        STATE["volume"] = volume
        STATE["sphere"] = sphere
        STATE["edited"] = client.operation("edit_sphere", node_id=sphere["context"]["node"]["node_id"], radius=14)
        STATE["volume_export"] = client.operation(
            "export_node", node_id=volume["context"]["node"]["node_id"], filename="phantom.nrrd"
        )
        STATE["model_export"] = client.operation(
            "export_node", node_id=sphere["context"]["node"]["node_id"], filename="sphere.stl"
        )
        STATE["negative_invalid_size"] = client.operation("create_volume", expect_success=False, size=999)
        STATE["negative_unknown_node"] = client.operation("edit_sphere", expect_success=False, node_id="missing")
        STATE["negative_overwrite"] = client.operation(
            "export_node", expect_success=False, node_id=volume["context"]["node"]["node_id"], filename="phantom.nrrd"
        )
        STATE["save"] = client.operation("save_scene", filename="synthetic-scene.mrb")
        STATE["reopen"] = client.operation("reopen_scene", filename="synthetic-scene.mrb")
        STATE["final_scene"] = client.operation("scene_info")
        assert STATE["final_scene"]["context"]["count"] == 6
        STATE["status"] = "PASS"
    except BaseException:
        STATE["status"] = "FAIL"
        STATE["traceback"] = traceback.format_exc()
    finally:
        STATE["done"] = True


def finish_if_done():
    if not STATE.get("done") or STATE.get("finishing"):
        return
    STATE["finishing"] = True

    def record_failure(phase):
        STATE["status"] = "FAIL"
        STATE.setdefault("finish_tracebacks", {})[phase] = traceback.format_exc()

    try:
        try:
            finish_timer.stop()
        except BaseException:
            record_failure("timer_stop")
        try:
            server.stop()
        except BaseException:
            record_failure("server_stop")
        try:
            STATE["server_stopped"] = not server.is_running
            STATE["remaining_new_listeners"] = sorted(list(set(listeners()) - set(BASELINE_LISTENERS)))
            assert STATE["server_stopped"], "Server is still running after shutdown"
            assert not STATE["remaining_new_listeners"], "New listeners remain after shutdown"
        except BaseException:
            record_failure("shutdown_verification")
        try:
            STATE["version"] = str(slicer.app.applicationVersion)
            STATE["main_thread_id"] = MAIN_THREAD
        except BaseException:
            record_failure("host_metadata")
        try:
            (OUT / "result.json").write_text(json.dumps(STATE, indent=2), encoding="utf-8")
        except BaseException:
            record_failure("result_write")
        try:
            print("SLICER_MCP_RESULT " + json.dumps(STATE), flush=True)
        except BaseException:
            record_failure("result_print")
            try:
                (OUT / "result.json").write_text(json.dumps(STATE, indent=2), encoding="utf-8")
            except BaseException:
                record_failure("result_write")
    finally:
        slicer.app.exit(0 if STATE.get("status") == "PASS" else 1)


def listeners():
    """Linux-only socket evidence; no assumptions from a configured URL."""
    inodes = set()
    for fd in Path("/proc/self/fd").iterdir():
        try:
            link = os.readlink(fd)
        except OSError:
            continue
        if link.startswith("socket:["):
            inodes.add(link[8:-1])
    result = []
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        if not Path(path).exists():
            continue
        for line in Path(path).read_text().splitlines()[1:]:
            parts = line.split()
            if parts[3] == "0A" and parts[9] in inodes:
                address, port = parts[1].split(":")
                if path.endswith("tcp"):
                    address = socket.inet_ntop(socket.AF_INET, bytes.fromhex(address)[::-1])
                result.append(address + ":" + str(int(port, 16)))
    return result


MAIN_THREAD = threading.get_ident()
BASELINE_LISTENERS = listeners()
try:
    server = start_server(
        port=0,
        gateway_port=0,
        enable_gateway_failover=False,
        enable_file_logging=False,
        enable_telemetry=False,
        enable_job_persistence=False,
        enable_checkpoint_persistence=False,
    )
    url = server.start().mcp_url()
    STATE["url"] = url
    STATE["new_listeners"] = sorted(list(set(listeners()) - set(BASELINE_LISTENERS)))
    assert STATE["new_listeners"] and all(address.startswith("127.0.0.1:") for address in STATE["new_listeners"])
    finish_timer = qt.QTimer()
    finish_timer.setInterval(50)
    finish_timer.connect("timeout()", finish_if_done)
    finish_timer.start()
    threading.Thread(target=run_client, args=(url,), daemon=True).start()
except BaseException:
    (OUT / "result.json").write_text(json.dumps({"status": "FAIL", "traceback": traceback.format_exc()}, indent=2))
    slicer.app.exit(1)
