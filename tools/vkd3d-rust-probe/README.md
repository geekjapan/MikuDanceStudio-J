# vkd3d C2Rust feasibility probe

This is an isolated migration experiment, not a production shader backend.
The [hosted continuation](HOSTED.md) describes the bounded GitHub Actions
attempt for large units, its status rules, and its unexecuted acceptance gates.
The generated Rust is derived from vkd3d and remains LGPL-2.1-or-later;
the script restores copyright/license comments and copies `LICENSE`.
Generated parser skeleton notices and exceptions must also be retained.

## Reproduce

Use an already configured vkd3d 2.1 tree containing `include/config.h`,
generated headers, `hlsl.tab.c`, and `hlsl.yy.c`. The configured tree's sibling
`hdr/include` and `spv/include` directories supply its native header dependencies.
The script copies its input and refuses to reuse an artifact directory.
Keep artifacts outside the repository and outside the input source tree.

The tested migration tool is official C2Rust commit
`ac687698b6c13491dfec45c6a9ad9e8b4da35227`, whose version command reports
`C2Rust 0.22.1`. The released crates.io 0.22.1 is **not** equivalent.
Current official [installation instructions](https://github.com/immunant/c2rust/blob/ac687698b6c13491dfec45c6a9ad9e8b4da35227/README.md#installation)
require LLVM 15 or newer, matching Clang libraries, CMake, and Rust.
No Docker image or paid service is used.

```sh
export PROBE_ARTIFACTS=/absolute/path/outside-the-repository
git clone https://github.com/immunant/c2rust.git "$PROBE_ARTIFACTS/c2rust-src"
git -C "$PROBE_ARTIFACTS/c2rust-src" checkout ac687698b6c13491dfec45c6a9ad9e8b4da35227
LLVM_CONFIG_PATH=/opt/homebrew/opt/llvm/bin/llvm-config \
LIBCLANG_PATH=/opt/homebrew/opt/llvm/lib \
CARGO_TARGET_DIR="$PROBE_ARTIFACTS/tool-target" \
cargo +stable install --locked --path "$PROBE_ARTIFACTS/c2rust-src/c2rust" \
  --root "$PROBE_ARTIFACTS/tool"

python3 tools/vkd3d-rust-probe/probe.py \
  --source /absolute/path/to/configured/vkd3d-2.1 \
  --artifacts "$PROBE_ARTIFACTS/run" \
  --c2rust "$PROBE_ARTIFACTS/tool/bin/c2rust" \
  --clang /opt/homebrew/opt/llvm/bin/clang \
  --filter '(debug|memory|checksum)[.]c$'
```

Omit `--filter` for all 24 shader/common translation units. Use separate fresh
artifact directories with filters `hlsl[.]tab[.]c$`, `hlsl[.]yy[.]c$`, or
`hlsl[.]c$` to bound expensive units independently. Default timeout is 300
seconds for translation. Syntax checks are capped at 120 seconds and Rust
builds default to 120 seconds each. `result.json` distinguishes a completed translation,
compiler failures, and timeout. Inspect logs even when the script exits zero:
the script is an evidence collector, and its exit status is not acceptance.

## Measured result, 2026-10-27 JST

Evidence root on the test machine:
`/Users/geekjapan/.codex/orchestrate/mikudance-rust-20261027/shader-c2rust/`.
The authoritative successful scripted run is `verified-final-02/result.json`.
Its input source hashes and command lines are recorded there.

Tools: Apple Silicon macOS; Rust/Cargo 1.95.0; Homebrew LLVM/Clang 23.1.2;
generated crate dependency `libc` 0.2.191 (checksum alone has no dependencies).

| Check | Observed result |
| --- | --- |
| Released C2Rust 0.22.1 build with LLVM 23 | Failed: three C++ errors, removed `ElaboratedType` and two deleted `getTypeForDecl` calls. See `install.log`. |
| Fixed official C2Rust commit with LLVM 23 | Built successfully. See `install-master.log`. |
| Native C syntax checks | All 24 shader/common C units passed; source hashes unchanged afterward. See `run-01/syntax-*.log` and `result.json`. |
| `checksum.c`, `debug.c`, `memory.c`, `--fail-on-error`, Rust 2024 | All three fully emitted. No compiler function was removed or stubbed. |
| Pristine Rust 2024 generated crate on stable | Failed: unstable feature gates. |
| Same crate with `RUSTC_BOOTSTRAP=1` | Failed: generated expression attribute needs an additional feature. |
| Same crate with explicit prototype flags | Both staticlib and rlib built. Flags: `RUSTC_BOOTSTRAP=1`, `RUSTFLAGS='-Zcrate-attr=feature(stmt_expr_attributes) -Astatic_mut_refs'`. This is experimental acceptance, not a production toolchain recommendation. |
| Checksum with actual `#![no_std]` | Stable Rust 2024 rlib built using the complete generated module and a new minimal crate root, with no bootstrap or C build step. |
| Generated checksum behavior | Six MD5 vectors passed: empty, `abc`, and 55/56/64/1000 repetitions of `a`, compared with Python `hashlib.md5`. |
| Whole compiler, HLSL semantic code, generated parser/lexer | Not proven; bounded translation attempts described below did not complete. |

The default Rust 2021 output is unsuitable for current Rust: the diagnostics
subset produced eight compile errors with bootstrap (one expression-attribute
gate, one removed atomic intrinsic, three `VaListImpl` references, and three
removed `as_va_list` calls). Official `--edition 2024` fixes the removed APIs;
it also exposes the mutable-static-reference lint, which the prototype flags
explicitly allow. That flag does not establish thread safety.

The broad run was terminated after 329 observed seconds while translating
`d3d_asm.c`; only checksum had emitted. Separate required-source and generated
parser runs were terminated after 303 and 312 observed seconds, respectively,
while translating `hlsl.c` and `hlsl.tab.c`, with no Rust source emitted for
either. The latter parser attempt used default edition 2021. A separate lexer
attempt used Rust 2024 and was terminated after 301 observed seconds without
emitting its Rust module. These are time-limited incomplete results, not a
count of unsupported C constructs. Logs contain no translation diagnostic
identifying an unsupported construct before termination.

`hlsl-parser-sample.txt` captures CPU activity inside C2Rust's
`Translation::convert_decl` / function translation and `DFExpr` AST traversal,
including `TypedAstContext::contains_node`. The process was doing CPU work;
the sample does not prove the cause or whether a longer run would finish.

## Remaining runtime dependencies and unsafe code

`verified-final-02/externs.json` inventories the generated declarations and
definitions. After resolving functions defined by the three Rust modules,
24 declared native symbols remain:

```text
_DefaultRuneLocale __error __maskrune __stderrp
free getenv malloc memchr memcmp memcpy memmove memset realloc
pthread_setname_np pthread_threadid_np
sprintf strchr strcmp strcspn strlen strstr strtoul vfprintf vsnprintf
```

These are macOS system C runtime/pthread interfaces, not a vkd3d shared
library. The generated crate has an empty Rust `build.rs`; `libc` also has a
Rust build script. Neither compiles C. There is no `cc` crate dependency,
Clang invocation, or vkd3d link dependency. The original shader library's Makefile links
the common library, `-pthread`, and `-lm`; this subset does not establish
that all native dependencies of the complete compiler have been removed.

An additional clean build denied `cc`, `clang`, `gcc`, and their C++ variants
with executable PATH shims and set `CC=CXX=/usr/bin/false`. The default build
failed because rustc uses `cc` as its linker driver for the Rust build-script
executables (`deny-c-build.log`). Repeating with the native linker directly
succeeded (`direct-ld-build.log`), using these additional flags:

```text
-Zunstable-options
-Clinker=/Library/Developer/CommandLineTools/usr/bin/ld
-Clinker-flavor=darwin
-Clink-arg=-syslibroot
-Clink-arg=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk
```

This proves a C compiler is avoidable for this subset, while the platform
linker and SDK remain necessary. These flags are in addition to the explicit
prototype feature/lint flags above. It does not prove a standalone no_std
shader compiler or portability to another target.

The checksum-only no_std object still references `memcpy`, `memmove`, and
`memset`, plus Rust core panic/unwind symbols. `--emit-no-std` alone only
changes emitted paths: it did not put `#![no_std]` in the generated crate
root. The scripted explicit no_std check supplies that attribute.

Generated code uses raw pointers, unsafe C ABI functions, mutable statics,
unchecked C lifetime/aliasing assumptions, and variadic diagnostics. The
diagnostics retain C formatting (`sprintf`, `vsnprintf`, `vfprintf`) and
nightly `c_variadic`, `extern_types`, `linkage`, and internal intrinsic
features. It is a mechanical translation, not a memory-safe implementation.
The host SDK's inlined ctype code and pthread ABI are captured in this output;
this macOS-generated subset is not Windows-target acceptance.

## Next bounded scope

First resolve or independently bound C2Rust's traversal on the original HLSL
parser and lexer using the intended target configuration and Rust 2024.
Keep every compiler function and grammar rule. Only after these complete,
compile the complete shader/common crate and exercise shader compilation
against pinned native fixtures. Then replace system C formatting, allocation,
ctype, threading, and math calls with Rust equivalents, consolidate duplicated
types/globals, and validate the intended Windows ABI. Do not select a full
Rust replacement architecture from this subset alone.

No production integration, GPU check, shader compiler equivalence check,
Windows build, full compiler link, or memory-safety claim is included.
