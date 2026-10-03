"""Bounded typed operations for mathematical test objects, never patient data."""

import hashlib
import json
import logging
import math
import os
import re
import tempfile
import threading
from functools import wraps
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree
from zipfile import ZipFile

from dcc_mcp_core.cancellation import DccMcpCancelledError, check_dcc_cancelled
from dcc_mcp_core.skill import skill_error, skill_success

from .dispatcher import require_main_thread

TAG = "DCCMCP.Synthetic"
KINDS = {"sphere", "volume"}
MAX_NODES = 100
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024


class InvalidInput(ValueError):
    pass


def host():
    require_main_thread()
    import slicer

    if not hasattr(slicer, "mrmlScene"):
        raise RuntimeError("A running 3D Slicer application is required")
    return slicer


def operation(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            require_main_thread()
            check_dcc_cancelled()
            return func(*args, **kwargs)
        except DccMcpCancelledError:
            raise
        except InvalidInput as exc:
            return skill_error(str(exc), "invalid_input")
        except Exception as exc:
            return skill_error(
                "Slicer operation failed", type(exc).__name__, _meta={"dcc.error": {"message": str(exc)}}
            )

    return wrapped


def finite(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidInput(f"{name} must be a number")
    try:
        value = float(value)
    except OverflowError as exc:
        raise InvalidInput(f"{name} must be a finite supported number") from exc
    if not math.isfinite(value) or not low <= value <= high:
        raise InvalidInput(f"{name} must be finite and between {low} and {high}")
    return value


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidInput(f"{name} must be an integer between {low} and {high}")
    return value


def name_value(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,64}", name):
        raise InvalidInput("name must contain 1–64 ASCII letters, digits, spaces, underscores or hyphens")
    return name


def artifact_path(filename, suffix, *, max_stem_length=80):
    root_value = os.environ.get("DCC_MCP_SLICER_WORKSPACE")
    if not root_value:
        raise InvalidInput("Set DCC_MCP_SLICER_WORKSPACE to an existing dedicated artifact directory")
    root = Path(root_value).resolve()
    if not root.is_dir():
        raise InvalidInput("Artifact workspace must exist")
    if not isinstance(filename, str) or not re.fullmatch(
        rf"[A-Za-z0-9_-]{{1,{max_stem_length}}}" + re.escape(suffix), filename
    ):
        raise InvalidInput(f"filename must be a plain basename ending in {suffix}")
    result = root / filename
    if result.is_symlink() or result.resolve().parent != root:
        raise InvalidInput("Symlinks and paths outside the artifact workspace are forbidden")
    return result


def managed_node(node_id, kind=None):
    if not isinstance(node_id, str) or not node_id or len(node_id) > 128:
        raise InvalidInput("A valid node_id is required")
    node = host().mrmlScene.GetNodeByID(node_id)
    if node is None:
        raise InvalidInput("Node does not exist")
    marker = node.GetAttribute(TAG)
    expected_class = "vtkMRMLScalarVolumeNode" if marker == "volume" else "vtkMRMLModelNode"
    if not node.IsA(expected_class):
        raise InvalidInput("Synthetic marker does not match the native node type")
    if marker not in KINDS or (kind and marker != kind):
        raise InvalidInput("Operation accepts only matching adapter-created synthetic nodes")
    return node


def snapshot(node):
    info = {"node_id": node.GetID(), "name": node.GetName(), "kind": node.GetAttribute(TAG)}
    if info["kind"] == "volume":
        info.update(
            dimensions=list(node.GetImageData().GetDimensions()),
            spacing=list(node.GetSpacing()),
            origin=list(node.GetOrigin()),
            scalar_range=list(node.GetImageData().GetScalarRange()),
        )
    elif info["kind"] == "sphere":
        poly = node.GetPolyData()
        info.update(points=poly.GetNumberOfPoints(), cells=poly.GetNumberOfCells(), bounds=list(poly.GetBounds()))
        display = node.GetDisplayNode()
        info.update(color=list(display.GetColor()), opacity=display.GetOpacity())
    # Session-local VTK modification times detect native edits even when counts,
    # bounds and scalar ranges happen to remain equal. Reacquire after reload.
    revision_state = {"metadata": info, "node_mtime": node.GetMTime()}
    data = node.GetImageData() if info["kind"] == "volume" else node.GetPolyData()
    revision_state["data_mtime"] = data.GetMTime()
    info["revision"] = hashlib.sha256(json.dumps(revision_state, sort_keys=True).encode()).hexdigest()
    return info


def verified(message, **context):
    return skill_success(
        message,
        verified=True,
        postcondition={"method": "native_MRML_VTK_readback"},
        execution_thread_id=threading.get_ident(),
        main_thread_id=threading.main_thread().ident,
        **context,
    )


@operation
def scene_info(limit=100):
    limit = integer(limit, "limit", 1, 100)
    slicer = host()
    nodes = []
    count = 0
    for index in range(slicer.mrmlScene.GetNumberOfNodes()):
        node = slicer.mrmlScene.GetNthNode(index)
        if node.GetAttribute(TAG) in KINDS:
            count += 1
            if len(nodes) < limit:
                nodes.append(snapshot(node))
    return verified(
        "Synthetic scene inspected",
        application_version=str(slicer.app.applicationVersion),
        nodes=nodes,
        count=count,
        truncated=count > limit,
    )


@operation
def create_volume(name="Synthetic volume", size=32, spacing=1.0, value=120):
    name = name_value(name)
    size = integer(size, "size", 8, 128)
    spacing = finite(spacing, "spacing", 0.01, 100)
    value = integer(value, "value", 1, 32767)
    slicer = host()
    ensure_capacity(slicer)
    import numpy as np

    k, j, i = np.ogrid[:size, :size, :size]
    center = (size - 1) / 2
    array = ((i - center) ** 2 + (j - center) ** 2 + (k - center) ** 2) < (size / 4) ** 2
    array = array.astype(np.int16) * value
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
    try:
        node.SetAttribute(TAG, "volume")
        slicer.util.updateVolumeFromArray(node, array)
        node.SetSpacing(spacing, spacing, spacing)
        node.CreateDefaultDisplayNodes()
        if tuple(node.GetImageData().GetDimensions()) != (size, size, size):
            raise RuntimeError("Volume dimensions did not match the request")
        return verified(
            "Synthetic volume created", node=snapshot(node), scalar_range=list(node.GetImageData().GetScalarRange())
        )
    except BaseException:
        remove_created_node(slicer, node)
        raise


def remove_created_node(slicer, node):
    """Release only the failed operation's own data/display/storage objects."""
    related = [node.GetNthDisplayNode(index) for index in range(node.GetNumberOfDisplayNodes())]
    storage = node.GetStorageNode()
    slicer.mrmlScene.RemoveNode(node)
    for owned in related + [storage]:
        if owned is not None:
            slicer.mrmlScene.RemoveNode(owned)


def sphere_poly(radius, resolution):
    import vtk

    source = vtk.vtkSphereSource()
    source.SetRadius(radius)
    source.SetThetaResolution(resolution)
    source.SetPhiResolution(resolution)
    source.Update()
    result = vtk.vtkPolyData()
    result.DeepCopy(source.GetOutput())
    return result


@operation
def create_sphere(name="Synthetic sphere", radius=10.0, resolution=32):
    name = name_value(name)
    radius = finite(radius, "radius", 0.01, 1000)
    resolution = integer(resolution, "resolution", 8, 64)
    slicer = host()
    ensure_capacity(slicer)
    poly = sphere_poly(radius, resolution)
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", name)
    try:
        node.SetAttribute(TAG, "sphere")
        node.SetAndObservePolyData(poly)
        node.CreateDefaultDisplayNodes()
        node.SetAttribute("DCCMCP.Radius", str(radius))
        node.SetAttribute("DCCMCP.Resolution", str(resolution))
        if node.GetPolyData().GetNumberOfPoints() < 1:
            raise RuntimeError("Sphere is empty")
        return verified("Synthetic sphere created", node=snapshot(node))
    except BaseException:
        remove_created_node(slicer, node)
        raise


@operation
def edit_sphere(node_id, radius=12.0, red=0.2, green=0.7, blue=0.9, opacity=1.0, expected_revision=None):
    radius = finite(radius, "radius", 0.01, 1000)
    color = [finite(v, n, 0, 1) for v, n in zip((red, green, blue), ("red", "green", "blue"), strict=True)]
    opacity = finite(opacity, "opacity", 0, 1)
    node = managed_node(node_id, "sphere")
    check_revision(node, expected_revision)
    resolution = integer(int(node.GetAttribute("DCCMCP.Resolution")), "resolution", 8, 64)
    node.SetAndObservePolyData(sphere_poly(radius, resolution))
    node.SetAttribute("DCCMCP.Radius", str(radius))
    display = node.GetDisplayNode()
    display.SetColor(*color)
    display.SetOpacity(opacity)
    actual = snapshot(node)
    if (
        any(abs(a - b) > 1e-6 for a, b in zip(actual["color"], color, strict=True))
        or abs(actual["bounds"][5] - radius) > 1e-4
    ):
        raise RuntimeError("Sphere edit readback mismatch")
    return verified("Synthetic sphere edited", node=actual)


def ensure_capacity(slicer):
    count = sum(
        slicer.mrmlScene.GetNthNode(index).GetAttribute(TAG) in KINDS
        for index in range(slicer.mrmlScene.GetNumberOfNodes())
    )
    if count >= MAX_NODES:
        raise InvalidInput("Scene is limited to 100 synthetic nodes")


def check_revision(node, expected):
    if expected is not None:
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise InvalidInput("expected_revision must be a lowercase SHA-256 revision")
        if snapshot(node)["revision"] != expected:
            raise InvalidInput("Node revision is stale; inspect the scene before retrying")


def artifact_info(path):
    size = path.stat().st_size
    if not path.is_file() or path.is_symlink() or not 0 < size <= MAX_ARTIFACT_BYTES:
        raise InvalidInput("Artifact must be a nonempty regular file no larger than 256 MiB")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"filename": path.name, "bytes": size, "sha256": digest.hexdigest()}


def publish_new(staged, destination):
    """Exclusive same-filesystem publication; never overwrite even after a race."""
    check_dcc_cancelled()
    with staged.open("r+b" if os.name == "nt" else "rb") as stream:
        os.fsync(stream.fileno())
    try:
        os.link(staged, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise InvalidInput("Output already exists; choose a new filename") from exc


@operation
def export_node(node_id, filename, expected_revision=None):
    node = managed_node(node_id)
    check_revision(node, expected_revision)
    suffix = ".nrrd" if node.GetAttribute(TAG) == "volume" else ".stl"
    path = artifact_path(filename, suffix)
    if path.exists():
        raise InvalidInput("Output already exists; choose a new filename")
    with tempfile.TemporaryDirectory(prefix=".dcc-mcp-export-", dir=path.parent) as directory:
        staged = Path(directory) / path.name
        # exportNode deliberately does not replace a node's scene storage path.
        if not host().util.exportNode(node, str(staged), properties={}):
            raise RuntimeError("Native export did not create an artifact")
        info = artifact_info(staged)
        publish_new(staged, path)
    return verified("Synthetic node exported", **info, node=snapshot(node))


def layout_owned_node_ids(slicer):
    """Identify intrinsic slice-plane/camera objects by live ownership, never names."""
    app = getattr(slicer, "app", None)
    manager = app.layoutManager() if app is not None else None
    owned = set()
    if manager is not None:
        for name in manager.sliceViewNames():
            logic = manager.sliceWidget(name).sliceLogic()
            for node in (logic.GetSliceModelNode(), logic.GetSliceModelTransformNode()):
                if node is not None:
                    owned.add(node.GetID())
        for index in range(getattr(manager, "threeDViewCount", 0)):
            view_node = manager.threeDWidget(index).threeDView().mrmlViewNode()
            camera = slicer.modules.cameras.logic().GetViewActiveCameraNode(view_node)
            if camera is not None:
                owned.add(camera.GetID())
    return owned


def assert_synthetic_scene(slicer):
    # Slicer's graphical layout owns intrinsic slice-plane models/transforms.
    # Only exact live owner references are exempted, not matching user names.
    layout_nodes = layout_owned_node_ids(slicer)
    for index in range(slicer.mrmlScene.GetNumberOfNodes()):
        node = slicer.mrmlScene.GetNthNode(index)
        if (
            node.IsA("vtkMRMLStorableNode")
            and (node.GetSaveWithScene() or node.IsA("vtkMRMLVolumeNode") or node.IsA("vtkMRMLModelNode"))
            and node.GetAttribute(TAG) not in KINDS
            and (not layout_nodes or node.GetID() not in layout_nodes)
        ):
            logging.getLogger(__name__).warning(
                "Synthetic guard rejected native class=%s id=%s",
                getattr(node, "GetClassName", lambda node=node: type(node).__name__)(),
                getattr(node, "GetID", lambda: "unknown")(),
            )
            raise InvalidInput("Scene contains non-synthetic storable data; use a fresh dedicated Slicer process")


@operation
def save_scene(filename):
    path = artifact_path(filename, ".mrb")
    receipt = artifact_path(filename[:-4] + "-receipt.json", ".json", max_stem_length=88)
    if path.exists() or receipt.exists():
        raise InvalidInput("Output already exists; choose a new filename")
    slicer = host()
    assert_synthetic_scene(slicer)
    before = scene_info()["context"]["count"]
    if before > 100:
        raise InvalidInput("Scene bundle limited to 100 synthetic nodes")
    if before == 0:
        raise InvalidInput("Create a synthetic node before saving")
    with tempfile.TemporaryDirectory(prefix=".dcc-mcp-scene-", dir=path.parent) as directory:
        staged = Path(directory) / path.name
        staged_receipt = Path(directory) / receipt.name
        if not slicer.util.saveScene(str(staged), properties={}):
            raise RuntimeError("Native scene save did not produce a bundle")
        info = artifact_info(staged)
        validate_bundle(staged)
        staged_receipt.write_text(json.dumps({"sha256": info["sha256"], "synthetic_nodes": before}), encoding="utf-8")
        # The bundle is the final commit marker. An interrupted receipt alone
        # cannot authorize reopening because both files are required.
        publish_new(staged_receipt, receipt)
        try:
            publish_new(staged, path)
        except BaseException:
            if receipt.exists() and os.path.samefile(staged_receipt, receipt):
                receipt.unlink()
            raise
    return verified("Synthetic scene bundle saved", **info, synthetic_nodes=before)


@operation
def reopen_scene(filename):
    path = artifact_path(filename, ".mrb")
    receipt = artifact_path(filename[:-4] + "-receipt.json", ".json", max_stem_length=88)
    if not path.is_file() or not receipt.is_file():
        raise InvalidInput("Only an adapter-saved bundle with its receipt may be reopened")
    if path.stat().st_size > 256 * 1024 * 1024 or receipt.stat().st_size > 4096:
        raise InvalidInput("Saved bundle or receipt exceeds the bounded import limit")
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise InvalidInput("Receipt must be valid UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise InvalidInput("Receipt must be an object")
    if artifact_info(path)["sha256"] != data.get("sha256"):
        raise InvalidInput("Bundle hash differs from the saved receipt")
    validate_bundle(path)
    expected = integer(data.get("synthetic_nodes"), "receipt synthetic_nodes", 1, 100)
    slicer = host()
    assert_synthetic_scene(slicer)
    before = scene_info()["context"]["count"]
    if before + expected > 100:
        raise InvalidInput("Imported scene would exceed 100 synthetic nodes")
    check_dcc_cancelled()
    if not slicer.util.loadScene(str(path)):
        raise RuntimeError("Slicer could not import the saved scene bundle")
    after = scene_info()["context"]["count"]
    if after != before + expected:
        raise RuntimeError("Reopened synthetic node count did not match the saved receipt")
    return verified(
        "Saved synthetic scene reopened by additive import",
        filename=path.name,
        nodes_before=before,
        nodes_after=after,
        imported_nodes=after - before,
    )


@operation
def create_phantom(name="Synthetic materials phantom", size=64, spacing=1.0):
    """Deterministic mathematical sphere with spherical and cylindrical inclusions."""
    name = name_value(name)
    size = integer(size, "size", 16, 128)
    spacing = finite(spacing, "spacing", 0.01, 100)
    slicer = host()
    ensure_capacity(slicer)
    import numpy as np

    k, j, i = np.ogrid[:size, :size, :size]
    center = (size - 1) / 2
    x, y, z = (i - center) / size, (j - center) / size, (k - center) / size
    body = x * x + y * y + z * z < 0.38**2
    sphere = (x + 0.14) ** 2 + (y + 0.07) ** 2 + z * z < 0.14**2
    cylinder = (x - 0.14) ** 2 + (y - 0.05) ** 2 < 0.07**2
    array = np.zeros((size, size, size), dtype=np.int16)
    array[body] = 60
    array[sphere & body] = 150
    array[np.broadcast_to(cylinder, array.shape) & body] = 240
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
    try:
        node.SetAttribute(TAG, "volume")
        slicer.util.updateVolumeFromArray(node, array)
        node.SetSpacing(spacing, spacing, spacing)
        node.SetOrigin(-center * spacing, -center * spacing, -center * spacing)
        node.SetIJKToRASDirections(1, 0, 0, 0, 1, 0, 0, 0, 1)
        node.CreateDefaultDisplayNodes()
        node.GetDisplayNode().SetAutoWindowLevel(False)
        node.GetDisplayNode().SetWindowLevel(260, 120)
        readback = slicer.util.arrayFromVolume(node)
        labels, counts = np.unique(readback, return_counts=True)
        if labels.tolist() != [0, 60, 150, 240]:
            raise RuntimeError("Phantom material readback mismatch")
        return verified(
            "Synthetic multi-material phantom created",
            node=snapshot(node),
            materials=[{"value": int(v), "voxels": int(c)} for v, c in zip(labels, counts, strict=True)],
            description="Mathematical sphere, spherical inclusion and cylindrical inclusion; no medical meaning",
        )
    except BaseException:
        remove_created_node(slicer, node)
        raise


def validate_bundle(path):
    """Reject archive traversal, unexpected payloads and external MRML references.

    Integrity receipts assume an operator-controlled trusted local workspace;
    neither this validation nor a hash authenticates arbitrary third-party data.
    """
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 1024 or sum(item.file_size for item in entries) > 512 * 1024 * 1024:
            raise InvalidInput("Scene bundle exceeds archive limits")
        names = {item.filename for item in entries}
        if len(names) != len(entries):
            raise InvalidInput("Duplicate archive members are forbidden")
        scenes = []
        for item in entries:
            pure = PurePosixPath(item.filename)
            if (
                pure.is_absolute()
                or not item.filename
                or "\x00" in item.filename
                or ":" in item.filename
                or item.flag_bits & 1
                or ".." in pure.parts
                or "\\" in item.filename
                or (item.external_attr >> 16) & 0o170000 not in {0, 0o040000, 0o100000}
            ):
                raise InvalidInput("Unsafe path in scene bundle")
            if item.is_dir():
                continue
            if pure.suffix.lower() not in {".mrml", ".vtk", ".vtp", ".nrrd", ".png"}:
                raise InvalidInput("Unexpected data type in scene bundle")
            if pure.suffix.lower() == ".mrml":
                if item.file_size > 4 * 1024 * 1024:
                    raise InvalidInput("Scene description is too large")
                scenes.append(item)
        if len(scenes) != 1:
            raise InvalidInput("Exactly one scene description is required")
        scene_path = PurePosixPath(scenes[0].filename)
        xml = archive.read(scenes[0])
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise InvalidInput("XML entity declarations are forbidden")
        for element in ElementTree.fromstring(xml).iter():
            for key, value in element.attrib.items():
                if "uri" in key.lower() and value:
                    raise InvalidInput("External URI references are forbidden")
                if (key.lower() == "filename" or key.lower().startswith("filelistmember")) and value:
                    value = unquote(value)
                    relative = PurePosixPath(value)
                    if relative.is_absolute() or ".." in relative.parts or "\\" in value:
                        raise InvalidInput("External storage paths are forbidden")
                    if str(scene_path.parent / relative) not in names:
                        raise InvalidInput("Scene references data outside its bundle")


def view_widget(view):
    if not isinstance(view, str) or view not in {"3D", "Red", "Yellow", "Green"}:
        raise InvalidInput("view must be 3D, Red, Yellow or Green")
    slicer = host()
    assert_synthetic_scene(slicer)
    layout_nodes = layout_owned_node_ids(slicer)
    for index in range(slicer.mrmlScene.GetNumberOfNodes()):
        node = slicer.mrmlScene.GetNthNode(index)
        if (
            node.IsA("vtkMRMLDisplayableNode")
            and node.GetDisplayVisibility() > 0
            and node.GetAttribute(TAG) not in KINDS
            and node.GetID() not in layout_nodes
        ):
            raise InvalidInput("View contains non-synthetic displayable data; use a dedicated synthetic scene")
    manager = slicer.app.layoutManager()
    if manager is None:
        raise InvalidInput("A Slicer graphical layout is required")
    widget = manager.threeDWidget(0) if view == "3D" else manager.sliceWidget(view)
    if widget is None:
        raise InvalidInput("Requested view is absent from the active Slicer layout")
    return widget.threeDView() if view == "3D" else widget.sliceView()


@operation
def configure_camera(node_id, direction="anterior", zoom=1.0):
    """Fit the first native 3D view to one managed model with a deterministic camera."""
    directions = {
        "anterior": ((0, 1, 0), (0, 0, 1)),
        "posterior": ((0, -1, 0), (0, 0, 1)),
        "left": ((-1, 0, 0), (0, 0, 1)),
        "right": ((1, 0, 0), (0, 0, 1)),
        "superior": ((0, 0, 1), (0, 1, 0)),
        "inferior": ((0, 0, -1), (0, 1, 0)),
    }
    if not isinstance(direction, str) or direction not in directions:
        raise InvalidInput("direction must be anterior, posterior, left, right, superior or inferior")
    zoom = finite(zoom, "zoom", 0.25, 4)
    node = managed_node(node_id, "sphere")
    view = view_widget("3D")
    bounds = node.GetPolyData().GetBounds()
    center = [(bounds[2 * axis] + bounds[2 * axis + 1]) / 2 for axis in range(3)]
    extent = max(bounds[2 * axis + 1] - bounds[2 * axis] for axis in range(3))
    axis, up = directions[direction]
    camera_node = host().modules.cameras.logic().GetViewActiveCameraNode(view.mrmlViewNode())
    if camera_node is None:
        raise RuntimeError("Native 3D view has no camera")
    camera = camera_node.GetCamera()
    camera.SetFocalPoint(*center)
    camera.SetPosition(*[center[i] + axis[i] * max(extent * 4, 1) for i in range(3)])
    camera.SetViewUp(*up)
    camera.SetParallelProjection(True)
    camera.SetParallelScale(max(extent * 0.65, 0.01) / zoom)
    view.renderWindow().GetRenderers().GetFirstRenderer().ResetCameraClippingRange()
    camera_node.Modified()
    expected_scale = max(extent * 0.65, 0.01) / zoom
    if (
        any(abs(a - b) > 1e-6 for a, b in zip(camera.GetFocalPoint(), center, strict=True))
        or abs(camera.GetParallelScale() - expected_scale) > 1e-6
        or not camera.GetParallelProjection()
    ):
        raise RuntimeError("Camera state readback mismatch")
    return verified(
        "Synthetic model camera configured",
        node_id=node_id,
        direction=direction,
        position=list(camera.GetPosition()),
        focal_point=list(camera.GetFocalPoint()),
        view_up=list(camera.GetViewUp()),
        parallel_scale=camera.GetParallelScale(),
    )


@operation
def configure_slice(node_id, view="Red", orientation="axial", offset_mm=0.0):
    if not isinstance(view, str) or view not in {"Red", "Yellow", "Green"}:
        raise InvalidInput("Slice view must be Red, Yellow or Green")
    orientations = {"axial": "Axial", "sagittal": "Sagittal", "coronal": "Coronal"}
    if not isinstance(orientation, str) or orientation not in orientations:
        raise InvalidInput("orientation must be axial, sagittal or coronal")
    offset = finite(offset_mm, "offset_mm", -10000, 10000)
    node = managed_node(node_id, "volume")
    view_widget(view)
    widget = host().app.layoutManager().sliceWidget(view)
    logic = widget.sliceLogic()
    composite = logic.GetSliceCompositeNode()
    composite.SetBackgroundVolumeID(node.GetID())
    composite.SetForegroundVolumeID(None)
    composite.SetLabelVolumeID(None)
    slice_node = logic.GetSliceNode()
    slice_node.SetOrientation(orientations[orientation])
    logic.FitSliceToAll()
    logic.SetSliceOffset(offset)
    actual = float(logic.GetSliceOffset())
    if (
        abs(actual - offset) > 1e-6
        or composite.GetBackgroundVolumeID() != node.GetID()
        or slice_node.GetOrientationString() != orientations[orientation]
    ):
        raise RuntimeError("Slice state readback mismatch")
    return verified(
        "Synthetic volume slice configured",
        node_id=node.GetID(),
        view=view,
        orientation=slice_node.GetOrientationString(),
        offset_mm=actual,
    )


def fit_image_dimensions(source_width, source_height, width, height):
    """Bounded aspect-preserving fit; at most one pixel of rounding per axis."""
    scale = min(width / source_width, height / source_height)
    fitted_width = min(width, max(1, round(source_width * scale)))
    fitted_height = min(height, max(1, round(source_height * scale)))
    return fitted_width, fitted_height, (width - fitted_width) // 2, (height - fitted_height) // 2


@operation
def export_view(filename, view="3D", width=800, height=600):
    """Native render-buffer export, not desktop capture; no other app is observed."""
    width = integer(width, "width", 128, 2048)
    height = integer(height, "height", 128, 2048)
    path = artifact_path(filename, ".png")
    if path.exists():
        raise InvalidInput("Output already exists; choose a new filename")
    widget = view_widget(view)
    import vtk

    widget.forceRender()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(widget.renderWindow())
    capture.SetInputBufferTypeToRGB()
    capture.ReadFrontBufferOff()
    capture.Update()
    dimensions = capture.GetOutput().GetDimensions()
    if dimensions[0] < 2 or dimensions[1] < 2:
        raise RuntimeError("Render buffer is unavailable; a working graphical context is required")
    resize = vtk.vtkImageResize()
    resize.SetInputConnection(capture.GetOutputPort())
    resize.SetResizeMethodToOutputDimensions()
    fitted_width, fitted_height, offset_x, offset_y = fit_image_dimensions(dimensions[0], dimensions[1], width, height)
    resize.SetOutputDimensions(fitted_width, fitted_height, 1)
    translated = vtk.vtkImageTranslateExtent()
    translated.SetInputConnection(resize.GetOutputPort())
    translated.SetTranslation(offset_x, offset_y, 0)
    letterbox = vtk.vtkImageConstantPad()
    letterbox.SetInputConnection(translated.GetOutputPort())
    letterbox.SetOutputWholeExtent(0, width - 1, 0, height - 1, 0, 0)
    letterbox.SetConstant(0)
    letterbox.Update()
    with tempfile.TemporaryDirectory(prefix=".dcc-mcp-render-", dir=path.parent) as directory:
        staged = Path(directory) / path.name
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(str(staged))
        writer.SetInputConnection(letterbox.GetOutputPort())
        writer.Write()
        if writer.GetErrorCode():
            raise RuntimeError("Native PNG writer failed")
        info = artifact_info(staged)
        reader = vtk.vtkPNGReader()
        reader.SetFileName(str(staged))
        reader.Update()
        image = reader.GetOutput()
        if image.GetDimensions() != (width, height, 1) or image.GetNumberOfScalarComponents() != 3:
            raise RuntimeError("Native PNG readback mismatch")
        scalar_range = list(image.GetScalarRange())
        if offset_x > 0:
            padding_sample = (0, height // 2)
        elif offset_y > 0:
            padding_sample = (width // 2, 0)
        else:
            padding_sample = None
        if padding_sample and any(image.GetScalarComponentAsDouble(*padding_sample, 0, c) != 0 for c in range(3)):
            raise RuntimeError("Letterbox pixel readback mismatch")
        publish_new(staged, path)
    return verified(
        "Synthetic view rendered and PNG decoded",
        **info,
        view=view,
        width=width,
        height=height,
        scalar_range=scalar_range,
        source_dimensions=list(dimensions),
        content_dimensions=[fitted_width, fitted_height],
        viewport_offset=[offset_x, offset_y],
        aspect_ratio_preserved=True,
        fit_mode="contain",
        resample_scale=[fitted_width / dimensions[0], fitted_height / dimensions[1]],
        padding=[offset_x, offset_y, width - fitted_width - offset_x, height - fitted_height - offset_y],
    )
