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
| Packages | Preparation retains explicit clang-18, llvm-18-dev, libclang-18-dev, libclang-cpp18-dev. It bypasses the hosted Azure mirror with Ubuntu's canonical HTTPS archive mirror; apt uses 0 retries and 30-second HTTP/HTTPS timeouts, with 120 seconds for update and 300 seconds for install. |
| Tool | Official C2Rust `ac687698b6c13491dfec45c6a9ad9e8b4da35227`; Rust 1.95.0. No refactorer, guessed reorganization option, or extra toolchain. |
| Translation | One call, no filter, `--fail-on-error --edition 2024`, 1,800 seconds. Exact shader/common source paths are checked against `full_compiler.UNITS`, not just a count. |
| Builds | Raw stable, working stable, then bootstrap and experimental flags if necessary. Each build/link gets 300 seconds. Native syntax checks remain capped at 120 seconds per unit. |
| Numeric proof | Original-header C, freestanding extracted C, and actual generated stable Rust compare 95 layout metrics and 200 numeric vectors. Each stage has 120 seconds. |
| Runtime | Four shader shapes, VS/PS, shader models 2/3, SPIR-V/D3D assembly/D3D9 bytecode: 48 cases, 30 seconds per process. The 55-minute step and 70-minute job cap aggregate work. |
| Trigger | Manual dispatch or executable-path push on `w3-shader-full-compiler-probe`, `w3-c2rust-win64-abi`, `w3-shader-variable-offset-fix`, or `w3-shader-offset-harness-fix`. No PR trigger. |
| Authority | `contents: read`, checkout credentials disabled, no secrets, publication, deployment, larger runner, or paid service. Root alone pushes/dispatches. |
| Artifacts | Pinned configured input, installed native baseline, and tool bundle for 1 day; setup and all experiment evidence for 7 days. Cargo targets excluded. |

Preparation reuses `tools/vkd3d/build.sh linux-native` unchanged. The native
library is solely the comparison oracle. The translated compiler's build
and executable link use generated Rust and platform libraries, with no
native vkd3d library on their link command. `ldd` records the executable's
dependencies. No full local translation/build is part of this continuation.

## Source preservation

`rust-raw/` preserves the emitted files byte for byte before license notices
are restored in `rust/`; `raw_sha256` records every original file.
`rust-working/` copies `rust/` without source edits. Both copies require one
owned `src/**/hlsl_tab.rs`. `working_source_identity` records identical complete
file manifests before the working build. The existing source/header SHA256
records, syntax checks, extern inventory, and LGPL license copy remain.
The untouched configured C input is copied. Cargo may add lockfiles.

Raw stable Cargo runs first and retains its actual status and log.
`working_stable_build` records the separate unchanged stable build in
`cargo-working-stable.log`. Copy or identity failures stop before that build.
The numeric probe below replaces the historical parser-only rewrite and proof.
No generated Rust source is rewritten to make this experiment compile.

The archived `full-compiler-fixtures/generated` parser remains historical
ownership test data. Its original bytes and Cargo EOF exception are preserved.
It is not evidence of current translator output or numeric correctness.

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

SPIR-V normal cases chain the pinned `vkd3d_shader_spirv_target_info` with
`KHR_FLOAT_CONTROLS` and the existing default Vulkan 1.0 environment. Both
native and translated calls receive that same chain. The compiler can emit
`SPV_KHR_float_controls` and `DenormFlushToZero 32`; SPIR-V bytes may therefore
change where those declarations were previously unavailable. Denormal behavior
is preserved. Assembly and legacy bytecode calls receive no SPIR-V target info.
Pixel struct IO uses separate TEXCOORD inputs and COLOR outputs.

Two controls live in `negative_controls`, outside the 48 successful cases:
missing float controls requires E2004, and the old invalid pixel TEXCOORD output
requires E5013. Each requires API -4, empty output, and equal diagnostics on
both implementations. An unexpected success or another rejection fails the gate.

