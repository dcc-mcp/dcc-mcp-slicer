"""Slicer's PythonQt host pump; Core owns both execution queues."""

import threading
import uuid

from dcc_mcp_core import HostUiDispatcherBase
from dcc_mcp_core.skill import skill_error


def require_main_thread():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Slicer operations require the application main thread")


class SlicerDispatcher(HostUiDispatcherBase):
    def __init__(self, qt_module=None):
        require_main_thread()
        super().__init__(label="slicer-pythonqt")
        if qt_module is None:
            import qt as qt_module
        self._closed = False
        self._timer = qt_module.QTimer()
        self._timer.setInterval(10)
        self._timer.connect("timeout()", self._tick)
        self._timer.start()

    def poke_host_pump(self):
        # Called by HTTP workers: no Qt/VTK/MRML API calls here. The repeating
        # timer installed on the application thread notices work within 10 ms.
        pass

    def dispatch_callable(self, func, *, affinity="main", timeout_hint_secs=None, **metadata):
        if self.is_shutdown:
            return skill_error("Host dispatcher has stopped", "Interrupted")
        request_id = str(uuid.uuid4())
        result = self.submit_callable(
            request_id,
            func,
            affinity=affinity,
            timeout_ms=int((timeout_hint_secs or 30) * 1000),
        )
        if result["success"]:
            return result["output"]
        detail = str(result["error"])
        if detail.startswith("Timeout"):
            self.cancel(request_id)
        code = (
            "Timeout"
            if detail.startswith("Timeout")
            else detail
            if detail in {"Interrupted", "Cancelled"}
            else "host_dispatch_failed"
        )
        return skill_error("Host dispatch failed", code, _meta={"dcc.error": {"message": detail}})

    def _tick(self):
        require_main_thread()
        self.drain_queue(5.0)

    def close(self):
        require_main_thread()
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._timer.disconnect("timeout()", self._tick)
        self.shutdown()
        # PythonQt releases the callback and native timer on its owning thread.
        if hasattr(self._timer, "deleteLater"):
            self._timer.deleteLater()
