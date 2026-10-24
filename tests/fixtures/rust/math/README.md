# Math reference data

Written by `tools/oracle/math_vectors.cpp` (last changed at `202acc6`) on the
Windows host `nanoha-lan`: i9-12900K, MSVC 19.44 UCRT, and
`C:\WINDOWS\SYSTEM32\d3dx9_43.dll`. Each file starts with a header that
records the CPU, compiler, and module.

| File | sha256 | Content |
|---|---|---|
| `d3dx-vectors.txt` | `6f42ec42ffa8ff0b791c6a30c5f85fc573cff260737e01713cd09af0649a820c` | Inputs and outputs as float bit patterns for the D3DX matrix, quaternion, and vector functions the app calls. Seed `0x4d445331`. |
| `crt-digests-fma3.txt` | `ce866ddf3faba21870eacb98216edb0e9fcad99a81e082922424d9903c87086e` | One digest per block of 2^20 inputs over all 2^32 float bit patterns, for `sinf` `cosf` `tanf` `asinf` `acosf` `atanf` `atan2f` `expf` `logf` `powf`, with the UCRT FMA3 paths on. |
| `crt-digests-nofma3.txt` | `513f99924266abee8e6a6c056a45112cd5cbca2f67f0b584173e329b0f611950` | The same with the FMA3 paths off. |

`tools/oracle/math_digest.hpp` defines the digest and the input of each
block. `tools/oracle/math_digest_host.cpp` computes the same digests for
another implementation, so a port can be compared block by block.
