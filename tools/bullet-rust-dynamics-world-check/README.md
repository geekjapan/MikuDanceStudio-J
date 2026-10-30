# Private dynamics world comparison

`DiscreteDynamicsWorld` connects the accepted collision owner, clock, islands, numeric solver, and motion kernels. `WorldObjects` retains the only durable body, activation, joint, and motion arrays. The dispatcher retains contact points and receives solver impulse writeback. One solver workspace survives groups and steps. Its initialized backing remains distinct from its live prefix.

The owner returns the requested step count before clamping. It saves kinematic state with the native fixed timestep and adds gravity once per outer call. Each executed substep predicts motion, generates collisions, calculates islands from every cached pair's actual owner, solves, integrates through `set_center_of_mass_transform`, updates activation, and synchronizes motion states. A zero-step call still synchronizes. Forces clear last. Registration order controls the non-static traversal. Native default CCD thresholds are zero in this unit.

The public `lib.rs`, FFI, application backend, and production C++ sources retain their current implementation. Public cutover, MMD AxisSweep integration, ordinary removal, queries, actions, ticks, debug APIs, and CCD sweeps remain separate work.

## Hosted execution

The exact `w6-world-dynamics-owner` push trigger starts four native jobs and four Windows-source replay destinations. Manual dispatch is supplementary. Windows x64 uses `mmd-win64-sse`. Apple Silicon macOS and Linux x64 and ARM64 use `generic-reference`. All jobs pin Rust `1.95.0`. The workflow uses existing pinned Actions, read-only credentials, bounded timeouts, disabled cancellation, and always-uploaded partial diagnostics.

Run the checker only in the authorized hosted gate.

```sh
python3 -B tools/bullet-rust-dynamics-world-check/test_check.py -v
python3 -B -O tools/bullet-rust-dynamics-world-check/test_check.py -v
python3 -B tools/bullet-rust-dynamics-world-check/check.py --out-dir PATH --policy generic-reference
```

`--replay-dir PATH --policy mmd-win64-sse` requires an admitted actual Windows capture from the same HEAD and canonical source closure. There is no historical fixture fallback.

The native consumer includes the original `mds_bt.cpp`, uses its genuine constructors, and calls actual `mds_bt_world_step`. A separately observed build adds reversible diagnostic hooks to copied sources. The unmodified archive consumer and observed consumer must agree on all common outputs. No native manifolds are injected into the Rust owner.

The corpus includes warmstart contacts, joint and contact solves, multiple islands, six shared kinematic registration orders through the zero-effective-mass public constructor, moving kinematic bodies, sleep and wake, first `dt=0`, zero, variable and clamped calls, active gravity updates, motion synchronization, hash, forces, and shutdown. Counts come from `cases.py` and parsed records.

## Retained evidence

The reader and producer retain the accepted archive, include, allocator, source, and link primitives from the collision-owner checker. They bind all 114 original archive payloads, validated Darwin index outputs, extracted bytes, actual link selection, macro and ABI policy, tools, CRT inputs, physical Windows source bytes, canonical source, source-before and source-end maps, generated hooks and exact inverses, binaries, inputs, and raw output. Every process has PID, argv, cwd, UTC start and end, exit, and closed stream hashes. The four allocator modes retain their original chronology and lifecycle domains.

`R` records the actual returned count and state hash. `W` records initialized dynamics state in body order. `K` records the native clock. `Y` records actual prepare, ordered global body, manifold and joint selections, and completion. `V` records the cleared live prefix and retained workspace capacity. The reader rejects missing records, reordered phases, malformed words, duplicate indices, and unknown fields. Comparisons retain exact numeric words and order. Synthetic receipts in tests are inert protocol fixtures, not physics calculations or runtime evidence.

Every compiled mutant has a clean same-host baseline and must exit normally with a complete trace and a directed numeric or order difference. Mutants cover requested versus executed return, gravity accumulation, pair ownership, contact-only union, group and step workspace resets, missing normal impulse writeback, COM integration, zero-step synchronization, and force clearing. The group-reset mutant targets groups without kinematic endpoints, so an unknown retained slot does not replace its intended capacity witness with a crash.

The unchanged public constructor forces kinematic descriptor mass to zero, even when the descriptor supplies a nonzero mass. The public shim has no kinematic setter. The six shared registration cases cover this reachable zero-effective-mass state. Nonzero-inverse-mass kinematic retained-slot coverage is UNRUN and remains a future obligation for broader state coverage.

`UninitializedSolverSlot` is a promotion hold. The implementation does not initialize unknown slots, reset companions outside the accepted island boundary, or invent values. New NaN differences require an actual causal diagnosis and independent review. Existing GJK and mixed profiles grant no waiver for this corpus.

## Limits

Address-rank binding occurs at input-operation boundaries. A clamped call may execute several collision substeps between those boundaries. If an actual within-call tree lifetime changes order, that difference requires finer native observation and diagnosis. No universal allocation ordering is claimed.

Discovery consumes headers before pre-use snapshots. Tool and SDK receipts do not attest every compiler read or inner subprocess. The ordinary allocator mode has no raw callback corroboration. Generated typed-node metadata is not direct type observation of the original binary. Native physical deletes remain separate from Rust logical teardown. Read-only bits and hashes are custody evidence, not OS immutability.

Source admission, source-only helper results, actual Rust tests, native comparison, compiled mutants, general CI, and independent acceptance are separate receipts. Old collision checkpoint counts are not dynamics execution evidence.

The zero-step case retains its original force and torque clearing controls. It adds a public pose reset followed by two true zero-time fixed calls. The first call must expose synchronization in `B` motion and the `R` hash. The repeated call is a no-op control. A `W` velocity difference alone cannot satisfy the `zero-step-sync` witness. The 16 cases contain 212 checkpoints. Synthetic transition values are inert protocol data, not native rotation or integration results. New native baselines and normally exiting compiled mutants remain required.
