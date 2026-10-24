# Rust cross-platform core plan, wave 1

MikuDanceStudio moves from C++ with Win32 and DirectX 9 to Rust, so that one codebase runs on Windows, macOS, and Linux. The operator fixed four product rules on 2026-10-24. The new code is Rust. Physics keeps MikuMikuDance parity through the vendored Bullet 2.75. MME ships in the first release. The UI may change when every function stays available.
Wave 1 builds the headless core that later waves draw on. It covers the file formats, the keyframe evaluation, the Bullet binding, the MME effect parser, and the shader compiler. Each PR compares Rust output with an oracle built from the C++ port.
The rule the program enforces is that no Rust module lands without a byte-level comparison against the C++ oracle or a recorded corpus count.
PR ids in order are RM-1, RM-2, RM-3, RM-4, RM-5, RM-6, RM-7, RM-8, and RM-9. Appendix D lists the later waves.
RM-3, and some lanes of RM-4, RM-5, RM-6, RM-7, RM-8, and RM-9, need a Windows host. Those PRs cannot reach merge-ready until gate G2 names one.

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, a file, a log line, a screenshot, a test run, or a SHA. The body is a how-to. The appendices explain and record.

The program runs `~/.claude/skills/poteto-mode/playbooks/orchestrate.md`. The operator merges every PR. Every PR id is an operator item that stops at merge-ready, because the global working agreement requires explicit authorization for push and merge.

Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

Wave 1 changes no interaction, so no PR is review-gated. Every live lane drives a command-line tool. A lane log file is the lane's screenshot.

## Program checklist

### Arm the program

- [ ] State the protocol and this plan to the operator, then stop. Start execution only on the operator's explicit go.
- [ ] Get the operator's answer to each gate in Appendix E, or record that its default applies. Write the result to `gates.md` in the program store.
- [ ] Get explicit authorization to push branches and open PRs for RM-1 to RM-9. Approval of this plan does not grant it.
- [ ] Commit this plan and `docs/prototypes/` to `main` once the operator authorizes the commit.
- [ ] Read these from trunk at program start. Re-read them at every tick.
  - [ ] `git show origin/main:docs/RUST_MIGRATION_PLAN.md`
  - [ ] `git show origin/main:AGENTS.md`
  - [ ] `git show origin/main:docs/prototypes/p1-bullet/RESULTS.md`
  - [ ] `git show origin/main:docs/prototypes/p2-mme/RESULTS.md`
  - [ ] `~/.claude/skills/poteto-mode/playbooks/orchestrate.md`
  - [ ] `~/.agents/skills/swarm/SKILL.md`
  - [ ] `~/.claude/skills/poteto-mode/playbooks/opening-a-pr.md`
  - [ ] `~/.agents/skills/show-me-your-work/SKILL.md`, `~/.agents/skills/how/SKILL.md`, and `~/.agents/skills/interrogate/SKILL.md`
  - [ ] `.claude/skills/verify-keyframe-pool/SKILL.md`, before RM-5 designs the key pool type.
- [ ] Frame the program with this done predicate. RM-1 to RM-9 are merged, and each has a ledger verdict of `unit-test-verified` or better at its merged head SHA.
- [ ] Run `orch init` for the store `orchestrate/rust-core-wave1/`. Open the decision trail per the show-me-your-work skill.
- [ ] On the operator's go, arm the audit tick as `/loop 1h` with the tick prompt below. Never leave the cadence to memory.
- [ ] Use this tick prompt, verbatim. "Re-read the execution playbook from trunk. Audit the operation against it and fix drift in this tick. Probe every active lane and judge progress by side effects only. Stand down a stuck lane and dispatch its replacement now. Then post a short status message to the operator in chat only when the audit found a tracked change that no earlier status message reported, such as a PR opened, a code-ready head, a round launched or closed, a verdict, a merge, a stuck agent and the action taken, a blocker added or cleared, or a decision only the operator can make. Name every such change and nothing else. Do not repeat a table, the merged list, or an unchanged blocker. If the audit found none, end the turn with no reply text. Either way, log this tick's row in your decision trail. The row names the items reported, or none."
- [ ] On the operator's hold or stand-down, send every owner a zero-writes order at once.

### Spawn owners

- [ ] Spawn one owner per PR with the full lifecycle the execution playbook names. Owners use the `coder` role (`claude-sonnet-5-5`). RM-5 and RM-9 use `claude-opus-5-5` because their data shapes are one-way doors.
- [ ] Follow this dependency graph. Start dependent work only after its parent merges.
  - [ ] RM-1 and RM-4 are independent and first. Both branch from `main`.
  - [ ] RM-2 after RM-1. RM-2 branches from `origin/next` and targets `next`, per gate G1.
  - [ ] RM-3 after RM-1. RM-3 branches from `main`.
  - [ ] RM-5 after RM-1, RM-2, and RM-4. Live lane 8 of RM-5 waits for RM-3.
  - [ ] RM-6 after RM-2 and RM-5.
  - [ ] RM-7 after RM-4.
  - [ ] RM-8 after RM-1 and RM-4. Live lane 9 of RM-8 waits for RM-3.
  - [ ] RM-9 after RM-8.
- [ ] Hold the file boundaries. RM-1 touches only `tools/fixtures/` and `tests/fixtures/rust/`. RM-2 touches only `src/tools/`, `tests/`, and `CMakeLists.txt` on `next`. RM-3 touches only `src/tools/`, `src/main/`, `tools/oracle/`, `tests/`, and `CMakeLists.txt`. RM-4 to RM-9 touch only `rust/`, `tools/rust/`, `tools/oracle/`, and `tools/vkd3d/`, and each crate PR owns only its own crate directory.
- [ ] Hold the review gate. No PR in wave 1 changes an interaction, so none waits for a review in chat.

### PR mechanics, for every PR

- [ ] Resolve the forge once. Default to `gh`; if `command -v origin` succeeds and Origin can resolve the repository, use `origin pr` for every PR operation. Record any fallback to `gh`. Never require `gt`.
- [ ] Open the PR ready, never draft, per **Opening a PR**. Use `gh pr create --base <base-branch>`. RM-2 targets `next`. Every other PR targets `main`.
- [ ] Run the local checks once before the PR-facing push, because GitHub Actions has no quota. Run `tools/rust/check.sh` for Rust PRs. Run the CMake build and `ctest` for C++ PRs. Push with hooks on.
- [ ] Run `/no-comments` before review. The `deslop` skill is not installed, so run `/unslop` on the PR body and review the diff by hand before each commit.
- [ ] Triage every reviewer-bot and security-reviewer comment per `~/.claude/skills/poteto-mode/references/bugbot-triage.md`.
- [ ] Keep every commit message free of AI attribution lines, per `AGENTS.md`.
- [ ] Rebase onto current trunk before the code-ready report and babysit. Keep that merge base in fix rounds. Rebase again only at merge prep, on a `git merge-tree` conflict with trunk, or on a local check failure that comes from a change on trunk.

### Verdict and merge, for every PR

