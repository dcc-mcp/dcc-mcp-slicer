from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import configure_slice


def main(node_id: str, view: str = "Red", orientation: str = "axial", offset_mm: float = 0.0) -> dict:
    return configure_slice(node_id=node_id, view=view, orientation=orientation, offset_mm=offset_mm)


if __name__ == "__main__":
    run_main(main)
