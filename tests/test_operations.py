import threading

import pytest

from dcc_mcp_slicer import operations as ops


@pytest.mark.parametrize("value", [True, -1, 0, 129, 1.2, "32", None])
def test_volume_rejects_invalid_size_without_host(value):
    result = ops.create_volume(size=value)
    assert result["success"] is False
    assert result["error"] == "invalid_input"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "3", None])
def test_sphere_rejects_bad_radius(value):
    result = ops.create_sphere(radius=value)
    assert result["success"] is False
    assert result["error"] == "invalid_input"


@pytest.mark.parametrize("value", ["../scene.mrb", "/tmp/scene.mrb", "a/b.mrb", "x.MRB", "x.mrb/extra", "x.mrb\x00"])
def test_path_confinement(value):
    with pytest.raises(ops.InvalidInput):
        ops.artifact_path(value, ".mrb")


def test_symlink_rejected(tmp_path):
    outside = tmp_path.parent / "outside.mrb"
    try:
        (tmp_path / "link.mrb").symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks the privilege to create symbolic links")
        raise
    with pytest.raises(ops.InvalidInput):
        ops.artifact_path("link.mrb", ".mrb")


def test_missing_workspace(monkeypatch):
    monkeypatch.delenv("DCC_MCP_SLICER_WORKSPACE")
    assert ops.save_scene("scene.mrb")["error"] == "invalid_input"


def test_existing_file_never_overwritten(tmp_path):
    file = tmp_path / "scene.mrb"
    file.write_text("preserve me")
    assert ops.save_scene("scene.mrb")["error"] == "invalid_input"
    assert file.read_text() == "preserve me"


def test_untrusted_bundle_cannot_open(tmp_path):
    (tmp_path / "scene.mrb").write_bytes(b"not a scene")
    assert ops.reopen_scene("scene.mrb")["error"] == "invalid_input"


def test_tampered_bundle_cannot_open(tmp_path):
    (tmp_path / "scene.mrb").write_bytes(b"not a scene")
    (tmp_path / "scene-receipt.json").write_text('{"sha256":"wrong", "synthetic_nodes":1}')
    assert ops.reopen_scene("scene.mrb")["error"] == "invalid_input"


def test_host_guard_returns_canonical_error_from_worker():
    results = []
    thread = threading.Thread(target=lambda: results.append(ops.scene_info()))
    thread.start()
    thread.join()
    assert results[0]["success"] is False
    assert results[0]["error"] == "RuntimeError"
    assert "main thread" in results[0]["_meta"]["dcc.error"]["message"]


@pytest.mark.parametrize("filename", ["../x.mrml", "/x.mrml", "x.py"])
def test_archive_paths_and_types_rejected(tmp_path, filename):
    from zipfile import ZipFile

    bundle = tmp_path / "bundle.mrb"
    with ZipFile(bundle, "w") as archive:
        archive.writestr(filename, "<MRML/>")
    with pytest.raises(ops.InvalidInput):
        ops.validate_bundle(bundle)


def test_external_mrml_data_reference_rejected(tmp_path):
    from zipfile import ZipFile

    bundle = tmp_path / "bundle.mrb"
    with ZipFile(bundle, "w") as archive:
        archive.writestr("scene/scene.mrml", '<MRML><VolumeArchetypeStorage fileName="../../secret.nrrd"/></MRML>')
    with pytest.raises(ops.InvalidInput):
        ops.validate_bundle(bundle)


def test_non_synthetic_storable_scene_rejected():
    class Node:
        def IsA(self, name):
            return True

        def GetSaveWithScene(self):
            return True

        def GetAttribute(self, name):
            return None

    class Scene:
        def GetNumberOfNodes(self):
            return 1

        def GetNthNode(self, index):
            return Node()

    from types import SimpleNamespace

    with pytest.raises(ops.InvalidInput):
        ops.assert_synthetic_scene(SimpleNamespace(mrmlScene=Scene()))


def test_encoded_storage_paths_validate(tmp_path):
    from zipfile import ZipFile

    bundle = tmp_path / "bundle.mrb"
    with ZipFile(bundle, "w") as archive:
        archive.writestr("scene/scene.mrml", '<MRML><VolumeArchetypeStorage fileName="Data/toy%20volume.nrrd"/></MRML>')
        archive.writestr("scene/Data/toy volume.nrrd", "synthetic")
    ops.validate_bundle(bundle)


def test_core_cancellation_is_not_swallowed(monkeypatch):
    from dcc_mcp_core.cancellation import DccMcpCancelledError

    def cancelled():
        raise DccMcpCancelledError("test cancellation")

    monkeypatch.setattr(ops, "check_dcc_cancelled", cancelled)
    with pytest.raises(DccMcpCancelledError):
        ops.scene_info()


def test_exclusive_publication_rejects_race(tmp_path):
    staged, destination = tmp_path / "stage", tmp_path / "target"
    staged.write_bytes(b"new")
    destination.write_bytes(b"keep")
    with pytest.raises(ops.InvalidInput):
        ops.publish_new(staged, destination)
    assert destination.read_bytes() == b"keep"
    assert staged.read_bytes() == b"new"


