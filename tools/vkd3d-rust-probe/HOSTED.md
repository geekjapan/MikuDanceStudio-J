# Hosted all-unit compiler prototype

The [workflow](../../.github/workflows/vkd3d-rust-probe.yml) now runs one
complete 24-unit translation, compilation, executable link, and shader
comparison experiment. This supersedes the four standalone unit jobs; it
has not been executed for this change. The root reviews and pushes the
commit before any hosted attempt.

## Execution contract

| Stage | Bound |
| --- | --- |
| Runner | Existing included standard `ubuntu-24.04`, Linux x64 only. |
| Preparation | 35-minute job; package step 10 minutes, Rust 3, pinned native source/baseline 8, official C2Rust build 12, bundle 2. Job limit caps their aggregate. |
| Packages | Explicit clang-18, llvm-18-dev, libclang-18-dev, libclang-cpp18-dev retained. apt acquisition uses 3 retries and 30-second HTTP/HTTPS timeouts. |
| Tool | Official C2Rust `ac687698b6c13491dfec45c6a9ad9e8b4da35227`; Rust 1.95.0. No refactorer, guessed reorganization option, or extra toolchain. |
| Translation | One call, no filter, `--fail-on-error --edition 2024`, 1,800 seconds. Exact shader/common source paths are checked against `full_compiler.UNITS`, not just a count. |
| Builds | Raw stable, patched stable, then bootstrap and experimental flags if necessary. Each build/link gets 300 seconds. Native syntax checks remain capped at 120 seconds per unit. |
| Numeric proof | Native C against actual configured `hlsl.h`, then stable Rust against complete translated layout declarations; each compiler 60 seconds, run 30 seconds. |
| Runtime | Four shader shapes, VS/PS, shader models 2/3, SPIR-V/D3D assembly/D3D9 bytecode: 48 cases, 30 seconds per process. The 55-minute step and 70-minute job cap aggregate work. |
| Trigger | Manual dispatch or executable-path push on `w3-shader-full-compiler-probe` or `w3-c2rust-win64-abi`. No PR trigger. |
| Authority | `contents: read`, checkout credentials disabled, no secrets, publication, deployment, larger runner, or paid service. Root alone pushes/dispatches. |
| Artifacts | Pinned configured input, installed native baseline, and tool bundle for 1 day; setup and all experiment evidence for 7 days. Cargo targets excluded. |

Preparation reuses `tools/vkd3d/build.sh linux-native` unchanged. The native
library is solely the comparison oracle. The translated compiler's build
and executable link use generated Rust and platform libraries, with no
native vkd3d library on their link command. `ldd` records the executable's
dependencies. No full local translation/build is part of this continuation.

## Preservation and the parser correction

`rust-raw/` preserves the emitted files byte for byte before license notices
are restored in `rust/`; `raw_sha256` records every original file.
`rust-working/` is a separate copy with restored original license notices.
The existing source/header SHA256 records, syntax checks, extern inventory,
and LGPL license copy remain. The untouched configured C input is copied.
Cargo may add lockfiles; generated source bytes must remain unchanged.

Only this known C2Rust output is corrected:

```rust
offset_of!(hlsl_attribute, args[(*yyvsp.offset(-2isize)).initializer.args_count as usize]) as size_t
```

Whitespace differences are allowed inside that exact token sequence. Exactly
one occurrence, the expected `hlsl_src` array element, `size_t = usize`, and
unsigned count declarations are required. Any mismatch stops patched builds.
The replacement is the base field offset plus wrapping `size_of::<hlsl_src>()`
times the index, both represented as `size_t`; it does not assume the element
is a pointer. The patch receipt includes occurrence counts and both SHA256s.

The native C proof evaluates real `offsetof(struct hlsl_attribute, args[n])`
for 0, 1, 31, 65535, and UINT_MAX. Stable Rust checks the actual translated
layout and every result. A failed proof blocks patched compilation. The
UINT_MAX case follows the grammar's unsigned argument count; no out-of-range
memory access is performed. This evidence does not establish other C ABI
layouts or another target's pointer width.

## Link and comparison

