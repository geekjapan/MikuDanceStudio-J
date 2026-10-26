# Rust migration, wave 3

Wave 3 replaces the remaining C++ with Rust and ends with a Rust application that does everything the C++ application does. Waves 1 and 2 built the headless core: file formats, scene evaluation, pose, physics, editing of the key pools, rendering with standard MMD shading, and the MME parser and pass planner. Wave 3 builds the document, the media, the remaining rendering, the MME runtime, the application shell, and the UI. It then removes the C++.

The slice mechanics of `docs/RUST_WAVE2_PLAN.md` hold unchanged, except that the operator delegated merging to the root for wave 3 on 2026-10-25. The root merges a PR once its gate passes and reports each merge. The rest of the mechanics are: `tools/orchestrate/`, the agent brief, ownership, `integrate.sh`, merge commits, one Windows slice at a time. Wave 3 slices keep the `w2-<id>` branch and worktree prefix of those scripts.

## End state

- One Rust binary, `mds-app`, runs on Windows, macOS, and Linux. It loads and saves every file the C++ application loads and saves, plays the scene with physics and MME, edits keys, and records video.
- The C++ under `src/`, `include/`, `third_party/mmeffect/`, `exports/`, and the C++ tests is deleted in one final PR. That PR needs the operator's explicit approval.
- Two C++ libraries stay, by the operator's product rules of 2026-10-24: Bullet 2.75 (vendored, through `mds-bullet-sys`) and vkd3d-shader (through `mds-shader`).
- The C++ oracle tools under `tools/oracle/`, `tools/keypool_check/`, and the wave 3 check harnesses keep building from the last C++ commit, which is tagged before the deletion PR.

## What the inventory found

Four read-only agents mapped the C++ on 2026-10-25 at `9367de3`. The remaining C++ is about 82,000 lines in the application and 25,000 in `third_party/mmeffect`.

- `src/window` (27,000 lines). Menus, dialogs, panels, the timeline, and the command handlers. The UI may change as long as every function stays available.
- `src/app` (10,500 lines). The frame loop, input modes, playback catch-up, recording, the Kinect pump, new scene, and shutdown.
- `src/io`, `src/media`, `src/features` (11,000 lines). PMM 0001 and 0002 loading, PMM, VMD, VPD, and PMD saving, VSQ lip sync, WAV, the background movie and picture, physics baking, and pose helpers.
- `src/render` (7,000 lines). The model passes that `mds-render` lacks: the shadow map, the projected ground shadow, accessories, the background, the text and line overlays, and the debug geometry.
- `src/model` (10,700 lines). Mostly ported. Missing: undo and redo, camera, light, self-shadow, and gravity key registration, key reduction, SDEF, material and UV morphs, and the PMD edge.
- `third_party/mmeffect` (25,000 lines). The compile and plan layer is in `mds-mme`. About 8,500 lines of runtime remain: material binding, EMM files, animated textures, the effect cache, the context, and the controller objects. About 5,000 lines are the Win32 host and dialog.
- `src/mmdxshow` (5,000 lines). A DirectShow source filter that only feeds the AVI recorder.
- `src/exports` (550 lines). The 37 `Exp*` functions that MME effect DLLs call. In the Rust application, MME runs in process and reads the state directly.

## The document

The application state is the PMM. `mds_formats::pmm::Pmm` already reads and writes PMM 0002 byte for byte, and `mds-edit` already edits its key pools with the C++ record-level behavior. The document is that struct, plus the model and accessory files it names, plus undo history. Every edit is a command on the document. Saving is `Pmm::write`. The pose, physics, and render state are derived from the document every frame, never stored in it.

This replaces `MMDAppState` (0xA55E0 bytes) and the per-model records. Their layouts were needed to match the x86 binary. The Rust application needs the behavior only.

## Oracles

Each slice gates on a committed oracle that runs without the Windows host, as in wave 2.

