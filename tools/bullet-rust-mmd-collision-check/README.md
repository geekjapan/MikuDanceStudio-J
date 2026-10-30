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
has been run locally. No compiled mutant is accepted.

The missing hosted acceptance work is explicit in `check.py`'s `PENDING` list.
It includes closed capture schema, include occurrence binding, extracted archive
membership, allocator chronology admission, full normally exiting directed
compiled controls, legal actual-capture admission before malformed peers, and
same-HEAD Windows producer admission with four destination replays. The current
common-output comparison excludes observer-only events, SAP arrays, spring
accessors, and generation identities. It is a diagnostic noninterference check.
It does not replace the missing provenance and actual-capture gates.

The initial workflow trigger is restricted to `w6-mmd-collision-owner` and uses
read-only contents permission. Its native and destination matrices target
Windows x64, Apple Silicon, Linux x64, and Linux ARM64. Until admission is
implemented, the native jobs fail and dependent replay jobs cannot accept data.
The existing General, discrete world, dynamics world, and GJK behavior gates
still require same-HEAD hosted execution before publication or acceptance.

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