`check_shader_inputs.py --header /path/to/vkd3d_shader.h --native-library
/path/to/library --artifacts /new/evidence/directory` runs a bounded CPU-only
native baseline. It compares the actual driver's complete SPIR-V target layout
with the original C header, records input identities, compiles all 48 cases,
checks generated SPIR-V float controls and pixel interfaces, and exercises both
negative controls. It explicitly leaves translated comparison `not_run`.
Run `test_shader_matrix.py` with normal Python and `python3 -O` for focused
runner acceptance controls. This native check does not replace the hosted
translated matrix or stable compiler acceptance.

The driver reads and frees compiler output only after a nonnegative compile
result. Rejections retain their status and diagnostics, write empty output,
and free diagnostics once. Run `python3 -m unittest discover -s
tools/vkd3d-rust-probe -p test_shader_driver.py` for a safe mock ABI regression
against the actual driver executable with Rust 1.95.0. It checks both rejection
and success ownership. It does not establish real compiler or hosted matrix
acceptance. Matching negative return codes in normal cases remain `compile_failure`.

## Status and acceptance

Raw stable builds clear inherited bootstrap, Rust flags and compiler wrappers.
All failures are retained. No feature attributes, real compiler functions,
variadic definitions or foreign types are removed or stubbed. Bootstrap and
experimental flags are recorded and remain prototype-only.

Statuses distinguish `incomplete`, `syntax_failure`, `translation_failure`,
`compiler_failure`, `working_copy_failure`, `linker_failure`, `runtime_unverified`,
and `prototype_success`. A successful working or bootstrap link and full matrix
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
whitespace, and the original-header versus extracted C layout check. Configuration
and those checks do not establish hosted translation, linkage, or semantics.

## Pinned C2Rust Win64 repair

The official source revision remains `ac687698b6c13491dfec45c6a9ad9e8b4da35227`.
`apply_c2rust_patch.py` refuses another revision or dirty source, checks the patch
with `git apply --check`, then saves the complete applied patch, original revision,
and exact bytes and SHA256 hashes for every patch destination, including new modules.
It rejects unsafe, duplicate, missing and symlink destinations. The tool bundle retains
this evidence under `tool/source-evidence`. After the build, `--tool` verifies the
compiler source against that evidence and binds both executable hashes to the source
receipt. `check_runtime.py` verifies the binding and retained source before accepting
the hosted runtime. The setup artifact also retains the official LICENSE and Cargo.lock.
Only the local patch is committed.

The exporter unwraps `MacroQualifiedType` for both type IDs and traversal, and
uses the equivalent type for calling-convention attributes. Function prototype
and no-prototype CBOR records carry a calling convention into a Rust enum.
Definitions, foreign declarations, function pointers, K&R pointer calls, type
comparison, declared-argument reconstruction, and variadic pointer extraction
preserve it. K&R reconstruction also unwraps attributed types, including nested
wrappers, before reading the function ABI. `C`, `win64`, and `sysv64` are supported. Other conventions stop
export rather than silently becoming C. This patch targets the pinned LLVM 18
hosted tool build; compatibility with other Clang versions is unverified.

For a focused check without rebuilding LLVM, run the actual patched K&R method
with minimal AST and output shims using the pinned Rust compiler.

```sh
python3 tools/vkd3d-rust-probe/check_c2rust_knr.py \
  --source /path/to/patched/c2rust --artifacts /path/to/knr-check
```

The check covers attributed and nested transparent wrappers, prototype and
no-prototype functions, eight alternating parameter types, all three supported
ABIs, variadic flags, and noreturn results. It checks the method's forwarding
contract. The native smoke below remains required to verify export and ABI execution.

Translation is gated by a test-only native x86_64 C/Rust executable. A macro
attributed Win64 function and vtable pointer receive eight alternating integer
and floating arguments, including stack arguments. A C caller checks translated
Rust direct and vtable calls against 204, a no-prototype vtable call against 204,
and an ordinary C function against 86. Translated Rust calls a native Win64
callback and the C caller checks 120. Every compile/link/run must succeed and
runtime output must exactly match. The native caller also populates a mixed and
no-prototype Win64 vtable. The translated C unit invokes both pointers with the
same eight arguments and checks both results against 120. The no-prototype
translated definition remains exercised separately against 17. This C fixture never enters the production
compiler driver. LLVM 18 AST output is retained for the fixture and real blob.

