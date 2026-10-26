# Bullet shape differential check

Run from the repository root with Python 3, Rust 1.95.0, and clang++ installed.
Choose a separate output directory outside the checkout.

```sh
python3 tools/bullet-rust-shape-check/check.py --out-dir /tmp/mds-bullet-shapes
```

The check compiles the actual vendored Bullet sources and a native driver. It
force-includes `mds-bullet-sys/shim/det_math.h`, puts `shim/sse_emu` first on the
include path, disables fast math and contraction, and links the Rust UCRT math
ports. It does not use system-math replacements or a previously built Bullet
archive. Native outputs must match the fixture before the standalone Rust test
runs. `--record` deliberately replaces the fixture with the new native capture.

The driver calls each shape's constructor, dimension accessors, `getMargin`,
`calculateLocalInertia`, and `getAabb`. It contains no translated shape formulas.
`cases.py` emits 288 deterministic cases. Native output rows contain case ID,
shape kind, 12 input float words, then 13 output float words. Floats are hexadecimal
IEEE 754 words. The inputs are shape parameters xyzw, mass, origin xyz, and
quaternion xyzw. Outputs are margin, dimensions xyz, inertia xyz, AABB minimum
xyz, and AABB maximum xyz. Dimensions mean sphere radius/0/0, box implicit half
extents without margin, capsule radius/half-height/radius, or normalized plane
normal. The plane constant remains the input constant.

Coverage includes four masses, four quaternions, unequal box dimensions, boxes
smaller than the default margin, small and large radii, zero capsule height,
non-unit quaternions, plane normal normalization and unbounded plane AABBs.
Three raw dimension cases preserve `mds_mmd`'s unchecked constructor path. The
public `mds_bt` facade rejects these inputs and remains unchanged.

## Translated behavior

The source of truth is `recipes/bullet275/bullet-src/src`.

- `btSphereShape.h/.cpp` stores radius as the full margin. AABB ignores rotation.
  Its local MMD patch evaluates inertia as double `r*r*mass*float(0.4)` and rounds
  to float once.
- `btBoxShape.h/.cpp` subtracts 0.04 from input half extents at construction and
  adds it back for AABB and inertia. The rounded subtraction and addition are
  retained even when the input is smaller than the margin. Its inertia coefficient
  is `0.083333336f`, applied after multiplication by mass.
- `btCapsuleShape.h/.cpp` uses Y as the up axis. Input height excludes the cap
  radii; its stored half-height is `0.5f*height`. This 2.75 version adds 0.04 to
  the radius-based AABB extents. Inertia approximates a box and uses the fixed
  `CONVEX_DISTANCE_MARGIN`, with `mass*0.083333328f` evaluated first.
- `btStaticPlaneShape.cpp` normalizes its input normal with reciprocal length
  multiplication. Its inertia is zero and AABB is always +/-`1e18f`.
- `btAabbUtil2.h` transforms box extents by absolute basis rows. Scalar
  `btVector3::dot` associates `(x+y)+z`, including under the configured SSE ABI.
- `mds_bt.cpp` validates finite parameters, positive sphere/box dimensions,
  nonnegative capsule height, and approximately unit plane normals. Plane body
  mass/kinematic checks remain a body-boundary concern. `mds_mmd.cpp` passes raw
  dimensions to Bullet, so the pure core keeps raw typed constructors.

`Shape` currently belongs to the native-free core migration. Its tests include
it by path until the parent integrates `core/mod.rs`. No public World or MMD
facade is switched to this module by this change. Local scaling, shape mutation,
contacts, support mapping, collision dispatch, and world dynamics are outside
this unit. Bullet's retained zlib notice lives in `core/mod.rs`; this is an
altered translation including vendored local patches whose ancestry is pending
audit.

The native capture was exercised on Apple Silicon macOS. This host tool uses
clang and Unix linker options. Windows x64 and Linux x64/ARM64 acceptance belongs
to the parent CI gate. No Win32 or Intel Mac acceptance is required.
