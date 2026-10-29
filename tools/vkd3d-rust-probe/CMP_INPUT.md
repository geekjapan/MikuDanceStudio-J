# Exact CMP translation input

`cmp_input.normalize(original, target, native_library, output, ownership_root)`
returns a ready input receipt after copying and validating the original source
and external headers. `output` must be a new direct child of an existing owned
parent outside all original source, HDR and SPIR-V include roots. Both the parent
and output reject identical, ancestor and descendant overlap before output creation.
An interrupted copy retains `INCOMPLETE` and
never becomes a ready input. Existing directories are never removed or reused.

The checked-in contract admits only `x86_64-unknown-linux-gnu` with the immutable
current 5ab native library `3ef0f20c…201ab6`, original `spirv.c`
`8b3aaa79…7dab41e`, complete configured source/header manifests and the existing
48 positive plus two negative native output pairs. It binds the full prepared
TAR inventory, ten HLSL inputs, current compiler patch and all 27 destinations.
The original producer compiler binary identity is unproven. This is a finite
immutable library/output contract, not a reproducible producer profile.

Only the CMP branch in `spirv_compiler_emit_movc` changes. Two `uint32_t` helper
results become explicit statements, zero first and bool type second. Each helper
runs once. The three loads, destination type, tr2 argument positions, opcode,
select, store and non-CMP paths retain their original bytes. Both helpers have
`static uint32_t` return declarations in the authenticated C source. Whole-file,
site, patch and normalized hashes reject unknown or duplicate application.
`opposite_control=True` creates the type-first diagnostic input under the same
Linux contract. It does not admit another native target.

Run focused inert checks without compilers or retained executable code:

```sh
python3 -B -m unittest discover -s tools/vkd3d-rust-probe -p test_cmp_input.py -v
python3 -B -O -m unittest discover -s tools/vkd3d-rust-probe -p test_cmp_input.py -v
```

The new exact-branch workflow `vkd3d-cmp-input.yml` performs hosted execution.
It keeps the existing two helper-purpose pins `12746124666` and `12745818632`
unchanged. Its separately authorized current input artifact is `12920086814`,
run `40922269162`, head `5ab78da625214729a0792680b3f8e107188cabbe`,
14,125,958 bytes, SHA256
`943be931424262b832bffb3f599c161c390978c4aa43c9f1f9d2f6d6f078a272`.
Acquisition checks the original API identity, name, run, head, expiry, size and
digest, then the complete safe ZIP/TAR inventory and modes. Expiry fails the job.
This new scoped input does not replace the expired historical INPUT or change
any default full-admission pins. It creates no permanent hosting.

After `run_cmp_input.py --acquire NEW_DIRECTORY`, the hosted invocation is:

```sh
python3 -B tools/vkd3d-rust-probe/run_cmp_input.py \
  --source NEW_DIRECTORY/unpacked/prepared/work-linux-native/vkd3d-2.1 \
  --native-library NEW_DIRECTORY/unpacked/prepared/linux-native/lib/libvkd3d-shader.so.1.19.0 \
  --c2rust NEW_DIRECTORY/unpacked/tool/bin/c2rust \
  --clang /usr/bin/clang-18 --target x86_64-unknown-linux-gnu \
  --artifacts NEW_OUTPUT_DIRECTORY
```

The wrapper really calls the unchanged existing `probe.py` twice. Each variant
translates all 24 C units with the retained current C2Rust tool. No generated Rust
rewrite occurs. Pristine output is checked separately from license-preserved
output and its identical compilation copy. The original raw comparator and
immutable native library remain the authority. Correct input predicts 48/48.
Actual opposite C input must produce only `branch-ps-2_0-1` and
`branch-ps-3_0-1` mismatches, with the other 46 outputs unchanged. Both API rejection
controls must retain -4, empty bytes, equal diagnostics and E2004/E5013.

Cargo may add one regular `Cargo.lock` to each actual build tree. The wrapper
preserves every recorded generated Rust and TOML hash, rejects unknown extra
paths, and checks generated file modes against the emitted compilation copy.
It records lockfile bytes by size and SHA256, parses the lock, binds it to the
actual Cargo command and stage receipt, and requires the raw and working locks
to agree for the same generated dependencies. Lockfiles remain build outputs
outside the immutable translation-input manifest.

Before any output write or process launch, the wrapper uses the same typed
admission boundary as the normalizer to authenticate source, HDR, SPIR-V,
translator and native inputs. Output equality, ancestor and descendant overlap
with any input refuses without changing input files or directory membership.
Input aliases and symlinked output paths refuse.

Hosted execution requires Linux child-subreaper and pidfd support. A real
self pidfd open and signal 0 preflight must succeed and close before writers
launch. Python attribute availability alone does not admit a host. The wrapper
admits no pre-existing children and owns one probe at a time. Separate-session
descendants become its adopted children when a parent exits. Cleanup signals
only owned children through pidfds and reaps them until the child set is empty.
A normal probe that leaves a writer is a custody failure even after cleanup.
SIGINT and SIGTERM cancel the whole wrapper, including validation and final
publication after probe wait. Scoped handlers restore the caller's handlers.
The first signal interrupts work; later signals defer while owned children
are closed and reaped. Timeouts and cancellation retain closed partial
diagnostics without a final output manifest. Cancellation leaves `CANCELLED`.
Each proven invocation closure has a separate `.log.custody.json` receipt.
Only a completed finite run publishes the final manifest atomically. Unproven cleanup retains `OWNED_WRITERS_UNPROVEN` and prevents
artifact publication. The workflow job limit remains 110 minutes, with an
85-minute actual-probe step and 3000-second deadline per probe.

The hosted-only inert process check covers clean exit, an unexpected orphan,
timeout, and child launch during cancellation. It also sends real SIGINT and
SIGTERM to an owned wrapper during probe wait and after a clean probe wait. It records actual process and
session IDs, exits, times, and task-directory hashes, then checks that writes
stop after the terminal receipt. Run it only on hosted Linux:

```sh
python3 -B tools/vkd3d-rust-probe/test_cmp_input.py --process-custody NEW_OUTPUT
python3 -B -O tools/vkd3d-rust-probe/test_cmp_input.py --process-custody OTHER_NEW_OUTPUT
```

`report.json` separates finite diagnostic success from actual stable build
results. Historical stable E0554 remains a failure until actual stable compilation
succeeds. Bootstrap is isolated diagnostic fallback, never production acceptance.
Partial logs, commands, source/tool/output manifests and stable failures are
retained on failure. Target build directories are excluded from upload; their
manifest entries do not imply retained intermediate archive bytes.

Windows x64, Apple ARM64 and Linux ARM64 contracts and generated execution are
UNRUN. OS-name fallback is refused. Four-target native loader transport, stable
ABI, native callback, typed Slots/cursor, 23 exports and mandatory integration of
this same capability in the distribution generator remain later root-owned
gates. This standalone wrapper does not complete the Rust migration.
