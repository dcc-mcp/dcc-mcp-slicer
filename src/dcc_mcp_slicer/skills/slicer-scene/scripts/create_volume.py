from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import create_volume


def main(name: str = "Synthetic volume", size: int = 32, spacing: float = 1.0, value: int = 120) -> dict:
    return create_volume(name=name, size=size, spacing=spacing, value=value)


if __name__ == "__main__":
    run_main(main)
