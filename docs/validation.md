# Validation

## Automated development checks

```sh
python -m pip install -e '.[dev]'
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m pytest -q
python -m build --outdir /tmp/dcc-mcp-slicer-dist
```

Core `validate_skill` runs in the tests against the actual installable skill
folder. The official dcc-mcp-skills-creator `validate_skill_dir.py` also reports
clean declarations with no errors or warnings. Tests cover schema closure,
limits, type validation, path confinement, symlink rejection, overwrite refusal,
archive traversal/types/external references, encoded safe storage paths,
untrusted/tampered bundle refusal, synthetic-only save checks, canonical errors,
main-thread dispatch, pure-any dispatch, cancellation propagation, timeout
cancellation of queued mutations, shutdown, and real Core loopback HTTP
initialize/search/load/call/unload.

Unit tests use a fake PythonQt timer and do not claim to validate the Slicer GUI.
No real host is downloaded or installed by CI.

## Real Slicer MCP acceptance

Run in a **fresh process**. The script creates only mathematical synthetic data,
exercises the real embedded HTTP server from a separate client thread, then
stops the server and exits. The Slicer main thread remains free to pump Qt.
Never run the acceptance script by injecting it into a user's existing scene.

```sh
export SLICER_BIN=/path/to/Slicer
export DCC_MCP_SLICER_WORKSPACE=/absolute/new/empty/artifacts
export DCC_MCP_REGISTRY_DIR=/absolute/new/empty/registry
# Optional: dependencies installed into a separate Python-compatible site directory
export DCC_MCP_SLICER_TEST_SITE=/absolute/isolated/site-packages
bash scripts/run_live_smoke.sh
```

On a normal desktop, the script uses the active display and hides its own main
window. In headless Linux CI, the host needs a compatible Qt platform plugin or
virtual display. The validated container used its already-installed Qt5 offscreen
plugin via `QT_QPA_PLATFORM=offscreen` and `QT_QPA_PLATFORM_PLUGIN_PATH`; this is
environment-specific, not a portable Slicer requirement. No renderer/screenshot
validation is inferred from offscreen scene/API acceptance.

The artifact directory must be new: no-overwrite tests deliberately leave output
files intact. `result.json` contains full local evidence, native-thread IDs, MCP
responses and results. Keep local diagnostic logs private; they can contain local
paths. Generated MRB/NRRD/STL files are editable native artifacts, not mock exports.

## Recorded acceptance: 2026-10-02

- Host: 3D Slicer 5.10.0, embedded Python 3.12.10, Linux x86-64
- Runtime: released dcc-mcp-core 0.20.39 and dcc-mcp-server 0.20.39 wheels
- MCP: 2025-11-25 initialize, nonempty list, search and load `slicer-scene`
- Created: 32³ int16 toy volume, 64³ multi-material phantom and 962-point sphere
- Edited: sphere radius 10 → 14; native RGB/opacity readback
- Exported: native NRRD and STL, both nonempty and SHA-256 measured
- Saved/reopened: native MRB bundle, additive import verified from 3 → 6 nodes
- Phantom readback: scalar values 0/60/150/240, voxel counts
  201888/54480/3030/2746 respectively
- Thread proof: each domain success reports identical execution and application
  main-thread IDs; HTTP calls originate from a separate Python worker
- Negative MCP calls: oversized volume, unknown node and existing output refused
- Network proof: `/proc` ownership inspection found exactly one new listener,
  bound to 127.0.0.1; after `server.stop()`, no new listener remained
- Cleanup: `server.is_running == False`; no gateway started and no registration
  row was created in the isolated direct-mode registry

## Installed-wheel repeat

The complete live smoke also passed with the built adapter wheel installed into
an isolated dependency directory, with source-path injection disabled. The
recorded module origin was `site-packages/dcc_mcp_slicer/__init__.py`; Core came
from that same isolated installation. The tested wheel was
`dcc_mcp_slicer-0.1.0-py3-none-any.whl`, SHA-256
`0a5d8ada0dd58e0ce6021bc31a7550b36665f07d00ecd1a936367c9eb318bff3`.

To force this mode, install the wheel into the test environment and set
`DCC_MCP_SLICER_TEST_INSTALLED=1` alongside `DCC_MCP_SLICER_TEST_SITE` before
running the smoke. This validates a local build, not a published release.

## Gaps and limits

The original baseline did not validate patient/DICOM data, clinical workflow,
GUI screenshot/camera, official MCP SDK matrix, LAN/gateway, Windows/macOS or other
Slicer versions. Current hardening results are recorded separately below.
A normal async Core job is not an interruptible Slicer native call; native
import failures may change scene state; current exports stage before publication. Reopen is additive rather
than replacing the open scene and may import scene-level display state. Hash
receipts provide integrity only; use trusted local artifacts.

Python package installation and manual removal are supported. An automated
Install SOP execute/rollback tool and extension-manager integration are not
implemented. Source tests and one local host acceptance do not establish a
published-release certification or broad platform support.

## Hardening acceptance (2026-10-02)

The hardening candidate adds supported-host rejection, startup workspace checks,
terminal/idempotent dispatcher lifecycle, callback cleanup, fresh-instance restart,
optimistic native revision checks, creation admission bounds, atomic exclusive
publication and native camera/slice/PNG operations. The tests use released Core
0.20.39 and the official Python MCP SDK 1.30.0. Core protocol negotiation and
paginated tool discovery are exercised rather than simulated.

