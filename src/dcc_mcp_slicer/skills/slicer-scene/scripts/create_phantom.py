from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import create_phantom


def main(name: str = "Synthetic materials phantom", size: int = 64, spacing: float = 1.0) -> dict:
    return create_phantom(name=name, size=size, spacing=spacing)


if __name__ == "__main__":
    run_main(main)