- `--mds-script <script> <out-dir>` in the C++ application (slice `script`). It runs a text script of commands through the real handlers and writes every saved file. The scripts and outputs are committed under `tests/fixtures/rust/script/`. This is the oracle for the document and for UI commands.
- Check harnesses on macOS that link the real C++ sources with shim headers, the way `tools/keypool_check` does. They serve the code that needs no device: WAV and VSQ.
- New golden images from the Windows application for shadows, accessories, SDEF, morphs, the background, and MME (slices `golden2` and `mmegold`).
- For output with no C++ equivalent (AVI written by Rust instead of DirectShow), an independent reader: `ffprobe` and `ffmpeg -f framemd5`. A test reports SKIP when `ffprobe` is absent.

## Slices

`tools/orchestrate/slices.tsv` holds the rows. Wave 3a starts now. Later slices start when their dependencies merge.

| Slice | Wave | Scope | Gate |
|---|---|---|---|
| `script` | 3a | `--mds-script` in the C++ application (Windows). Commands: load PMM, PMX, PMD, VMD, VPD, and accessories; select model, bone, morph, and frame; set camera, light, self-shadow, gravity, and accessory values; register, copy, paste, and delete keys of every kind; undo and redo; new scene; save PMM, VMD, VPD, and PMD. | Two runs give the same bytes. The committed scripts exercise every command in the list, and the README names any command a script could not reach and why. |
| `doc` | 3a | `mds-doc`. The document and its commands: bone, morph, and display keys through `mds-edit`, camera, light, self-shadow, gravity, and accessory keys, undo and redo, new scene, and save. | Every PMM fixture loads and saves byte for byte through the document. A property test checks the pool invariants after random command sequences. `docgold` adds the `script` comparison. |
| `media` | 3a | `mds-media`. WAV load and the timeline waveform, and an AVI writer (uncompressed video and PCM audio) for recording. | `tools/wave_check` links the real `src/media` sources and gives the same chunk offsets and waveform arrays on generated WAV files. AVI files written by Rust decode with `ffprobe` and `ffmpeg -f framemd5` to the frames written. |
| `vsq` | 3a | `mds-vsq`. VSQ to the lip sync text and the morph keys. | `tools/vsq_check` links the real `src/io/vsq_load.cpp` and gives the same text bytes and key list on generated VSQ files. |
| `accessory` | 3a | `mds-accessory`. The DirectX `.x` meshes that MMD accepts, their materials and textures, and the accessory transform and parenting. | Generated `.x` fixtures parse to the expected meshes. `accgold` compares with a Windows mesh dump. |
| `skin` | 3a | `mds-skin`. CPU skinning and morphs as the C++ computes them: BDEF, SDEF, QDEF, the edge scale, the PMD edge, and vertex, UV, material, bone, and group morphs. | `tools/skin_check` links the real `src/model/model_skinning.cpp` and `morph_apply.cpp` and gives the same vertex buffers and material values, bit for bit, on the fixtures. |
| `ops` | 3a | `mds-ops`. The bulk key operations: unused-key removal, frame-line insert and delete, the multiply and bias dialogs, lip shift, random blinks, the delete-all and register-all morph menus, physics ON/OFF conversion, select-all, and the frame-range scale. | Unit tests derived from the C++ now, and the `script` outputs in `docgold`. |
| `mmert` | 3a | `mds-mmert`. The MME runtime on wgpu: render targets, pass execution, material binding, EMM files, animated textures, and controller objects. | Every `passplan` plan of the ray-mmd corpus executes with no wgpu validation error and creates the planned resources. `mmegold` adds the pixel comparison. |
| `shell` | 3b | The first `mds-app`: the window, the viewport through `mds-render`, playback with physics, play, stop, loop, frame step, and camera navigation (`src/app/pump_navigation.cpp`). It opens a PMM read-only; editing comes with `doc`. | A headless frame-dump run of the binary equals `mds-render` output for the same poses, and the navigation math has unit tests derived from the C++. |
| `accgold` | 3b | A Windows D3DX mesh dump of the accessory fixtures, and `mds-accessory` aligned with it. | Every fixture mesh equals the dump. |
| `docgold` | 3b | `mds-doc` against the `script` outputs. | Every script replays in Rust to the same saved bytes. |
| `pmm1` | 3b | PMM 0001 loading in `mds-formats`. | Generated 0001 fixtures, loaded by the C++ application and saved as 0002 by `script`, equal the Rust load and save. |
| `golden2` | 3b | Golden images of shadows, accessories, SDEF, morphs, and the background (Windows). | Two runs give the same bytes. |
| `render2` | 3b | The `mds-render` passes that `golden2` covers. | The per-pixel rule of `rendergold`, per scene. |
| `mmegold` | 3b | Golden images of MME effects (Windows). | Two runs give the same bytes. |
| `app` | 3c | `mds-app`: the window, the viewport, playback with physics and audio, file open and save, and the camera, bone, and selection input modes. | Scripted runs of the binary give the same document bytes as `script`, and frame dumps meet the per-pixel rule. |
| UI slices | 3c | One slice per menu and panel group of the UI inventory. | Every function of the inventory is reachable, and its scripted effect equals `script`. |
| `record` | 3c | Recording from `mds-app` through `mds-media`. | Recorded frames equal frame dumps. |
| `package` | 3c | Builds for Windows, macOS, and Linux with the license texts. | The builds start and load a fixture on each platform. |
| `rmcpp` | 3d | Deletion of the C++. Operator approval required. | `tools/rust/check.sh` passes with no C++ under the deleted paths. |

