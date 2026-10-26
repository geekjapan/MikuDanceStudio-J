# Packaging mds-app

Wave 3 ships one Rust binary, `mds-app`, on Windows, macOS, and Linux
([RUST_WAVE3_PLAN.md](RUST_WAVE3_PLAN.md), slice `package`). The scripts in
`tools/package/` build one archive per platform locally and run the packaged
binary from the unpacked archive. Nothing here publishes anything, and the
release workflow `.github/workflows/release.yml` still builds the C++ app.

## Archives

| Platform | Target | Built | Archive |
|---|---|---|---|
| macOS | `aarch64-apple-darwin` | on the Mac | `mds-app-<VERSION>-<commit>-macos.tar.gz` |
| Linux | `aarch64-unknown-linux-gnu` (or `x86_64` with `linux-amd64`) | in a pinned `rust:1-bookworm` container | `mds-app-<VERSION>-<commit>-linux-arm64.tar.gz` |
| Windows | `x86_64-pc-windows-msvc` | on the Windows host, from the Mac | `mds-app-<VERSION>-<commit>-windows-x86_64.zip` |

Each archive has one top folder with:

- `mds-app` (`mds-app.exe`). Bullet 2.75 is linked in through `mds-bullet-sys`.
- The vkd3d-shader 2.1 library from `tools/vkd3d/build.sh`, beside the
  binary, where `mds-shader` looks for it when `MDS_VKD3D_LIB` is unset:
  `libvkd3d-shader.1.dylib`, `libvkd3d-shader.so.1`, or
  `libvkd3d-shader-1.dll`. The Windows DLL is a MinGW build and needs
  `libgcc_s_seh-1.dll`, which ships beside it.
- `licenses/` (below) and a short `README.txt`.

`mds-app` reads no files of `res/` at run time. It uses system fonts for the
Japanese text (`rust/crates/mds-app/src/window.rs`). The Windows build has the `dxopenni`
feature. The MoCap menu then loads `Data\DxOpenNI.dll` beside the exe. That
DLL is not in the package, and without it the menu reports that Kinect is
unavailable, as it does without the feature.

### Run-time requirements

- macOS 11 or later on Apple silicon. `package.sh` builds vkd3d-shader with
  `MACOSX_DEPLOYMENT_TARGET=11.0` and refuses a library that targets a later
  version. The binary is not signed or notarized.
  A downloaded copy carries the quarantine flag; remove it with
  `xattr -d com.apple.quarantine`.
- Linux: glibc 2.36 or later (Debian 12), `libasound2`, `libwayland-client0`,
  `libvulkan1`, and a Vulkan driver. The window also needs the X11 or Wayland
  libraries that winit opens at run time.
- Windows 10 or later with a DX12 adapter. The C runtime is linked statically
  (`+crt-static`), so no Visual C++ redistributable is needed.

## Build

```sh
tools/package/package.sh macos          # here; needs Xcode tools and bison >= 3
tools/package/package.sh linux-arm64    # Docker; linux-amd64 runs under emulation
tools/package/package-windows.sh        # the Windows host over ssh (tools/windows/README.md)
```

Output goes to `$MDS_PACKAGE_OUT`, else `${TMPDIR}/mds-package`, never into
the repository. The vkd3d-shader build is `$MDS_VKD3D_OUT`, else
`<out>/vkd3d`. The scripts run `tools/vkd3d/build.sh` when the library is
missing.

`package-windows.sh` needs a clean, committed tree. It sends the branch as a
git bundle and the vkd3d DLLs to `C:\mds\w2-package` (`MDS_WINDOWS_DIR`), and
runs `package.ps1` there over ssh. That script builds `mds-app` twice, with
the default features and with `dxopenni`, prints `dumpbin /dependents` of
both, and zips the `dxopenni` build. Delete the host folder when you are done.

## Licenses

`tools/package/licenses.py` writes `licenses/`, which every archive carries:

| Path | What |
|---|---|
| `LICENSE`, `LICENSE-MIT`, `FORK.md` | Copies of the repository's files. `FORK.md` says which paths are MIT and which are license pending. |
| `bullet-2.75/` | `recipes/bullet275/LICENSE.txt` (zlib). |
| `vkd3d/` | `LICENSE`, `COPYING` (LGPL-2.1), and `AUTHORS` from the vkd3d 2.1 tarball, the applied patches, and `SOURCE.md`, which names the source tarball, its sha256, and the patches. |
| `mingw-runtime/` | The Debian copyright file of the package `libgcc_s_seh-1.dll` comes from, written by `tools/package/mingw-copyright.sh`. |
| `mds-crtmath/` | The AOCL-LibM notice from `rust/crates/mds-crtmath/README.md`. |
| `rust/` | `COPYRIGHT-library.html` and the license texts of the pinned toolchain's standard library, which is linked into `mds-app`. |
| `crates.tsv`, `THIRD-PARTY.txt` | Every third-party crate of the dependency graph and its license files. `THIRD-PARTY.txt` gives each distinct text once, after the crates that use it. |
| `fetched/` | Texts of crates whose packages have none. |

