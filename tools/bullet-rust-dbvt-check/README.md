# Verify the DBVT tree kernel

Run `python3 tools/bullet-rust-dbvt-check/check.py --out-dir /tmp/bullet-dbvt --expected-profile generic --rust-policy generic-reference` on macOS/Linux. Windows uses `--expected-profile sse --rust-policy mmd-win64-sse`.
The check requires Clang C++ (or activated MSVC x64 on Windows), Python 3,
and Rust 1.95.0. It compiles unmodified
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
changes outside this unit remains unaudited. This slice registers the module and pure tests. It does not wire World/broadphase stages.
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

Existing native evidence is Apple Silicon macOS with the generic DBVT profile.
The dedicated `bullet-dbvt-hosted.yml` runs the complete check on ubuntu-24.04,
ubuntu-24.04-arm, macos-15, and windows-2022 with Rust 1.95.0. It triggers on
pushes to `w3-bullet-dbvt-hosted` and manual dispatch. Hosted execution remains
pending until an actual run succeeds. A generic macOS fixture does not prove
Windows SSE parity.

The gate asserts actual CPU architecture and the profile observed from
`btDbvt.h`. Windows uses `/DWIN32`, `/O2`, `/MD`, `/EHsc`, and `/fp:precise`,
matching the original CMake MSVC x64 SSE selection. Other hosts require generic
DBVT. Each host retains the original 2,326 operation prefix and appends 29 bounds/root-vs-leaf operations: 7,065 strict snapshots, 2,355 ordinary allocator comparisons, and 10 native/Rust lifecycle cases. An
additional directed Select test compares native and Rust callback order for
point boxes whose float association distinguishes generic from SSE. Its native
inputs and output are separate from the original corpus.

Windows also compiles a diagnostic oracle with `det_math.h` force-included and
without adding `WIN32`. Source inspection of `build.rs` and locked `cc` 1.10.0
predicts generic DBVT despite `BT_USE_SSE`. This remains an inference until the
hosted run records actual macros. The diagnostic requires generic selection and
saves four native address-history traces plus the directed case. These traces
are never compared with the Windows Rust SSE kernel. Ambient `CL`, `_CL_`, and
`CXXFLAGS` values are recorded. Unexpected profiles fail. This probe does not
claim to build or execute the full FFI library.

The vendored header undefines its DBVT configuration at the footer. The
profile-only probe includes an output-directory copy with observation constants
inserted before cleanup. The copy is marked as altered and its hash is saved.
Oracle and lifecycle programs include the original unmodified header and
algorithms. `BT_HAS_ALIGNED_ALLOCATOR` must remain undefined, retaining Bullet's
raw allocation hooks and hidden alignment header. Only oracle arena storage
uses matched `_aligned_malloc` and `_aligned_free` on Windows. Lifecycle raw
`malloc` and `free` observation remains unchanged. CRLF and LF are normalized
only when comparing lifecycle event records.

Artifacts include compiler commands as JSON argument arrays, tool versions,
runner image, commit, source SHA-256 hashes, stdout and stderr logs, inputs,
profiles, lifecycle events, and native captures. Failed commands preserve logs.
Profile or architecture mismatches fail without weakening comparisons. No
intentionally crashing native top-down or overflow input runs. Existing Rust
repair regressions still run.

Run cheap helper checks with
`python3 -I tools/bullet-rust-dbvt-check/test_check.py -v` and repeat with `-O`.
Add `--expected-profile generic --expected-arch arm64` to `check.py --rust-policy generic-reference` on Apple
Silicon, or `--expected-profile sse --expected-arch x64 --rust-policy mmd-win64-sse` in an activated MSVC shell.

The two native comparison tests require `DBVT_FIXTURES` to name the capture
output directory. `check.py` sets it. They are callable helpers with mandatory standalone wrappers; pure tests do not require native captures.
`DBVT_POLICY` is required by the wrappers and is explicitly set by the checker.

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

Destructive optimization detaches the root before fetching and freeing internal
nodes. An unwind during rebuilding therefore cannot make Drop traverse the old
links. Test-only fault injection after fetch exercises both public optimization
entry points in child processes and catches the original panic through Drop.
This guarantees safe destruction on that unwind, not transactional rollback or
reuse of a partially rebuilt tree.

Finite AABB endpoints do not imply a finite size heuristic. Three identical
boxes from zero to `1e20` overflow the native `f32` size computation. When no
candidate satisfies the existing strict comparison, Rust uses the first pair.
All selected finite-native comparisons and their order remain unchanged. Native
Bullet leaves pair indices at `-1` in this case and then indexes them, so this
fallback is a deliberate safety repair with no native parity claim. The large
finite regression checks both optimization entry points in child processes,
exact leaf-bound bits, live links, leaf count, volume queries and self-tree pairs.
Before the repair both children aborted from a second panic in Drop.

`Dbvt::new(DbvtPolicy)` requires an immutable explicit policy. There is no host
inference or default. `MmdWin64Sse` is the future production policy on all four
targets; `GenericReference` is used for genuine generic native comparisons.
Cross-tree and root-vs-leaf TT require matching policies. `bounds()` reads the
actual root, including after clear (which preserves native leaf count).
`collide_leaf` reads the stored leaf volume and uses native TT traversal order,
including suppression of the same leaf. Node IDs remain private.

The small `tests/dbvt_data` fixtures are raw actual-Windows CMake run 40465192152,
artifact 12716603181. Their provenance binds ZIP/member hashes, source association,
commands and results. Registered pure tests replay all 51 numeric rows, both
archive Merge insertion orders, and directed Select on every target. These are
numeric fixtures, not portable allocator goldens.

The hosted workflow additionally replays the fresh Windows controlled captures
on all four Rust targets using `--replay-dir ... --rust-policy mmd-win64-sse`.
These results are labelled Windows-sourced replay. The local native generic lanes
remain separate. The checker compiles and runs a genuine Rust numeric binary
with each policy: both must exit zero with the complete numeric schema; the
wrong generic policy must disagree on exactly cases 27..50 and directed Select.
It never edits oracle output or emulates native Windows SSE on ARM.

No World, production broadphase integration, allocator-independent callback order,
or full public acceptance follows from this bounded core unit. Hosted execution
and independent reviews are required before root acceptance.
