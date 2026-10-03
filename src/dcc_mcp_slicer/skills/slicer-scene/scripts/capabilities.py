from dcc_mcp_core.skill import run_main, skill_success


def main() -> dict:
    return skill_success(
        "Synthetic-only 3D Slicer adapter",
        application="3D Slicer",
        max_volume_edge=128,
        max_sphere_resolution=64,
        exports=["nrrd", "stl", "mrb", "png"],
        supported_host="Slicer 5.10.x",
        max_synthetic_nodes=100,
        max_png_edge=2048,
        graphics_context_required_for_png=True,
        patient_data=False,
        reopen_mode="additive import",
        native_calls_interruptible=False,
    )


if __name__ == "__main__":
    run_main(main)
