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
enables the finite `mds-vkd3d-fresh-producer-v1` recording contract. Only the
Windows cross producer and Linux native producer are supported in record mode.
The default non-record recipe and runtime comparators retain their behavior.
Record mode requires fresh output, authenticates the three raw archives with the
existing fixed hashes, applies the reviewed patches, and records full input
snapshots at preparation, configuration, generation/freeze, compilation, and
installation. Configuration uses `--disable-dependency-tracking`; every generation,
parallel build, fallback, and install invocation explicitly selects the same
`-f /physical/source/Makefile` and `V=1`. Ambient make flags, `MAKEFILES`, compiler
include/search injection, and tool overrides are rejected. Configure and all
make/generator children receive only PATH, HOME, TMPDIR, LANG, LC_ALL, CC, and
CONFIG_SITE; CONFIG_SITE is explicitly `/dev/null`. Receipt Python runs isolated. `CC` may be unset or
`/usr/bin/gcc-13`, matching the two hosted recipes.

The configured-to-frozen transition may change only the eight listed generated
outputs. All other prepared/configured files, including Makefile, config.status,
config.h, libtool, and executable build helpers, are frozen before compilation.
Compilation and installation must preserve every frozen file and executable bit.
The receipt records actual ordered make argv, including a fallback only if run.
The retained work tree contains frozen inputs and logs; build-output symlinks are
excluded. Installed libraries and runtime DLLs remain in the retained prefix.
Failures retain available work, stage/error records, and build exit status.

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

The producer receipt binds the reviewed recipe hash, archive hashes, patches,
ordered stages, frozen manifest, and physical ordered include roots to a strict
relative mapping under `record/work`. The collector checks every transported
frozen file before any caller compiler or native command. Original POSIX producer
paths are compared as POSIX strings and need not exist on Windows. The original
vendor prefix must exactly match the recorded Makefile; arbitrary sibling-prefix
normalization does not authorize a different producer tree.

The existing Makefile projection and literal include graph are supplementary
catalog observations. `identical_source_profile` is explicitly scoped by
`identity_scope: reference_catalog_only`; it is not complete compiler-input
identity or native admission. Generated/configuration differences are accepted
for capture only when bound to a complete fresh producer receipt and unchanged
post-freeze snapshots. An old configured tree without that receipt is rejected.

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

The eight generated filenames classify catalog differences; their names alone
never authorize received generated bytes. The collector also requires the
versioned producer contract for native-only captures. Missing, unknown, incomplete,
mutated, duplicate-path, escaping-path, or wrongly mapped receipts fail closed.

`python3 test_native_profiles.py --archive /path/to/vkd3d-probe-input.zip
--artifacts /path/to/new/verification`
authenticates the ZIP and prepared tar and requires exact local and vendor archive
inventory equality with the manifest. It checks the complete include graph and
actual Makefile binding, mutates and removes all 209 frozen inputs, and exercises
first-root shadows throughout the search trees, unknown additions, linked roots
and directories, cycles, unsupported includes, recipe/order drift, and separate
configuration receipts. These original 209 input and 41 boundary controls remain
catalog checks. Eight additional authenticated historical-tree controls cover the
unchanged tree, GNUmakefile/makefile, an extra make fragment, the exact previously
untracked `.Plo` path, config.h, libtool, and generated C; all require sealed
pre-native rejection without a fresh receipt. Synthetic receipt tests separately
exercise relocation and receipt invariants. Real CLI rejections retain sealed partial receipts with
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

A producer receipt is evidence, not a cryptographic attestation. Its reviewed
recipe hash identifies the contract; it does not authenticate who ran it.
Independent GitHub job/API provenance auditing is required for hosted acceptance.
No old prepared artifact is relabeled as a new trusted producer. Neither the
receipt nor catalog traversal proves complete system SDK/compiler identity,
remote reproducibility, native Windows/ARM execution, or Rust acceptance.
