# Continuous integration

`CI` runs on branch pushes, pull requests, and manual dispatches. Push and pull request runs share a concurrency group for the source branch, so a newer run cancels an older run. Manual runs use a separate group for each branch.

- Windows x64: build the vendored Bullet dependency with Conan, build Release with CMake, install the checksum-verified DirectX June 2010 runtime, and run CTest. JUnit results and CTest logs are uploaded even when a test fails.
- Rust release builds: compile the entire workspace with the lockfile on Windows x64, macOS Apple Silicon, and Linux x64 and ARM64. Each target uploads the `mds-app` executable in a tar archive to preserve executable permissions.
- Linux Rust: install the toolchain from `rust/rust-toolchain.toml`, fetch the pinned ray-mmd corpus, build the patched vkd3d-shader library, and run `tools/rust/check.sh` (format, Clippy with warnings denied, and workspace tests). Mesa supplies a software Vulkan adapter. FFmpeg supplies the media test tools. The Rust log is uploaded even when a check fails. Missing GPU adapters fail the job.

Windows CI and `Windows release` call `windows-build.yml`. CI archives Rust executables as build artifacts. It does not publish a release. The release workflow retains its `v*` tag and manual existing-tag triggers. It packages Windows x64 and publishes only after its build and tests succeed. Only the publish job has repository write permission.

Windows Win32 and Intel macOS are unsupported and are excluded from the CI matrices.

The official Actions are pinned to release commit SHAs. No repository secrets or self-hosted runners are required.

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
