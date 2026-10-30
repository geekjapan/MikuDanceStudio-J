# Private MMD collision owner scaffold

This checkpoint connects one `WorldObjects` to `AxisSweep32` and the existing
`CollisionDispatcher`. It adds no public backend, stepping, or caller adoption.
`MmdCollisionWorld` registers the ground first, uses raw registration bounds,
updates current COM bounds with the contact margin, releases algorithms during
SAP updates, and precleans pairs before reverse proxy teardown.

The diagnostic native consumer includes the genuine `mds_mmd.cpp`. Its ray
accelerator remains enabled. Generated observation edits add read-only SAP and
spring accessors, lifecycle events, and native allocator chronology. Each edit
has an exact byte inverse. The Rust runner borrows the owner's existing objects
and dispatcher storage through a generated fixture. `W` independently seeds
already-created contacts on each side. No native manifold is transferred.

`cases.py` derives 55 cases from nine source-derived families. Huge boxes place
their center at their half extent so the lower edge remains within the SAP
range. The parser retains checkpoint, edge, pair, manifold, contact, and event
order. It preserves raw float words, including signed zero and NaN payloads.

## Current acceptance boundary

This is an incomplete verification scaffold. `admit_capture` rejects every
capture. A successful diagnostic comparison remains `DIAGNOSTIC_EQUAL_UNADMITTED`
and exits unsuccessfully at the admission boundary. The workflow cannot report
an accepted MMD migration from this checkpoint. No actual native or Rust binary
has been run locally. No compiled mutant is accepted. Control definitions live in `MUTANTS`; their count is derived at runtime and
is separate from the executed success count.

The missing hosted acceptance work is explicit in `check.py`'s `PENDING` list.
The hosted driver now records include occurrences before and after measured
compilation and resolves them again at the end. It binds every archive payload
to its compiled object and source, retains native link maps, and records native
allocation and physical deletion chronology. The compiled-control loop checks
a clean baseline, normal exit, full trace, and a directed field difference.
These paths remain unrun. Strict closed capture admission, legal actual-capture
admission before malformed peers, and Windows producer/replay admission remain
unimplemented. The replay body is wired behind that admission boundary. The current
common-output comparison excludes observer-only events, SAP arrays, spring
accessors, and generation identities. It is a diagnostic noninterference check.
It does not replace the missing provenance and actual-capture gates.

The initial workflow trigger is restricted to `w6-mmd-collision-owner` and uses
read-only contents permission. Its native and destination matrices target
Windows x64, Apple Silicon, Linux x64, and Linux ARM64. Until admission is
implemented, the native jobs fail and dependent replay jobs cannot accept data.
A separate four-host regression matrix retains the discrete world, dynamics
world, and GJK behavior gates. The unchanged General workflow still runs
`tools/rust/check.sh` on branch push. All require same-HEAD hosted execution
before publication or acceptance.

## Hosted commands

```sh
python3 -B tools/bullet-rust-mmd-collision-check/test_check.py -v
python3 -B -O tools/bullet-rust-mmd-collision-check/test_check.py -v
python3 -B tools/bullet-rust-mmd-collision-check/test_evidence.py -v
python3 -B tools/bullet-rust-mmd-collision-check/check.py --out-dir "$RUNNER_TEMP/mmd-collision-world"
```

Compilation is restricted to GitHub Actions. The diagnostic command records
actual child PIDs, UTC boundaries, executable hashes, source-before/end maps,
input/output hashes, normal wait results, and stream closure. These records are
not a strict admission seal. The source-only GJK admission remains `UNRUN`.

Rust ray queries, native allocator parity, MMD dynamics, nonzero-mass kinematic
stepping, public FFI adoption, and native-source deletion are outside this slice.
