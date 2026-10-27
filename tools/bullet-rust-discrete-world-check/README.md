# Private discrete collision-world checks

`DiscreteCollisionWorld` connects the existing `WorldObjects`, default-owned DBVT, pair cache, and persistent dispatcher. `lib.rs`, the public FFI, and application backend keep their native implementation.

The owner registers raw current shape bounds. Updates expand each side by `0.02` and accept the current static bit or an expanded diagonal squared length strictly below `1e12`. Rejected updates preserve the proxy and request activation state 5 through the protected setter. The default updates every registered body. Public kinematic transforms keep the existing motion-state semantics.

Shutdown cleans each body's matching algorithm slots in cache order before reverse proxy destruction. All body storage and the dispatcher remain alive through synchronous release. Native joint and physical body deletion events have a separate ledger. Rust does not claim the same physical deletion timing.

## Hosted checks

`.github/workflows/bullet-discrete-world.yml` starts on the exact private branch and supports manual dispatch after publication. Four jobs compile on Windows x64, Apple Silicon macOS, Linux x64, and Linux ARM64. Four jobs replay the current Windows capture. Rust is pinned to `1.95.0`.

`check.py --out-dir PATH --policy generic-reference` builds the 114-member Bullet archive, extracts every member, and links a consumer that includes the unchanged `mds_bt.cpp`. The consumer calls the genuine world, body, and joint constructors, original collision-world methods, and original destruction. The Windows policy is `mmd-win64-sse`. `--replay-dir PATH` requires a complete current Windows capture with exact physical sources, canonical source closure, native inputs, and commit identity.

`evidence.py` is the common entrance for completed native captures. Native finalization admits an in-memory schema 2 report and manifest before publishing those exact bytes, with the report replaced last. Refusal leaves a diagnostic `FAIL`. Windows replay consumes only admitted rows, bound inputs, and the producer report digest. Its schema 3 output cannot substitute for a native capture. Source-only handoffs are a separate contract.

Admission checks caller-supplied current HEAD, canonical source bytes, corpus, and allowed host/policy. It binds source start/end, physical checkout and Git attributes, exact generated hooks and inverses, ordered commands and retained outputs, pre-use direct inputs, all 114 source/object/archive payload/extracted-member relationships, consumer overrides and actual link selections, produced/use/executed/end binary identities, eight traces, allocator and physical ledgers, bound Rust comparisons, and all seventeen clean-baseline directed semantic controls. Counts are derived from the corpus and parsed results. Closed schemas reject unknown fields, missing or extra paths, duplicates, case collisions, nonfinite numbers, and booleans in integer fields.

The reader limits file and directory counts to 24,000, each file to 512 MiB, total bytes to 4 GiB, and relative paths to 1,024 characters before reading payloads. It rejects symlinks and nonregular files. Windows path identities use Windows semantics on every replay host. Root mappings use path components. JSON object key order has no meaning; command, traversal, archive-member, mode, and mutant arrays retain their real order.

Each native C++ compilation has a separately labelled discovery compilation. The checker retains discovery outputs, reads and stores the discovered include bytes, snapshots them before measured compilation, requires the measured include list and hashes to agree, and checks the union again at the end. Discovery itself consumes headers before that snapshot. These receipts do not attest to the compiler's internal reads.

Resolved executable bytes and hashes are retained before use and checked at the end. Rustup and its actual pinned rustc have separate identities. Native Rust builds explicitly select the resolved linker driver. Unix native consumer links use the linker discovered by the compiler and an explicit selector. Windows records the existing developer environment's resolved `link.exe`; this does not attest to cl's internal subprocess selection. Relevant named compiler/linker settings are recorded without an environment dump. Inner driver subprocesses, compiler libraries, the SDK, and the full operating environment are not attested. Replay preserves its original implicit Rust linker behavior and records that remaining gap. Selector changes do not claim byte equivalence with former implicit linkage.

The exact native schedules include 119 discovery commands: 457 commands on Windows and 345 on Unix. Replay has 87 commands, including the actual pinned compiler-path receipt, and no native discovery or explicit linker selector. All commands must exit normally. Blanket `/W0` and `-w` suppression is absent; numeric, ABI, CRT, and deterministic-math options are preserved.

The checker retains expanded DBVT policies, fourteen ABI and deterministic math macros, the direct Rust CRT library, archive members, link selections, and produced and executed binary identities. Original dispatcher and world source copies receive bounded observation hooks. Exact inverse edits recover the original physical bytes, including Windows line endings. Unmodified archive consumers supply the common-output control.

Algorithm allocation generations and manifold allocation generations have independent ledgers. Plane-plane algorithms can own no manifold. Snapshots retain registration order, activation, current, interpolation, and motion transforms, requested and leaf AABBs, proxy owners and UIDs, pair order, manifold owners, initialized numeric words, contact lifetimes, and synchronous release. No snapshot comparison sorts pairs or manifolds.

The corpus separates public-shim operations from generated fixture injection for activation, flags, and independent transform sentinels. It covers all 16 ordered shape pairs, force-update states, the strict huge-boundary cases, filters, disabled joint collisions, no-contact response, stale pairs, fixed-tree migration, reactivation, repeated dispatch, allocation reuse, and shutdown.

The controlled allocator and node-rank checks reuse the accepted broadphase method. Production Rust has no address override. Three controlled allocation orders and the ordinary allocation run remain finite observations. They do not establish universal allocator-independent ordering.

Seventeen owner-connection mutants must compile, exit normally with zero status, produce a complete valid trace, and change the intended semantic fields against a clean same-host Rust baseline. Compile, parser, crash, and timeout failures do not satisfy this requirement. The dedicated six behavior tests and unchanged 97-test native-free suite run separately.

## Compiler-free checks

`python3 -B tools/bullet-rust-discrete-world-check/test_check.py -v` runs the ten existing helper controls and ten complete-admission test methods. The latter construct independent synthetic Windows, Linux, and Darwin capture records using the full current source closure and real 81-case, 707-checkpoint corpus. Refusal controls refresh the manifest and affected command-output/artifact digests. They exercise required evidence families, source end/transport, flags/tools/environment, objects/archive payloads, includes/policy/overrides/binaries, modes/lifetimes, directed mutant witnesses, native finalization, Windows replay entry, and distinct replay schemas. Synthetic bytes are never actual execution evidence. The same command with `-O` checks that validation survives optimization. These commands do not compile or run Rust or C++.

The private source packet records these compiler-free checks. All Rust tests, native consumers, compiled mutants, cross-host numeric comparisons, and final integration remain `UNRUN` until root-owned GitHub Actions and independent artifact acceptance.

## Exclusions

Solver stepping, islands, motion integration, CCD, queries, actions, ticks, clocks, MMD deferred AxisSweep and null-cache acceleration, ordinary body removal, and public backend adoption remain separate work. Both shims use a null debug drawer. The nonnull warning latch is outside this boundary. Intel Mac and Win32 are unsupported. Existing GJK admission updates authorize source identity only and do not inherit earlier executions.
