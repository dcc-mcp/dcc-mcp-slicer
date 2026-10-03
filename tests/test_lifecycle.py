import threading
from types import SimpleNamespace

import pytest
from test_dispatcher import Timer

from dcc_mcp_slicer.dispatcher import SlicerDispatcher
from dcc_mcp_slicer.server import SlicerMcpServer, validate_host_version


@pytest.mark.parametrize("version", ["5.8.1", "5.11.0", "6.0.0", "5.10", "5.10.0evil", None])
def test_unsupported_host_fails_before_timer(version):
    with pytest.raises(RuntimeError, match="5.10"):
        validate_host_version(version)


def make_server():
    dispatcher = SlicerDispatcher(qt_module=SimpleNamespace(QTimer=Timer))
    return SlicerMcpServer(host_version="5.10.0", dispatcher=dispatcher)


def test_constructor_error_closes_timer():
    dispatcher = SlicerDispatcher(qt_module=SimpleNamespace(QTimer=Timer))
    with pytest.raises(TypeError):
        SlicerMcpServer(host_version="5.10.0", dispatcher=dispatcher, unknown_option=True)
    assert dispatcher.is_shutdown
    assert dispatcher._timer.running is False
    assert dispatcher._timer.callback is None


def test_stop_is_idempotent_and_new_instance_restart():
    first = make_server()
    first.start()
    first.stop()
    first.stop()
    assert not first.is_running
    assert first.host_dispatcher.is_shutdown
    with pytest.raises(RuntimeError, match="create a new"):
        first.start()
    second = make_server()
    try:
        second.start()
        assert second.is_running
    finally:
        second.stop()


def test_wrong_thread_stop_does_not_partially_stop():
    server = make_server()
    server.start()
    errors = []

    def stop():
        try:
            server.stop()
        except RuntimeError as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=stop)
    worker.start()
    worker.join()
    try:
        assert errors and server.is_running
    finally:
        server.stop()