- [ ] A full swarm runs once, at the code-ready head. Another full swarm runs only for new behavior, a redesign, or a large new diff. A rebase, a merge-conflict resolution, or a minor fix gets a single verifier at the new head. Run each full swarm per `~/.agents/skills/swarm/SKILL.md`. One gates lane. The ten live lanes from the PR's **Verify, live** block. The perf lane from its **Verify, perf** block. Two or more audit lanes, each with its own focus, that read the diff and the receipts and distrust the PR body. The root audits the receipts in the merge-ready report before the verdict.
- [ ] Clean only when every lane is `PASS`. Findings go back to the owner, including a defect that a lane filed as a note. A new head gets a fresh verdict, except for results that stay valid under the patch-id rule in `playbooks/shipping.md`.
- [ ] Record each verdict with `orch ledger record`, keyed by PR number and head SHA. The owner never merges. The owner stops at merge-ready, and the operator merges. After any rebase, compare `git patch-id` before and after. Keep the verdict only when the patch-id is unchanged.

### Boot recipe, for every live lane

Each live lane runs at the PR head on this Mac, in Docker, or on the Windows host that gate G2 names. No `control-cli` skill is installed, so each lane drives the tools through plain shell commands and saves its terminal output.

- [ ] `git fetch origin <head-branch> && git checkout <head SHA>`.
- [ ] Build what the lane needs. Run `tools/rust/check.sh` for Rust crates, `tools/oracle/build_l1.sh` for the C++ oracle, and `tools/rust/check-linux.sh` for Docker lanes. Wait for exit 0.
- [ ] Run the lane's command with its full output piped through `tee`. Read-only diagnostics are `ls`, `shasum`, `cmp`, `otool -L`, `ldd`, and `mds-trace-diff`.
- [ ] Save every log as the lane's screenshot in `/tmp/swarm-<pr-id>/worker-<n>/<slug>.txt` and return the paths with the report.

## Generate deterministic fixture files (RM-1)

**Depends on.** None.

**Files.**

- [ ] Create `tools/fixtures/gen_fixtures.py`.
- [ ] Create `tools/fixtures/test_gen_fixtures.py`.
- [ ] Create `tools/fixtures/fetch_corpus.sh`.
- [ ] Create `tests/fixtures/rust/` with `chain8.pmd`, `chain8.pmx`, `chain8_ik.pmx`, `morph4.pmx`, `swing600.vmd`, `pose.vpd`, and `swing600.pmm`.

**Build.**

- [ ] Write `gen_fixtures.py` with the Python standard library only. One spec table per file drives the bytes. `chain8` has 8 bones in a chain, rigid bodies, and 6DOF joints. `chain8_ik` adds one IK chain. `morph4` has 4 vertex morphs. Names use Shift-JIS in PMD, VMD, and PMM, and UTF-16LE in PMX.
- [ ] Write a freed record in the middle of one bone track of `swing600.pmm`, so that readers meet a key pool with a gap.
- [ ] Add `--write` to regenerate the files and `--check` to regenerate into a temporary directory and compare bytes.
- [ ] Write `fetch_corpus.sh` to clone `https://github.com/ray-cast/ray-mmd` at commit `218a91cd1c53f49850b2772ebbcb98bf258e75b1` into `${TMPDIR:-/tmp}/mds-corpus/ray-mmd`, then verify the commit. The corpus stays outside the repository.

**You see.**

- [ ] `python3 -I tools/fixtures/gen_fixtures.py --check` prints `fixtures: 7 files match` and exits 0.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tools/fixtures/test_gen_fixtures.py` checks that two runs give the same bytes and that each header has the right magic, version, and record counts. Run `python3 -I tools/fixtures/test_gen_fixtures.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `worker (claude-sonnet-5-5, effort high)` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Trunk has no fixtures, so record that `tests/fixtures/rust` is absent at trunk, then run `gen_fixtures.py --check` at the head. Save `regression.txt`. Pass when trunk lacks the directory and the head prints `fixtures: 7 files match`.
- [ ] Lane 2. Build the C++ oracle with `tools/oracle/build_l1.sh` from RM-4, or with the `next` CMake build if RM-4 has not merged. Run `mds_scene_cli tests/fixtures/rust/swing600.pmm /tmp/re.pmm --root tests/fixtures/rust`. Save `cpp-load.txt`. Pass when the command exits 0.
- [ ] Lane 3. Load `/tmp/re.pmm` from lane 2 again with `mds_scene_cli`. Save `cpp-reload.txt`. Pass when the second load exits 0.
- [ ] Lane 4. Run `gen_fixtures.py --check` in `rust:1-bookworm` for `linux/amd64`. Save `linux-amd64.txt`. Pass when the output matches the committed files.
- [ ] Lane 5. Run the same check for `linux/arm64`. Save `linux-arm64.txt`. Pass when the output matches the committed files.
- [ ] Lane 6. Decode the bone names of `chain8.pmd` with `cp932`. Save `sjis-names.txt`. Pass when all 8 names equal the spec table.
- [ ] Lane 7. Read the PMX header of `chain8.pmx`. Save `pmx-header.txt`. Pass when the text encoding byte is 0 (UTF-16LE) and the name lengths are even.
- [ ] Lane 8. Count the bone keys per bone in `swing600.vmd`. Save `vmd-counts.txt`. Pass when the counts equal the spec table.
- [ ] Lane 9. Measure the fixture directory with `du -k tests/fixtures/rust`. Save `size.txt`. Pass when the total is under 256 KiB.
- [ ] Lane 10. Flip one byte in a copy of the fixtures, then run `--check` against the copy. Save `drift.txt`. Pass when `--check` exits 1 and names the changed file.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Wall time of `gen_fixtures.py --check`. Trunk has no generator, so the diff-added work is the whole run, and the user-visible end state is a green `--check`.
- [ ] Probe. Run `/usr/bin/time -p python3 -I tools/fixtures/gen_fixtures.py --check` 5 times at the head.
- [ ] Baseline. Record that trunk has no generator, so it produces no value.
- [ ] Rule. The median must stay under 5 s. A median of 5 s or more fails.

**Review gate.** None. RM-1 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Reviewer-bot triage done, or recorded as no comments.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The operator merges RM-1 into `main`.

## Dump per-frame traces from the portable C++ evaluator (RM-2)

**Depends on.** RM-1.

**Files.**

- [ ] Edit `src/tools/scene_cli.cpp` on `next`.
- [ ] Create `tests/scene_trace_test.cpp` on `next`.
- [ ] Create `include/mikudancestudio/det_math.hpp` on `next`.
- [ ] Edit `src/io/pmm_scene_evaluation.cpp` on `next`.
- [ ] Edit `CMakeLists.txt` on `next`.

**Build.**

- [ ] Add `--trace <file>` and `--frames <n>` to `mds_scene_cli`. For each frame, the tool evaluates the scene with `EvaluatePmmSceneFrame` and writes one line per bone, morph, camera, and light track. Each float is a C99 hex float (`%a`). The first line is `mds-trace 1 L1`.
- [ ] Reject a negative or non-numeric `--frames` with the usage text and exit code 2. Write no file in that case.
- [ ] Route the `std::acos` and `std::sin` calls of the slerp in `src/io/pmm_scene_evaluation.cpp` (lines 554 to 610 on `next`) through `det_math.hpp`, which evaluates in `double` and rounds to `float`. Without this, the L1 trace depends on the platform libm, as P1 showed for Bullet.

**You see.**

