# Native solver companion-index lifecycle

This test characterizes Bullet 2.75 companion indices across real
`btDiscreteDynamicsWorld::stepSimulation` calls. It changes no native or Rust
physics and does not freeze non-live storage as a Rust oracle.

Run with Python 3, Clang, and Rust 1.95.0:

```sh
python3 tools/bullet-solver-index-lifecycle/check.py --out-dir /tmp/bullet-solver-index
```

On Windows x64, use `python` in a Visual Studio x64 developer command prompt with
`CXX=cl`. All variants use AddressSanitizer. Leak detection is disabled; address
diagnostics remain enabled. Each scene has a ten-second timeout, and each compiler
invocation has a 120-second timeout.

The 36 scenes vary three body types, all six registration permutations, and one or
two dynamic spheres. Every scene takes two variable timesteps of `float32(1)/60`.
Body 0 is a box with half extents `(5, .5, 1)` at the origin. Bodies 1 and 2 are
unit-mass spheres of radius `.5`, initially at `(-2, .9, 0)` and `(2, .9, 0)`.

- `kind=0`: body 0 has mass 1 and the kinematic flag.
- `kind=1`: body 0 has mass 0 and the kinematic flag, retaining its static flag.
- `kind=2`: body 0 is dynamic and joins the contacts into one island.

Every registered body disables deactivation and has zero friction. Gravity is
`(0, -10, 0)`, with ten solver iterations. Constructor defaults are pinned by source
hashes. `inputs.json` records parameters and exact nonintegral float encodings.
Stdout records raw binary32 input mass, position, derived inverse inertia,
timestep, and final velocities. State columns are `step`, `body`, `island tag`,
`companion`, `linear xyz`, and `angular xyz`.

Three executables link the same native objects:

- `original` uses the unchanged vendored solver.
- `observed` compiles a source copy with lookup, pool access, row index, entry,
  and capacity logging. Each access reads the current owner only within live size.
  Owner -1 is the fixed entry. Owner -3 means outside live size; the observer does
  not read its old fields. The original unchecked native access still executes.
- `reset` explicitly resets companions before clearing each pool. This diagnostic
  control is not a proposed correction or an equivalent native oracle.

Original and observed stdout must match byte for byte, with matching terminal
results. Assertions check World group counts, retained companions in shared
nonzero-mass kinematic cases, absence in controls, and the distinction between
in-range aliases and accesses beyond live pool size. PASS means these
characterization assertions passed, not that the native behavior is safe.

The output retains commands, terminal codes, timeouts, stdout, stderr, copied
sources and diffs, compiler and Rust versions, source/input hashes, and
`summary.json`. The scoped workflow targets Windows x64, Apple Silicon macOS,
and Linux x64/ARM64. Workflow configuration is not execution evidence.
