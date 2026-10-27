# Native producer profile capture

`vkd3d-native-profiles.yml` measures the existing Debian MinGW x64 producer on
Windows 2022 and the existing native GCC 13 recipe on Ubuntu 24.04 ARM64.
It runs the unchanged 48 shader inputs and two rejection controls through the
actual native library. `translated_comparison` remains `not_run`.
The strict Linux translated comparator and its oracle remain independent.

`shader_driver.rs` keeps its linked generated compiler mode by default.
`rustc +1.95.0 --edition 2024 --cfg native_only shader_driver.rs` excludes linked
compiler exports and rejects `-`. The native-only caller needs no generated
archive. Windows loads an absolute UTF-16 DLL path with
`LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS`.
Missing libraries and exports fail without fallback. Both caller modes share
input construction, status, diagnostics, output, and compile/free ownership.

`MDS_VKD3D_RECORD_DIR=/absolute/fresh/path bash tools/vkd3d/build.sh windows`
enables recording. The default recipe and compiler selection are unchanged.
Record mode runs actual make commands with `V=1`, including generation, retries,
and installation. It retains configure arguments, environment build flags,
compiler path, hash, version, target, specs, internal tool hashes, package and
generator versions, configured work, logs, dependency files, generated sources,
installed libraries, runtime DLLs, licenses, and Windows import tables.
The container EXIT trap copies work and prefix to the mounted record directory
on success and failure before `--rm` removes the container.
Use an empty record directory for each build.

`check_shader_inputs.py --native-only --cc /path/to/caller-cc --source
/path/to/configured/vkd3d-2.1 --build-record /path/to/record --header
/path/to/vkd3d_shader.h --native-library /path/to/library --artifacts
/path/to/new/capture` binds the source and producer records to the capture.
`--cc` measures header layouts. It does not identify the native producer compiler.
Layouts cover shader code, options, compile info, HLSL info, and SPIR-V target info.
The capture retains commands, source inputs, outputs, API status, diagnostics,
caller binary identity, actual loaded module paths and hashes, and a file seal.
Failure and timeout receipts retain partial results. Each caller process has a
30-second timeout. On macOS, module hashes absent from disk because of the dyld
shared cache are `null`. Windows and Linux require hashes for every observed path.

`native-profile-reference.json` comes from the actual d046 run 40457744278,
artifact 12712854308. Its ZIP was verified against SHA-256
`5e91fd623d475c8519a024e9f80a1db758e1a23a3e9af4fa6642263edf8f7d84`.
It freezes the actual 24 production units, headers, fixture bytes, and patch.
Handwritten source drift fails. Generated source differences are retained and
prevent an identical source profile claim. Target configuration is recorded
separately. No capture claims an identical producer profile or reproducible
build, because the pinned image's APT packages are not version pinned.
Synthetic `compile_commands.json` files are not native build commands.

The ARM64 job also runs the frozen d046 caller against the same native library
and compares all 50 output, status, and diagnostics files byte for byte.
`--compare-driver /path/to/d046/shader_driver.rs` enables that POSIX transport
check. Windows mock DLL tests exercise the actual platform loader and free counts.
Mock tests, caller compilation, and configured workflows do not prove native
Windows or ARM64 execution. Those results require completed hosted capture jobs.