- [ ] `mds_scene_cli swing600.pmm /tmp/out.pmm --root tests/fixtures/rust --trace /tmp/l1.trace --frames 600` exits 0, and `head -1 /tmp/l1.trace` prints `mds-trace 1 L1`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/scene_trace_test.cpp` checks that two traces of `swing600.pmm` are byte-identical and that frame 0 equals key 0 exactly. Run `cmake --build build --target scene_trace_test && ctest --test-dir build -R scene_trace`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `worker (claude-sonnet-5-5, effort high)` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Build trunk `next` with `-ffp-contract=off` added to the formats library, as the head does. Run `mds_scene_cli swing600.pmm out.pmm --root tests/fixtures/rust` without `--trace` at trunk and at the head. Save `regression.txt`. Pass when `cmp` reports the two `out.pmm` files identical. Stock `next` on arm64 contracts multiply-adds into FMA and differs by 1 ULP, so the flag is the intended baseline change.
- [ ] Lane 2. Write the 600-frame trace on macOS arm64. Save `trace-macos.txt`. Pass when the trace has the header and one block per frame for 600 frames.
- [ ] Lane 3. Write the same trace in Docker for `linux/amd64`. Save `trace-amd64.txt`. Pass when `cmp` finds it identical to the lane 2 trace.
- [ ] Lane 4. Write the same trace in Docker for `linux/arm64`. Save `trace-arm64.txt`. Pass when `cmp` finds it identical to the lane 2 trace.
- [ ] Lane 5. Trace 700 frames of a 600-frame motion. Save `hold.txt`. Pass when frames 600 to 699 repeat the frame 599 values.
- [ ] Lane 6. Trace a key pair with the linear curve and compare the midpoint with a value computed by hand. Save `linear-mid.txt`. Pass when the midpoint equals the hand value bit for bit.
- [ ] Lane 7. Run `--frames -1` and `--frames abc`. Save `bad-args.txt`. Pass when both exit 2, print the usage, and create no trace file.
- [ ] Lane 8. Run with a wrong `--root`. Save `missing-model.txt`. Pass when the command exits non-zero and creates no trace file.
- [ ] Lane 9. Trace `morph4` keys. Save `morph.txt`. Pass when every weight is in the range 0 to 1 and equals the key value at each key frame.
- [ ] Lane 10. Build with `-O0` and with `-O2`, both with `-ffp-contract=off`, and trace `swing600.pmm`. Save `opt-levels.txt`. Pass when the two traces are identical.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Wall time of the `mds_scene_cli` re-save without `--trace` at trunk and at the head. The diff-added work is the 600-frame trace.
- [ ] Probe. Alternate trunk and head runs, 10 each, with `/usr/bin/time -p`. Then run the trace command 5 times at the head.
- [ ] Baseline. Record the trunk re-save median first.
- [ ] Rule. The head re-save median must stay within 1.05 times the trunk median. The trace median must stay under 2 s. Either limit exceeded fails.

**Review gate.** None. RM-2 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Reviewer-bot triage done, or recorded as no comments.
- [ ] Rebased onto current `next` after the verdict, patch-id unchanged.
- [ ] The operator merges RM-2 into `next`.

## Record full-model traces and math vectors on Windows x64 (RM-3)

**Depends on.** RM-1.

**Files.**

- [ ] Edit the entry point in `src/main/` to accept `--mds-trace`.
- [ ] Create `src/tools/trace_mode.cpp`.
- [ ] Create `tools/oracle/math_vectors.cpp`.
- [ ] Create `tools/oracle/fx_reflect.cpp`.
- [ ] Create `tools/oracle/startup_time.ps1`.
- [ ] Create `tests/trace_format_test.cpp`.
- [ ] Edit `CMakeLists.txt`.

**Build.**

- [ ] Add `--mds-trace <pmm> <out> <frames>` to the x64 app. The mode loads the PMM, runs the normal per-frame model update with physics, skips presenting, writes bone world matrices, morph weights, and rigid body transforms as hex floats, and exits. The first line is `mds-trace 1 L2`.
- [ ] Write `math_vectors.exe`. For each D3DX math function that `src/model` and `src/physics` call, it feeds fixed seeded inputs and writes inputs and outputs as hex. For `sinf`, `cosf`, `tanf`, `asinf`, `acosf`, `atanf`, `atan2f`, `expf`, `logf`, and `powf`, it writes one digest per block of 2^20 inputs over all 2^32 float bit patterns, plus the mismatching inputs of any block that a later comparison flags.
- [ ] Write `fx_reflect.exe`. It loads each `.fx` with the real `D3DXCreateEffectFromFileW` and dumps parameters, semantics, annotations, techniques, and passes as JSON.

**You see.**

- [ ] On Windows x64, `MikuDanceStudio.exe --mds-trace tests\fixtures\rust\swing600.pmm l2.trace 600` exits 0 and writes `mds-trace 1 L2` as its first line.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/trace_format_test.cpp` checks the line formatter on fixed matrices on every platform. Run `ctest --test-dir build -R trace_format`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `worker (claude-sonnet-5-5, effort high)` at the PR head, per the boot recipe. Every lane in this block runs on the Windows host that gate G2 names.

- [ ] Lane 1. Regression lane against trunk. Open `swing600.pmm` in the normal GUI at trunk and at the head without `--mds-trace`, move to frame 600, and save the project as a new PMM. Save `regression.txt` with both sha256 values. Pass when the two saved files are identical.
- [ ] Lane 2. Write the L2 trace for `swing600.pmm` twice. Save `l2-repeat.txt`. Pass when the two traces are byte-identical.
- [ ] Lane 3. Write the L2 trace for `chain8_ik.pmx` in a PMM. Save `l2-ik.txt`. Pass when the trace exists and two runs are identical.
- [ ] Lane 4. Write the L2 trace for the `chain8` rigid bodies. Save `l2-physics.txt`. Pass when the trace has 600 frames of rigid body transforms and two runs are identical.
- [ ] Lane 5. Compare the L2 local poses with the L1 trace from RM-2 for the same file. Save `l1-vs-l2.txt`. Pass when the lane log lists every differing track, so the gap between the two C++ evaluators is on record.
- [ ] Lane 6. Run `math_vectors.exe` for the D3DX functions. Save `d3dx-vectors.txt`. Pass when the output covers every function pointer in `struct Api` of `include/mikudancestudio/d3dx_dyn.hpp` that `src/model` or `src/physics` calls through `d3dx::Get()`.
- [ ] Lane 7. Run `math_vectors.exe` for the CRT float functions. Save `crt-digests.txt`. Pass when the output has 4096 block digests for each of the 10 functions.
- [ ] Lane 8. Compute the same block digests on macOS with `det_math.h`. Save `det-vs-crt.txt`. Pass when the lane log lists, per function, the count of blocks that differ from MSVC.
- [ ] Lane 9. Run `fx_reflect.exe` over the ray-mmd corpus and `res/assets/*.fx`. Save `fx-reflect.txt`. Pass when every file has a JSON dump or a D3DX error string.
- [ ] Lane 10. Start the app with no arguments and with an unknown `--mds-trace` path. Save `startup.txt`. Pass when the GUI starts as before without arguments and the bad path exits 1 without writing a trace.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Startup time to the first presented frame without `--mds-trace` at trunk and at the head. The diff-added work is the 600-frame trace run.
- [ ] Probe. Alternate trunk and head starts, 5 each, timed by `tools/oracle/startup_time.ps1` from process start until the main window exists. Then run the trace mode 3 times at the head.
- [ ] Baseline. Record the trunk startup median first.
- [ ] Rule. The head startup median must stay within 1.05 times the trunk median. The trace run must stay under 30 s. Either limit exceeded fails.