After an all-unit static library exists, `nm` records defined and undefined
archive symbols. Those raw undefined entries include references resolved by
other archive members, and are not all final external dependencies. The
standalone Rust `shader_driver.rs` links the real public compile/free C ABI
exports from that archive, plus system math/thread/dynamic-loader libraries.
The actual linker result/log decides executable closure. If compilation does
not produce an archive, link and symbol evidence are explicitly unavailable.

The same executable invokes the pinned native library via `dlopen` only in
its native comparison process. Its translated mode calls linked Rust exports.
The deterministic matrix covers c4 uniforms, helpers, branches, struct IO,
VS/PS and shader models 2/3. It compares return codes, diagnostics and output
bytes. Nonempty output and success on both sides are required: matching
unsupported-target rejections are failures. Process crashes/timeouts remain
failures. Scan/reflection and GPU execution are explicitly `not_run`.

## Status and acceptance

Raw stable builds clear inherited bootstrap, Rust flags and compiler wrappers.
All failures are retained. No feature attributes, real compiler functions,
variadic definitions or foreign types are removed or stubbed. Bootstrap and
experimental flags are recorded and remain prototype-only.

Statuses distinguish `incomplete`, `syntax_failure`, `translation_failure`,
`compiler_failure`, `patch_failure`, `linker_failure`, `runtime_unverified`,
and `prototype_success`. A successful patched/bootstrap link and full matrix
still yields only `prototype_success`. The all-unit validator checks exact
input and translated inventories and always fails production stable acceptance
for this experiment. A red hosted gate is expected until the faithful stable
migration is independently complete; it must not be reported as stable PASS.

Known gaps remain real c_variadic definitions, glibc extern types, other
emitted compiler errors not reached previously, C runtime dependencies,
unsafe aliasing/lifetimes/mutable statics, scan/reflection, Windows x64,
Linux ARM64, and full Apple Silicon compiler acceptance. The unavailable
2023 refactorer is not a Rust-2024 solution.

Local checks are Python unit tests, actionlint, rustfmt, shell syntax, diff
whitespace, and the tiny saved-parser native C/Rust numeric check. Configuration
and those checks do not establish hosted translation, linkage, or semantics.

## Pinned C2Rust Win64 repair

The official source revision remains `ac687698b6c13491dfec45c6a9ad9e8b4da35227`.
`apply_c2rust_patch.py` refuses another revision or dirty source, checks the patch
with `git apply --check`, then records its SHA256, applied diff, original revision,
and modified source hashes. The setup artifact also records executable hashes and
retains the official LICENSE and Cargo.lock. Only the local patch is committed.

The exporter unwraps `MacroQualifiedType` for both type IDs and traversal, and
uses the equivalent type for calling-convention attributes. Function prototype
and no-prototype CBOR records carry a calling convention into a Rust enum.
Definitions, foreign declarations, function pointers, K&R pointer calls, type
comparison, declared-argument reconstruction, and variadic pointer extraction
preserve it. `C`, `win64`, and `sysv64` are supported. Other conventions stop
export rather than silently becoming C. This patch targets the pinned LLVM 18
hosted tool build; compatibility with other Clang versions is unverified.

Translation is gated by a test-only native x86_64 C/Rust executable. A macro
attributed Win64 function and vtable pointer receive eight alternating integer
and floating arguments, including stack arguments. A C caller checks translated
Rust direct and vtable calls against 204, a no-prototype vtable call against 17,
and an ordinary C function against 86. Translated Rust calls a native Win64
callback and the C caller checks 120. Every compile/link/run must succeed and
runtime output must exactly match. This C fixture never enters the production
compiler driver. LLVM 18 AST output is retained for the fixture and real blob.

Only after this executable passes does real `blob.c` receive a 60-second
`--fail-on-error` translation gate. `--translation-only` stops this targeted probe
before redundant compiler builds and labels the result `translation_only_success`.
It does not count as compilation, link, or runtime acceptance. Then the unchanged
24-unit experiment includes all five common and 19 shader units. Remaining
variadic and foreign-type stable-Rust failures stay visible. The parser offsetof
patch, raw/working hashes, runtime comparison, and status classification are
otherwise unchanged. Extern inventory includes every emitted ABI and preserves
the aggregate declared/defined/unresolved sets alongside per-ABI sets.

No hosted tool build, smoke executable, or 24-unit result for this patch has been
observed during implementation. Passing local script tests and workflow lint do
not establish translator compilation or ABI correctness.
