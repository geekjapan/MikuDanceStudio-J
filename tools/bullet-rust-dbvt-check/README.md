# Verify the DBVT tree kernel

Run `python3 tools/bullet-rust-dbvt-check/check.py --out-dir /tmp/bullet-dbvt`.
The check requires Clang C++, Python 3, and Rust 1.95.0. It compiles unmodified
vendored `btDbvt.cpp` and runs a native-free Rust harness. No World or GPU runs.

The stream covers 2,326 operations per native allocation history, including 12
seeded mutation histories, ordered TV, self TT, and cross-tree TT callbacks, internal ray queries,
margin and velocity update, lookahead, clear, bottom-up, top-down, and incremental
optimization. AABB values compare exact float bits; metadata and ordered children
compare exactly. Native compiler commands, inputs, and complete traces remain in
the output directory. Regenerate them for each host; they are not portable frozen
allocator fixtures.

The native driver controls actual allocations with the official allocation hooks.
This distribution's generic `btAlignedAllocInternal` bypasses the aligned hook,
so the driver also installs `btAlignedAllocSetCustom`. It retains the native
alignment header and never modifies Bullet source. Ascending, descending, and
alternating address histories exercise actual native pointer comparisons. The
private Rust test observer assigns these observed ranks to corresponding live
nodes after each strict comparison. Production always compares actual stable
`Box<Node>` addresses. Normal allocator topology and callback ordering depend on
allocation history and are not claimed to be allocator independent.

The tree owns one cached free Box. Deleting another node drops the former cache;
creation consumes it. Lifetime IDs are private and never escape through callers.
Callers identify live leaves with the existing `pair_cache::ProxyKey`. Duplicate
insertion and operations on absent keys panic, matching native caller preconditions.

The module is an altered translation of the locally modified Bullet 2.75 sources.
The full zlib notice is preserved in `core/dbvt.rs`. Ancestry of local native
changes outside this unit remains unaudited. This slice deliberately does not
register the module, modify shared test drivers, or wire World/broadphase stages.
KDOP, OCL, clone, softbody, and compound helpers are outside this application's
required tree API.

The original seeded `t 4` operation at row 295 crashes native Bullet with stack
overflow. `native-topdown-nontermination.tsv` preserves the complete reproducer.
Native counts centers with `> 0` and partitions with `< 0`; a zero center and a
positive center can therefore produce an empty left partition. The Rust version
falls back to the existing bottom-up builder for an empty partition. This is a
localized behavior repair for native nontermination, not a native parity claim.
Terminating native cases retain strict comparisons. The regression validates
termination, retained exact leaf bounds, tree links, and query sets. A second
regression reduces the failure to two boxes.

An additional ordinary native allocator run compares exact leaf volume bits and
query sets with production Rust addresses. Its optimization topology and callback
order are intentionally conditional on each allocator's addresses. A direct Rust
sort test checks that the actual larger parent address triggers a rotation and
that Box addresses remain stable.

The standalone harness compiles unmodified `core/math.rs` as a path dependency.
`cargo clippy --manifest-path tools/bullet-rust-dbvt-check/Cargo.toml --all-targets
--no-deps -- -D warnings` lints the changed DBVT and harness without linting that
unchanged dependency. Without `--no-deps`, existing `Vec3::add` and `Vec3::sub`
trigger `should_implement_trait`. No lint allowance is added to production code.

Current native evidence is Apple Silicon macOS with the generic DBVT profile.
The source selects Windows DBVT SSE proximity association and unordered comparison
semantics separately from generic math. Windows x64 native recapture, Windows Rust
branch execution, and Linux x64/ARM64 native recaptures remain pending. A generic
macOS topology fixture is not evidence for the Windows SSE profile.

The two native comparison tests require `DBVT_FIXTURES` to name the capture
output directory. `check.py` sets it. Shared-suite registration must preserve
this capture step or move these tests behind the standalone harness.

The lifecycle probe additionally compares actual allocator release events for
empty, single-leaf, populated, cached-free, and completely removed trees. Each
case runs implicit destruction and repeated explicit clear followed by destruction.
The Rust owner is moved before teardown. Native uses the official allocator hook
with real `malloc`/`free`; Rust observes real 16-byte-aligned Box allocations and
`System` deallocations. Fixed buffers avoid allocations inside callbacks, and
allocation/release counts guard the observer's scope. Neither probe changes the
production address comparison or simulates the native deletion algorithm.
`native-lifecycle.tsv` and `rust-lifecycle.tsv` record scenario, explicit-clear
flag, allocation count, pre-teardown release count, and the complete release
sequence of allocation ordinals, including the final cached node.