## Progress

On 2026-10-26, after PR #109:

- **3a and 3b are merged.** That includes `script`, `doc`, `media`, `vsq`, `accessory`, `skin`, `ops`, `mmert`, `accgold`, `docgold`, `pmm1`, `golden2`, `mmegold`, and `shell`.
- **Added slices.** The plan table above did not list these:
  - `shaderwire`: all 515 ray-mmd effects compile through vkd3d.
  - `kinect` and `bgmovie`.
  - `script2`: oracles for the bulk operations, the physics scenarios, and PMM 0001.
  - `doccmds` and `doccmds2`: the document commands that the UI needs.
  - `winprobe`: the self-shadow and ground-shadow probe lines.
  - `mmertgold`: `mds-mmert` gated on the mmegold images. 6 of the 8 scenes pass.
- **The UI.** 321 of the 399 inventory rows have an action. 7 of the 19 areas are in `ui::COMPLETE`, and `tests/ui_coverage.rs` prints the count per area.
- **Running.**
  - `render4`: the self-shadow map.
  - `winoracle3`: C++ oracles for the newer commands.
  - `doccmds3`: outside parent, order, view offset, physics record, and background media.
  - `appmedia`: recording and audio.
  - `uiphysics` and `uimocap`.
- **Left after that.**
  - The background area, and the UI rows that wait on `doccmds3`.
  - `package`.
  - The pool fixes that change C++ and Rust together.
  - `rmcpp`.

## Product decisions

These functions depend on hardware or APIs that a cross-platform Rust application cannot carry as they are. The operator decided all five on 2026-10-25: Kinect is ported, 3D Vision is dropped, and the other three take the defaults below.

| Function | C++ dependency | Default |
|---|---|---|
| Kinect capture | `DxOpenNI.dll`, Windows, a Kinect | Decided: port behind a Windows-only feature that loads the same DLL. Unverified, because no device is available. |
| NVIDIA 3D Vision recording | NVAPI | Decided: drop. NVIDIA ended 3D Vision in 2019. |
| AVI recording with system codecs | DirectShow, VFW, `MMDxShow.dll` | Decided: Built-in AVI writer (uncompressed) and PNG sequences, with no codec picker. |
| Background movie | VFW | Decided: Uncompressed and Motion JPEG AVI decoded in Rust. Other codecs are reported as unsupported. |
| `Exp*` functions for MME DLLs | PE exports | Decided: Drop. The Rust MME runtime runs in process. |
