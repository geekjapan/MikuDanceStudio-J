# Windows CMake DBVT reference

This verification measures the current repository's native Windows x64 CMake target. It does not establish the behavior of a shipped MMD executable. Product Rust DBVT policy remains a separate decision.

The existing Windows build creates Bullet with Conan 2.27.1 in a fresh job-owned cache. The probe uses the application's generated Conan toolchain, Visual Studio 2022 generator, x64 architecture, Release configuration, C++17, and `BULLET275::BULLET275`. It compiles no Bullet implementation source. The normal application build gains logging-only `/VERBOSE:LIB`; its existing tests, camera oracle, and release packaging run before the measurement.

The workflow runs these commands from the repository root.

```powershell
python -I tools/bullet-dbvt-cmake-reference/test_check.py
python -I tools/bullet-dbvt-cmake-reference/check.py prepare --out-dir out/ci/dbvt-reference
# Existing normal CMake configuration, with logging-only /VERBOSE:LIB.
python -I tools/bullet-dbvt-cmake-reference/check.py record-build --out-dir out/ci/dbvt-reference --build-command cmake --build out/ci/build --config Release --parallel 4 -- /verbosity:normal /clp:ShowCommandLine
python -I tools/bullet-dbvt-cmake-reference/check.py measure --out-dir out/ci/dbvt-reference
```

`CONAN_HOME` must name a nonexistent directory directly inside `RUNNER_TEMP`. The workflow assigns a directory containing the run ID, attempt, and architecture. `prepare` captures the checkout, parents, event SHA, PR head and base, run, attempt, job key, runner image, and allowlisted `CL` and `_CL_` options. It saves the complete resolved Conan install graph. Cache paths use that graph's exact recipe revision, package ID, and package revision. The native CMake cache identifies the actual build and copied source directories.

The `dbvt-cmake-reference-x64` artifact contains these records.

- Actual CL, LIB, and LINK command evidence from normal build output and MSBuild tlogs, including expanded response files and their encodings, contents, and hashes.
- Project files, CMake caches, toolchains, compiler and MSBuild versions, and actual compiler source and header reads.
- Four package archives, their matching build-output hashes, and the DBVT object files. App and probe LINK commands must name those same four archive paths. Each target-specific LINK map must identify both `btDbvt.obj` and `btDbvtBroadphase.obj` from `BulletCollision`. Its exact LINK output, map path, executable hash, and matching linker-read task are recorded. Both LINK arguments and reads must uniquely name each canonical archive. Whole-build member log lines cannot supply this proof. The real CL `/Fo` output must exist, be the exact LIB input, and match the uniquely resolved archive member path and bytes. The probe object must also be the exact LINK input and read object.
- Original-flag preprocessing of `btDbvt.cpp`, `btDbvtBroadphase.cpp`, `btCompoundShape.cpp`, `btCompoundCollisionAlgorithm.cpp`, `scene_create.cpp`, and the probe. Replays remove compile and output modes and add `/E`, `/showIncludes`, and logging-only `/Bv`. They preserve ordered semantic flags. SDK include paths come from the matched compiler's `VsDevCmd.bat`; replay headers must cover actual CL read tlogs. Unknown or missing response files fail validation.
- Separate inline `Intersect`, `Select`, `Merge`, and template or virtual policy classifications. The post-header-undef aligned-local branches in `btDbvt.cpp` are recorded separately. Ordered DBVT definitions, undefinitions, floating-point, architecture, C++ standard, and forced-include flags must agree across translation units.
- Raw numeric inputs and outputs, native and Rust command records, executable hashes, source and header hashes, and a finalized artifact hash manifest. The report excludes itself and Rust build scratch from that manifest. The executed Rust executable is copied outside scratch and hashed with its generated source, build command, and toolchain record. Native probe source, compiler command, object bytes, LINK inputs, and executable bytes are associated explicitly. All captured process streams are closed before finalization.

Build output is bounded and filtered to compiler, librarian, linker, archive-member, and recognized compiler, linker, CMake, and Conan diagnostics. Retained lines are also forwarded to Actions output. Failures name the retained stdout and stderr paths. It does not retain an MSBuild diagnostic environment dump. Only compiler-relevant `CL` and `_CL_` options and replay include paths are saved. Missing identities, source association, link evidence, compiler flags, header closure, or changed archives produce an incomplete observation.

The runtime probes each have a ten-second deadline and bounded input and output. Input uses a temporary file, so a child that never reads stdin cannot block the caller. Process groups on POSIX and a kill-on-close Windows job terminate owned descendants. Teardown has an additional bounded five-second wait. They execute these operations.

| Capture | Execution | Comparison |
| --- | --- | --- |
| Directed Select | Three finite point inserts call the archive's `btDbvt::insert`; one probe-TU inline volume query records leaf order. | Current pure Rust DBVT inserts and query. |
| Direct AABB | Probe-TU inline `Intersect` and `Merge` in both orders on 51 runtime word rows. | Current Rust `Aabb::intersects` and both-order `merge`, 13 result words. |
| Archive Merge | Two archive inserts in a fresh tree in both orders for each row. | Insertion A then B compares against Rust `Merge(B,A)`; B then A compares against `Merge(A,B)`. All six words retain their exact bits. |
| Archive Intersect | Two proxies in a fresh archive broadphase. Immediate collision must be enabled. Read the sole pair's presence, then explicitly destroy both proxies. | Pair presence against current Rust AABB intersection. |

A separate native `dbvt_insert_order_control` links the same imported library and checks real two-leaf inserts with signed zeros and distinct quiet-NaN payloads against explicit reversed Merge arguments. It uses explicit failure returns even in Release. A local portable build of this small control exercises the checked-in DBVT source only and supplies no Windows reference evidence.

There is no NaN optimization, `calculateOverlappingPairs`, or additional tree mutation. Inputs retain zero signs and quiet-NaN payloads. Rust uses the existing DBVT, pair cache, math, and CRT math dependency sources with the pinned 1.95.0 toolchain and its existing host-specific profile. The generated Rust driver has no native Bullet FFI dependency and never changes the CMake probe's link or CRT settings.

`report.json` distinguishes observation from compatibility. A complete, valid numeric mismatch reports `observation=complete`, `compatibility=FAIL`, and `classification=compatibility-mismatch`. A missing or malformed capture reports `observation=incomplete`, `compatibility=not-evaluated`, and `classification=validation-gap`. Both exit nonzero. Neither outcome authorizes a product profile change.

Local parser controls and a portable syntax check do not execute the Windows reference. Only a completed Actions artifact can supply that evidence.
