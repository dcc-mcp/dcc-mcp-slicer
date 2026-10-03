"""Composition root for a server owned by the running Slicer process."""

import os
import re
import sys
from pathlib import Path

from dcc_mcp_core import DccServerBase, DccServerOptions, HostExecutionBridge, MinimalModeConfig

from . import __version__
from .dispatcher import SlicerDispatcher, require_main_thread


def validate_host_version(version):
    """Fail before creating a timer/listener outside the qualified API profile."""
    if not isinstance(version, str) or not re.fullmatch(r"5\.10\.\d+(?:[-+].*)?", version):
        raise RuntimeError("Supported host profile is 3D Slicer 5.10.x; native acceptance uses 5.10.0")
    return version


class SlicerMcpServer(DccServerBase):
    def __init__(self, port=None, dispatcher=None, host_version=None, **kwargs):
        require_main_thread()
        if host_version is None:
            import slicer

            if not hasattr(slicer, "mrmlScene"):
                raise RuntimeError("Start inside the 3D Slicer application, not the unrelated PyPI slicer package")
            if sys.version_info[:2] != (3, 12):
                raise RuntimeError("The supported Slicer 5.10 profile requires embedded Python 3.12")
            host_version = str(slicer.app.applicationVersion)
        self.host_version = validate_host_version(host_version)
        workspace = os.environ.get("DCC_MCP_SLICER_WORKSPACE")
        if not workspace or not Path(workspace).is_dir():
            raise ValueError("Set DCC_MCP_SLICER_WORKSPACE to an existing trusted directory before startup")
        self.host_dispatcher = dispatcher if dispatcher is not None else SlicerDispatcher()
        self._closed = False
        kwargs.setdefault("gateway_port", 0)
        kwargs.setdefault("enable_gateway_failover", False)
        try:
            options = DccServerOptions.from_env(
                "slicer",
                Path(__file__).parent / "skills",
                port=port,
                execution_bridge=HostExecutionBridge(dispatcher=self.host_dispatcher),
                server_name="dcc-mcp-slicer",
                server_version=__version__,
                adapter_version=__version__,
                instance_type="gui",
                **kwargs,
            )
            super().__init__(options=options)
            self.register_quit_hook(self.host_dispatcher.close)
            self.register_builtin_actions(minimal_mode=MinimalModeConfig(skills=()))
        except BaseException:
            self.host_dispatcher.close()
            self._closed = True
            raise

    def start(self, **kwargs):
        require_main_thread()
        if self._closed or self.host_dispatcher.is_shutdown:
            raise RuntimeError("This server has stopped; create a new SlicerMcpServer to restart")
        try:
            return super().start(**kwargs)
        except BaseException:
            self.stop()
            raise

    def stop(self):
        # Reject wrong-thread shutdown before Core can alter the listener state.
        require_main_thread()
        if self._closed:
            return
        try:
            super().stop()
        finally:
            self.host_dispatcher.close()
            self._closed = True

    def _version_string(self):
        # Cached on construction; gateway/worker callbacks do not touch Qt.
        return self.host_version
