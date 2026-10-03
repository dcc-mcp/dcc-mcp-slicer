from dcc_mcp_core.skill import run_main

from dcc_mcp_slicer.operations import export_node


def main(node_id: str, filename: str, expected_revision: str | None = None) -> dict:
    return export_node(node_id=node_id, filename=filename, expected_revision=expected_revision)


if __name__ == "__main__":
    run_main(main)
