from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import edit_sphere


def main(
    node_id: str,
    radius: float = 12.0,
    red: float = 0.2,
    green: float = 0.7,
    blue: float = 0.9,
    opacity: float = 1.0,
    expected_revision: str | None = None,
) -> dict:
    return edit_sphere(
        node_id=node_id,
        radius=radius,
        red=red,
        green=green,
        blue=blue,
        opacity=opacity,
        expected_revision=expected_revision,
    )


if __name__ == "__main__":
    run_main(main)
