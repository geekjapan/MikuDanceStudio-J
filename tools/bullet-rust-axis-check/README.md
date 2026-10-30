# Verify 32-bit sweep-and-prune pair maintenance

Run from the repository root:

```sh
python3 tools/bullet-rust-axis-check/check.py --out-dir /tmp/bullet-axis-sweep
```

This compiles the real, unmodified vendored `bt32BitAxisSweep3` and hashed cache
at `-O2`, compares their trace to the committed fixture, and runs the pure Rust
fixture test. It requires Python 3, Clang C++ and Rust 1.95.0. No native World,
GPU, deterministic CRT shim, or signed-overflow compiler override is used.
The native implementation is not replaced with a formula in the driver.

`--record` replaces the input and native fixtures. Ordinary checks never write
fixtures. Output includes the compiler command, complete operation stream and
native trace. Every supported host must run the native check. Local Apple Silicon
success does not establish Windows x64 or Linux x64/ARM64 success.

The native subclass only reads protected edges, live handle fields, active count
and free-list head. Each operation records all three ordered edge arrays with
indices, quantized positions and handles; live UIDs, filters, owner/parent tokens
and six edge indices; ordered pairs with algorithm and user-data tokens; and
separate ordered algorithm destructor and dispatcher-free events. Undefined,
uninitialized native handle fields are never inspected. Fresh add does not
initialize the native cached AABB, so this Rust unit exposes no cached-AABB getter.

The 4,974-operation fixture includes 32 seeds with 128 mixed operations each,
plus algorithm attachments every thirteen mixed operations. Directed cases cover
empty maintenance, three identical points and their historical pair order,
small full pools, LIFO handle reuse, empty and nonempty reset, touching/separated
boxes, each-axis expansion/shrinkage, teleports, unchanged quantization, filters
including signed bit 15, boundary-adjacent f32 values, out-of-world coordinates,
and large finite values. A real native 1,500,000-capacity constructor is also
checked. Invalid keys, unordered/nonfinite input AABBs and capacity overflow are
internal precondition violations. Rust's capacity assertion is tested separately;
native release-mode undefined behavior is not treated as an outcome to preserve.

`AxisSweep32::new_mmd` uses the application's [-10000,10000] bounds and 1,500,000
live-handle capacity. Handle zero is reserved in addition to that capacity. Tests
use a constructor with smaller bounds/capacity but the same algorithm. Pools grow
lazily using a high-water mark and freed-handle LIFO. This preserves valid handle
allocation order, UIDs and capacity, but does not reproduce native eager memory
allocation or allocation-failure timing.

The application enables a DBVT ray accelerator. This bounded pair-maintenance
oracle deliberately passes `disableRaycastAccelerator=true`. DBVT, generic ray,
CCD/query behavior, `unQuantize` (including native ushort truncation), deferred or
sorted pair caches, optional user pair callbacks, and application World wiring
remain outside this unit. There is no full-world completion claim. Production
continues to use the native implementation.

`core/axis_sweep.rs` is an altered Rust translation of this repository's locally
modified Bullet 2.75 distribution. The original zlib notice is preserved. Existing
local-patch ancestry is outside this unit's audit.

Integration owner must register `core::pair_cache` and `core::axis_sweep`, register
`tests/pure_bullet/axis_sweep.rs` in the common pure test driver, add this tool to
the host CI/integration gate, and run `tools/rust/check.sh`. These shared files are
intentionally outside this unit's exclusive write scope.
