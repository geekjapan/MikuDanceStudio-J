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
constants. A test in `mds-math` checks that the constants equal this file.
