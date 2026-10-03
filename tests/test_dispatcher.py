import threading
import time
from types import SimpleNamespace

import pytest
from dcc_mcp_core import HostExecutionBridge

from dcc_mcp_slicer.dispatcher import SlicerDispatcher, require_main_thread


class Timer:
    def setInterval(self, interval):
        self.interval = interval

    def connect(self, signal, callback):
        self.callback = callback

    def disconnect(self, signal, callback):
        self.callback = None

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


def dispatcher():
    return SlicerDispatcher(qt_module=SimpleNamespace(QTimer=Timer))


def test_main_routes_to_original_thread():
    dispatch = dispatcher()
    bridge = HostExecutionBridge(dispatcher=dispatch)
    bridge.resolve_host_dispatcher()
    result = []
    worker = threading.Thread(
        target=lambda: result.append(bridge.dispatch_callable(threading.get_ident, thread_affinity="main"))
    )
    worker.start()
    while worker.is_alive():
        dispatch._tick()
        time.sleep(0.001)
    worker.join()
    assert result == [threading.get_ident()]
    dispatch.close()


def test_pure_any_runs_on_caller():
    dispatch = dispatcher()
    result = []
    worker = threading.Thread(
        target=lambda: result.append(dispatch.dispatch_callable(threading.get_ident, affinity="any"))
    )
    worker.start()
    worker.join()
    assert result == [worker.ident]
    dispatch.close()


def test_timeout_cancels_queued_mutation():
    dispatch = dispatcher()
    changed = []
    result = []
    worker = threading.Thread(
        target=lambda: result.append(dispatch.dispatch_callable(lambda: changed.append(1), timeout_hint_secs=0.005))
    )
    worker.start()
    worker.join()
    assert result[0]["success"] is False
    assert isinstance(result[0]["error"], str)
    dispatch._tick()
    assert not changed
    dispatch.close()


def test_closed_dispatcher_rejects_main_work():
    dispatch = dispatcher()
    dispatch.close()
    result = dispatch.dispatch_callable(lambda: 1)
    assert result["success"] is False
    assert result["error"] == "Interrupted"


def test_worker_cannot_pump_or_touch_host():
    errors = []

    def worker():
        with pytest.raises(RuntimeError) as error:
            require_main_thread()
        errors.append(str(error.value))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert errors


def test_closed_dispatcher_rejects_any_work_without_late_effects():
    dispatch = dispatcher()
    dispatch.close()
    changed = []
    result = dispatch.dispatch_callable(lambda: changed.append(1), affinity="any")
    assert result["error"] == "Interrupted"
    assert not changed
