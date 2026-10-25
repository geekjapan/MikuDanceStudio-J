# mds-crtmath

`sinf` `cosf` `tanf` `asinf` `acosf` `atanf` `atan2f` `expf` `logf` `powf` in
pure Rust. They give the same results as the MSVC x64 UCRT on its FMA3 code
paths, the paths that modern x64 CPUs take, on any host. MMD's physics links
against these functions, so `mds-bullet-sys` can use them through the C entry
points `mds_crt_sinf` ... `mds_crt_powf` (all `extern "C" fn(f32...) -> f32`).

## Status

The oracle is `tests/fixtures/rust/math/crt-digests-fma3.txt`: 4096 block
digests per function over all 2^32 float inputs (see its README).

| Function | Matching blocks |
|---|---|
| sinf | 4096 / 4096 |
| cosf | 4096 / 4096 |
| tanf | 4096 / 4096 |
| asinf | 4096 / 4096 |
| acosf | 4096 / 4096 |
| atanf | 4096 / 4096 |
| atan2f | 4096 / 4096 |
| expf | 4096 / 4096 |
| logf | 4096 / 4096 |
| powf | 4096 / 4096 |

The counts are the same on aarch64 (Apple M4 Pro) and on x86_64
(`--target x86_64-apple-darwin` under Rosetta, without the `fma` target
feature).

The digests cover every float input of the one-argument functions. For
`atan2f` and `powf` they cover one second argument per first argument, as
defined in `tools/oracle/math_digest.hpp`.

- `cargo test -p mds-crtmath` checks 16 blocks per function, chosen to cross
  every code path. It takes about 2 s in a debug build.
- `cargo test -p mds-crtmath --release -- --ignored --nocapture` runs the
  full sweep and prints the count per function. It takes about 1 min on 14
  cores.

## The digest port

`src/digest.rs` ports `tools/oracle/math_digest.hpp`. To check the port,
`tools/oracle/math_digest_host.cpp` was built with Apple clang and run for
`sinf`, `atan2f`, and `powf` over all 4096 blocks. The same functions in
Rust, `(x as f64).sin() as f32` and so on through the same macOS libm, gave
identical output for all 12288 lines. Those three functions cover the one-
and two-argument schemes. That every function now matches all of its oracle
digests is a second check.

The digest is invertible: each step is an xor, a multiplication by an odd
constant, and an xorshift. So when a block differs in one output, the
expected value of that output can be solved from the block digest. That is
how the departures listed below were found.

## Determinism

The functions use only IEEE f32/f64 arithmetic, `sqrt`, `round_ties_even`,
and `mul_add`. Rust defines `mul_add` as a fused multiply-add with a single
rounding on every target, which is what the FMA3 instructions compute. No
step depends on the host's libm except `mul_add` on targets without a
hardware FMA. There, the compiler calls the platform `fma`, which must be
correctly rounded. glibc, musl, macOS, and the UCRT provide one.

The library does not model NaN payloads and signs (the digest does not
compare them), `errno`, or floating-point exception flags.

## Sources

The algorithms, constants, and tables come from AMD AOCL-LibM 5.3.2
(<https://github.com/amd/aocl-libm-ose>, BSD-3-Clause). The UCRT x64 math
library has the same AMD origin. No UCRT source or binary was read. These
AOCL files were used:

- `sinf`, `cosf`, `tanf`: `src/isa/avx2/gas/{sinf,cosf,tanf}_fma3.S` and the
  macros and constants in `src/isa/avx2/include/trig_func.h`, including the
  double-double Payne-Hanek reduction. The Taylor coefficients come from
  `src/isa/avx/masm/sinf.asm`.
- `asinf`, `acosf`, `atanf`, `atan2f`: `src/ref/{asinf,acosf,atanf,atan2f}.c`.
- `expf`: `src/isa/avx2/gas/expf_fma3.S` and `src/isa/include/exp_tables.h`.
- `logf`: `src/isa/avx2/masm/logf_fma3.asm`.
- `powf`: `src/isa/avx2/masm/powf_fma3.asm`.

The MASM files include `fm.inc` and `trig_func.inc`, which are not in the
AOCL repository. The trig code follows the GAS macros instead.

### Where the UCRT departs from those files

The digests show these differences. Each one was confirmed over the full
sweep.

- `sinf` and `cosf` use the Taylor coefficients of the non-FMA3
  `sinf.asm`, not the minimax table in `trig_func.h`.
- `sinf`, `cosf`, and `tanf` use the Cody-Waite reduction up to at least
  5.88e8, not 5e6. Above the cut they use the double-double Payne-Hanek
  reduction (`call_remainder_piby2_fma3`), not the float one. Any cut in
  [5.88e8, 3.3e9] gives the same results. The UCRT constant is unknown, so
  the code uses 2^30.
- `tanf` uses its full kernel from 2^-13. It has no `x + x^3/3` step.
- `asinf` and `acosf` fuse every `a * b + c` that the C code contains, as a
  compiler that contracts for FMA3 does. `acosf` rounds the product `x * u`
  to float before it widens the product to double.
- `atan2f` takes the exponent difference from the double values of its
  arguments, so a subnormal `y` counts at its true scale.
- `expf` flushes to zero below about -103.972 (ln 2^-150), not below
  -103.279. Any cut in [-110, -103.972] gives the same results. The code
  uses -104.
- `logf` has no shortcut that returns 1 for `x == e`.
- `powf` evaluates `exp(r)` as `r + r^2 (1/2 + r/6)`. Its near-one `log`
  keeps the `u^7` term, and it does not fuse `m ln 2 + log F`. The MASM file
  computes `r^2/6` and drops the `u^7` term.

## License

The crate is `MIT`. It contains constants, tables, and algorithms translated
from AOCL-LibM, which is under this notice:

```
Copyright (C) 2008-2022 Advanced Micro Devices, Inc. All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:
1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software without
   specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```
