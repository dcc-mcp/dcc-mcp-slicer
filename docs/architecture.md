# Runtime architecture

The running Slicer process owns `SlicerMcpServer`, derived from Core's public
`DccServerBase`. `DccServerOptions.from_env` owns option resolution. A
`HostExecutionBridge` is attached before skill discovery, and Core owns catalogs,
HTTP/MCP, progressive skill loading, async jobs, envelopes and shutdown.

Slicer uses **PythonQt** (`qt`), not PySide/PyQt. `SlicerDispatcher` subclasses
Core's `HostUiDispatcherBase`. A PythonQt QTimer is created on the main thread
and drains the shared queue on its 10 ms ticks with a 5 ms pump budget. The budget
bounds scheduling, not a native call's duration. The worker-side `poke_host_pump`
never calls Qt. The bridge's public `dispatch_callable` seam delegates to the
Core queue; it does not create a second script executor or queue.

Core attaches its native HTTP queue to the same dispatcher. Main-affinity scripts
therefore run on the original application thread, with an additional thread guard
before importing or using Slicer/VTK. Pure capabilities metadata is affinity-any.
An idle UI does not require scene polling. If a modal dialog or busy native call
blocks Slicer's event loop, calls may time out; clients must query existing jobs.

The package has no host imports at discovery time and no global server singleton.
The application version is cached during construction, so registry callbacks do
not query Qt from a worker. Core owns the canonical result shape; domain outputs
are under `context`, errors are string codes, and mutations include readback
postconditions. Async native operations check cancellation before entry, but
cannot interrupt Slicer midway or promise rollback after native failure.

## Data and security model

This is an initial synthetic-workflow adapter. Bounded int16 arrays are generated
mathematically. Synthetic node attributes restrict editing/exporting and are
preserved in native scene serialization; they are not an authentication mechanism.
An operator must use a trusted local workspace and dedicated Slicer process.
Third-party MRB files and receipts are unsupported even if renamed to match.

Archive validation rejects traversal, symlinks, unexpected members, excessive
compressed/uncompressed sizes, XML declarations with entities and external MRML
file/URI references. Reopen is additive and capped at 100 synthetic nodes. The
adapter refuses to save any scene containing unmarked storable data. No DICOM,
patient imports, arbitrary source execution or raw script tool is added by this
package. Core administrative and external skill surfaces retain Core's own
capabilities; only trusted clients should connect to the loopback endpoint.

## Upstream contracts

- [Core adapter onboarding](https://github.com/dcc-mcp/dcc-mcp-core/blob/main/docs/guide/new-adapter-onboarding.md)
- [Core dispatcher API](https://github.com/dcc-mcp/dcc-mcp-core/blob/main/docs/api/dispatcher.md)
- [Slicer Python scripting](https://slicer.readthedocs.io/en/latest/developer_guide/python_faq.html)
- [Slicer script repository](https://slicer.readthedocs.io/en/latest/developer_guide/script_repository.html)

Development consulted the official dcc-mcp-creator and dcc-mcp-skills-creator
packages and organisation repository/adapter contracts. Runtime code does not
parse their markdown or declarations. Historical validation used the exact Core
0.20.39 release. The current candidate pins Core and server to 0.20.41;
qualification of that upgrade is tracked separately in the
[runtime upgrade record](RUNTIME_UPGRADE_0_20_41.md). Unreleased source-head APIs
are not required.

## Hardened lifecycle and commit boundaries

The supported embedded host profile is Slicer 5.10.x with Python 3.12. Unsupported
hosts and missing workspaces fail before creating a timer or listener. Options or
startup failure closes the owned timer. Stop must run on the application thread,
is idempotent, disconnects the timer callback, schedules its deletion and shuts
down Core queues. Reusing a closed server fails explicitly; restart creates a new
server and Core queue. No old queued request is reused by that instance.

Creation checks the 100-node budget before allocating native data. Failure removes
the newly created data and its own display/storage nodes. Optional optimistic
revision guards include native node/data modification times plus bounded metadata;
revisions are session-local and must be reacquired after imports or outside edits.

NRRD/STL exports use Slicer's `exportNode`, preserving existing scene storage
filenames. All file exports write to a private same-filesystem staging directory,
validate nonempty bounded output, then check cooperative cancellation and publish
using an exclusive hard link. An existing output, including one created while the
native writer was running, is never overwritten. Temporary files are removed on
all ordinary success/failure/cancellation exits. Filesystems must support hard links.
Native calls may run to completion after cancellation, but cancelled staged output
is not published if Core delivers cancellation before the commit checkpoint.

The MRB and JSON receipt cannot be made one atomic filesystem transaction. The
receipt is published first and the MRB last as the commit marker. If final
publication fails, the operation removes only its own linked receipt. A process
crash may leave an orphan receipt; reopening requires both files and a matching
hash. Scene import itself is monolithic and can change MRML/display state before
a failure; cancellation/rollback of an already-entered import is not promised.

Camera and slice tools use native MRML/VTK APIs on the application thread. PNG
export uses a native render buffer and validates its decoded dimensions/components,
never a desktop screenshot. It rejects non-synthetic visible displayable data and
requires a working native graphical context. No custom GUI input provider is added.

## Core security boundary

The historical Core 0.20.39 review found stock introspection, dynamic-registration
and administrative surfaces in addition to this adapter's twelve typed tools;
empty MinimalModeConfig did not remove those builtins. These observations describe
the earlier artifact and do not qualify the pinned Core/server 0.20.41 candidate.
This package does not patch private Core internals.
A public least-privilege Core opt-out remains an upstream requirement before this
endpoint could be offered to untrusted clients. Loopback is a reachability limit,
not authentication. The artifact workspace restrictions apply to typed adapter
tools and assume trusted local clients and operator-controlled files.

Fresh graphical Slicer creates three intrinsic slice-plane models/transforms and active 3D camera. The
synthetic-scene guard recognizes only objects returned by live layout slice-logic and camera-logic
ownership references. A matching name is insufficient. User-created/imported
non-synthetic volume/model nodes remain forbidden even if SaveWithScene is false.

PNG export captures the current native viewport at its actual resolution, then
fits it into the requested canvas with centered black letterboxing. It reports
source_dimensions separately from canvas width/height, content_dimensions,
viewport_offset, resample_scale and left/bottom/right/top padding. Pixel scaling
preserves aspect ratio within integer-pixel rounding; it does not claim a native
render at the larger output resolution. Decoded padding pixels are checked.
