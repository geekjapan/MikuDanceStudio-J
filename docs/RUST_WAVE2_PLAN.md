# Rust migration, wave 2

Wave 1 (`docs/RUST_MIGRATION_PLAN.md`) built the headless core: file formats, keyframe evaluation, the Bullet binding, the MME parser, and the shader compiler. Wave 2 builds the math, pose, physics, editing, rendering, and MME runtime on top of it.

Wave 2 runs as slices. A slice is one crate or one oracle tool, small enough for one agent, with its own git worktree and its own set of owned paths. Agents work on slices in parallel. The root session (the orchestrator) creates the worktrees, briefs the agents, integrates each finished slice into `main`, and is the only one that pushes.

## Oracles

Every slice gates on a committed oracle that runs on any host. These were recorded on the Windows host `nanoha-lan` and are in the repository:

- `tests/fixtures/rust/l2/`. L2 traces of `swing600.pmm` (physics on) and `swing600-nophys.pmm` (physics off), 600 frames each, with `bone`, `bonew`, `morph`, and `rigid` lines. About 14 MB. That is larger than the fixture budget of wave 1, and it is accepted because the traces are the gate for pose and physics.
- `tests/fixtures/rust/math/`. D3DX function vectors and the UCRT block digests of ten float functions, with FMA3 on and off. The two digest files differ in 1,997 blocks, most of them in `logf`.

Each directory has a README with the build, host, and sha256 of each file. Oracles that need the Windows app still to be written (golden images, MME pass plans) are slices of their own.

## Slices

`tools/orchestrate/slices.tsv` is the table the scripts read: id, wave, dependencies, host, model, license, and owned paths. Wave 2a slices have no dependencies and start together. Wave 2b slices start when their dependencies are merged.

| Slice | Wave | Scope | Gate |
|---|---|---|---|
| `math` | 2a | `mds-math`. The D3DX matrix, quaternion, and vector functions the app calls, in Rust. | Every output in `math/d3dx-vectors.txt` matches bit for bit. |
| `crtmath` | 2a | `mds-crtmath`. `sinf` `cosf` `tanf` `asinf` `acosf` `atanf` `atan2f` `expf` `logf` `powf` that match the MSVC UCRT, with a C ABI that `mds-bullet-sys` can link later. The implementer does not read UCRT source. | `cargo test` checks a fixed sample of blocks against `math/crt-digests-fma3.txt`. A full sweep (ignored test or binary) prints the matching block count per function. A function counts as done only when all 4096 blocks match. The PR lists the count per function, and partial results can merge. |
| `render` | 2a | `mds-render` core. wgpu offscreen rendering of a PMX model in bind pose with standard MMD shading. | Image hashes of the fixture models, recorded by the slice itself, with a fixed adapter and size. A run without a GPU adapter reports SKIP, not pass. |
| `edit` | 2a | `mds-edit`. Keyframe register, paste, and delete over the `mds-formats` key pools. | The Rust operations replay the operation sequences of `tools/keypool_check` to depth 4 and give the same pool states as the C++ harness, which gets a state dump mode in this slice. A property test checks the pool invariants in `.claude/skills/verify-keyframe-pool/SKILL.md`. |
| `golden` | 2a | `--mds-frame-dump <pmm> <dir> <frames>` in the C++ app, and golden images of the fixture models. Windows. | Two runs give the same bytes. The images are committed under `tests/fixtures/rust/golden/` with a README. |
| `rcptable` | 2b | The `rcpss` and `rsqrtss` results of the Windows host's CPU for every f32 input, recorded by a new oracle tool, and `mds-math` switched from its modelled estimate tables to the recorded ones. Windows. | `mds-math` reproduces both instructions for all 2^32 inputs, checked against committed block digests the same way as `crtmath`. The 428 D3DX vectors still match. |
| `pose` | 2b | `mds-pose`. Bone hierarchy, IK, append transforms, and morphs, from the L1 evaluation of `mds-scene`. | The `bone`, `bonew`, and `morph` lines of `l2/swing600-nophys-600.trace` match. |
| `physics` | 2b | `mds-physics`. Bullet in the loop through `mds-bullet-sys`, linked to `mds-crtmath`. | All lines of both L2 traces match, `rigid` included. |
| `passplan` | 2b | A pass-plan dump of the MME runtime in the C++ app, and plans for the ray-mmd corpus. Windows. | Two runs give the same bytes. The plans are committed under `tests/fixtures/rust/mme/`. |
| `rendergold` | 2b | `mds-render` compared with the golden images. | A per-pixel metric and threshold that the slice proposes and the root accepts in the PR. |
| `mme` | 2b | `mds-mme`. The SAS interpreter, the pass planner, and material binding from `third_party/mmeffect`. | The pass plans equal the `passplan` oracle. The effects come from the ray-mmd corpus (`tools/fixtures/fetch_corpus.sh`), so the test reports SKIP when the corpus is absent. |

