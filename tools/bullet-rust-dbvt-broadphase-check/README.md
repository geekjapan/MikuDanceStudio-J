# Default-owned DBVT broadphase verification

This checker compares the Rust lifecycle with the repository's unmodified Bullet
2.75 `btDbvtBroadphase` and its default owned hashed pair cache. The core requires
an explicit immutable `DbvtPolicy`. It does not connect the public World or the
AxisSweep ray accelerator.

`manifest.json` fixes 16 histories and 1,193 checkpoints. The corpus covers
create, touching and filtered boxes, duplicate add attempts, unchanged and
contained updates, signed prediction, margin, teleport, stage refresh, two-cycle
migration, fixed reactivation, cleanup budget and cursor, swap removal, real
sphere algorithm/manifold creation and synchronous release, UID reuse, live and
empty reset, and fixed optimization at 99, 100, 101 and 200 leaves. Pair creation
uses actual tree queries. There is no pair injection.

The workflow builds a real native archive separately on Windows x64, Apple
Silicon macOS, Linux x64 and Linux ARM64. It retains actual compiler arguments,
include receipts, object hashes, archive members and extracted member bytes,
consumer link maps, compiler identity, expanded policy bodies and runtime macros.
The archive and its new oracle consumer must select the same observed policy.
This is a new standalone consumer measurement. It does not assert equivalence to
a CMake or final Rust FFI consumer.

Three native allocation histories install both raw and aligned callbacks in
ascending, descending and alternating order. The current non-debug, non-CellOS,
non-`BT_HAS_ALIGNED_ALLOCATOR` profile uses the raw callback. A node's raw request
is `sizeof(btDbvtNode) + sizeof(void*) + 15`. The bounded 64-bit layouts admit
56-byte nodes with type alignment 8 and 79-byte requests, or 64-byte nodes with
type alignment 16 and 87-byte requests. Both request alignment 16. The node
volume, parent and child-union offsets must be 0, 32 and 40 bytes respectively. The size-matched arena returns a backing slot, and Bullet
adds its own header and alignment to produce the node at backing + 16. Other
allocations of that size may also use slots. Raw fallback uses malloc/free;
aligned fallback keeps its separate hidden-header pair. Slots have stride 128
and are never reissued, including across history resets. Unknown macro or layout
profiles fail without changing Bullet flags.

Each actual mode invocation writes `allocator-<mode>.jsonl` through a separate
oracle argument. The `profile` invocation and every strict allocator header
record actual `sizeof`, `alignof`, field offsets, raw request size and allocator
macro states. `node_alignment` is the requested alignment 16;
`node_type_alignment` is `alignof(btDbvtNode)`. Header layout facts must match
the validated native profile exactly during local capture and Windows replay.
The header also records mode, hook selection and arena geometry. A diagnostic
header emitted before a fatal layout guard does not prove that hooks ran.
Each checkpoint records its identity, cumulative raw/aligned allocation/free
callback counters and size-matched arena callback events in actual order. Event
ordinals count all callbacks on that route, including fallback allocations.
The first checkpoint includes constructor events. The trailer includes final
frees after all owned Bullet objects have been destroyed.

Capture and Windows replay require these receipts before ordinary comparison or
rank binding. The Python ledger reconstructs each mode's slot order, checks every
live and cached-free node against a live allocation, rejects duplicate addresses
across both trees, and requires cached-free to live reuse without an intervening
free callback. Eligible allocations never observed as nodes are permitted but
must be freed. Ordinary mode installs neither hook and requires zero callbacks,
no events and node addresses outside the static arena. Missing receipts fail;
a producer's `CONTROLLED_PASS` label alone supplies no allocator evidence. Every checkpoint captures preorder
node kind, leaf owner, all volume bits, node address and cached-free address.
Rust binds those observations through a test-only private-node adapter. It
rejects missing nodes, wrong topology or volume bits, duplicate or zero ranks,
and missing cached-free coverage. No NodeId or pointer escapes into production.
Address comparisons occur only during incremental optimization. create/set
queries can allocate nodes before the next checkpoint supplies their addresses.
calculate optimizes before allocating migration nodes. The next operation binds
all new nodes before another optimization can compare their addresses.

Every tree's leaf count, lookahead and optimization path counter is observed.
Broadphase counters include the fixed default update rates, owned-cache flag and
immediate-collision mode. Float observations retain raw u32 bits. Stage lists,
proxy UIDs, requested and leaf AABBs, tree roots, ordered pair arrays, algorithm
generations, manifold order and release events are compared without sorting.

The ordinary native allocator and ordinary Rust allocator run separately. Their
raw ordered traces and every differing checkpoint are retained. An order
difference is recorded as `DIVERGED`, never repaired by sorting. Public World
acceptance stays `HOLD`, including when this finite ordinary sample agrees.

Fifteen semantic controls compile altered Rust copies and run the full corpus.
Every control must exit normally, emit every checkpoint in the strict schema,
and change its directed semantic observation. Compile errors, timeouts, missing
rows and malformed outputs fail the gate. The controls cover query side, filter,
stage, migration, reactivation, containment, margin, prediction sign, teleport,
cleanup budget, cursor, release, live reset, stored-leaf cleanup and query order.
They run independently of native rank binding so a semantic divergence cannot be
miscounted as a binder panic.

The four replay jobs consume the actual Windows artifact with the explicit
`mmd-win64-sse` policy. They verify its member hashes and canonical source closure
before replaying all controlled captures. Raw source bytes and hashes remain
retained. Canonical comparison only normalizes CRLF to LF across host checkouts.
The source closure includes every directly compiled Rust core, test fixture,
helper and the full `mds-crtmath/src` module tree, including `lib.rs`. PR214's
inherited omission of that direct CRT entry point is disclosed separately and
is not copied into this checker.

The previous verifier assumed every node occupied 64 bytes. At base `b15a8e0`,
run `40501081248` measured 56-byte nodes on Apple Silicon macOS, Linux x64 and
Linux ARM64, then refused them before hook installation. That diagnostic measured
node size and pointer size, and reported requested alignment 16. It did not
measure type alignment, offsets or callback request sizes on those hosts. The
56-byte natural-alignment-8 layout follows from the unchanged native definition;
fresh CI must record the new layout facts and actual 79-byte callbacks. Synthetic
fixtures are unit controls, not native execution proof. Fresh acceptance requires
all four native captures, four Windows replays and all 15 compiled semantic
controls. Strict archive binding and Rust parity gates remain unchanged.

Run helpers with Python normally and under `-O`. From any directory:

```sh
python3 -B tools/bullet-rust-dbvt-broadphase-check/test_check.py -v
python3 -B -O tools/bullet-rust-dbvt-broadphase-check/test_check.py -v
```

From the repository root, native capture on an authorized CI host uses:

```sh
python3 -B tools/bullet-rust-dbvt-broadphase-check/check.py \
  --out-dir /absolute/evidence/path --policy generic-reference
```

Windows uses `--policy mmd-win64-sse` in an activated x64 MSVC environment.
`--replay-dir /absolute/windows/artifact` selects Windows-sourced replay.
`--rust-only` compiles and runs only focused Rust checks and the Rust producer.
It always reports `PREPARATION_ONLY`; it supplies no native acceptance.

The `CONTROLLED_PASS` status concerns one hosted capture or replay. Four-host
acceptance, final PR214 acceptance, fresh independent reviews and the integrated
`tools/rust/check.sh` gate remain the root's responsibility. Prepared workflows
and unrun controls do not supply runtime evidence.
