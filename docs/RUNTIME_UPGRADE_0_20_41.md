# Core/server 0.20.41 candidate

This candidate updates both exact package dependencies and the bootstrap minimum
to the official stable `dcc-mcp-core==0.20.41` and `dcc-mcp-server==0.20.41`
releases. The skill compatibility declaration and executable CI installation
steps use the same versions. The official `dcc-mcp-cli` is a separate shared
runtime tool; this adapter continues to declare only the
`slicer = dcc_mcp_slicer.server:SlicerMcpServer` plugin and no adapter CLI.

## Frozen baseline and rollback

The source baseline is commit
`6ec3ff3b899b5c5bc76719ea70380d9e3953a57b`, which pins Core/server 0.20.39.
Its retained wheel has SHA-256
`171a79309e411408ff848b539d19ec2f75b7ad597450ec1786b127b0f8f83efa`.
The previous source, wheel and isolated environment are retained separately;
the candidate must be installed into a new environment or explicit isolated
dependency directory. Do not replace dependencies inside an active host.

Stop the candidate from the Slicer application thread and exit its dedicated
process before rollback. Start a fresh Slicer process with the preserved baseline
wheel and its exact Core/server 0.20.39 environment. Do not combine old and new
site-packages or treat the shared adapter version `0.1.0` as proof of wheel
identity; verify the artifact's SHA-256.

The Windows artifact publication fix (`r+b` before `fsync`) and 80-character
public scene filename/88-character integrity receipt fix remain present. The
public filename bound, path confinement, synthetic guard, no-overwrite semantics,
lazy host imports and owned application-thread dispatcher remain unchanged.

## Validation scope

New portable and installed-wheel checks must report the actually resolved
Core/server/CLI versions, Python version, MCP SDK version, wheel hashes and test
results in separate evidence. They do not inherit previous 0.20.39 results.
Windows checks exercise source/schema contracts, fake Qt lifecycle, synthetic
operation fixtures and real loopback HTTP through the official MCP SDK. These
checks do not demonstrate native Slicer APIs or an active graphical layout.

The 2026-10-03 isolated Windows 11 / Python 3.12.10 run resolved Core, server
and CLI to **0.20.41**, with the official MCP SDK **1.30.0**. Ruff lint and
format checks, the 85-case portable suite and wheel/sdist build all passed.
The suite had **84 passed and 1 skipped**: the existing symlink rejection case
requires a Windows account permitted to create symbolic links. No compatibility
failure, new runtime repair or new skip was introduced by this upgrade. This
measurement includes skill validation and real loopback HTTP tests, not native
Slicer execution. Separate installed-wheel evidence must still validate package
origins and the declared plugin from the built artifact.

The records in `validation.md`, `architecture.md` and `wire-cancellation-validation.md`
describe earlier Core/server 0.20.39 measurements. Native Slicer 5.10.0, native
camera/slice rendering and native asynchronous cancellation must be rerun with
the exact new installed wheel. The manual `native-wheel` workflow requests this
acceptance from an explicitly provisioned Linux/Slicer 5.10 runner; its presence
does not mean it ran or passed. No new Windows/macOS native support is claimed.

## Trust boundary

Core's loopback defaults do not authenticate clients or establish a least
privilege endpoint. This adapter still assumes trusted local clients and an
operator-controlled synthetic workspace. The runtime upgrade does not claim to
solve Core administration, dynamic registration or embedded fallback risks.
Remote CI, native host acceptance and graphical MCP acceptance remain separate
requirements before the upgraded candidate can be called production ready.