**Review gate.** None. RM-3 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Reviewer-bot triage done, or recorded as no comments.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The operator merges RM-3 into `main`.

## Create the Rust workspace and the trace comparer (RM-4)

**Depends on.** None.

**Files.**

- [ ] Create `rust/Cargo.toml` and `rust/rust-toolchain.toml`.
- [ ] Create `rust/crates/mds-trace/`.
- [ ] Create `tools/rust/check.sh`, `tools/rust/check-linux.sh`, and `tools/rust/check.ps1`.
- [ ] Create `tools/oracle/build_l1.sh`.

**Build.**

- [ ] Pin the toolchain to rustc 1.95.0 in `rust-toolchain.toml`.
- [ ] Write `mds-trace`, which parses trace format 1. Its binary `mds-trace-diff <a> <b>` exits 0 when the traces match. It exits 1 and prints the first difference as frame, track, field, and both hex values. It exits 2 on a parse error and names the line number.
- [ ] Write `check.sh` to run `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and `cargo test`. Write `check-linux.sh` to run `check.sh` in `rust:1-bookworm`, pinned by digest, for `linux/amd64` and `linux/arm64`. Write `check.ps1` with the same steps for Windows.
- [ ] Write `build_l1.sh <next-sha>` to build `mds_scene_cli` from `git archive` of `next` at that SHA, configured with `-DMIKUDANCESTUDIO_FORMATS_ONLY=ON`, into `${TMPDIR:-/tmp}/mds-oracle/<sha>/`. A second run with the same SHA reuses the build.

**You see.**

- [ ] `tools/rust/check.sh` exits 0, and `mds-trace-diff` on two copies of one trace exits 0.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `rust/crates/mds-trace/tests/diff.rs` covers identical traces, a first difference, and a bad header. Run `tools/rust/check.sh`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `worker (claude-sonnet-5-5, effort high)` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Trunk has no `rust/` directory, so record that, then run `tools/rust/check.sh` at the head. Save `regression.txt`. Pass when trunk lacks `rust/` and the head check exits 0.
- [ ] Lane 2. Run `tools/rust/check-linux.sh` for `linux/amd64`. Save `linux-amd64.txt`. Pass when the check exits 0.
- [ ] Lane 3. Run `tools/rust/check-linux.sh` for `linux/arm64`. Save `linux-arm64.txt`. Pass when the check exits 0.
- [ ] Lane 4. Compare two copies of an L1 trace from RM-2. Save `diff-same.txt`. Pass when `mds-trace-diff` exits 0.
- [ ] Lane 5. Change one hex digit in a copy, then compare. Save `diff-one.txt`. Pass when `mds-trace-diff` exits 1 and names the frame, track, and field of the change.
- [ ] Lane 6. Cut a trace in the middle of a line, then compare. Save `diff-cut.txt`. Pass when `mds-trace-diff` exits 2 and names the line number.
- [ ] Lane 7. Run `tools/oracle/build_l1.sh` with the merged RM-2 SHA. Save `build-l1.txt`. Pass when it prints the path and sha256 of `mds_scene_cli`.
- [ ] Lane 8. Run `build_l1.sh` again with the same SHA. Save `build-l1-again.txt`. Pass when it skips the build and prints the same sha256.
- [ ] Lane 9. Add a failing test to a scratch copy of the workspace, then run `check.sh` there. Save `check-fails.txt`. Pass when `check.sh` exits non-zero.
- [ ] Lane 10. Run `tools/rust/check.ps1` on the Windows host that gate G2 names. Save `windows.txt`. Pass when the check exits 0.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Warm wall time of `tools/rust/check.sh`, and the time of `mds-trace-diff` on a 600-frame trace. Trunk has no Rust code, so both are diff-added work.
- [ ] Probe. Run each command 5 times at the head with `/usr/bin/time -p`.
- [ ] Baseline. Record that trunk has no Rust workspace, so it produces no value.
- [ ] Rule. The warm check median must stay under 60 s, and the diff median under 0.5 s. Either limit exceeded fails.

**Review gate.** None. RM-4 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Reviewer-bot triage done, or recorded as no comments.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The operator merges RM-4 into `main`.

## Read and write the MMD file formats in Rust (RM-5)

**Depends on.** RM-1, RM-2, and RM-4. Live lane 8 also needs the PMM that RM-3 lane 1 saves.

**Files.**

- [ ] Create `rust/crates/mds-formats/` with modules `pmd`, `pmx`, `vmd`, `vpd`, `pmm`, and `key_pool`.
- [ ] Create `rust/crates/mds-formats/tests/roundtrip.rs` and `rust/crates/mds-formats/tests/truncation.rs`.

**Build.**

- [ ] Name the data shape first. Each format is a typed struct that keeps every field the C++ writer emits. Strings keep their raw bytes next to the decoded text, so a name that does not survive a Shift-JIS round trip still writes back unchanged. Decode with `encoding_rs`.
- [ ] Model PMM key tracks as `KeyPool<K>`, a fixed-capacity arena with track heads at their C++ indices and the raw `previous` and `next` indices. `src/io/pmm_save.cpp:141` writes those indices into the file, so the Rust writer must reproduce them.
- [ ] Validate every count and offset against the remaining bytes before any allocation. Return `Err` on bad input and never panic.
- [ ] Add the binary `mds-formats` with the subcommands `roundtrip <file> [--out <file>]` and `flipfuzz --seed <n> --iters <n>`.

**You see.**

- [ ] `mds-formats roundtrip tests/fixtures/rust/swing600.pmm` prints `identical 1 file`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `roundtrip.rs` round-trips all 7 fixtures. `truncation.rs` cuts each fixture at every byte offset and expects `Err`. Run `tools/rust/check.sh`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `worker (claude-sonnet-5-5, effort high)` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Trunk has no Rust reader, so re-save `swing600.pmm` with the C++ `mds_scene_cli` from `build_l1.sh` and with `mds-formats roundtrip --out`. Save `regression.txt`. Pass when the Rust file is byte-identical to the input, and the log records whether the C++ re-save is identical too. Identity with the input is the rule, because the `next` writer `pmm_scene_writer.cpp` is not the MMD port `pmm_save.cpp`.
- [ ] Lane 2. Round-trip all 7 fixtures. Save `fixtures.txt`. Pass when every file is byte-identical.
- [ ] Lane 3. Round-trip `ray_controller.pmx` from the corpus that `fetch_corpus.sh` fetches. Save `ray-pmx.txt`. Pass when the file is byte-identical.
- [ ] Lane 4. Run `cargo test --release -p mds-formats --test truncation`. Save `truncation.txt`. Pass when the test passes with no panic.
- [ ] Lane 5. Run the byte-flip check `mds-formats flipfuzz --seed 1 --iters 100000` on each fixture. Save `flipfuzz.txt`. Pass when no run panics and peak memory stays under 64 MiB.
- [ ] Lane 6. Print the decoded bone names of `chain8.pmd`. Save `sjis.txt`. Pass when they equal the RM-1 spec table.
- [ ] Lane 7. Load the Rust-written `swing600.pmm` with the C++ `mds_scene_cli`, then re-save it. Save `cpp-reads-rust.txt`. Pass when the C++ re-save equals the Rust bytes.
- [ ] Lane 8. Round-trip the PMM that RM-3 lane 1 saved with the MMD port `src/io/pmm_save.cpp`. Save `mmd-writer.txt`. Pass when the file is byte-identical.
- [ ] Lane 9. Round-trip `pose.vpd`. Save `vpd.txt`. Pass when the file is byte-identical, CRLF line endings included.
- [ ] Lane 10. Read a PMM whose key pool has a freed record in the middle of a track. The generator writes this case into `swing600.pmm`. Save `pool-gap.txt`. Pass when the round trip keeps the gap and every `previous` and `next` index.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Read-and-write time of `swing600.pmm` and `ray_controller.pmx`. Trunk measures the C++ re-save. The head measures `mds-formats roundtrip`.
- [ ] Probe. Alternate C++ and Rust runs, 20 each, per file, with `/usr/bin/time -p`.
- [ ] Baseline. Record the C++ medians first.
- [ ] Rule. Each Rust median must stay within 1.5 times the C++ median. A larger ratio fails.

**Review gate.** None. RM-5 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Reviewer-bot triage done, or recorded as no comments.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The operator merges RM-5 into `main`.

## Evaluate keyframes in Rust to match the L1 trace (RM-6)

**Depends on.** RM-2 and RM-5.

**Files.**

- [ ] Create `rust/crates/mds-scene/` with modules `curve`, `track`, and `frame`.
- [ ] Create `rust/crates/mds-scene/tests/l1_parity.rs`.

**Build.**

- [ ] Port `EvaluatePmmSceneFrame` and its helpers from `src/io/pmm_scene_evaluation.cpp` on `next`. Keep the same operation order and `f32` and `f64` types, so that the results match bit for bit.
- [ ] Route every transcendental call through one `mds_math` module that evaluates in `f64` and rounds to `f32`, as `det_math.hpp` does. `f32::sin` calls the platform `sinf`, so it would break the cross-platform lanes.
- [ ] Add the binary `mds-scene trace <pmm> --root <dir> --frames <n>` that writes trace format 1 with the header `mds-trace 1 L1`.

**You see.**

- [ ] `mds-trace-diff` of the Rust trace and the C++ trace of `swing600.pmm` exits 0.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `l1_parity.rs` compares the Rust trace of each fixture with a C++ trace committed under `rust/crates/mds-scene/tests/l1/`. Unit cases cover the curve at 0, at 1, and at the linear midpoint. Run `tools/rust/check.sh`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `worker (claude-sonnet-5-5, effort high)` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Trunk has no Rust evaluator, so trace `swing600.pmm` with the C++ L1 oracle and with `mds-scene trace`. Save `regression.txt`. Pass when `mds-trace-diff` exits 0.
- [ ] Lane 2. Compare the traces of a PMM with `chain8_ik.pmx`. Save `ik-keys.txt`. Pass when `mds-trace-diff` exits 0.
- [ ] Lane 3. Compare the traces of a PMM with `morph4.pmx`. Save `morph.txt`. Pass when `mds-trace-diff` exits 0.
- [ ] Lane 4. Run lane 1 in Docker for `linux/amd64`. Save `linux-amd64.txt`. Pass when `mds-trace-diff` exits 0.
- [ ] Lane 5. Run lane 1 in Docker for `linux/arm64`. Save `linux-arm64.txt`. Pass when `mds-trace-diff` exits 0.
- [ ] Lane 6. Trace 700 frames of the 600-frame motion. Save `hold.txt`. Pass when `mds-trace-diff` against the C++ trace exits 0.
- [ ] Lane 7. Trace at `--seconds 1.2345` on both sides. Save `seconds.txt`. Pass when `mds-trace-diff` exits 0.
- [ ] Lane 8. Compare only the camera and light tracks. Save `camera-light.txt`. Pass when `mds-trace-diff` exits 0 and the trace has both tracks.
- [ ] Lane 9. Trace frames 0 to 600 in steps of 0.5 on both sides. Save `half-frames.txt`. Pass when `mds-trace-diff` exits 0.
- [ ] Lane 10. Run lane 1 on the Windows host that gate G2 names. Save `windows.txt`. Pass when `mds-trace-diff` exits 0.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Time to trace 600 frames of `swing600.pmm`. Trunk measures the C++ L1 oracle. The head measures `mds-scene trace`.
- [ ] Probe. Alternate C++ and Rust runs, 10 each, with `/usr/bin/time -p`.
- [ ] Baseline. Record the C++ median first.
- [ ] Rule. The Rust median must stay within 1.5 times the C++ median. A larger ratio fails.

**Review gate.** None. RM-6 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Reviewer-bot triage done, or recorded as no comments.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The operator merges RM-6 into `main`.

## Wrap Bullet 2.75 for Rust with deterministic float math (RM-7)

**Depends on.** RM-4.

**Files.**

- [ ] Create `rust/crates/mds-bullet-sys/` with `build.rs`, `shim/mds_bt.cpp`, `shim/mds_bt.h`, and `shim/det_math.h`.
- [ ] Create `rust/crates/mds-bullet/` with the safe `World` type.
- [ ] Create `rust/crates/mds-bullet/examples/chain8.rs`.
- [ ] Create `rust/crates/mds-bullet-sys/shim/bench_main.cpp`.

**Build.**

- [ ] Compile `recipes/bullet275/bullet-src/src` and the shim in `build.rs` with the `cc` crate. Use `-O2 -ffp-contract=off -fno-fast-math -fdeclspec` on clang and `/fp:precise` on MSVC. Force-include `det_math.h` with `-include` on clang and `/FI` on MSVC.
- [ ] Expose a C API for the parts MMD uses. These are world create, step, and destroy, rigid bodies with sphere, box, and capsule shapes, mass, damping, restitution, friction, collision group and mask, the kinematic flag, `btGeneric6DofSpringConstraint` joints, and transform get and set.
- [ ] Wrap the C API in `mds_bullet::World`, which owns every handle and frees them on drop.
- [ ] Port the P1 scene from `docs/prototypes/p1-bullet/shim/bt_shim.cpp` as the `chain8` example. Both print the mean time per step.
- [ ] Write `bench_main.cpp`, a C++ driver that runs the same `chain8` scene through the shim without Rust.

**You see.**

- [ ] `cargo run -p mds-bullet --example chain8` prints `final b7be367fb1ece153`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `rust/crates/mds-bullet/tests/world.rs` checks the `chain8` hash and that dropping a world frees its bodies. Run `tools/rust/check.sh`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `worker (claude-sonnet-5-5, effort high)` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Trunk has no Rust binding, so the reference is the P1 hash `b7be367fb1ece153` in Appendix A. Run the example on macOS arm64. Save `regression.txt`. Pass when the final hash equals the reference.
- [ ] Lane 2. Run the example for `x86_64-apple-darwin` under Rosetta. Save `macos-x64.txt`. Pass when the final hash equals the reference.
- [ ] Lane 3. Run the example in Docker for `linux/amd64`. Save `linux-amd64.txt`. Pass when the final hash equals the reference.
- [ ] Lane 4. Run the example in Docker for `linux/arm64`. Save `linux-arm64.txt`. Pass when the final hash equals the reference.
- [ ] Lane 5. Run the example with MSVC on the Windows host that gate G2 names. Save `windows.txt`. Pass when the final hash equals the reference.
- [ ] Lane 6. Run the example on Windows with `MDS_BT_SYSTEM_MATH=1`, which drops `det_math.h`. Save `windows-crt.txt`. Pass when the lane log records the hash and the MSVC version next to the lane 5 hash.
- [ ] Lane 7. Build the shim with `MDS_BT_ASAN=1` on macOS and run 600 frames. Save `asan.txt`. Pass when AddressSanitizer reports nothing.
- [ ] Lane 8. Create and drop 10000 worlds in a loop. Save `leak.txt`. Pass when resident memory grows by less than 5 MiB.
- [ ] Lane 9. Drop a body onto a plane in a group that the plane's mask excludes. Save `filter.txt`. Pass when the body falls through the plane.
- [ ] Lane 10. Build with `RUSTFLAGS="-C target-cpu=native"` and run the example. Save `native.txt`. Pass when the final hash equals the reference.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Mean time per `stepSimulation` call over 600 frames of the `chain8` scene. Trunk has no Rust binding, so the comparison is a C++ driver that calls the same shim directly.
- [ ] Probe. Alternate the C++ driver and the Rust example, 10 runs each, and read the per-step mean that each prints.
- [ ] Baseline. Record the C++ driver mean first.
- [ ] Rule. The Rust mean must stay within 1.05 times the C++ mean. A larger ratio fails.

**Review gate.** None. RM-7 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Reviewer-bot triage done, or recorded as no comments.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The operator merges RM-7 into `main`.

## Parse MME effect files in Rust (RM-8)

**Depends on.** RM-1 and RM-4. Lane 9 also needs the `fx_reflect.exe` output from RM-3.

**Files.**

- [ ] Create `rust/crates/mds-fx/` with modules `preprocess`, `lex`, `parse`, `ast`, and `entries`.
- [ ] Create `rust/crates/mds-fx/tests/golden/` with 20 hand-checked annotation values.

**Build.**

- [ ] Write the preprocessor. It resolves `#include` against the top-level `.fx` directory first and the including file's directory second. It matches path parts without case and treats `\` as `/`. It defines the macros that `third_party/mmeffect` passes to D3DX, `_INDEX` and `MME_MIPMAP` among them. It keeps a line map back to each source file.
- [ ] Write the lexer. It joins adjacent string literals into one literal.
- [ ] Write the parser for globals with semantics, annotations, and initializers, for `sampler_state` blocks, and for `technique` and `pass` blocks with state assignments and `compile` expressions.
- [ ] Return `shader_source()` with the technique blocks removed, `entries()` with each profile, function, and argument list, and a wrapper function for each entry that binds `uniform` parameters to the `compile` arguments.
- [ ] Decode Shift-JIS source bytes when they are not valid UTF-8.
- [ ] Add the binary `mds-fx scan <dir>...`. With `--entries`, it prints one line per unique entry in the column order of `docs/prototypes/p2-mme/shaders-direct.tsv`.

