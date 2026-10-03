from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import export_view


def main(filename: str, view: str = "3D", width: int = 800, height: int = 600) -> dict:
    return export_view(filename=filename, view=view, width=width, height=height)


if __name__ == "__main__":
    run_main(main)