The smoke requires a new owned artifact directory, including refusal of an
existing empty directory. Workflow setup creates only its parent `evidence/`.
The real translation enables `--emit-c-decl-map` and requires the used Win64
`native_callback` declaration in `translated.c_decls.json`. No stale Rust output
can satisfy a fresh run. Existing evidence is left untouched on refusal.
The pinned translator places these files in `rust/src/`. The smoke requires
exactly that source and sibling declaration map within its owned artifact tree.
Missing, duplicate, or outside-owned files fail before compilation. The same
validated source path is passed directly to `rustc`; this smoke has no Cargo manifest.

`abi-fixtures/generated/src/` preserves the unmodified Rust source and declaration
map emitted by hosted run `40395084023` at repository commit `c0cd511`.
The regression tests replay these files through the smoke stages. Mocked build,
link, and runtime stages test orchestration only; hosted execution remains the ABI gate.

The patched upstream `translator/mod.rs` also fixes header-module reexports of
foreign blocks. Setup runs the filtered
`win64_foreign_block_names_and_reexports` Rust unit test after building the tool.
It calls the actual `make_submodule` consumer, checks both emitted import names
through the resulting Rust AST, and checks that the block retains `win64`.
This avoids requiring unstable `register_tool` attributes for a reorganized
translation compile. Neither gate is a source-string assertion. Both hosted
gates remain unexecuted locally.

Only after this executable passes does real `blob.c` receive a 60-second
`--fail-on-error` translation gate. `--translation-only` stops this targeted probe
before redundant compiler builds and labels the result `translation_only_success`.
It does not count as compilation, link, or runtime acceptance. Then the unchanged
24-unit experiment includes all five common and 19 shader units. Remaining
variadic and foreign-type stable-Rust failures stay visible. The numeric
`offsetof` probe compares actual translated expressions against Clang 18, and
the generated Rust working copy is checked byte-identical to its source. Extern
inventory includes every emitted ABI and preserves
the aggregate declared/defined/unresolved sets alongside per-ABI sets.

No hosted tool build, smoke executable, or 24-unit result for this patch has been
observed during implementation. Passing local script tests and workflow lint do
not establish translator compilation or ABI correctness.

## Prepared tool runtime setup

Run 40398350686 prepared the pinned patched tool successfully on Ubuntu image
20261023.334.3. Both translate attempts stopped downloading `libclang-18-dev`
before the ABI or all-unit gates ran. Their logs confirm that clang-18 and
llvm-18-dev 18.1.3 were already installed.

The prepared `c2rust-transpile` links `libclang-cpp.so.18.1` and
`libLLVM.so.18.1`, plus system shared libraries. The pinned exporter's
`build.rs` uses development headers for bindgen and CMake during tool build;
the prepared executable needs the versioned runtime libraries, not those
build headers or the development link symlinks.

`check_runtime.py --record` records compiler and runtime package versions in
`tool/runtime.json` before bundling. Translate uses the Ubuntu image's existing
runtime without apt downloads. It requires exactly matching recorded versions,
Clang/LLVM 18, Rust 1.95.0, successful `ldd` resolution and executable version
checks for both C2Rust binaries. Missing libraries or a changed runner runtime
fail setup before the unchanged ABI, blob and all-24-unit gates. The ldd output
is retained in setup and translation evidence. This check is a setup gate;
it does not prove ABI or translation acceptance.

Focused local check: `python3 -m unittest discover -s tools/vkd3d-rust-probe -p 'test_check_runtime.py'`.

The variable `offsetof` regression runs after the ABI smoke and before the full
24-unit translation. `check_variable_offsetof.py` extracts 19 exact-source
struct and enum declarations, including all by-value dependencies, and ten
affected expressions from the prepared source. Missing or duplicate declarations
fail. `provenance.json` records source positions, whole-file and declaration
hashes, the metric inventory, and separately labeled synthetic operand holders.
Six pointer-only leaves use inert complete substitutes. Their bodies are never
instantiated, dereferenced, or measured. The translated fixture includes only
`stddef.h`, `stdint.h`, and `stdbool.h`.

