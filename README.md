<p align="center"><img src="https://raw.githubusercontent.com/dcc-mcp/.github/main/profile/dcc-mcp-logo.png" width="180" alt="DCC MCP"></p>

# dcc-mcp-slicer

A typed **3D Slicer** adapter for DCC MCP. Create bounded mathematical volumes,
material phantoms and sphere meshes, inspect and edit them, then export NRRD/STL
or round-trip a native MRB scene bundle through MCP. Configure native cameras and
orthogonal slices, then render bounded PNG previews.

**Current candidate:** trusted local synthetic workflows with exact
**dcc-mcp-core 0.20.41 / dcc-mcp-server 0.20.41** dependencies. Native Slicer,
graphical camera/render and native MCP cancellation acceptance must be rerun for
this candidate. The earlier Linux native evidence used **Slicer 5.10.0 /
Python 3.12.10 / Core and server 0.20.39**; it does not qualify the upgraded
runtime. See the [runtime upgrade and rollback record](docs/RUNTIME_UPGRADE_0_20_41.md).
Synthetic data only; no patient data, medical interpretation, clinical claims,
DICOM import or arbitrary scene-file loading.

## Quick start

Install this checkout with Slicer's bundled **PythonSlicer**, not system Python:

```sh
/path/to/Slicer/bin/PythonSlicer -m pip install /path/to/dcc-mcp-slicer
```

Set up a dedicated, trusted artifact directory, then run in a fresh Slicer
Python console:

```python
import os
from dcc_mcp_slicer import start_server

os.environ["DCC_MCP_SLICER_WORKSPACE"] = "/absolute/existing/synthetic-artifacts"
server = start_server()  # OS-assigned loopback port; gateway disabled by default
print(server.mcp_url)
```

Keep `server` alive. Call `server.stop()` from the same application/main thread
to shut down. A stopped server/dispatcher is terminal; call `start_server()` again
to create a fresh instance. See [installation and removal](install.md), [architecture](docs/architecture.md),
and [reproducible validation](docs/validation.md).

## MCP workflow

Initialize a normal MCP Streamable HTTP client at the printed URL:

1. `search_skills({"query":"slicer synthetic"})`
2. `load_skill({"skill_name":"slicer-scene"})`
3. Call the returned canonical tool slug, for example:
   `slicer_scene__create_phantom({"size":64})`
4. Use returned node IDs with the edit/export tools
5. Poll Core's `jobs_get_status` with the returned job ID for asynchronous calls

| Tool | Result |
| --- | --- |
| `capabilities` | Bounds and supported formats without host access |
| `scene_info` | Bounded synthetic-node metadata and native execution-thread evidence |
| `create_volume` | 8–128³ int16 mathematical sphere volume |
| `create_phantom` | Centered 16–128³ sphere with sphere/cylinder inclusions; four scalar materials |
| `create_sphere` | Polygonal sphere with bounded radius and resolution |
| `edit_sphere` | Native geometry replacement, RGB color and opacity |
| `export_node` | New NRRD or STL artifact; existing files rejected |
| `save_scene` | Native synthetic-only MRB scene and integrity receipt |
| `reopen_scene` | Additive import of an unchanged locally saved MRB; existing nodes retained |
| `configure_camera` | Six deterministic model-facing camera directions and bounded zoom |
| `configure_slice` | Synthetic volume, Red/Yellow/Green view, orthogonal orientation and offset |
| `export_view` | Native 3D/slice render buffer, 128–2048 px PNG, decoded before publication |

Prefix each local tool name with `slicer_scene__`. Core may advertise shortened
aliases or paginate/cap tool listings; the `load_skill` response contains canonical
registered slugs. This package does not implement its own MCP wire protocol.

## Boundaries

- MRML, VTK and Qt calls execute on the Slicer application thread
- Startup rejects unsupported Slicer versions and missing workspaces. Synthetic
  node creation/import is capped at 100 nodes
- Node readback includes a session-local revision. Pass `expected_revision` to
  sphere edit/export to reject stale requests; reacquire node IDs after reload
- Output paths are plain basenames in the configured workspace; traversal,
  symlinks and overwrite are rejected. Native writes use private staging and
  exclusive atomic publication; failed/cancelled exports do not publish partial files
- Only adapter-marked synthetic nodes can be edited/exported; scene saves reject
  non-synthetic storable data, including hidden storable nodes
- MRB imports have size, archive-path, member-type and external-reference checks
- The workspace must be operator-controlled and trusted. A hash receipt detects
  accidental changes; it **does not authenticate third-party content**
- Native save/load/export calls are asynchronous but cannot be interrupted after
  entering Slicer. Poll the existing job; never replay a timed-out mutation
- Trusted loopback clients can also access Core administration/discovery surfaces.
  This adapter is not a sandbox for hostile clients or third-party skills
- PNG rendering requires a working native graphics context and active graphical
  layout. This captures only Slicer view buffers, never the desktop or other apps
- Windows/macOS and Slicer versions outside the 5.10 family are not supported by
  this profile. Earlier native acceptance used 5.10.0 with runtime 0.20.39;
  the 0.20.41 candidate still requires the same native acceptance procedure

## Development

```sh
python -m pip install -e '.[dev]'
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m pytest
python -m build --outdir /tmp/dcc-mcp-slicer-dist
```

CI runs source, closed input/typed output schemas, the official MCP SDK, real
loopback HTTP and fake-timer tests. Real Slicer
acceptance is a separate executable smoke; it is not silently replaced by mocks.
No package release or automated publishing workflow is enabled.
