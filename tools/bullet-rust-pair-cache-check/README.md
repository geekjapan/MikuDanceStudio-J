# Verify the hashed pair cache

Run from the repository root:

```sh
python3 tools/bullet-rust-pair-cache-check/check.py --out-dir /tmp/bullet-pair-cache
```

The check compiles the real vendored `btHashedOverlappingPairCache` at `-O2`,
checks its output against the committed fixture, and runs the pure Rust fixture test.
It requires Python 3, Clang C++, and Rust 1.95.0. It uses no World, shape, rigid body,
GPU, deterministic CRT shim, or native library build. The native sources are unmodified.
No flag changes signed overflow behavior. The native hash uses signed `int` shifts
and overflow, so every supported host must run the real native comparison.

`--record` replaces both fixtures. Use it only when deliberately changing the
operation stream or auditing a native behavior change. A normal check never writes
fixtures. Output includes the native compiler command, input stream, and native trace.

The fixture covers 2,323 operations. It includes 32 deterministic seeds with 64 mixed
operations each. Directed cases cover empty operations, reverse and duplicate add,
filter changes, signed masks and bit 15, collisions, repeated growth, removal with
compaction, scan revisits, clean, proxy removal, UID reuse, signed hash boundaries,
and the direct pair constructor's UID tie rule.

Each trace row contains the operation result, ordered pairs, logical capacity,
buckets, live next links, and callback events. Pairs record both proxy identity and
current UID, algorithm token, and user data. `-` means absent, so a removed pair with
zero user data differs from an absent pair. The native driver observes protected
hash tables through a subclass. It does not replace the cache algorithm. Real
collision algorithm destructors and dispatcher frees emit separate ordered events.
The trace excludes nonlive next slots because native removal leaves stale links.

`core/pair_cache.rs` is an altered Rust translation of this repository's locally
modified Bullet 2.75 distribution. The zlib source notice is preserved. Upstream
ancestry of existing local changes remains outside this unit's audit.

The combined strict suite registers this fixture through `super::core::pair_cache`.
The dedicated CI runs all 14 frozen-fixture tests on four supported hosts and
recaptures this native operation stream on Linux x64. Other native host captures
remain unverified until run separately.
