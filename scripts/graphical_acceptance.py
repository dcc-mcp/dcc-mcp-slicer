"""Owned fresh graphical Slicer host; external SDK client, bounded deadline, clean exit.

Run only in a newly launched Slicer process with a new empty workspace. This script
never attaches to an existing session. See docs/validation.md for launch settings.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = os.environ["DCC_MCP_SLICER_TEST_SITE"]
sys.path.insert(0, SITE)
if os.environ.get("DCC_MCP_SLICER_TEST_INSTALLED") != "1":
    sys.path.insert(0, str(ROOT / "src"))

import qt  # noqa: E402
import slicer  # noqa: E402

import dcc_mcp_slicer  # noqa: E402

OUT = Path(os.environ["DCC_MCP_SLICER_WORKSPACE"])
OUT.mkdir(parents=True, exist_ok=True)
if any(OUT.iterdir()):
    raise RuntimeError("Acceptance requires a new empty output directory")
STATE = {
    "host_version": str(slicer.app.applicationVersion),
    "adapter_module_file": dcc_mcp_slicer.__file__,
    "python_version": sys.version,
    "host_pid": os.getpid(),
    "main_thread_id": threading.get_ident(),
}


def listeners():
    inodes = set()
    for fd in Path("/proc/self/fd").iterdir():
        try:
            link = os.readlink(fd)
        except OSError:
            continue
        if link.startswith("socket:["):
            inodes.add(link[8:-1])
    result = []
    for file in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in Path(file).read_text().splitlines()[1:]:
            parts = line.split()
            if parts[3] == "0A" and parts[9] in inodes:
                address, port = parts[1].split(":")
                if file.endswith("tcp"):
                    address = socket.inet_ntop(socket.AF_INET, bytes.fromhex(address)[::-1])
                result.append(address + ":" + str(int(port, 16)))
    return result


server = None
client = None
log = None
start = time.monotonic()
baseline = set(listeners())


def finish():
    if client.poll() is None and time.monotonic() - start < 300:
        return
    timer.stop()
    try:
        if client.poll() is None:
            client.kill()
            client.wait(timeout=10)
            STATE["deadline_exceeded"] = True
        STATE["client_exit"] = client.returncode
        if client.returncode == 0:
            # Synthetic test-specific visual regression: the known blue sphere
            # must remain circular after the viewport-to-canvas transform.
            import numpy as np
            import vtk
            from vtk.util.numpy_support import vtk_to_numpy

            reader = vtk.vtkPNGReader()
            reader.SetFileName(str(OUT / "sphere-view.png"))
            reader.Update()
            pixels = vtk_to_numpy(reader.GetOutput().GetPointData().GetScalars()).reshape(480, 640, 3)
            mask = (pixels[:, :, 2] > 20) & (pixels[:, :, 2] > pixels[:, :, 0] * 1.7)
            mask &= pixels[:, :, 1] > pixels[:, :, 0] * 1.7
            rows, columns = np.where(mask)
            assert len(rows) > 1000, "Synthetic sphere pixels missing"
            bounds = [int(columns.min()), int(rows.min()), int(columns.max()), int(rows.max())]
            ratio = (bounds[2] - bounds[0] + 1) / (bounds[3] - bounds[1] + 1)
            STATE["sphere_pixel_bounds"] = bounds
            STATE["sphere_pixel_aspect"] = float(ratio)
            assert abs(ratio - 1) < 0.03, "Rendered sphere was stretched"

        server.stop()
        server.stop()
        STATE["server_stopped"] = not server.is_running
        STATE["timer_stopped"] = server.host_dispatcher.is_shutdown
        STATE["listeners_after_stop"] = sorted(set(listeners()) - baseline)
        assert not STATE["listeners_after_stop"]
        # Restart explicitly uses a new server because closed pumps are terminal.
        restarted = dcc_mcp_slicer.start_server(port=0, gateway_port=0, enable_gateway_failover=False)
        STATE["restart_url"] = restarted.mcp_url
        assert restarted.is_running
        restarted.stop()
        STATE["listeners_after_restart_stop"] = sorted(set(listeners()) - baseline)
        assert not STATE["listeners_after_restart_stop"]
        STATE["status"] = "PASS" if client.returncode == 0 else "FAIL"
    except BaseException:
        STATE["status"] = "FAIL"
        STATE["traceback"] = traceback.format_exc()
    finally:
        log.close()
        (OUT / "host-result.json").write_text(json.dumps(STATE, indent=2))
        slicer.app.exit(0 if STATE["status"] == "PASS" else 1)


try:
    slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    slicer.util.mainWindow().resize(1200, 900)
    STATE["initial_storable_nodes"] = [
        {"id": node.GetID(), "class": node.GetClassName(), "saved": bool(node.GetSaveWithScene())}
        for node in (slicer.mrmlScene.GetNthNode(i) for i in range(slicer.mrmlScene.GetNumberOfNodes()))
        if node.IsA("vtkMRMLStorableNode")
    ]
    # Test-only pause after actual native STL staging. No product tool or raw-exec
    # interface is added, and in-progress native calls are never claimed preemptible.
    from dcc_mcp_slicer import operations as tested_operations

    original_publish = tested_operations.publish_new

    def controlled_publish(staged, destination):
        if destination.name != "cancelled.stl":
            return original_publish(staged, destination)
        assert staged.is_file() and staged.stat().st_size > 0
        (OUT / "cancel-staged.json").write_text(json.dumps({"native_bytes": staged.stat().st_size}))
        try:
            deadline = time.monotonic() + 15
            while not (OUT / "cancel-release").exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("Cancellation test barrier timed out")
                time.sleep(0.01)
            return original_publish(staged, destination)
        finally:
            (OUT / "cancel-callback-exited").write_text("callback exited")

    tested_operations.publish_new = controlled_publish
    server = dcc_mcp_slicer.start_server(port=0, gateway_port=0, enable_gateway_failover=False)
    STATE["mcp_url"] = server.mcp_url
    STATE["listeners_started"] = sorted(set(listeners()) - baseline)
    assert len(STATE["listeners_started"]) == 1
    assert STATE["listeners_started"][0].startswith("127.0.0.1:")
    (OUT / "ready.json").write_text(json.dumps(STATE, indent=2))
    log = (OUT / "sdk-client.log").open("w")
    client_env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH"):
        client_env.pop(name, None)
    client = subprocess.Popen(
        [
            os.environ["DCC_MCP_SLICER_SDK_PYTHON"],
            "-I",
            str(ROOT / "scripts/sdk_acceptance.py"),
            server.mcp_url,
            str(OUT),
        ],
        env=client_env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    timer = qt.QTimer()
    timer.setInterval(100)
    timer.connect("timeout()", finish)
    timer.start()
except BaseException:
    STATE["status"] = "FAIL"
    STATE["traceback"] = traceback.format_exc()
    if server is not None:
        server.stop()
    if log is not None:
        log.close()
    (OUT / "host-result.json").write_text(json.dumps(STATE, indent=2))
    slicer.app.exit(1)