Source checks currently cover 76 passing tests. The official SDK negative suite
checks closed inputs, unknown fields, wrong types, oversize values and async job
failure results; schema failures are not assumed to be immediate synchronous
errors. The native source smoke passed synthetic volume/model/phantom creation,
NRRD/STL export, exclusive MRB+receipt save and additive 3→6 import, with exactly
one new loopback listener and none after stop. Rendering is a separate graphical
gate and is never inferred from that offscreen result.

Run the graphical acceptance in a fresh process on an already-working desktop:

```sh
DCC_MCP_SLICER_ACCEPTANCE_ROOT=/absolute/new/acceptance \
  bash scripts/run_graphical_acceptance.sh
```

The runner preserves the caller's existing display, isolates HOME/XDG/cache and
Core registry directories, and starts its own Slicer process. It never attaches to
an existing session. It uses the official SDK from a separate Python environment,
strips Slicer's Python/loader overrides for that child, and passes `-I`. Set
`DCC_MCP_SLICER_SDK_PYTHON` and `DCC_MCP_SLICER_TEST_SITE` to prepared environments.
Set `DCC_MCP_SLICER_TEST_INSTALLED=1` when TEST_SITE contains the installed adapter
wheel. The runner itself installs nothing.

The external client creates only mathematical data, validates advertised schemas,
configures model camera and orthogonal slice, renders and decodes PNGs, exports
native data, checks stale requests and overwrite refusal, round-trips MRB, and
issues concurrent reads. The host verifies its exact loopback listener, stops
idempotently, creates/stops a fresh server and exits with a bounded 300-second
client deadline. `sdk-result.json`, `sdk-transcript.json`, `host-result.json` and
PNG/native artifacts record the actual results. A failed gate stays a failure.

Known non-goals remain: untrusted clients, clinical/patient/DICOM workflows,
Windows/macOS and other Slicer versions, durable jobs, and interruption/rollback
inside a native import. Core's stock administration/introspection tools remain
present because no public least-privilege opt-out exists in 0.20.39. CI does not
install Slicer or claim native graphics acceptance. Remote CI/release/publishing
has not been run or authorized.

### Final installed-wheel graphical result

The final local wheel passed the graphical gate on 2026-10-02:

- Slicer 5.10.0, embedded Python 3.12.10, Linux x86-64, Core/server 0.20.39
- Official external MCP SDK 1.30.0, protocol negotiated as 2025-06-18
- 46 recorded tool calls, all twelve adapter tools exercised, with input/output
  schema validation and async jobs followed to terminal results
- Six-direction camera interface exercised through its anterior setting; native
  position/focal point/view-up/parallel-scale readback matched the request
- Red axial slice selected the synthetic phantom at 0 mm with native readback
- Real sphere and phantom PNGs decoded and visually inspected, 640×480 canvases
- Native captures were 411×352 (3D) and 412×352 (slice); contain-fit content was
  560×480 / 562×480, with centered horizontal padding. These are upsampled
  previews, not claims of native 640×480 rendering
- Pixel geometry regression measured the blue sphere at aspect ratio 0.99095;
  the earlier anisotropic resize measured 1.13575 and is rejected by this gate
- NRRD/STL exports, MRB+receipt save, additive 3→6 reopen, camera use after reopen,
  stale edit rejection, overwrite refusal and eight concurrent reads passed
- Exactly one new 127.0.0.1 listener; no new listener after stop or fresh-instance
  restart/stop; dispatcher timer stopped and external SDK child exited 0
- Import origin was the isolated lifecycle environment's site-packages, not src

The tested wheel SHA-256 is
`12325bfaf54fce63e45d049185e27ba7e44078ec2317233c651f7ed90f265400`.
All 76 source tests and all 76 installed-package tests pass. Discovery import and
manifest tests intentionally inspect the source declaration as well; installed
package files were separately matched byte-for-byte to the wheel. The final
installed offscreen native smoke also passed. Creator validation and strict
repository contract validation on a clean source copy have no errors/warnings.
Ignored build/cache directories explain the raw working-tree allowlist warnings.

The first graphical attempts exposed and fixed SDK environment contamination,
a test-helper argument collision, and native layout-owned storable nodes. Only
exact live slice-plane/transform and active-camera ownership references are
exempted from synthetic data checks. Non-owned camera, model and volume regressions
remain rejected. The later pixel inspection caught the aspect distortion that
nonempty-file tests alone had missed. These failed runs are not counted as passes.

### Standard package lifecycle rehearsal

A fresh owned environment installed the frozen baseline wheel, then explicitly
force-reinstalled the hardened wheel at the same prerelease version 0.1.0.
Installed package hashes matched the wheel. A corrupt-wheel attempt exited 1
without changing either package or distribution-metadata hashes. Uninstall made
both import and distribution lookup absent from an isolated clean working
directory. Reinstall matched the final wheel again, then the installed native
and graphical SDK acceptance passed.

This is standard pip lifecycle and failed-install preservation evidence. It does
not implement or certify Core Install SOP, automatic rollback, extension-manager
integration, external release CI, or publication. Keep the previous wheel for an
operator-directed rollback. No installed host/vendor package was changed.