def test_cancelled_native_output_is_not_published(tmp_path, monkeypatch):
    from dcc_mcp_core.cancellation import DccMcpCancelledError

    staged, destination = tmp_path / "stage", tmp_path / "target"
    staged.write_bytes(b"new")

    def cancel():
        raise DccMcpCancelledError("cancel before commit")

    monkeypatch.setattr(ops, "check_dcc_cancelled", cancel)
    with pytest.raises(DccMcpCancelledError):
        ops.publish_new(staged, destination)
    assert not destination.exists()


def test_export_failure_leaves_no_partial_output(tmp_path, monkeypatch):
    from types import SimpleNamespace

    node = SimpleNamespace(GetAttribute=lambda key: "sphere")
    monkeypatch.setattr(ops, "managed_node", lambda *args: node)

    def save(node, filename, properties):
        from pathlib import Path

        Path(filename).write_bytes(b"partial")
        return False

    monkeypatch.setattr(ops, "host", lambda: SimpleNamespace(util=SimpleNamespace(exportNode=save)))
    assert ops.export_node("id", "sphere.stl")["success"] is False
    assert not list(tmp_path.iterdir())


def test_stale_revision_rejected_before_edit(monkeypatch):
    monkeypatch.setattr(ops, "managed_node", lambda *args: object())
    monkeypatch.setattr(ops, "snapshot", lambda node: {"revision": "1" * 64})
    result = ops.edit_sphere("node", expected_revision="0" * 64)
    assert result["error"] == "invalid_input"
    assert "stale" in result["message"]


def test_capacity_checked_before_host_allocation():
    from types import SimpleNamespace

    scene = SimpleNamespace(
        GetNumberOfNodes=lambda: 100,
        GetNthNode=lambda index: SimpleNamespace(GetAttribute=lambda key: "sphere"),
    )
    with pytest.raises(ops.InvalidInput, match="100"):
        ops.ensure_capacity(SimpleNamespace(mrmlScene=scene))


def test_duplicate_bundle_members_rejected(tmp_path):
    from zipfile import ZipFile

    path = tmp_path / "duplicate.mrb"
    with ZipFile(path, "w") as archive:
        archive.writestr("scene.mrml", "<MRML/>")
        with pytest.warns(UserWarning):
            archive.writestr("scene.mrml", "<MRML/>")
    with pytest.raises(ops.InvalidInput, match="Duplicate"):
        ops.validate_bundle(path)


@pytest.mark.parametrize("argument", [{"width": 2049}, {"height": True}, {"width": 127}])
def test_png_limits_reject_before_host_access(argument):
    assert ops.export_view("view.png", **argument)["error"] == "invalid_input"


@pytest.mark.parametrize("direction", ["unknown", 1, None, []])
def test_camera_direction_rejects_before_host(direction):
    assert ops.configure_camera("node", direction=direction)["error"] == "invalid_input"


def fake_scene_save(monkeypatch):
    from types import SimpleNamespace
    from zipfile import ZipFile

    def save(filename, properties):
        with ZipFile(filename, "w") as archive:
            archive.writestr("scene/scene.mrml", "<MRML/>")
        return True

    monkeypatch.setattr(ops, "host", lambda: SimpleNamespace(util=SimpleNamespace(saveScene=save)))
    monkeypatch.setattr(ops, "assert_synthetic_scene", lambda slicer: None)
    monkeypatch.setattr(ops, "scene_info", lambda: {"context": {"count": 1}})


def test_scene_publish_collision_rolls_back_only_own_receipt(tmp_path, monkeypatch):
    fake_scene_save(monkeypatch)
    publish = ops.publish_new

    def collide(staged, destination):
        if destination.suffix == ".mrb":
            destination.write_bytes(b"other writer")
        publish(staged, destination)

    monkeypatch.setattr(ops, "publish_new", collide)
    result = ops.save_scene("scene.mrb")
    assert result["error"] == "invalid_input"
    assert (tmp_path / "scene.mrb").read_bytes() == b"other writer"
    assert not (tmp_path / "scene-receipt.json").exists()
    assert len(list(tmp_path.iterdir())) == 1


def test_scene_cancelled_before_commit_removes_staging_and_receipt(tmp_path, monkeypatch):
    from dcc_mcp_core.cancellation import DccMcpCancelledError

    fake_scene_save(monkeypatch)
    calls = []

    def cancel_at_commit():
        calls.append(1)
        if len(calls) == 3:
            raise DccMcpCancelledError("cancel at bundle publication")

    monkeypatch.setattr(ops, "check_dcc_cancelled", cancel_at_commit)
    with pytest.raises(DccMcpCancelledError):
        ops.save_scene("scene.mrb")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("stem_length", [72, 73, 80])
