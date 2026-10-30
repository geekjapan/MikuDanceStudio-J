# Private MMD collision owner check

`MmdCollisionWorld` connects one `WorldObjects` to `AxisSweep32` and the existing
`CollisionDispatcher`. It registers the ground first, uses raw registration
bounds, updates current COM bounds with the contact margin, releases algorithms
during SAP updates, and precleans pairs before reverse proxy teardown. Public
backend selection, stepping, and caller adoption remain outside this change.

The native consumer includes the genuine `mds_mmd.cpp`. Its ray accelerator stays
enabled. Generated observations add read-only SAP and spring accessors,
algorithm/manifold lifecycle events, Bullet aligned-allocation events, and
explicit body/joint physical deletion events. Every generated edit has an exact
byte inverse. Ordinary C++ heap allocations and inner toolchain subprocesses are
not attested. Rust ray/query and accelerator allocation parity are not claimed.

Aligned-allocation events record requested payload bytes. A zero-byte request
still owns its positive, unique, aligned pointer and requires a corresponding
free before world and final closure. Bullet's default collision configuration
constructs `btStackAlloc(0)`; `btStackAlloc::create` unconditionally requests
`btAlignedAlloc(size,16)`. The default allocator reserves pointer metadata and
alignment padding even for zero payload bytes. Allocation event sequences remain
consecutive across worlds, including zero-byte requests and their frees.

The Rust runner uses generated access to the owner's existing storage. `W` seeds
nonzero warmstart values independently into already-created legal contacts on
each side. Native contacts are never transferred to Rust.
The generated `--cfg test` source tree includes the DBVT test fixture and its
included regression TSV; both are bound by the same source manifest as the core.

`cases.py` derives 55 cases. Huge boxes place their center at their half extent,
keep their lower edge inside the SAP range, and cover float32 bounds below,
equal to, and above `1e12`. Motion, reseat, and stop-at use separate interpolation
velocity markers. The parser preserves checkpoint, SAP edge, pair, manifold,
contact, and event order. It preserves raw float words and NaN payloads.

The hosted driver records actual child PIDs, UTC boundaries, resolved tool
hashes, source-before/end maps, include occurrences before and after measured
compilation, archive payload/source/object identities, link maps, binary
production/use/execution identities, normal waits, and stream closure. A fixed
recipe checks command order, arguments, output roles, and corpus inputs. Rust
and native linker identities are recorded before use. The driver selects the
recorded Rust linker and the recorded non-Windows native linker explicitly.

Expanded-policy command labels use lowercase source stems. Source paths and
`policy-btDbvt.json` / `policy-btDbvtBroadphase.json` retain their exact casing.

Compiled controls must exit normally, produce a complete valid lifetime trace,
match a fresh same-host clean baseline, and differ in their intended semantic
fields. Algorithm and manifold generations have separate lifetime checks. The
delayed-release control remains a valid complete trace and differs in event
timing. Counts come from the corpus, command records, and control definitions.

`admit_capture` requires frozen producer member size/SHA and closed-command authority.
It authenticates each member once and parses only the retained immutable bytes, including
the manifest itself. It rederives observations
and mutations from current source, checks command and include ownership, and
compares the complete genuine native and Rust outputs. The native driver first
admits the actual compiled capture before constructing bound malformed peers.
It publishes `CONTROLLED_PASS` only after those peers are rejected and the final
closed capture is admitted again. Replay requires an admitted same-HEAD Windows
producer and validates its own current-source command and binary receipts. Windows
uses a detached authority receipt whose size/SHA comes from the explicit Windows
producer job outputs. Replay authenticates those receipt bytes before JSON parsing.
All JSON members and authority receipts have an 8 MiB limit.
Complete closed commands are stored once in `command-records/000001.json` and subsequent ordinal files.
`commands.json` and the detached authority contain ordered label/path/size/SHA commitments;
readers authenticate every record through the same capture cache before parsing its complete observations.

## Verification status

These producer/admission/replay paths have not run on a native host locally.
No native comparison, compiled control, actual capture admission, or Windows
replay is accepted from source checks. Their first legal executions and any
required repairs remain GitHub Actions work after independent source review.
The source-only GJK admission remains `UNRUN` and changes no historical record.

The initial workflow trigger is restricted to `w6-mmd-collision-owner`. It uses
read-only contents permission and four native plus four Windows replay targets.
Targets are Windows x64, Apple Silicon, Linux x64, and Linux ARM64. A separate
four-host regression matrix retains discrete world, dynamics world, and GJK
gates. The unchanged General workflow runs `tools/rust/check.sh` on branch push.

```sh
python3 -B tools/bullet-rust-mmd-collision-check/test_check.py -v
python3 -B -O tools/bullet-rust-mmd-collision-check/test_check.py -v
python3 -B tools/bullet-rust-mmd-collision-check/test_evidence.py -v
python3 -B tools/bullet-rust-mmd-collision-check/check.py --out-dir "$RUNNER_TEMP/mmd-collision-world" --authority "$RUNNER_TEMP/mmd-collision-authority.json"
```

Compilation and actual-capture tests are hosted-only. MMD dynamics,
nonzero-mass kinematic stepping, public FFI adoption, native-free product builds,
and C++ source deletion remain separate work.