**You see.**

- [ ] `mds-fx scan "${TMPDIR:-/tmp}/mds-corpus/ray-mmd" res/assets` prints the counts of files, techniques, and unique entries. The unique entry count is 1483, as in the prototype.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Inline tests cover string joining, both include rules, annotation types, and the uniform-argument wrapper. The golden test checks the 20 annotation values. Run `tools/rust/check.sh`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `worker (claude-sonnet-5-5, effort high)` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Trunk has no parser, so the reference is the entry list from `docs/prototypes/p2-mme/corpus.py`. Run `mds-fx scan --entries` and the prototype on the same corpus. Save `regression.txt`. Pass when the two entry sets are equal for every file.
- [ ] Lane 2. Scan every ray-mmd `.fx` file. Save `ray-scan.txt`. Pass when every file parses, except for the one file whose include `shader/CameraMotion.fxsub` is missing, which returns an error that names the include.
- [ ] Lane 3. Scan `res/assets/skin_effect_sm2.fx` and `res/assets/skin_effect_sm3.fx`. Save `standard.txt`. Pass when the technique and pass counts equal the counts of `technique` and `pass` blocks in each file.
- [ ] Lane 4. Log the include resolutions for the corpus. Save `includes.txt`. Pass when all 2303 includes resolve against the top-level directory.
- [ ] Lane 5. Scan the raw Shift-JIS `skin_effect_sm3.fx` without `iconv`. Save `sjis.txt`. Pass when the result equals the result for the UTF-8 copy.
- [ ] Lane 6. Run the golden test. Save `golden.txt`. Pass when all 20 annotation values match.
- [ ] Lane 7. Cut `skin_effect_sm3.fx` at every byte offset and parse each prefix. Save `truncation.txt`. Pass when every prefix returns a result or an error and none panics.
- [ ] Lane 8. Run lane 2 in Docker for `linux/amd64`, where the file system is case-sensitive. Save `linux-case.txt`. Pass when the result equals lane 2.
- [ ] Lane 9. Compare parameters, semantics, annotations, techniques, and passes with the `fx_reflect.exe` JSON from RM-3. Save `d3dx-reflect.txt`. Pass when every file matches, or when every difference is listed in the PR as a known D3DX behavior with a test.
- [ ] Lane 10. Parse a copy of the corpus with a syntax error placed at line 12 of an included `.fxsub`. Save `line-map.txt`. Pass when the error names that `.fxsub` file and line 12.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Wall time of `mds-fx scan` over the corpus. Trunk has no parser, so the scan is diff-added work.
- [ ] Probe. Run the scan 5 times at the head with `/usr/bin/time -p`.
- [ ] Baseline. Record that trunk has no parser, so it produces no value.
- [ ] Rule. The median must stay under 5 s. A median of 5 s or more fails.

