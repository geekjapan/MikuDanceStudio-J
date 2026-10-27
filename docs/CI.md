# Continuous integration

`CI` runs on branch pushes, pull requests, and manual dispatches. Push and pull request runs share a concurrency group for the source branch, so a newer run cancels an older run. Manual runs use a separate group for each branch.

- Windows x64: build the vendored Bullet dependency with Conan, build Release with CMake, install the checksum-verified DirectX June 2010 runtime, and run CTest. JUnit results and CTest logs are uploaded even when a test fails.
- Rust release builds: compile the entire workspace with the lockfile on Windows x64, macOS Apple Silicon, and Linux x64 and ARM64. Each target uploads the `mds-app` executable in a tar archive to preserve executable permissions.
- Linux Rust: install the toolchain from `rust/rust-toolchain.toml`, fetch the pinned ray-mmd corpus, build the patched vkd3d-shader library, and run `tools/rust/check.sh` (format, Clippy with warnings denied, and workspace tests). Mesa supplies a software Vulkan adapter. FFmpeg supplies the media test tools. The Rust log is uploaded even when a check fails. Missing GPU adapters fail the job.

Windows CI and `Windows release` call `windows-build.yml`. CI archives Rust executables as build artifacts. It does not publish a release. The release workflow retains its `v*` tag and manual existing-tag triggers. It packages Windows x64 and publishes only after its build and tests succeed. Only the publish job has repository write permission.

Windows Win32 and Intel macOS are unsupported and are excluded from the CI matrices.

The official Actions are pinned to release commit SHAs. No repository secrets or self-hosted runners are required.

## Keyframe pool verification

The dedicated **Keyframe pool verification** workflow runs on relevant
`src`, `include`, harness, and Rust replay changes, and manual dispatch. It
uses Ubuntu hosted runners and clang AddressSanitizer; it does not require
secrets. It does not add heavy local checks to the ordinary development
loop.

It runs the real C++ model-pool verifier at depth 4 with the existing bounds
(2 bones, 2 morphs, frames 0..2, 24 tracked records, 4 configurations),
including the display and morph pool-full checks. ASan findings and
tracked-window cuts fail the job. The generated dump must match
`rust/crates/mds-edit/tests/data/keypool-depth4.txt` byte-for-byte, then the
Rust `keypool_replay` test must pass.

A separate mutation step removes the exact production display-selector
bounds guard in a disposable source copy and runs depth 1. It must fail
with the display-paste trace and a symbolized ASan heap-buffer-overflow in
`key_registrars.cpp`. Compilation errors, unrelated crashes, or a passing
mutant fail the job. The original checkout remains unchanged on failure or
interruption. Baseline and mutation builds use separate temporary directories.

The `keyframe-pool-<sha>` artifact is uploaded even on failure and retains
compiler and commit information, verifier logs, ASan logs, the generated
oracle, the comparison result, and the targeted Rust replay log when those
steps ran. Read the run conclusion and these logs together. A missing step
or canceled run is not verification. Floating-point output may differ on a
hosted CPU from the existing Apple clang baseline; investigate a mismatch
without weakening bounds or silently refreshing the fixture.

The maintained skill at `.claude/skills/verify-keyframe-pool/SKILL.md`
records the property, assumptions, audited source, exclusions, and sync
commit. Advance sync only after inspecting covered-source changes and an
actual successful run at the new commit. Adding this workflow alone is not
proof of a hosted run. Camera, light, self-shadow, gravity, accessory,
undo/redo, and unmodeled call orders are outside its proof.

## Verification limits

The Rust build artifacts contain the application executable only. They are not standalone installers: MME requires the matching vkd3d-shader shared library at runtime, and Linux requires the application system libraries. These jobs verify compilation and linking; the Linux test job verifies runtime behavior separately. The C++ application targets Windows only.

Hosted runners do not replace native GUI checks or comparisons on the reference Windows host. CTest can report GPU tests as skipped. Rust adapter-specific hash tests can report a missing baseline on a new adapter, and corpus tests can report unsupported effects. Read the saved test logs before treating those checks as verified. The Rust suite also contains tests that deliberately exercise missing-input handling and tests ignored by default.

## Local checks

Run the Rust checks with the corpus and vkd3d library prepared as described in `tools/fixtures/fetch_corpus.sh` and `tools/vkd3d/build.sh`:

```sh
bash tools/rust/check.sh
```

Validate all workflow files, including reusable-workflow inputs:

```sh
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
```

GitHub execution requires these workflow files to be pushed. Branch protection and required checks are configured separately in repository settings.
