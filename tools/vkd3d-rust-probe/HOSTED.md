# Hosted translation probe

The [workflow](../../.github/workflows/vkd3d-rust-probe.yml) collects
evidence for `hlsl.c`, `hlsl.tab.c`, `hlsl.yy.c`, and `d3d_asm.c` separately.
Configuration and local script checks do not establish a hosted result.
No extended local translation is part of this continuation.

## Execution contract

| Stage | Configuration |
| --- | --- |
| Runner | Standard `ubuntu-24.04`, Linux x64. No larger runner or external service. |
| Setup | One job, maximum 35 minutes. Package installation 5 minutes, Rust installation 3, native input preparation 8, C2Rust build 12, bundle 2. |
| Input | Existing `tools/vkd3d/build.sh linux-native`, with unchanged source URLs, checksums, patches, and `build_in` rules. |
| Source location | `$MDS_VKD3D_OUT/work-linux-native/vkd3d-2.1`, with sibling `hdr` and `spv` include trees. The workflow checks `include/config.h` and all four generated or handwritten C files. |
| Migration tool | Official C2Rust `ac687698b6c13491dfec45c6a9ad9e8b4da35227`, compiled once and shared in a tar artifact. |
| LLVM | Ubuntu Noble `clang-18`, `llvm-18-dev`, `libclang-18-dev`, and `libclang-cpp18-dev`. Actual package versions and dynamic dependencies are logged. A failed tool build is a setup failure, not a translation timeout. |
| Rust | Explicit `1.95.0` for the tool and generated crate, independent of runner defaults. |
| Translation | Four matrix entries, serialized with `max-parallel: 1`, `fail-fast: false`. Each translator gets 1,800 seconds with `--fail-on-error --edition 2024`. |
| Other limits | Native syntax check 120 seconds. Each Rust build 120 seconds. Probe step 40 minutes, each matrix job 50 minutes, including setup and artifact slack. |
| Permissions | `contents: read`, checkout credentials disabled. No PR trigger, secrets, deployment, or package publication. |
| Triggers | Manual dispatch, or pushes to `w2-shader-c2rust-prototype` that change this workflow, probe Python files, or `tools/vkd3d/build.sh`. Documentation-only changes do not trigger translation. |
| Concurrency | Grouped by repository and Git ref. An existing attempt is not canceled by another dispatch. |
| Artifacts | Input/tool bundle retained 1 day. Setup logs and each unit's complete generated source, copied input, license notices, hashes, logs, and extern inventory retained 7 days. Cargo targets are excluded. |

Ubuntu's [Noble LLVM package](https://packages.ubuntu.com/noble/llvm-18-dev)
and the official [Ubuntu 24.04 runner image inventory](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
establish this toolchain's availability. The hosted C2Rust build is still a
required check. The workflow does not assume that the local LLVM 23 result
proves LLVM 18 compatibility.

The new native target requires Linux and fresh `work-linux-native` and
`linux-native` output paths. It rejects existing directories and symlinks
before download or cleanup. Existing build targets keep their behavior.

## Result interpretation

`probe.py` checkpoints `result.json` before external tools run. It records
UTC start and end timestamps, elapsed time, user and system CPU time, peak RSS
in bytes, exit code, and timeout for each command. Resource values come from
POSIX `wait4`; they describe the command and its waited children, not total
runner memory. A time limit kills the command's entire process group.

`validate.py` checks that the expected C unit was selected and reports:

- `incomplete` for missing output, timeout, signal termination, or interrupted evidence collection.
- `syntax_failure` for rejected native C input.
- `translation_failure` for a translator error or emitted placeholder macro.
- `compiler_failure` when complete emitted Rust does not compile.
- `prototype_success` when only explicit bootstrap or experimental flags compile the unit.
- `success` only when the entire emitted unit builds on the pinned stable compiler.

Only `success` passes the hosted validation step. Prototype success remains
visible but does not make the job green. Missing translation units,
`compile_error!`, `unimplemented!`, and `todo!` cannot count as a complete
translation. A failed or incomplete job still uploads available artifacts.
Setup failure prevents the matrix from starting and has separate setup
metadata and logs. An absent result is never treated as success.

The result concerns one translation unit. It does not prove a full compiler
link, shader equivalence, Windows portability, memory safety, or GPU behavior.
The faithful vkd3d Rust translation remains the selected migration route;
C2Rust remains a helper for that work.

## Dispatch and checks

The root owns independent review, integration, push, and dispatch. The initial
attempt starts when the root pushes the independently reviewed commit to
`w2-shader-c2rust-prototype`. The push trigger applies only to that branch
and the executable paths above. No translation has been started here.

GitHub requires a manual workflow to [exist on the default branch before dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
After integration, the root can select the exact reviewed ref manually:

```sh
gh workflow run vkd3d-rust-probe.yml --ref REVIEWED_REF
```

The dispatch must stay within the repository's existing included Actions
and artifact-storage allowance. This workflow does not enable additional
spending. Maximum configured job time is 235 standard runner minutes across
one setup and four serialized matrix jobs; actual billed use depends on
execution and the repository's plan. No hosted job has been started here.

Focused local checks:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/vkd3d-rust-probe -p 'test_*.py' -v
actionlint .github/workflows/vkd3d-rust-probe.yml
bash -n tools/vkd3d/build.sh
```
