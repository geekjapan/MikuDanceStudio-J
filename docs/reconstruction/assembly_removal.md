# Source assembly removal (2026-10-23)

The refactor baseline is `d7425a5`. The application's 14 inline assembly
blocks and the vendored Bullet tree's 24 blocks (including disabled alternatives)
are expressed as C++ or removed when unreachable. Naked functions are gone.
The inertia tensor uses typed matrix/vector fields instead of body byte offsets.

`LinearMath/btMmdMath.cpp` contains the arithmetic that needs VC9 x86 evaluation.
Its source compiler options are `/arch:IA32 /fp:precise /O2 /Oi /GL- /RTC-`.
Only that translation unit receives these options. The x64 branches retain their
existing expressions and compiler settings.

`double` expressions keep intermediate values in x87 registers in this isolated
translation unit. Explicit `volatile float` variables preserve the original float
stores. MSVC's `long double` is 8 bytes, so changing the variable type alone would
lose the original extended evaluation. Ordered sums cross a `noinline` boundary
before relaxed sqrt/trigonometric expressions, selecting native math instructions
without allowing reassociation of the sums. Scalar SSE intrinsics preserve the
single-precision stages of direction normalization, inertia and Taylor expansion.
These boundaries also preserve the caller's precision and rounding settings.

## Verification

The old implementations were extracted from `d7425a5` into an ignored build
folder and linked beside the new implementations for direct bit comparisons.
The comparison covered 32 distinct operations, 100,000 input sets per domain,
three domains (finite float bit patterns, moderate exponents, and directed edge
patterns), three x87 precision settings (24/53/64 bits), and four rounding modes
(nearest/down/up/chop). The edge patterns include both zeros, subnormals, largest
finite values, infinities and quiet/signaling NaNs. Skinning weights and integration
time steps were varied as well. No output bit differences were observed.

`tests/mmd_math_test.cpp` retains a deterministic subset: 512 input sets per domain
and precision/rounding combination. `tests/mmd_math_golden.hpp` records output
hashes from the old implementations, including signed zero and NaN payload bits.
The seed is `0x191234`, the generator is xorshift32, and the output accumulator is
64-bit FNV-1a over float bit words. The fixture must not be regenerated from the
replacement implementation.

A separate Bullet simulation compared old/new libraries over 600 steps for each
of PC24/53/64. It includes a ground box, 16 dynamic boxes/spheres/capsules, five
6DoF spring constraints, gravity, collisions and applied torque. World transforms,
linear/angular velocity and world inverse inertia were compared after every step:
1,800 frame records were identical.

Both x86 and x64 Release builds completed. The x86 numeric regression passed.
The full suites each encountered the existing `mme_d3dx_runtime` mesh-creation
failure at `tests/mme_regression.cpp:208`; older built x86 and x64 tests reproduced it.
Seven GPU tests per architecture skipped in the current environment. This run
therefore does not provide new visual parity evidence for the original MMD binary.

To run the retained numeric regression after installing the local Bullet recipe:

```powershell
ctest --test-dir out/bullet-diagnostics/x86/build -C Release -R '^mmd_math$' --output-on-failure
```

The follow-up investigation on 2026-10-24 is recorded in
[d3dx_runtime_failure.md](d3dx_runtime_failure.md). The same x64 suite subsequently
passed 45/45 before native D3D9 capability queries became unavailable again.
Historical failure logs lack HRESULTs; they do not establish one stable D3DX defect.
