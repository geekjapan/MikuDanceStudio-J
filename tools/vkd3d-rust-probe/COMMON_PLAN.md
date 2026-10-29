# Compiler-owned diagnostic common plan

`--diagnostic-common-plan` preserves the existing `transpile()` entry point and shared preparation and emitter. It prepares every C compilation command before applying emission filters. The original typed contexts are consumed once. Native buffer snapshots, effective commands, link domain, target widths and same-export AST identity bind the immutable plan before AST transformations. Definition, declaration and enclosing Call lookups execute in the existing converters.

The plan records existing emission or Deferred. It has no lowering permission. Unknown original types, signatures, attributes, visibility, cursor dataflow, aliases and escapes remain blockers. The Python inventory remains `inventory_only`; it does not authorize compiler semantics.

The initial diagnostic publication mode requires a Linux compiler host with `renameat2(RENAME_NOREPLACE)`, `--fail-on-error` and a new `--output-dir`. It refuses existing roots, encoded link or assembly database rows, ambiguous commands, colliding selected output paths, postprocessing, definition refactoring and relative dependency paths. These are compiler-host and output-layout limits. They do not describe generated target ABI support. Shell command strings require an explicit `arguments` array. Existing optional preprocessing for declaration maps still uses a second native `Tool.run()`.

The hosted `shader-format-facts.yml` gate uses Rust 1.95.0 and LLVM18. It discovers and runs `closed_variadic_plan_` tests against real native contexts and emission. Its full24 gate retains the complete compiler plan, source and tool receipts, all blocker reasons, export/import traces and measured process resources. It compares all generated Rust and TOML build bytes with the flag off and on. Boundary controls exercise publication refusal after native intake and conversion failure.

Run the hosted collector after the existing untouched full24 report run:

```sh
python3 -B tools/vkd3d-rust-probe/check_common_plan.py \
  --tool "$TOOL/bin/c2rust-transpile" \
  --database "$RESULT/compile_commands.json" \
  --output "$EVIDENCE/common-plan"
```

Compiler tests, full24 resource acceptance and byte equality require actual hosted execution. Source checks do not establish stable Rust build, cursor CFG analysis, native ABI, callbacks, CMP, four-host runtime or product integration. A hosted OOM fails this candidate and requires a storage-design decision. It does not permit a smaller command universe.
