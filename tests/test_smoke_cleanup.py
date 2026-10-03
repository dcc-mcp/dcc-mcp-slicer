"""Independent fixtures load exact public-head AST; no production source changes."""

import ast
import json
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]


def load_function(filename, name, namespace):
    tree = ast.parse((REPO / "scripts" / filename).read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {name, "wait_for_owned_listeners"}]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(REPO / "scripts" / filename), "exec"), namespace)
    return namespace[name]


def make_fixture(faults=(), initial_status="PASS"):
    faults = set(faults)
    calls = []
    writes = []
    exits = []
    state = {"done": True, "status": initial_status, "traceback": "primary-client-failure"}

    def maybe_fail(phase):
        calls.append(phase)
        if phase in faults:
            raise RuntimeError("injected-" + phase)

    class Output:
        def __truediv__(self, name):
            return self

        def write_text(self, text, **kwargs):
            maybe_fail("result_write")
            writes.append(json.loads(text))

    class Server:
        running = True
        host_dispatcher = SimpleNamespace(is_shutdown=False)
        mcp_url = "http://127.0.0.1:1234/mcp"

        def stop(self):
            maybe_fail("server_stop")
            self.running = False
            self.host_dispatcher.is_shutdown = True

        @property
        def is_running(self):
            maybe_fail("server_state")
            return self.running

    class App:
        @property
        def applicationVersion(self):
            maybe_fail("host_metadata")
            return "5.10.0"

        def exit(self, code):
            calls.append("exit")
            exits.append(code)

    def listeners():
        maybe_fail("listeners")
        return ["127.0.0.1:1234"] if "lingering_listener" in faults else []

    def output(*args, **kwargs):
        maybe_fail("result_print")

    server = Server()
    namespace = dict(
        STATE=state,
        traceback=traceback,
        json=json,
        finish_timer=SimpleNamespace(stop=lambda: maybe_fail("timer_stop")),
        client_thread=None,
        server=server,
        listeners=listeners,
        BASELINE_LISTENERS=[],
        slicer=SimpleNamespace(app=App()),
        MAIN_THREAD=1234,
        OUT=Output(),
        print=output,
    )
    clock = [0.0]
    namespace["time"] = SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    return SimpleNamespace(ns=namespace, calls=calls, writes=writes, exits=exits, server=server, clock=clock)


@pytest.mark.parametrize(
    "phase",
    [
        None,
        "timer_stop",
        "server_stop",
        "server_state",
        "listeners",
        "lingering_listener",
        "host_metadata",
        "result_write",
        "result_print",
    ],
)
def test_changed_finish_exits_and_preserves_primary(phase):
    f = make_fixture([phase] if phase else [])
    load_function("live_smoke.py", "finish_if_done", f.ns)()
    assert f.exits == [1 if phase else 0]
    assert f.ns["STATE"]["traceback"] == "primary-client-failure"
    assert "server_stop" in f.calls
    if phase:
        assert f.ns["STATE"]["status"] == "FAIL"
        assert f.ns["STATE"]["finish_tracebacks"]
    assert f.calls[-1] == "exit"


def test_changed_finish_combined_cleanup_and_reporting_failures():
    f = make_fixture(["timer_stop", "server_stop", "result_write", "result_print"])
    load_function("live_smoke.py", "finish_if_done", f.ns)()
    assert f.exits == [1]
    assert f.ns["STATE"]["traceback"] == "primary-client-failure"
    assert set(f.ns["STATE"]["finish_tracebacks"]) == {
        "timer_stop",
        "server_stop",
        "shutdown_verification",
        "result_write",
        "result_print",
    }


def test_changed_finish_preserves_client_failure():
    f = make_fixture(initial_status="FAIL")
    load_function("live_smoke.py", "finish_if_done", f.ns)()
    assert f.exits == [1]
    assert f.writes[0]["traceback"] == "primary-client-failure"


def test_changed_finish_reentry_is_noop():
    f = make_fixture()
    finish = load_function("live_smoke.py", "finish_if_done", f.ns)
    finish()
    finish()
    assert f.exits == [0]
    assert f.calls.count("server_stop") == 1


