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
It freezes the actual 24 production units and every `.h`, `.l`, and `.y` file
recursively under the complete configured source directory, including demos,
tests, and other libraries. `include/config.h` is classified separately as target
configuration. Generator inputs, the shader export map, fixture bytes, and patch
remain frozen. The complete authenticated `hdr/include/` Vulkan tree (45 files)
and `spv/include/` SPIRV tree (73 files) include conditional, unused, C++, grammar,
and `vk_video/` child inputs. This intentionally conservative inventory rejects
changes to shipped files even when the current target does not use them.

The retained in-tree Makefile has `srcdir`, `builddir`, `top_srcdir`, and
`top_builddir` equal to `.`. Its actual compile recipes search the including file's
directory for quoted includes, then `-I.`, `include/`, `include/private/`, the two
vendor roots from `CPPFLAGS`, and (for shader units) `libs/vkd3d-shader/`.
The checker binds these Makefile variables, the `COMPILE`/`LTCOMPILE` order,
shader flags, and actual compiler recipe lines to the authenticated reference.
Vendor absolute prefixes may relocate together with the retained bundle; their
ordered sibling suffixes remain fixed. Raw Makefile hashes remain in target
configuration. Different ordinary compiler flags retain separate configuration
identity; include-affecting flags outside this contract fail closed.

All files under both vendor roots and all local header/grammar files must be
classified. Every symlink in the source tree or vendor include trees, including
root and vendor-parent symlinks, fails before input hashing. The checker does not
follow linked directories or cycles. The source remains `vkd3d-2.1/`, with `hdr/`
and `spv/` siblings, matching the existing transport layout.

A conservative traversal of literal includes across all conditional branches of
all 24 production units reaches 84 files and records 40 distinct unresolved
system, SDK, or disabled-branch include names. Every reachable non-system literal
include has a `.h` filename and belongs to the frozen inventory or target
configuration. Dynamic includes, `include_next`, imports, unsupported filename
suffixes, changed resolution edges, and changed unresolved includes fail closed,
including changes in generated files. This graph is source inspection, not a
target preprocessor execution. The tar contains no compiler dependency records.

Only the eight explicitly listed Makefile parser/lexer and private generated
outputs may differ as generated files. Missing inputs, changed handwritten or
external inputs, and unclassified headers/grammars fail before native commands.
Generated and target configuration differences retain raw hashes and separate
lists; either prevents an identical source profile claim. Failure receipts retain
observed hashes, missing paths, classifications, and available graph/recipe data.

`python3 test_native_profiles.py --archive /path/to/vkd3d-probe-input.zip
--artifacts /path/to/new/verification`
authenticates the ZIP and prepared tar and requires exact local and vendor archive
inventory equality with the manifest. It checks the complete include graph and
actual Makefile binding, mutates and removes all 209 frozen inputs, and exercises
first-root shadows throughout the search trees, unknown additions, linked roots
and directories, cycles, unsupported includes, recipe/order drift, and separate
configuration receipts. Real CLI rejections retain sealed partial receipts with
zero native commands. Repeat with `python3 -O`; the checks do not use assertions.
The ordinary synthetic unit tests do not replace authenticated verification.

System C headers, compiler builtins, Windows/MinGW SDKs, and conditional platform
SDKs (including X11, Wayland, and Zircon) remain outside source identity. Disabled
SPIRV-Tools and legacy Vulkan SPIRV fallback branches remain unresolved records.
No capture claims complete compiler/SDK identity, an identical producer profile,
or reproducible builds. The image's APT packages are not version pinned.
Synthetic `compile_commands.json` files are not native build commands.

The ARM64 job also runs the frozen d046 caller against the same native library
and compares all 50 output, status, and diagnostics files byte for byte.
`--compare-driver /path/to/d046/shader_driver.rs` enables that POSIX transport
check. Windows mock DLL tests exercise the actual platform loader and free counts.
Mock tests, caller compilation, and configured workflows do not prove native
Windows or ARM64 execution. Those results require completed hosted capture jobs.
