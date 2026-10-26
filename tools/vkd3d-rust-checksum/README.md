# Recapture vkd3d checksum fixtures

The test-only oracle compiles the original vkd3d 2.1 `checksum.c` unchanged.
The script verifies the archive and source SHA-256 values before compilation.
A private-header shim extracts the two integer helpers, enum, and prototype from hash-verified upstream headers.
The Rust crate never builds or loads this native code.

Run the recapture from the repository root on a supported little-endian 64-bit macOS or Linux host with Python 3 and a C11 compiler.

```sh
python3 tools/vkd3d-rust-checksum/capture.py --output /tmp/vkd3d-checksum
```

This downloads the same pinned archive used by `tools/vkd3d/build.sh`.
To use an existing extracted source tree, add `--source-dir /path/to/vkd3d-2.1`.
`CC` selects a compiler executable. No extra flags or shell syntax are accepted through `CC`.
Add `--write-fixture` only to deliberately replace the checked-in fixture.
The normal command fails if the captured fixture differs.

The corpus has 400 inputs. It covers every length from 0 through 129, fourteen further block boundaries, and 256 deterministic random multiblock lengths.
Each input byte comes from xorshift32 with shifts 13, 17, and 5, masked to 32 bits after each left shift. The low byte is emitted after each state update.
Each fixture row records the initial seed, input size, standard digest bytes, and DXBC digest bytes.
Python `hashlib` independently checks the native standard MD5 digest.
The oracle makes 1600 native calls in total, including synthetic `size_t` values of `2^32 + actual_size` for both variants.
This proves the original API's 32-bit truncation without allocating 4 GiB.
The Rust tests separately check the size conversion arithmetic.

`native.log` preserves compiler identity, commands, native output, and exit status.
`native.tsv` is the candidate fixture. `source.json` records the source hashes and corpus count.
The dedicated workflow checks the fixed Rust fixtures on all four supported targets and recaptures the actual source on Linux x64.
Logs from queued or configured jobs are not evidence of execution.

The checksum translation and its test tools are LGPL-2.1-or-later. See [the crate license](../../rust/crates/mds-vkd3d/LICENSE).
Product linkage and distribution terms remain a separate decision.