A separate native oracle includes the original headers and the exact source-local
declarations. The caller requires original C, extracted C, and actual generated
Rust to agree on 95 size, alignment, and field-offset metrics. Flexible arrays
contribute field offsets, not invalid array sizes. Direct stable Rust 1.95.0
compiles the complete generated file with `stable_env`, without bootstrap or edits.
The local `word_count` follows the source's `unsigned int`, while allocator count
and stride remain `size_t`. The native caller checks 200
numeric comparisons, including signed and unsigned indices, size wrapping,
compound index arithmetic, fixed and flexible arrays, typedefs, reserved names,
packed/aligned structs, nested immediate array/struct element layout, and index
side effects with used and discarded results. The reserved-name cases preserve
the upstream `variable_offsetof.c` regression shapes. Negative and huge indices
exercise Clang's byte-offset extension, without forming references or allocating
objects.

The translator supports the exporter's existing two-component field/array AST
contract. A matrix row's full immediate element size is supported. Arbitrary
runtime paths such as `outer.items[i].member` and `matrix[i][j]` are not supported
by this change. Arithmetic uses the original C `size_t` type before any requested
result cast. `WithStmts` preserves index effects and inserts the index once.
Constant offsets and the existing ABI lowering remain unchanged.

Local expression checks compile the patch's actual emitted expression template
with Rust 1.95.0. They do not rebuild or execute the whole translator. Native-forwarding tests
check only the caller and are not translated success. Only a new hosted LLVM 18
tool rebuild, the numeric probe, the ABI receipts, and regeneration
of all 24 units establish integration evidence. Any subsequent raw or working
Cargo errors remain failures. `validate.py --all-units` continues to reject the
prototype as production acceptance.

The variable offsetof base field follows the translator's existing alignment
wrapper representation. It uses `offset_of!(ConvertedType, 0.renamed_field)`
when the owning record has an inner struct, and a direct field otherwise.
The original C size type, wrapping arithmetic, immediate element stride, and
index conversion remain unchanged. The upstream regression includes direct
and typedef aligned records with the reserved field name `mod`.

For a focused token API check against the patched pinned source, run
`python3 tools/vkd3d-rust-probe/check_offsetof_tokens.py --source /path/to/c2rust --artifacts /path/to/evidence`.
It compiles the actual field-path and arithmetic snippets with the pinned
AST builder and syn, then compares 40 values with the upstream native C
fixture. The record predicate is supplied as a boolean, and the Rust record
representations are explicit test fixtures. This check does not run the
exporter, type converter, field renamer, or complete translator. Hosted tool
rebuild, ABI 204/120/86, all 95 metrics and 200 vectors, and the unchanged raw
and working stable all-24-unit gates remain required.

Evaluated `ConstantExpr` values retain an effective enum type through the existing
type resolver and enum constructor. Integer and pattern contexts keep their
previous lowering. The upstream `constant_array.c` regression covers named
enumerators, zero, negative values, explicit casts, multiple elements, a typedef,
and ordinary integer arrays. The setup job translates it with the rebuilt tool
and compares 12 values and six layout metrics with native C on stable Rust.
Its evidence is under the setup artifact's `enum-constants` directory.

For a local check without rebuilding LLVM, run
`python3 tools/vkd3d-rust-probe/check_enum_constants.py --source /path/to/c2rust --artifacts /path/to/evidence --focused`.
This compiles the actual ConstantExpr branch, type resolver, constant emitter,
and enum constructor with AST shims and the pinned AST builder. It compares
the emitted arrays with the same native C fixture and checks pattern delegation.
It does not execute the exporter, complete translator, or all 24 shader units.
Use `--c2rust /path/to/c2rust` in place of `--focused` for the actual translator.
The 145 enum-array diagnostics and the separate stable E0554 blocker still need
a new hosted all-unit result. This regression does not waive any existing gate.

The setup job also runs `check_stable_boundaries.py --c2rust` on the rebuilt
pinned translator. It compiles the untouched Rust 2024 output with stable 1.95.0
and compares 48 explicit unsigned int cases, 48 stdint uint32_t cases and 11
pointer-container/refcount layouts with C,
including wraparound, decrement and single argument evaluation. The fixture
covers both legacy sync and AtomicExpr add-and-fetch callers. Other atomic
operations retain their existing intrinsic lowering. A separate C fixture checks
that signed and 64-bit types, relaxed ordering and fetch-first operations retain
intrinsics in actual translated output.