def test_scene_filename_schema_boundaries_save_and_reopen(tmp_path, monkeypatch, stem_length):
    from types import SimpleNamespace

    fake_scene_save(monkeypatch)
    filename = "a" * stem_length + ".mrb"
    saved = ops.save_scene(filename)
    assert saved["success"] is True, saved
    receipt = tmp_path / ("a" * stem_length + "-receipt.json")
    assert (tmp_path / filename).is_file()
    assert receipt.is_file()
    count = [1]

    def load(path):
        assert path == str(tmp_path / filename)
        count[0] += 1
        return True

    monkeypatch.setattr(ops, "host", lambda: SimpleNamespace(util=SimpleNamespace(loadScene=load)))
    monkeypatch.setattr(ops, "scene_info", lambda: {"context": {"count": count[0]}})
    reopened = ops.reopen_scene(filename)
    assert reopened["success"] is True, reopened
    assert reopened["context"]["imported_nodes"] == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted([filename, receipt.name])


@pytest.mark.parametrize("action", [ops.save_scene, ops.reopen_scene])
def test_scene_filename_over_schema_limit_rejected_before_native(tmp_path, monkeypatch, action):
    def unexpected_host():
        pytest.fail("Invalid public filename reached the native host")

    monkeypatch.setattr(ops, "host", unexpected_host)
    result = action("a" * 81 + ".mrb")
    assert result["error"] == "invalid_input"
    assert not list(tmp_path.iterdir())


def test_internal_receipt_bound_stays_inside_workspace(tmp_path):
    name = "a" * 80 + "-receipt.json"
    receipt = ops.artifact_path(name, ".json", max_stem_length=88)
    assert receipt == tmp_path.resolve() / name
    with pytest.raises(ops.InvalidInput):
        ops.artifact_path("a" * 81 + "-receipt.json", ".json", max_stem_length=88)


@pytest.mark.parametrize("filename", ["../x-receipt.json", "C:x-receipt.json", "folder/x-receipt.json"])
def test_internal_receipt_cannot_escape_workspace(tmp_path, filename):
    with pytest.raises(ops.InvalidInput):
        ops.artifact_path(filename, ".json", max_stem_length=88)
    assert not list(tmp_path.iterdir())


def test_non_json_receipt_is_invalid_input(tmp_path):
    (tmp_path / "scene.mrb").write_bytes(b"archive")
    (tmp_path / "scene-receipt.json").write_text("not json")
    assert ops.reopen_scene("scene.mrb")["error"] == "invalid_input"


def test_unrepresentable_integer_is_invalid_input():
    assert ops.create_sphere(radius=10**1000)["error"] == "invalid_input"


def test_only_live_layout_owned_nodes_are_exempted():
    from types import SimpleNamespace

    class Node:
        def __init__(self, id_, kind="vtkMRMLModelNode", saved=True):
            self.id, self.kind, self.saved = id_, kind, saved

        def GetID(self):
            return self.id

        def IsA(self, name):
            return name in {self.kind, "vtkMRMLStorableNode"}

        def GetSaveWithScene(self):
            return self.saved

        def GetAttribute(self, name):
            return None

    plane = Node("actual-native-plane")
    camera = Node("actual-native-camera", "vtkMRMLCameraNode")
    impostor = Node("user-model-with-slice-like-name")
    hidden_volume = Node("unsaved-user-volume", "vtkMRMLVolumeNode", False)
    nodes = [plane, camera]
    logic = SimpleNamespace(GetSliceModelNode=lambda: plane, GetSliceModelTransformNode=lambda: None)
    manager = SimpleNamespace(
        sliceViewNames=lambda: ["Red"],
        sliceWidget=lambda name: SimpleNamespace(sliceLogic=lambda: logic),
        threeDViewCount=1,
        threeDWidget=lambda index: SimpleNamespace(threeDView=lambda: SimpleNamespace(mrmlViewNode=lambda: object())),
    )
    slicer = SimpleNamespace(
        app=SimpleNamespace(layoutManager=lambda: manager),
        modules=SimpleNamespace(
            cameras=SimpleNamespace(logic=lambda: SimpleNamespace(GetViewActiveCameraNode=lambda view: camera))
        ),
        mrmlScene=SimpleNamespace(GetNumberOfNodes=lambda: len(nodes), GetNthNode=lambda i: nodes[i]),
    )
    ops.assert_synthetic_scene(slicer)
    for foreign in (impostor, hidden_volume, Node("user-camera", "vtkMRMLCameraNode")):
        nodes.append(foreign)
        with pytest.raises(ops.InvalidInput, match="non-synthetic"):
            ops.assert_synthetic_scene(slicer)
        nodes.pop()


@pytest.mark.parametrize(
    "source,target,expected",
    [
        ((411, 352), (640, 480), (560, 480, 40, 0)),
        ((800, 200), (400, 400), (400, 100, 0, 150)),
        ((200, 800), (400, 400), (100, 400, 150, 0)),
        ((640, 480), (640, 480), (640, 480, 0, 0)),
    ],
)
def test_view_output_letterboxes_without_anisotropic_stretch(source, target, expected):
    assert ops.fit_image_dimensions(*source, *target) == expected
