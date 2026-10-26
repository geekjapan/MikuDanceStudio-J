# Verify the DBVT tree kernel

Run `python3 tools/bullet-rust-dbvt-check/check.py --out-dir /tmp/bullet-dbvt`.
The check requires Clang C++, Python 3, and Rust 1.95.0. It compiles unmodified
vendored `btDbvt.cpp` and runs a native-free Rust harness. No World or GPU runs.

The stream covers 2,314 operations per native allocation history, including 12
seeded mutation histories, ordered TV and self TT callbacks, internal ray queries,
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
