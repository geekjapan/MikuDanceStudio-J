# Persistent solver workspace comparison

Run `python3 tools/bullet-rust-persistent-solver-check/check.py --out-dir /absolute/evidence/path`.
The four supported hosts run this command through `bullet-persistent-solver.yml`.

`persistent-solver-v1` is distinct from the fresh mixed-solver trace schema. It
compares all six registration orders, two consecutive steps and six controls per
order against actual native World island scheduling. The native collision inputs
are replayed through Rust `SimulationIslands::calculate` and immediate solver
callbacks. Rust retains one workspace, performs the existing body integration,
and checks incoming second-step transforms, velocities and normal impulses.
Collision generation and a complete Rust World are outside this check.

`G` records ordered global body/manifold selections, `BPOOL` records the incoming
live length/capacity, and `S` records setup live length/capacity, row endpoint IDs
and live owners. `V` records final linear/angular velocity words. The native
observer never reads retained non-live owner fields. Original and observed native
stdout and collision-input captures must agree exactly.

The safe Rust model keeps initialized backing slots separate from the live prefix
and modeled native capacity. Group writeback consumes the group and writes only
live entries. IslandObject owns companion IDs; only native island step stages
reset them. An unknown uninitialized slot returns `UninitializedSolverSlot`.
This is measured compatibility with observed retained allocation behavior, not a
portable C++ lifetime guarantee.

The checker compiles behavioral mutants for retained zeroing/writeback, append
overwrite, capacity/live confusion, per-group resets, same-slot simultaneous
writes, wrong endpoint mass, selection order, and step-wide workspace clearing.
It records source/fixture hashes, observer differences, commands and outputs in
the requested evidence directory.

Historical mixed-solver measurements remain bound to their original producer
hashes. This check does not approve a changed mixed arithmetic source profile.
The separate mixed checker must retain its capture and reject unknown current
source profiles until an independently audited exact profile is approved.

The original 36 scenes remain the ordered prefix. An additional 48 scenes cover
nonzero-row linear and angular motors, both endpoint orientations, all six body
registration orders and SIMD/scalar modes. Their finite asymmetric contact history
crosses real World island groups. Initial velocity inputs are captured before
stepping. Second-step state still comes from Rust integration. A newly generated
contact (native lifetime 1) must have zero warmstart; surviving contacts must match
Rust's prior writeback. A source-copy mutant suppresses both joint delta resets
and must differ in complete first-step final velocities from genuine native
output. Separate controls suppress only the linear or angular reset. `JROWS`
records nonzero joint row endpoint IDs, including reachable same-slot aliases.

The live source manifest recursively includes the complete CRT Rust source tree.
Closure tests reject omitted compiled modules, altered math module contents and
new source files at the end gate. Start and end manifests are retained separately.
Use `--mutation joint-delta-reset` to run only the new native mutation control
when the unrelated workspace controls have already been verified.
