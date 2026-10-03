# Contributor instructions

- Keep host API imports lazy. All MRML/VTK/Qt work runs on Slicer's application thread
- Reuse DccServerBase, DccServerOptions, HostExecutionBridge and Core result helpers
- Do not parse skill manifests in adapter runtime or access the private inner server
- Keep tools typed, bounded and synthetic-only. Never test with patient data
- Preserve path confinement, no-overwrite defaults and loopback-only default startup
- New native long operations are asynchronous; document cancellation limits honestly
- Run ruff check/format, pytest, skill validation and an isolated live Slicer smoke
- Keep artifacts outside the repository. Distinguish mock, native and HTTP evidence
- No publication or releases without the owner's separate authorization
