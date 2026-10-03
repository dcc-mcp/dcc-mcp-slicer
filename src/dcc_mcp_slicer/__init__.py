"""3D Slicer adapter. Importing this module does not import Slicer or Qt."""

__version__ = "0.1.0"


def start_server(port=None, **options):
    """Start from Slicer's Python console/main thread and retain the returned server."""
    from dcc_mcp_core import capture_bootstrap_errors

    with capture_bootstrap_errors("slicer", adapter_version=__version__, min_core_version="0.20.41"):
        from .server import SlicerMcpServer

        server = SlicerMcpServer(port=port, **options)
        try:
            server.start()
        except BaseException:
            server.stop()
            raise
        return server


def stop_server(server):
    """Stop the supplied server; this package keeps no global server singleton."""
    server.stop()