**Review gate.** None. RM-8 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Reviewer-bot triage done, or recorded as no comments.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The operator merges RM-8 into `main`.

## Compile MME shaders to WGSL, MSL, and HLSL (RM-9)

**Depends on.** RM-8.

**Files.**

- [ ] Create `rust/crates/mds-shader/` with modules `vkd3d`, `spirv_fix`, `ctab`, and `backend`.
- [ ] Create `tools/vkd3d/build.sh`.

**Build.**

- [ ] Write `tools/vkd3d/build.sh` to build vkd3d-shader 2.1 from the tarball with sha256 `7510146aff2adfb4ae07ab890701a607e5ff7c66e57100cfc9f630ec92eeda6a` as a shared library. It builds for macOS, for Linux, and for Windows with mingw-w64 in Docker.
- [ ] Load the shared library at run time with `libloading`, so the program links vkd3d-shader dynamically, per gate G3.
- [ ] Compile each entry from `mds-fx` straight from HLSL to SPIR-V. Rewrite `sampler2D` parameters to `sampler` before the compile.
- [ ] Remove the `PointSize` output that vkd3d-shader adds to every vertex shader. Use `rspirv` on the SPIR-V module, not text editing.
- [ ] Parse the `CTAB` block of a d3dbc compile to map each parameter name to its constant register. Record a different reflection source for the shaders whose d3dbc compile fails, per the reflection box below.
- [ ] Validate each module with `naga` and write WGSL, MSL, and HLSL. Pin `naga` to the version that the planned `wgpu` release uses.
- [ ] Add the binary `mds-shader corpus <dir>...`. With `--list`, it prints one line per shader in the format of `docs/prototypes/p2-mme/shaders-direct.tsv`. With `--wgpu-check`, it creates a `wgpu` device, then a shader module and a render pipeline for each WGSL output.
- [ ] Pick the reflection source for the 36 shaders whose d3dbc compile fails on the register limit while the direct compile succeeds. Record the choice in the PR body.

