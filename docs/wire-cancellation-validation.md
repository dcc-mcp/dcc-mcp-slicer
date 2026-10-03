# Native wire cancellation and pinned wheel acceptance

The historical Core/server 0.20.39 graphical acceptance includes a controlled test-only pause after
real Slicer native export has produced a 96,084-byte STL staging file. The official
MCP SDK receives the export job ID, sends DELETE to that Core job endpoint, and
then releases the callback into the adapter's existing cancellation checkpoint.
HTTP 204 and terminal `cancelled` are observed. A later `scene_info` traverses the
same native lane and verifies that the callback actually exited, the final file
was never published, the staging directory was removed, and the scene remains
usable. The script adds no product tool and never claims to preempt native calls.

The pinned fresh wheel also repeats the full graphical workflow: all 12 tools,
51 recorded MCP calls, camera/slice PNGs, native NRRD/STL, MRB 3-to-6 additive
reopen, 8 concurrent reads, loopback listener cleanup, Qt timer stop and a new
server-instance restart. Source/installed unit suites remain 76 distinct tests;
scripted graphical calls are not added to that suite count. Sphere aspect remains
0.99095 with truthful native-buffer letterboxing.

Both Core and server package requirements now pin the 0.20.41 candidate. The
0.20.39 measurements above remain historical and do not qualify this upgrade.
No native adapter implementation changed in the runtime-pinning increment.
Native graphical and wire-cancellation acceptance must be repeated with the exact
new installed wheel; full automated Install SOP and remote exact-head CI remain
separate gates. See [the runtime upgrade record](RUNTIME_UPGRADE_0_20_41.md).
