# Private discrete collision-world checks

`DiscreteCollisionWorld` connects the existing `WorldObjects`, default-owned DBVT, pair cache, and persistent dispatcher. `lib.rs`, the public FFI, and application backend keep their native implementation.

The owner registers raw current shape bounds. Updates expand each side by `0.02` and accept the current static bit or an expanded diagonal squared length strictly below `1e12`. Rejected updates preserve the proxy and request activation state 5 through the protected setter. The default updates every registered body. Public kinematic transforms keep the existing motion-state semantics.

Shutdown cleans each body's matching algorithm slots in cache order before reverse proxy destruction. All body storage and the dispatcher remain alive through synchronous release. Native joint and physical body deletion events have a separate ledger. Rust does not claim the same physical deletion timing.

## Hosted checks

`.github/workflows/bullet-discrete-world.yml` starts on the exact private branch and supports manual dispatch after publication. Four jobs compile on Windows x64, Apple Silicon macOS, Linux x64, and Linux ARM64. Four jobs replay the current Windows capture. Rust is pinned to `1.95.0`.

`check.py --out-dir PATH --policy generic-reference` builds the 114-member Bullet archive, extracts every member, and links a consumer that includes the unchanged `mds_bt.cpp`. The consumer calls the genuine world, body, and joint constructors, original collision-world methods, and original destruction. The Windows policy is `mmd-win64-sse`. `--replay-dir PATH` requires a complete current Windows capture with exact physical sources, canonical source closure, native inputs, and commit identity.

The checker retains effective compiler commands, include hashes, expanded DBVT policies, ABI and deterministic math macros, the direct Rust CRT library, archive members, link selections, and produced and executed binary identities. Original dispatcher and world source copies receive bounded observation hooks. Exact inverse edits recover the original physical bytes, including Windows line endings. Unmodified archive consumers supply the common-output control.

Algorithm allocation generations and manifold allocation generations have independent ledgers. Plane-plane algorithms can own no manifold. Snapshots retain registration order, activation, current, interpolation, and motion transforms, requested and leaf AABBs, proxy owners and UIDs, pair order, manifold owners, initialized numeric words, contact lifetimes, and synchronous release. No snapshot comparison sorts pairs or manifolds.

The corpus separates public-shim operations from generated fixture injection for activation, flags, and independent transform sentinels. It covers all 16 ordered shape pairs, force-update states, the strict huge-boundary cases, filters, disabled joint collisions, no-contact response, stale pairs, fixed-tree migration, reactivation, repeated dispatch, allocation reuse, and shutdown.

The controlled allocator and node-rank checks reuse the accepted broadphase method. Production Rust has no address override. Three controlled allocation orders and the ordinary allocation run remain finite observations. They do not establish universal allocator-independent ordering.

Seventeen owner-connection mutants must compile, exit normally with zero status, produce a complete valid trace, and change the intended semantic fields against a clean same-host Rust baseline. Compile, parser, crash, and timeout failures do not satisfy this requirement. The dedicated six behavior tests and unchanged 97-test native-free suite run separately.

## Compiler-free checks

`python3 -B tools/bullet-rust-discrete-world-check/test_check.py -v` runs synthetic parser and lifetime controls, actual-source inverse checks, mutation-anchor checks, corpus checks, and physical-delete ledger controls. The same command with `-O` checks that validation survives optimization. These commands do not compile or run Rust or C++.

The private source packet records these compiler-free checks. All Rust tests, native consumers, compiled mutants, cross-host numeric comparisons, and final integration remain `UNRUN` until root-owned GitHub Actions and independent artifact acceptance.

## Exclusions

Solver stepping, islands, motion integration, CCD, queries, actions, ticks, clocks, MMD deferred AxisSweep and null-cache acceleration, ordinary body removal, and public backend adoption remain separate work. Both shims use a null debug drawer. The nonnull warning latch is outside this boundary. Intel Mac and Win32 are unsupported. Existing GJK admission updates authorize source identity only and do not inherit earlier executions.