**You see.**

- [ ] `mds-shader corpus "${TMPDIR:-/tmp}/mds-corpus/ray-mmd" res/assets` prints `shaders 1483 spirv 1413 wgsl 1413 msl 1413 hlsl 1413` or higher counts.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Tests check that the `PointSize` removal leaves a module that `naga` validates, and that the `CTAB` parser reads the names `EgColor`, `LightDir`, `SpcColor`, and `ToonColor` from the `BufferShadow_PS` d3dbc. Run `tools/rust/check.sh`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `worker (claude-sonnet-5-5, effort high)` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Trunk has no shader compiler, so the reference is the per-shader list `docs/prototypes/p2-mme/shaders-direct.tsv`. Run `mds-shader corpus --list`. Save `regression.txt`. Pass when every shader marked `OK` in the list passes, and the SPIR-V count is 1413 or more.
- [ ] Lane 2. Run lane 1 in Docker for `linux/amd64`. Save `linux-amd64.txt`. Pass when the counts equal lane 1.
- [ ] Lane 3. Run lane 1 on macOS arm64 with the macOS `.dylib`. Save `macos.txt`. Pass when the counts equal lane 1.
- [ ] Lane 4. Run lane 1 and `--wgpu-check` on DX12 on the Windows host that gate G2 names, with the mingw `.dll`. Save `windows.txt`. Pass when the counts equal lane 1 and every pipeline is created.
- [ ] Lane 5. Print the reflection of the `skin_effect_sm3.fx` shaders. Save `ctab.txt`. Pass when every name and register equals the `vkd3d-compiler -b d3d-asm` listing.
- [ ] Lane 6. Print the reflection source used for each of the 36 register-limit shaders. Save `reflection-gap.txt`. Pass when all 36 have a parameter map and the PR body names the source.
- [ ] Lane 7. Parse each WGSL output again with `naga`. Save `wgsl-reparse.txt`. Pass when all 1413 or more outputs validate.
- [ ] Lane 8. Run `mds-shader corpus --wgpu-check` on macOS, where `wgpu` uses Metal. Save `metal-pipelines.txt`. Pass when every shader module and render pipeline is created without a validation error.
- [ ] Lane 9. Run `mds-shader corpus --wgpu-check` in Docker for `linux/amd64` with the Mesa `lavapipe` Vulkan driver. Save `vulkan-pipelines.txt`. Pass when every shader module and render pipeline is created without a validation error.
- [ ] Lane 10. Inspect the release binary with `otool -L` on macOS and `nm` on Linux. Save `linkage.txt`. Pass when no vkd3d symbol is defined inside the binary and the library loads from its own file.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Median and 95th percentile time per shader for the corpus. Trunk has no compiler, so the reference is the prototype pipeline in `docs/prototypes/p2-mme/corpus.py`.
- [ ] Probe. Alternate the prototype run and the `mds-shader corpus` run, 3 each, and read the per-shader times that each prints.
- [ ] Baseline. Record the prototype median first.
- [ ] Rule. The Rust median must not exceed the prototype median, and the 95th percentile must stay under 200 ms. Either limit exceeded fails.

**Review gate.** None. RM-9 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Reviewer-bot triage done, or recorded as no comments.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The operator merges RM-9 into `main`.

## Close the program

- [ ] Every box above is checked with its evidence.
- [ ] Write the wave 2 plan from Appendix D with the evidence that RM-3, RM-6, RM-7, and RM-9 produced.
- [ ] Reply to the operator with the report the execution playbook names.

## Appendix A. Prototype evidence

Both prototypes ran on 2026-10-24 at `main` commit `4708ef8`. Their files are under `docs/prototypes/` and are not committed yet.

**P1. Bullet from Rust on four CPUs.** `docs/prototypes/p1-bullet/RESULTS.md` has the setup and the table.

- Proven. A Rust binary drives the vendored Bullet 2.75 through a C ABI.
- Proven. With platform libm, macOS arm64, macOS x86_64, and Linux give three different final hashes. The two macOS builds first differ at frame 30.
- Proven. With `det_math.h`, macOS arm64, macOS x86_64, Linux arm64, and Linux amd64 all end at `b7be367fb1ece153`, and their per-frame traces are byte-identical.
- Unproven. No Windows build ran. MSVC's CRT is a fifth libm.
- Unproven. Parity with MikuMikuDance physics. The vendored `mmd*` x87 helpers compile only under `_MSC_VER && _M_IX86`, so the reachable target is the x64 SSE behavior. Physics parity with MMD x64 also needs `det_math.h` to return the MSVC x64 CRT results. RM-3 lanes 7 and 8 measure that gap.

**The L1 evaluator depends on libm.** The slerp in `src/io/pmm_scene_evaluation.cpp` on `next` calls `std::acos` and `std::sin` (lines 554 to 610). RM-2 and RM-6 route those calls through double-evaluated math, for the reason P1 shows.

**The L1 oracle builds on macOS.** `git archive origin/next` configured with `-DMIKUDANCESTUDIO_FORMATS_ONLY=ON` built `mds_scene_cli` with Apple clang 21.0.0, and the binary printed its usage line.

**P2. MME shaders through vkd3d-shader and naga.** `docs/prototypes/p2-mme/RESULTS.md` has the setup, the counts, and the failure samples. The corpus is ray-mmd at commit `218a91cd1c53f49850b2772ebbcb98bf258e75b1` plus the two standard effects in `res/assets/`. The tools are vkd3d-shader 2.1 and naga 30.0.1.

- Proven. The `fx_2_0` writer in vkd3d-shader 2.1 cannot build MME effects. It stops on `sampler_state` initializers and on pass state assignments. The effect layer must be Rust code.
- Proven. vkd3d-shader rejects adjacent string literals in annotations, which MME `Script` annotations use. Removing technique blocks before the shader compile avoids the problem.
- Proven. All 2303 includes in the corpus resolve against the top-level `.fx` directory with no fallback. Path parts need a case-insensitive match, because ray-mmd writes `shader/` for the `Shader/` directory.
- Proven. The direct HLSL to SPIR-V compile builds 1413 of 1483 shaders (95.3%) into SPIR-V that `spirv-val` accepts. The d3dbc route builds 1377 (92.9%).
- Proven. After the `PointSize` removal, naga writes WGSL, MSL, and HLSL for all 1413 modules.
- Proven. The d3dbc output carries a `CTAB` block with parameter names.
- Unproven. Rendered output. The counts measure compile and validation, not image parity.
- Unproven. Driver acceptance. This Mac has no Metal compiler (`xcrun metal` is missing), so no MSL output reached a Metal compiler. vkd3d-shader compiled the naga HLSL of 2 of 3 standard pixel shaders as `ps_5_0`. The third stopped on E5022 at the `nagaSamplerHeap` index that naga writes for DX12, so vkd3d-shader cannot check DX12 HLSL. RM-9 lanes 4, 8, and 9 check through `wgpu` devices instead.
- Unproven. Reflection for the 36 shaders whose d3dbc compile fails on the register limit.
- Unproven. The remaining 70 failures are vkd3d-shader defects. 40 fail on E9022 in the pixel shader input signature. 30 fail on E5027 when constant folding of `pow(0, 2.2)` meets `-inf`.

