from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import create_sphere


def main(name: str = "Synthetic sphere", radius: float = 10.0, resolution: int = 32) -> dict:
    return create_sphere(name=name, radius=radius, resolution=resolution)


if __name__ == "__main__":
    run_main(main)
