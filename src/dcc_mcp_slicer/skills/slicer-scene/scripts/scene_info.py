from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import scene_info


def main(limit: int = 100) -> dict:
    return scene_info(limit=limit)


if __name__ == "__main__":
    run_main(main)