UI (egui), media output, and packaging are wave 2c. They get slices once the 2b crates have merged.

## Licensing

The rule in `docs/RUST_MIGRATION_PLAN.md` holds. A slice is `MIT` only if it ports no upstream code. `math`, `rcptable`, `crtmath`, `render`, and `rendergold` are `MIT`, so their agents read no upstream C++ under `src/`, `include/`, or `third_party/mmeffect/`. `crtmath` is `MIT AND BSD-3-Clause`, because it translates AMD AOCL-LibM, and its README keeps AMD's notice. They work from the oracles, the fixtures, public format documents, and the wave 1 crates they depend on. The other slices port upstream code and leave the `license` field unset.

## How the root runs a slice

1. Once this plan and `tools/orchestrate/` are on `main`, `tools/orchestrate/new-slice.sh <id>` creates `.claude/worktrees/w2-<id>` on branch `w2-<id>` from `origin/main`. It refuses when a dependency's PR is not merged yet, or when another Windows slice still has a worktree.
2. The root starts one agent in that worktree with the brief below and the model from the table. Agents of independent slices start in the same message.
3. The agent commits in its worktree and reports. It does not push, open PRs, or start other writing agents.
4. `tools/orchestrate/integrate.sh <id>` checks ownership, merges `origin/main` into the slice branch, resolves `rust/Cargo.lock`, and runs `tools/rust/check.sh`. It also runs the clang-format check when the slice changed `src/` or `include/`. Windows slices also need the Windows lane (`tools/windows/`) to pass.
5. The root pushes `w2-<id>` and opens a PR into `main`. After the gate passes, the PR is merged with a merge commit, never squashed or rebased, because `new-slice.sh` finds merged dependencies by the `Merge pull request ... /w2-<id>` subject. Then the root removes the worktree.

Who merges is the operator's call. Until the operator says otherwise, the root stops at merge-ready and the operator merges. If the operator lets the root merge PRs whose gate passed, the root merges them and reports each one, and the operator can take merging back at any time.

### Shared files

An agent writes only the paths its slice owns. `rust/Cargo.lock` is the exception, because adding a dependency changes it. `integrate.sh` resolves it. On a conflict it takes `main`'s lock and lets cargo add the slice's packages back. If a package the slice added now resolves to another version than the one the slice tested, it aborts the merge and names the package, so the root pins it or the slice retests.

`rust/Cargo.toml` names `crates/*`, so a new crate needs no workspace edit. The plans, `docs/FORK.md`, and the root `README.md` belong to the root.

When an agent needs a path outside its set, it stops and reports the path. The root then extends the row in `slices.tsv` or does the edit itself.

### Windows

The Windows host runs one slice at a time. Each Windows slice checks out into `C:\mds\w2-<id>\` and builds with `tools/windows/build.ps1`. Console runs go through `tools/windows/runtask.ps1`, with `-Exclusive` for anything that sends input.

## Agent brief

The root fills in the brackets and sends this as the agent's prompt.

```
You own wave 2 slice <id> of MikuDanceStudio's Rust migration.
Read docs/RUST_WAVE2_PLAN.md (your row and the rules) and AGENTS.md first.

Worktree: <path>. Work and commit only there, on branch w2-<id>.
Owned paths: <owned>. Write nothing else except rust/Cargo.lock. If you need
another path, stop and report it.
License: <MIT: read no upstream C++ under src/, include/, third_party/mmeffect/ |
pending: leave the license field unset>.
Gate: <gate from the table>. The gate runs inside `cargo test` (or the
Windows lane for Windows slices) and must not depend on files outside the
repo, except the ray-mmd corpus from tools/fixtures/fetch_corpus.sh. A test
that needs the corpus reports SKIP, not pass, when it is absent.

Before you report, run tools/rust/check.sh and
tools/orchestrate/check-ownership.sh <id> from the worktree. Both must pass.
Commit messages carry no AI attribution lines. Do not push, open PRs, or start
agents that write files.

Report: the commits, the gate output (counts, hashes, or the first mismatch),
anything you skipped and why, and any decision the root should review.
```
