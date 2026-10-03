# Installation and lifecycle

## Plan

Use a fresh supported Slicer installation and a separate process. Initial
validation targets Slicer 5.10.0's embedded Python 3.12. Do not install the unrelated
PyPI package named `slicer`. Review the adapter and Core dependencies first.

This checkout is the **Core/server 0.20.41 candidate**. The earlier native
acceptance used 0.20.39 and does not qualify this upgrade. Keep the frozen older
wheel and dependency environment for rollback; use a new isolated dependency
directory for the candidate. See [the upgrade record](docs/RUNTIME_UPGRADE_0_20_41.md)
for exact scope and the required native, graphical and MCP revalidation.

Create an empty trusted workspace for synthetic artifacts. Do not point it at a
patient-data directory, an untrusted download folder or a shared writable mount.
The adapter neither scans existing workspaces nor changes Slicer startup settings.

## Install

From the checkout, using the interpreter shipped with the selected host:

```sh
/path/to/Slicer/bin/PythonSlicer -m pip install /absolute/path/to/dcc-mcp-slicer
/path/to/Slicer/bin/PythonSlicer -c "import dcc_mcp_slicer; print(dcc_mcp_slicer.__version__)"
```

For an isolated dependency directory, use `pip install --target /trusted/site`
and add that directory to `sys.path` in your explicit Slicer startup script.
This avoids updating the host's existing dependencies. The live smoke supports
`DCC_MCP_SLICER_TEST_SITE` for this purpose. Package installation alone does not
prove that Slicer host APIs or the Qt dispatcher are working.

## Start and verify

Inside the application's Python console, set `DCC_MCP_SLICER_WORKSPACE` and call
`dcc_mcp_slicer.start_server()`. Pass `port=0` for an automatically assigned port;
leaving it unset also honors `DCC_MCP_SLICER_PORT`. Inspect `server.mcp_url` and
`server.is_running`. Verify MCP discovery, load and `scene_info`, then run the
synthetic creation/export smoke in a dedicated process.

The service is embedded and owned by the Slicer process. Default gateway port is
zero: it opens only a direct loopback MCP endpoint and does not start/elect a
machine-wide gateway or request LAN exposure. Use the returned direct URL;
registry registration is not promised when gateway participation is disabled.
A caller may explicitly configure Core gateway options for their deployment.

## Stop, upgrade and remove

Call `server.stop()` from Slicer's application thread before exiting, upgrading or
removing the adapter. Start a fresh Slicer process after package replacement.
Retain the previous wheel if an upgrade needs rollback; reinstall that wheel
with the same host interpreter. The adapter does not silently upgrade Core.

```sh
/path/to/Slicer/bin/PythonSlicer -m pip uninstall dcc-mcp-slicer
```

Only the adapter package is removed. Generated files and user-owned startup
scripts are retained. Remove an explicit startup import yourself if you added
one. This initial adapter supplies a documented manual lifecycle, not an automated
Install SOP executor or extension-manager installer; no such certification is claimed.

## Verified standard-package lifecycle

The local acceptance rehearsed baseline-wheel install, explicit same-version
`pip install --force-reinstall --no-deps` replacement, corrupt-wheel rejection
without modifying the previous installation, uninstall/import absence, and final
reinstall/native validation in a fresh isolated environment. This does not add an
automated installer or automatic rollback. For prerelease builds sharing 0.1.0,
identify the exact wheel by SHA-256, not the version string alone.

## Candidate dependency pins

The package pins both `dcc-mcp-core==0.20.41` and `dcc-mcp-server==0.20.41`.
The former 0.20.39 native profile remains historical evidence. Portable tests,
installed package checks and plugin discovery are distinct from native host
acceptance; a successful install does not qualify Slicer, camera rendering or
native cancellation on 0.20.41. Package resolution cannot silently select a
different Core/server release. The adapter exposes the existing `slicer` plugin
entry point and does not declare a command-line entry point.

To roll back, stop the candidate on Slicer's application thread, close that
dedicated process and start a fresh process using the preserved 0.20.39
environment and exact adapter wheel from baseline commit
`6ec3ff3b899b5c5bc76719ea70380d9e3953a57b`. Do not load both dependency trees into
one process or replace packages while an embedded server is running.