For a bounded local check without the native exporter, use
`check_stable_boundaries.py --source <patched-source> --artifacts <new-directory> --focused`.
It compiles the actual shared atomic method, resolver and opaque item builder
with AST-storage shims. It also checks that opaque records cannot be constructed
and do not implement Send, Sync or Unpin. Their Rust marker layout is not a C
pointee layout. Only thin pointers are supported by this incomplete-type model.
This check does not establish libc portability or complete stable generation.
Variadic ABI and all-unit acceptance remain separate.

The setup job runs `check_function_pointer_nulls.py --c2rust` after these gates.
The rebuilt actual translator processes the nonvariadic C fixture, and stable
Rust 1.95.0 compiles its untouched Rust 2024 output without lint suppression.
Native comparison checks 268 results for null/non-null truth, negation, null
comparison in both directions, storage qualifiers, single evaluation and short
circuiting. Each isolated volatile function must contain exactly one volatile
read and one raw address in the generated source.

For a local bounded emitter check use
`check_function_pointer_nulls.py --source <patched-source> --artifacts <new-directory> --focused`.
It compiles the actual shared pointer-null method and WithStmts map with the
pinned AST builder. Expression conversion, type classification, volatile inputs
and surrounding control flow are shims. This does not execute the exporter or
prove actual volatile lowering. Actual all-24 diagnostic removal and complete
stable acceptance remain separate, including the public variadic VaList boundary.

## Closed variadic inventory prerequisite

The project patch emits a sibling `*.variadic.json` before Rust generation when
`--emit-variadic-inventory` is enabled. The existing `--emit-c-decl-map` option
also retains inventory output for compatibility. The dedicated inventory option
does not request preprocessed source collection, declaration ranges, or source
slicing. ABI smoke still requests declaration maps and requires the
`definitions.native_callback` record. It records actual typed AST function signatures,
ABI, target C widths read from Clang, original typedef types before portable
pullback, promoted argument types and implicit conversion chains, direct
calls, function references outside direct callees, and `va_arg` locations.
Global identities include Clang asm labels and join across units; static identities include
the unit. These records authorize no conversion.

`check_closed_variadic_inventory.py --c2rust /path/to/c2rust --artifacts /new/path`
uses the rebuilt tool on untouched `variadic-fixtures/definition.c` and
`caller.c`. The separate C consumer checks the callback, two independent copies,
14 mixed arguments, narrow unsigned and enum promotions, native long widths,
15 fixed/tail evaluations, nested zero-tail calls, formatting retries and stream
bytes. Only the native C executable runs at this stage. Generated Rust is kept
and hashed, but is not yet stable or executed. The fixture deliberately leaves
its indirect public callback unclassified in the inventory plan.

The hosted all-unit probe and both inventory fixture translations request these
sidecars with `--emit-variadic-inventory`. Translation still runs to completion;
exit zero, all 24 Rust outputs, and no invalid output markers remain required.
The decoupled actual exporter and complete 24-unit run require hosted execution.
The subsequent
`closed_variadic_plan.py --probe /path/to/result --output /new/plan.json` requires
the exact 24 source paths and the actual 23-export map with `local: *`. It joins
all declarations before distinguishing private definitions from external libc
calls, and retains source, map and inventory hashes. The plan reports unsupported
promoted tails, exported candidates, address escapes, signature conflicts,
`va_arg` and unclassified indirect calls. Cursor alias/control-flow analysis,
four-host C width execution, actual lowering, and four-host generated-code ABI execution
remain required. No production variadic definition is enabled by this work.

Top-level `{"unproved":"reason"}` function signatures retain their definition
unit, declaration ID, name, location, raw signature, and reason in
`unclassified_definitions`, separate from known `symbols`. Each produces
`candidate_signature_unproved`. Calls to those definitions, including aliases,
produce `call_signature_unproved` without assigning tail slots. An unproved
declaration cannot establish compatibility with a known candidate. Malformed
signature envelopes raise `PlanError`. Unknown signatures supply no ABI,
variadic flag, or parameter defaults. The additional list is omitted when empty.