## Appendix B. Alternatives rejected

- **Go.** The operator chose Rust on 2026-10-24.
- **Rapier or another Rust physics engine.** It cannot give Bullet 2.75 parity, which is a product rule.
- **The `fx_2_0` path of vkd3d-shader.** P2 shows it is not implemented for MME effects.
- **DXC with SPIRV-Cross.** DXC accepts shader model 6 only, so every community effect would need a rewrite.
- **DXVK or Gallium Nine.** Neither runs on macOS.
- **wgpu shader passthrough as the main path.** It skips validation, and DX12 passthrough needs HLSL or DXIL that vkd3d-shader does not write.
- **The glslang HLSL front end.** It was deprecated in April 2026.
- **A nanoem-style text translator.** Its MPL-2.0 code needs a full source read before reuse, and the Rust effect parser is required anyway.
- **The C++ RHI on `next` as the renderer.** wgpu covers Metal, Vulkan, and DX12 in Rust and replaces it.
- **The L1 evaluator on `next` as the only oracle.** It covers key interpolation only. It has no bone hierarchy, IK, or physics, so RM-3 adds the Windows L2 trace.

## Appendix C. Risks

- **No Windows host for agents.** RM-3, and lane 10 of RM-4, RM-6, and RM-9, need Windows. The owner of each PR parks those lanes under gate G2 until a host exists, and the PR stays short of merge-ready.
- **MSVC CRT math differs from `det_math.h`.** Physics would then diverge from MMD x64 within about 30 frames, as P1 showed for two libm builds. RM-3 lane 8 measures it. If blocks differ, wave 2 adds a correction table or a port of the MSVC routines.
- **D3DX math is not bit-reproducible by formula.** The model code in `src/model` calls D3DX. RM-3 lane 6 records vectors, and wave 2 adds a Rust math crate gated on them.
- **The two C++ evaluators may disagree.** RM-3 lane 5 lists the gaps between L1 and L2. The owner of RM-6 matches L1, and wave 2 moves the scene crate to L2.
- **No rendering oracle.** Wave 2 needs golden images captured on Windows with MMD and MME. The images stay outside the repository.
- **No licensed models.** Only `res/assets/axis.x` ships in the repository. RM-1 makes synthetic fixtures. Operator models stay outside the repository, per gate G5.
- **No `control-cli` or `deslop` skill.** Lanes run shell commands and save logs. The desktop UI in a later wave has no control skill either.
- **vkd3d-shader defects.** The owner of RM-9 pins version 2.1, carries the `sampler2D` rewrite, and files the E9022 and E5027 cases upstream.
- **The LGPL terms of vkd3d-shader.** The project license is freeware with all rights reserved. Gate G3 decides the terms.
- **PMM files store key pool indices.** `src/io/pmm_save.cpp:141` writes `previous` and `next`. If the Rust key pool allocates in a different order, saved files differ from MMD files. The owner of RM-5 matches the allocation in `kfa::AllocateFromCursor`, and the editing wave ports `verify-keyframe-pool` as a Rust property test.
- **Two PMM writers.** `pmm_scene_writer.cpp` on `next` is a separate writer from the MMD port `src/io/pmm_save.cpp` on `main`. Files that MMD or the MMD port write are the parity target. RM-5 checks identity with the input file and round-trips a file from RM-3 lane 1.
- **GitHub Actions has no quota.** Every check runs locally or in Docker.

## Appendix D. Links and reading list

Read before editing.

- `docs/prototypes/p1-bullet/RESULTS.md` and `docs/prototypes/p2-mme/RESULTS.md`.
- `src/io/pmm_scene_evaluation.cpp` and `src/tools/scene_cli.cpp` on `origin/next`.
- `src/io/pmm_save.cpp`, `src/model/keyframe_common.hpp`, and `.claude/skills/verify-keyframe-pool/SKILL.md` on `main`.
- `third_party/mmeffect/src/effect_engine.cpp`, `sas_interpreter.cpp`, `pass_planner.cpp`, and `material_bind.cpp`.
- The vkd3d-shader 2.1 header `vkd3d_shader.h` and the naga front-end table at `https://github.com/gfx-rs/wgpu/tree/trunk/naga`.

RM-5 and RM-9 go through `~/.agents/skills/how/SKILL.md` before code and `~/.agents/skills/interrogate/SKILL.md` before merge-ready, because their data shapes and the library linkage are hard to reverse. The decision trail lives in the program store per `~/.agents/skills/show-me-your-work/SKILL.md`.

Wave 2 gets its own plan when RM-3, RM-6, RM-7, and RM-9 have merged. Each later item waits for an oracle.

- **Math and scene parity with L2.** A Rust D3DX math crate gated on RM-3 vectors, then the bone hierarchy, IK, append transforms, and physics in the loop gated on L2 traces.
- **Renderer.** wgpu with winit, standard MMD shading first, gated on Windows golden images.
- **MME runtime.** A port of the SAS interpreter, the pass planner, and material binding from `third_party/mmeffect`, on top of RM-8 and RM-9.
- **UI.** egui with keyframe editing. The `verify-keyframe-pool` property becomes a Rust property test.
- **Media.** Video and audio output in place of DirectShow, VFW, and DirectSound.
- **Packaging.** Signed builds for Windows, macOS, and Linux, with the vkd3d-shader library and its license text.

## Appendix E. Operator gates

Each gate has a default. The program applies the default when the operator gives no answer, and reports it.

- **G1. Branch for RM-2.** Default. RM-2 targets `next`, because `mds_scene_cli` and the portable evaluator exist only there. The Rust PRs target `main` and build the oracle from a pinned `next` SHA. The operator could instead merge `next` into `main` first.
- **G2. Windows host.** Default. The operator's Windows PC runs the Windows lanes, and those lanes wait until the operator says it is ready. The operator could instead name a GitHub Actions Windows runner once the quota returns.
- **G3. vkd3d-shader license terms.** Default. Ship vkd3d-shader as a separate shared library with its LGPL-2.1 text and a source offer, and load it at run time. The operator could instead choose a different license plan or ask for a Rust HLSL front end, which costs much more work.
- **G4. Push and PR authorization.** Default. None. Owners stop before the first push until the operator authorizes pushes and PRs for this program.
- **G5. Operator models.** Default. Wave 1 uses synthetic fixtures and the ray-mmd corpus only. The operator could instead name a local directory of MMD models in `MDS_CORPUS`, which lanes read and never commit.
- **G6. Using `d3dx9_43` as a test oracle.** Default. `fx_reflect.exe` and `math_vectors.exe` run on the operator's Windows host with the D3DX runtime that MMD already needs. Nothing from D3DX enters the repository or a release.