The graph is `cargo metadata` with the `dxopenni` feature, for the targets
of the three packages, following normal and build dependencies from
`mds-app`. It can include a few crates that a given platform does not link
(for example `egui_glow`). A crate's texts are the files named `LICENSE*`,
`COPYING*`, `NOTICE*`, `COPYRIGHT*`, or `UNLICENSE*` in its package, outside
`tests/`, plus `fonts/*.txt` of `epaint_default_fonts`.

When a package has none, `licenses.py --fetch` downloads the license files of
its repository with `gh api`, at the commit in its `.cargo_vcs_info.json`, or
at its release tag when that commit is not on GitHub, and records the URL in
`fetched/<crate>/SOURCE`. Without the texts the script fails and names the
crate. `dispatch 0.2.0` declares MIT but has no license file in its package or
its repository; `fetched/dispatch-0.2.0/NOTE` records that instead of a text.

`package.sh` runs `licenses.py` and stops if `licenses/` then differs from
the commit. After a dependency change, run `licenses.py --fetch`, then
commit `licenses/`. Run `mingw-copyright.sh` when the vkd3d Windows build
changes its runtime DLLs.

License generation also needs the pinned toolchain's `rust-docs` component,
which the minimal Rust profile does not install. From `rust/`, run
`rustup component add rust-docs` if it is missing. Generated files are staged
before replacement, so a missing input leaves the previous generated files
intact. The cached `fetched/` and `mingw-runtime/` notices are preserved.

## Smoke test

`tools/package/smoke.sh <archive>` (macOS, Linux) and `smoke.ps1` (Windows,
run by `package-windows.sh` in the console session through
`tools/windows/runtask.ps1`) unpack the archive into a new folder. Then they
run the binary from there, with `MDS_VKD3D_LIB` unset:

1. `--frame-dump` of `tests/fixtures/rust/swing600.pmm` at frames 0, 150, 300,
   and 599.
2. The same for `swing600-golden.pmm`, which is the scene of the golden images.
   `compare.py` scores its PNGs against `tests/fixtures/rust/golden/` by the
   rule of `rust/crates/mds-app/tests/frame_dump.rs`: at least 0.9999 of the
   pixels within 4, no pixel off by more than 48, and the same overlay mask.
3. `--frame-dump` of the MME scene `tests/fixtures/rust/mmegold/anime.pmm`,
   frames 0 and 3. The effect needs vkd3d-shader. If the library beside the
   binary does not load, the MME runtime does not start and the dump fails.
   This dump is not scored.

Linux runs in a new `debian:bookworm` container with only the run-time
packages. Docker on the Mac has no GPU, so wgpu runs on Mesa lavapipe
(llvmpipe), the only Vulkan driver there. Mesa prints
`error: XDG_RUNTIME_DIR is invalid or not set` there while wgpu probes the
window systems; the dumps do not need one. The logs are
`<out>/smoke-<platform>.log`.

A comparison failure or interrupted comparator makes the shell script fail;
its output and diagnostics remain in the log. Run the local gate checks with
`python3 -I tools/package/test_smoke.py` and
`python3 -I tools/package/test_licenses.py`. They use temporary directories
and stand-ins, without builds, GPUs, containers, or Windows host access.

## Unverified

- `mds-app` does not print its wgpu adapter. The logs list the system's
  adapters, and the backend is fixed per platform (Metal, DX12, Vulkan in
  `mds_render::Gpu::new`). Which adapter wgpu chose is inferred.
- The editor window was not opened from a package. The smoke test is
  headless.
- The Kinect path of the `dxopenni` build is not exercised: no device and no
  `DxOpenNI.dll`. It is only confirmed to build with MSVC.
- The packages were run only on the build machines: macOS 27 on an M4 Pro,
  Windows on the RTX 3090 host, and the Debian 12 container. Older OS
  versions, other GPUs, and `linux-amd64` were not run.
- The MME frame is not compared with its golden image.
- The Linux run-time library list comes from the smoke container, not from
  an audit of every `dlopen` (Wayland, X11, and xdg-desktop-portal for the
  file dialogs).
