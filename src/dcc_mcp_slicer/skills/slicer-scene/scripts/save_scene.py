from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import save_scene


def main(filename: str) -> dict:
    return save_scene(filename=filename)


if __name__ == "__main__":
    run_main(main)
