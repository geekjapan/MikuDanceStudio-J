# Compiler-owned diagnostic common plan

`--diagnostic-common-plan` preserves the existing `transpile()` entry point and shared preparation and emitter. It prepares every C compilation command before applying emission filters. The original typed contexts are consumed once. Native buffer snapshots, effective commands, link domain, target widths and same-export AST identity bind the immutable plan before AST transformations. Definition, declaration and enclosing Call lookups execute in the existing converters.

The plan records existing emission or Deferred. It has no lowering permission. Unknown original types, signatures, attributes, visibility, cursor dataflow, aliases and escapes remain blockers. The Python inventory remains `inventory_only`; it does not authorize compiler semantics.

The initial diagnostic publication mode requires a Linux compiler host with `renameat2(RENAME_NOREPLACE)`, `--fail-on-error` and a new `--output-dir`. It refuses existing roots, encoded link or assembly database rows, ambiguous commands, colliding selected output paths, postprocessing, definition refactoring and relative dependency paths. These are compiler-host and output-layout limits. They do not describe generated target ABI support. Shell command strings require an explicit `arguments` array. Response-file arguments and the argument separator `--` are also refused because they need a separate effective-argument binding. Existing optional preprocessing for declaration maps still uses a second native `Tool.run()`.

The hosted `shader-format-facts.yml` gate uses Rust 1.95.0 and LLVM18. It discovers and runs `closed_variadic_plan_` tests against real native contexts and emission. Its full24 gate retains the complete compiler plan, source and tool receipts, all blocker reasons, export/import traces and measured process resources. It compares all generated Rust and TOML build bytes with the flag off and on. Boundary controls exercise publication refusal after native intake and conversion failure.

Run the hosted collector after the existing untouched full24 report run:

```sh
python3 -B tools/vkd3d-rust-probe/check_common_plan.py \
  --tool "$TOOL/bin/c2rust-transpile" \
  --database "$RESULT/compile_commands.json" \
  --output "$EVIDENCE/common-plan"
```

Compiler tests, full24 resource acceptance and byte equality require actual hosted execution. Source checks do not establish stable Rust build, cursor CFG analysis, native ABI, callbacks, CMP, four-host runtime or product integration. A hosted OOM fails this candidate and requires a storage-design decision. It does not permit a smaller command universe.

Independent closed-format packets use packet schema 2 and the mandatory
`unknown_authority_representation: native-unclassified-definitions-v1` tag.
Every unit binds an `authority` role with a same-stem `.unknown-authority.json`
file, including units with no unclassified definitions. The native producer
borrows the completed facts after compiler-session insertion and serializes the
exact eight-field authority through an 8 MiB sink before opening its output.
An oversized authority refuses explicitly. All six fields and nested values of
each unclassified definition remain intact.

Full replay still checks the complete native graph, census, source buffers,
raw CBOR, typed AST and generated Rust. It also requires recursive type-strict
authority equality with the verified facts. The common collector admits the
sealed exact all24 packet, current compiler and source receipts, current source
bytes and independent compiler sessions. It opens only the bounded authorities
for the existing SQLite full source/name-byte preservation join. It hashes full
facts as opaque packet members. Packet limits remain 4,096 files, 4 GiB total
and 512 MiB per member. The common report retains schema 2 and diagnostic-only
authorization. Historical packet schema 1 requires its original frozen verifier.
Actual all24 authority fit and native/Python replay remain hosted gates until
measured. No lowering or runtime adoption is established by this representation.

Prepared native intake uses schema 3 with a version 1 invocation envelope. The ordinary report path keeps schema 2 and its native `format_locations` body ranges and buffer hashes. Prepared export omits that unused key before collection; native input capture and same-CBOR instance binding remain unchanged. The envelope contains the actual command selected from the private native compilation database, parser-selected arguments and the expected result of the native argument-adjustment pipeline. One typed compiler boundary binds this evidence to the intended row and extra arguments, checks the target and regenerated cc1 invocation, rejects all native unsupported reasons, and requires complete physical-buffer, builtin-buffer, AST-source and lexer coverage. A separate prepared-only FFI entry rejects a failed native `Tool.run()`, including recoverable diagnostics with a structurally valid AST.

`PreparedProgram` owns the output transaction and publication. Its final commit checks every captured physical source, including units excluded from emission. When a filter excludes all units, a successful commit publishes only the complete diagnostic report after that check. A changed source refuses publication. The transaction and its publish method are private to the program module; the driver cannot publish after an early return.

Hosted native controls include recoverable `#error`, modules and VFS-overlay refusals after a legal baseline, coordinated metadata negatives, source changes in filtered and unemitted units, and report-only filter-zero publication. Test names and successful executions are compared with the definitions in applied source. The separate `arm64-ordinary-types` job checks the actual patched ordinary tool source on an Ubuntu ARM64 host with `DOCS_RS=1`. It skips native exporter building and proves typing only; it does not execute the exporter, test native ABI or replace the LLVM18/full24 gates. All new hosted checks require an actual run before acceptance.

The `w4-shader-retention-diagnostic` push branch reuses same-run preparation to
run the complete all24 ON command once with internal Rust phase observations.
`MDS_C2RUST_RETENTION_DIAGNOSTICS=1` and an owned `MDS_C2RUST_RETENTION_LOG`
sidecar opt in; ordinary runs have telemetry disabled. Validated complete events
are forwarded promptly by the existing parent wait loop. Records contain counts
and Linux process RSS/HWM (not live heap), with 4,096 event, 4 MiB total, 2 KiB
line and 64 KiB proc-read limits. Missing measurements remain null. Logging
failures do not change the compiler result. This diagnostic grants only
`authorization=diagnostic_only`, `paired_acceptance=UNRUN`; the unchanged all24
Rust/TOML paired gate is still required after a measured fix. It establishes no
root cause or performance improvement.
