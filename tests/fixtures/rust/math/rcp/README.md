# SSE reciprocal estimates

Written by `tools/oracle/rcp_table.cpp` at commit `e9adb54` on the Windows
host `nanoha-lan`: 12th Gen Intel Core i9-12900K, MSVC 19.44
(`cl /nologo /O2 /EHsc /utf-8 /std:c++17 rcp_table.cpp`), default MXCSR
`0x1F80`. Each file starts with a header that records the CPU, compiler, and
MXCSR.

```
rcp_table.exe table  > rcp-table.txt
rcp_table.exe digest > rcp-digests.txt
```

| File | sha256 | Content |
|---|---|---|
| `rcp-table.txt` | `8932a8eb2c7e6a954451ed4930a06a92d8b8cae44a416277fa76ec360c3b2850` | The output of `rcpss` and `rsqrtss` at 2048 reference inputs each. With the exponent and special-value rules in `rcp_table.cpp`, these give the instruction for every input. The two `# verified` lines at the end record that the tool compared the rules with the instruction for all 2^32 inputs of each, bit for bit, with 0 mismatches. |
| `rcp-digests.txt` | `3b2239b78dec05d07eba11d529dfc2084525b917e03a4bd083b51f214a72f027` | One digest per block of 2^20 inputs over all 2^32 float bit patterns, for `rcpss` and `rsqrtss`. The digest rules are those of `tools/oracle/math_digest.hpp`. |

The output of `rcpss` depends on the sign, the exponent, and mantissa bits
22..12 of the input. The output of `rsqrtss` depends on the sign, the
exponent, and mantissa bits 22..13. The digests replace every NaN output by
`0x7FC00000`, as the CRT digests do, so they do not check NaN signs or
payloads. The `table` sweep does check them.

`rust/crates/mds-math/src/estimate_table.rs` holds the two tables as Rust
constants. The `table_matches_fixture` test in `mds-math` checks that they
equal `rcp-table.txt`. To write the file again, run this from the repository
root:

```sh
awk '!/^#/ { t[$1] = t[$1] sprintf("%s0x%s,", n[$1]++ % 8 ? " " : "\n    ", $3) }
END {
  print "//! Generated from `tests/fixtures/rust/math/rcp/rcp-table.txt`; the `table_matches_fixture`"
  print "//! test checks it. Entry `i` is the output bits of `rcpss(0x3F800000 | i << 12)` and of"
  print "//! `rsqrtss(0x3F000000 + (i << 13))` on the i9-12900K.\n"
  printf "pub(crate) const RCP: [u32; 2048] = [%s\n];\n", t["rcpss"]
  printf "pub(crate) const RSQRT: [u32; 2048] = [%s\n];\n", t["rsqrtss"]
}' tests/fixtures/rust/math/rcp/rcp-table.txt > rust/crates/mds-math/src/estimate_table.rs
```

## Difference from the earlier model

Before this table, `mds-math` modelled the estimates from the D3DX vectors:
the bucket centre of the mantissa, with the exact result rounded to 13 bits.
That model gives the recorded value in all 2048 `rcpss` buckets and all 2048
`rsqrtss` buckets. It differed only at the edges:

| Instruction | Range | Earlier model | CPU | Inputs | Digest blocks |
|---|---|---|---|---|---|
| `rcpss` | 2^126 <= \|x\| < 2^128 | denormal | signed zero | 33,554,432 | 32 (`0x7E8`..`0x7F7`, `0xFE8`..`0xFF7`) |
| `rcpss` | signalling NaN | input unchanged | input with the quiet bit set | 8,388,606 | none, NaNs are canonicalised |
| `rsqrtss` | -0 and negative denormals | +inf | -inf | 8,388,608 | 8 (`0x800`..`0x807`) |
| `rsqrtss` | other negatives, -inf | `0x7FC00000` | `0xFFC00000` | 2,130,706,433 | none |
| `rsqrtss` | NaN | `0x7FC00000` | input with the quiet bit set | 16,777,213 | none |

None of the 428 D3DX vectors reaches these inputs, but real calls can. For
example, `Mat4::inverse` of a matrix whose determinant is at least 2^126 now
returns zeros, as the CPU's zero estimate does. The earlier model returned
denormals.