def test_changed_finish_waits_for_worker():
    f = make_fixture()
    f.ns["STATE"]["done"] = False
    load_function("live_smoke.py", "finish_if_done", f.ns)()
    assert not f.calls


def test_candidate_waits_for_native_listener_drain():
    f = make_fixture()
    clock = [0.0]
    f.ns["time"] = SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    def draining_listeners():
        return ["127.0.0.1:1234"] if clock[0] < 0.03 else []

    f.ns["listeners"] = draining_listeners
    load_function("live_smoke.py", "finish_if_done", f.ns)()
    assert f.exits == [0]
    assert not f.ns["STATE"]["remaining_new_listeners"]
    assert 0.03 <= clock[0] < 2.0


def test_candidate_does_not_hide_persistent_listener():
    f = make_fixture(["lingering_listener"])
    clock = [0.0]
    f.ns["time"] = SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    load_function("live_smoke.py", "finish_if_done", f.ns)()
    assert f.exits == [1]
    assert f.ns["STATE"]["remaining_new_listeners"] == ["127.0.0.1:1234"]
    assert 2.0 <= clock[0] < 2.02


def make_graphical_fixture(faults=()):
    f = make_fixture(faults)
    f.ns.update(
        client=SimpleNamespace(poll=lambda: 1, returncode=1),
        start=0.0,
        baseline=set(),
        restarted=None,
        timer=f.ns["finish_timer"],
        log=SimpleNamespace(close=lambda: None),
        dcc_mcp_slicer=SimpleNamespace(start_server=lambda **kw: make_fixture().server),
    )
    return f


def test_existing_graphical_timer_exception_must_exit_and_stop():
    f = make_graphical_fixture(["timer_stop"])
    try:
        load_function("graphical_acceptance.py", "finish", f.ns)()
    except RuntimeError:
        pass
    assert f.exits == [1] and "server_stop" in f.calls


def test_existing_graphical_result_write_exception_must_exit():
    f = make_graphical_fixture(["result_write"])
    try:
        load_function("graphical_acceptance.py", "finish", f.ns)()
    except RuntimeError:
        pass
    assert f.exits == [1]


def test_existing_live_startup_report_failure_must_exit_and_stop():
    f = make_fixture(["result_write"])

    def fail_timer():
        raise RuntimeError("primary-timer-startup-failure")

    f.server.start = lambda: SimpleNamespace(mcp_url=lambda: f.server.mcp_url)
    f.ns.update(
        start_server=lambda **kw: f.server, qt=SimpleNamespace(QTimer=fail_timer), listeners=lambda: ["127.0.0.1:1234"]
    )
    load_function("live_smoke.py", "finish_if_done", f.ns)
    tree = ast.parse((REPO / "scripts/live_smoke.py").read_text())
    final_try = tree.body[-1]
    assert isinstance(final_try, ast.Try)
    try:
        exec(compile(ast.Module(body=[final_try], type_ignores=[]), "live_smoke.py", "exec"), f.ns)
    except RuntimeError:
        pass
    assert f.exits == [1] and "server_stop" in f.calls


@pytest.mark.parametrize("drains", [True, False])
def test_graphical_native_drain_has_fixed_deadline(drains):
    f = make_graphical_fixture()
    load_function("graphical_acceptance.py", "finish", f.ns)
    f.ns["listeners"] = lambda: ["127.0.0.1:1234"] if not drains or f.clock[0] < 0.03 else []
    remaining = f.ns["wait_for_owned_listeners"]()
    assert remaining == ([] if drains else ["127.0.0.1:1234"])
    assert 0.03 <= f.clock[0] < 2.02
    if not drains:
        assert f.clock[0] >= 2.0


def test_graphical_probe_error_fails_closed_and_exits():
    f = make_graphical_fixture(["listeners"])
    load_function("graphical_acceptance.py", "finish", f.ns)(force=True)
    assert f.exits == [1]
    assert "shutdown_verification" in f.ns["STATE"]["finish_tracebacks"]
    assert f.ns["STATE"]["traceback"] == "primary-client-failure"


