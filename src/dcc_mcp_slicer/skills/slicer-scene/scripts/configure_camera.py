from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import configure_camera


def main(node_id: str, direction: str = "anterior", zoom: float = 1.0) -> dict:
    return configure_camera(node_id=node_id, direction=direction, zoom=zoom)


if __name__ == "__main__":
    run_main(main)