The new hosted inventory checks have not yet executed. The existing isolated
four-host native cursor probe remains separate prerequisite evidence.

The actual two-TU inventory gate also translates `exporter-fixtures/late_asm_label.c`.
The fixture introduces an asm label after the first declaration. The gate requires
both its exported declaration and direct call to use the effective later label.
This check requires the rebuilt LLVM18 exporter. A local AST API check does not
satisfy that hosted gate.


The closed variadic inventory and plan use schema 2 with record evidence schema 2.
Schema 1 and mixed evidence versions are rejected. Existing inventories must be
recollected with the bound patched exporter. They cannot be upgraded from their
TU-local diagnostic identities.

Record references carry the kind, tag, dedicated physical path and coordinates,
and a proved file or record owning scope. The finite definition table retains
ordered qualified field types and layout facts, including union alignment, and
enum variants and underlying types. Definitions refer to record identities, so
self and mutual recursion do not expand the table indefinitely. The planner
compares the actual facts from each TU and retains each TU's table in the plan.
Missing locations, macro declarations, unsupported scopes or types, forward-only
records and incomplete definitions yield `record_compatibility_unproved`.
Diagnostic locations retain their previous presumed `#line` semantics.

The existing prepare gate runs `check_closed_variadic_inventory.py` against the
built translator. Its record fixtures first syntax-check each TU independently,
then compare actual inventories. Negative cases do not depend on incompatible
C declarations being linked. The same-header case requires distinct diagnostic
file IDs and identical physical identities despite a presumed `#line` path.
The cases cover recursion, typedefs, forward-to-complete records, nested owners,
field and array changes, packing, record and union alignment, enums, qualifiers,
and function ABI. This evidence remains `inventory_only`. It does not authorize
stable lowering or replace the complete 24-unit translation, build, link,
runtime, native 23-export, target-width and source/binary provenance gates.


Schema 2 array evidence retains the original qualified element type in an
inventory-only side table for constant and incomplete arrays. Missing original
elements are unproved. The actual record matrix checks const and volatile
scalar elements, nested and flexible arrays, and valid restrict-qualified
pointer elements, including identical-qualified positive cases. LongDouble is
unproved even when both TUs report the same kind. Its ABI shape is not encoded;
the negative callback fixture uses independent x86_64 Linux compile commands
with default and `-mlong-double-64` modes and static size assertions of 16 and 8.
This is a conservative type restriction, not a general ABI-option validator.

The same gate exports valid 40-level pointer and atomic-field C fixtures and
requires the actual serializer's depth and unsupported-type sentinels in both
TUs. Identical unknown facts must remain unproved. Physical boundary cases
mutate copies of the actual same-header exporter output and retain the mutated
inventories and plans. They test rejection of unknown paths and zero physical
coordinates; they do not claim Clang emitted invalid file mappings. Dedicated
physical evidence carries a path directly, independent of diagnostic file IDs.
The existing hosted Rust inventory unit test also exercises the actual typed
CBOR decoder with malformed tuples and invalid physical coordinates. These
checks still require execution by the newly built exporter in CI.

Plain `char` carries Clang's `Char_S` or `Char_U` signedness as a boolean in
its existing type-node extras. Conversion preserves that fact in an
inventory-only typed side table. Shared translator type tags and `CTypeKind`
remain unchanged. Schema 2 requires `{"kind": "Char", "signed": true|false}`;
missing or non-boolean evidence is unproved, including through pointers,
arrays, callbacks and records. Explicit `SChar` and `UChar` keep their kinds.

The prepare gate retains all previous 28 record cases and adds five char
cases. Independent default and `-funsigned-char` x86_64 Linux TUs include the
same physical callback header and statically assert opposite char signedness.
The checker requires the actual exported callback metadata to differ and the
planner to reject the signature. Same-signed and same-unsigned profiles and
explicit signed/unsigned char callbacks remain positive. Copies of the actual
same-signed exports test missing, unknown and integer signedness rejection.
The hosted Rust serializer test checks both signedness values and missing
side-table evidence. Compiled exporter and Rust execution remain CI gates.
