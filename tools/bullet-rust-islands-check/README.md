# Bullet 2.75 SimulationIslands verification

This gate compares the native island manager and World scheduling methods with `core/islands.rs`. It does not run a numeric constraint solver or connect the Rust public World.

Run from the repository root with Clang, Python 3 and Rust 1.95.0 installed.

```sh
python3 tools/bullet-rust-islands-check/check.py --out-dir /tmp/bullet-islands
```

`--record` updates only the dedicated `tests/islands_data` fixtures. Existing fixtures remain unchanged. `pure_bullet.rs` registers the frozen replay in the existing Windows x64, Apple Silicon macOS, Linux x64 and Linux ARM64 CI matrix. The native Linux job recaptures the corpus and runs the mutation checks. Configuring these jobs does not establish a hosted PASS.

## Native boundary

The oracle compiles the actual sources under `recipes/bullet275/bullet-src/src`, with `det_math.h`, `sse_emu`, `BT_NO_PROFILE=1`, Clang `-O2 -ffp-contract=off -fno-fast-math`, and the pinned Rust CRT math library. Exact commands, compiler/target provenance, all preprocessor macros and source hashes are saved in the output directory.

Each scenario constructs a real `btDiscreteDynamicsWorld`, collision dispatcher and 32-bit axis sweep, then registers rigid bodies in dense collision-object order. Explicit default/all broadphase filters keep test pair insertion independent of the World's static default arguments. The hashed pair cache receives serialized pair insertions. Its endpoint UIDs increase with registration, so the input generator serializes those cache endpoints in UID order. The Rust island implementation accepts the supplied endpoint order without normalization. Standalone union-find and constraint cases exercise reversed endpoints separately.

Manifolds come from `btCollisionDispatcher::getNewManifold`, including zero-contact and far-contact manifolds. A small point-to-point constraint subclass supplies explicit zero/nonzero row counts. Collision disabling is a real `addConstraint` argument. Bullet 2.75 has no `setEnabled` API here. Island scheduling does not inspect either constraint row counts or collision disabling.

Manager scenarios snapshot update, constraint union, store and build separately. The manager-only constraint union loop mirrors the caller. World scenarios independently call the actual protected `calculateSimulationIslands` and `solveConstraints` methods through a subclass. A `btConstraintSolver` recorder captures `prepareSolve`, every `solveGroup` array, and `allSolved`. It does no numeric emulation. The ordered arrays contain registration indices found by pointer equality, never pointer values or stable application body IDs.

`observe.py` copies the source tree into the output directory and inserts observers at reset, find, unite, sort, group sleep, manifold wake, group scan, cursor advance and constraint sorting. Source hashes and exact diffs identify every insertion. The original and observed executable stdout must be byte-identical across the full corpus. Observers write a separate trace. Branch assertions require sleeping and awake groups, skipped and active scans, wake passes, and cursor advances. The original repository C++ sources remain unchanged.

## Serialized schema

The schema identifier is `bullet275-islands-v1`. `schema.json` records status, complete and compact input/output hashes, source/hook provenance, compiler flags, macro hash, toolchain and allocator history. `sha256.json` includes the verifier, kernel, activation dependency, fixtures and native sources. `branches.json` reports actual observed branch counts. `summary.json` records exact scenario/snapshot/mutation counts.

Every input row is a complete scenario and begins with a case ID. Integers are decimal. Float values are decimal raw `u32` words, including NaNs and signed zero. The native parser rejects missing or trailing tokens; the Rust parser does the same.

- `U n command_count commands...` resets a union-find of size `n`. Commands are `J p q`, `F x` and destructive final `S`. Each command produces a snapshot with its return value and every `(id, size_or_body_index)` element.
- `W n split mode objects... pair_count pairs... constraint_count constraints... manifold_count manifolds...` constructs a complete world scenario. Each object has `state classification_bits contact_response deactivation_time_bits initial_tag initial_companion hit_fraction_bits`. Each pair has two dense endpoints. Each constraint has `a b row_count disable_linked_collisions`. Each manifold has `a b point_count distance_bits`. Mode zero uses staged manager APIs; mode one uses the real World methods.

World output rows contain `case phase element_count elements... object_count objects... event_count events...`. Each object stores `registration_index state classification_bits contact_response tag companion hit_fraction_bits deactivation_time_bits`. `C island_id body_count bodies... manifold_count manifolds...` records a manager callback. `P object_count manifold_count`, `G body_count bodies... manifold_count manifolds... constraint_count constraints...` and `A` record solver preparation, a solve call, and completion. The replay generates and compares every output token and rejects trailing input.

Observer rows use `UF operation arg result element_count elements...`, `O operation a b c object_count objects...`, or `Q constraint_count constraints...`. Object observer records contain index, state, tag, companion and both float words. Sleep arguments are root/all-sleeping/group-size. Scan arguments are root/any-inactive/manifold-cursor. Cursor arguments are root/new-cursor/manifold-count. Wake arguments identify the dispatcher manifold index. The trace retains defined state only. Padding, absolute addresses and uninitialized manifold fields are excluded; no float word is masked.

The frozen fixture is a complete compact scenario prefix, including all activation states 0 through 5, all static/kinematic flag combinations, response filtering, empty/far manifolds, OR-active constraints, equal-root swaps, union cycles and path halving, skipped-group cursors, unsplit wake side effects, and 127/128/129 single and multiple islands. The full run adds deterministic random scenarios after that prefix.

## Mutation checks and limits

Each mutation is compiled independently and must fail an exact native snapshot assertion. Compilation failure does not count. The suite covers weighted/reverse union, omitted path halving, manifold-only unions, both pair merge guards, both constraint classification guards, active OR changed to AND, omitted state initialization/store, stable/Rust unstable/tiebreak sorting, awake predicates, protected setters, response-before-wake filtering, `isActive` outer filtering, empty/far manifold removal, any-inactive versus all-inactive skip, stale cursors, min/max island keys, unsorted arrays, preparation/completion order, and real minimum-128 batching with tail flushing. Manifold-only and empty/far mutations modify the compiled endpoint adaptation because the production kernel deliberately borrows endpoint-only views.

Native 2.75 calls each active island with work immediately. There is no minimum solver batch size. The 127/128/129 cases include both large individual islands and many small islands.

No public World wiring, dispatcher algorithm ownership, numeric solver state, application body/proxy ID registration, or shared kinematic companion policy is implemented here. A nonzero-inverse-mass kinematic shared across separate numeric solver calls can retain a stale companion ID in native 2.75. That requires a bounded native reproducer and a defined-behavior/UB decision in the later World numeric integration. This port neither resets those companions nor unions kinematic islands to hide the issue.

Empty split mode is covered. Empty unsplit mode is excluded because native takes `&collisionObjects[0]` on an empty array. Invalid endpoints and union-find use after destructive sort are outside the native defined-input contract. No broader input restriction, threshold relaxation or NaN mask is introduced.