def test_graphical_startup_failure_kills_and_reaps_owned_client():
    f = make_graphical_fixture()
    running = [True]

    def kill():
        f.calls.append("client_kill")
        running[0] = False

    def wait(timeout):
        assert timeout == 10
        f.calls.append("client_wait")

    f.ns["client"] = SimpleNamespace(poll=lambda: None if running[0] else -9, kill=kill, wait=wait)
    f.ns["STATE"]["status"] = "FAIL"
    load_function("graphical_acceptance.py", "finish", f.ns)(force=True)
    assert f.exits == [1]
    assert f.calls.count("client_kill") == f.calls.count("client_wait") == 1
    assert not f.server.running


def test_graphical_log_close_failure_still_exits_and_preserves_primary():
    f = make_graphical_fixture()

    def fail_close():
        raise OSError("injected-log-close")

    f.ns["log"] = SimpleNamespace(close=fail_close)
    f.ns["STATE"]["status"] = "FAIL"
    load_function("graphical_acceptance.py", "finish", f.ns)(force=True)
    assert f.exits == [1]
    assert f.ns["STATE"]["traceback"] == "primary-client-failure"
    assert "log_close" in f.ns["STATE"]["finish_tracebacks"]


def test_graphical_visual_failure_stops_owned_server(monkeypatch):
    import builtins

    f = make_graphical_fixture()
    f.ns["client"] = SimpleNamespace(poll=lambda: 0, returncode=0)
    original_import = builtins.__import__

    def broken_visual(name, *args, **kwargs):
        if name == "numpy":
            raise RuntimeError("injected-visual-readback")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_visual)
    load_function("graphical_acceptance.py", "finish", f.ns)()
    assert not f.server.running and f.exits == [1]
    assert "injected-visual-readback" in f.ns["STATE"]["finish_tracebacks"]["acceptance"]


@pytest.mark.parametrize("alive", [True, False])
def test_live_client_thread_join_is_bounded(alive):
    f = make_fixture()
    joins = []
    f.ns["client_thread"] = SimpleNamespace(
        ident=42, join=lambda timeout: joins.append(timeout), is_alive=lambda: alive
    )
    load_function("live_smoke.py", "finish_if_done", f.ns)()
    assert joins == [2.0]
    assert f.exits == [1 if alive else 0]
    assert ("client_join" in f.ns["STATE"].get("finish_tracebacks", {})) is alive


@pytest.mark.parametrize("script", ["live_smoke.py", "graphical_acceptance.py"])
@pytest.mark.parametrize("fault", ["missing_table", "denied_table", "denied_fd", "disappeared_fd"])
def test_linux_listener_inventory_fails_closed(script, fault):
    import socket

    class FakePath:
        def __init__(self, path):
            self.path = path

        def iterdir(self):
            return ["/proc/self/fd/1"]

        def exists(self):
            return fault != "missing_table"

        def read_text(self):
            if fault == "missing_table":
                raise FileNotFoundError(self.path)
            if fault == "denied_table":
                raise PermissionError(self.path)
            return "header\n"

    def readlink(path):
        if fault == "denied_fd":
            raise PermissionError(path)
        if fault == "disappeared_fd":
            raise FileNotFoundError(path)
        return "socket:[123]"

    namespace = {"Path": FakePath, "os": SimpleNamespace(readlink=readlink), "socket": socket}
    probe = load_function(script, "listeners", namespace)
    if fault == "disappeared_fd":
        assert probe() == []
    else:
        with pytest.raises(OSError):
            probe()


@pytest.mark.parametrize("script", ["live_smoke.py", "graphical_acceptance.py"])
def test_startup_listener_probe_failure_still_exits(script):
    f = make_graphical_fixture(["listeners"]) if script.startswith("graphical") else make_fixture(["listeners"])
    f.ns["server"] = None
    f.ns["finish_timer"] = None
    f.ns["timer"] = None
    f.ns["client"] = None
    f.ns["log"] = None
    load_function(script, "finish" if script.startswith("graphical") else "finish_if_done", f.ns)
    tree = ast.parse((REPO / "scripts" / script).read_text())
    startup = tree.body[-1]
    assert isinstance(startup, ast.Try)
    exec(compile(ast.Module(body=[startup], type_ignores=[]), script, "exec"), f.ns)
    assert f.exits == [1]
    assert "injected-listeners" in f.ns["STATE"]["traceback"]
    assert "server_stop" not in f.calls
