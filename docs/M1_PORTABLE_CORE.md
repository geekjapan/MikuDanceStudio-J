# M1: portable core extraction

The current Win32/D3D9 application remains the behavioral reference while
portable code is extracted from it. An extracted module must build without
Windows SDK headers, keep its runtime state independent of original executable
object layouts, and have a headless test. The original x86/x64 layout records
remain in the Windows adapter for parity checks.

## First boundary: Bullet world ownership

`mikudancestudio_physics` owns the Bullet world construction and destruction
sequence. `PhysicsWorldState` contains only Bullet pointers. The existing
`PhysicsScene` retains its ABI-pinned fields and D3D9 gizmo buffers; its create
and dispose functions transfer the Bullet pointers across this boundary.
The Windows UI, physics callers, and renderer still use `PhysicsScene`.

On non-Windows hosts CMake builds only `mikudancestudio_physics` and the
`physics_world_state` headless test. The host's Bullet 2.75 Conan package is
still required. This build path has not yet been run on Linux; Windows x86 and
x64 builds and the headless, scene disposal, and gizmo reset tests cover the
current change.

## Next boundaries

The VPD reader and writer are now in `mikudancestudio_formats`. Their API uses
byte-oriented model/bone names and caller-owned `FILE*` streams. The Windows
adapter opens wide paths, maps selected bones into the format document, and
applies loaded poses through its undo, UI, and legacy model records. The format
test pins the legacy writer bytes and checks LF/CRLF parsing and a truncated
file.

The VMD1/VMD2 binary reader and writer now live in the same portable target.
`VmdDocument` holds file names, bone/morph keys, camera/light/shadow tracks,
and IK entries without original runtime layouts. The Windows save adapter
collects the existing key tables and rebases frames; the load adapter applies
parsed keys through the existing registrars, undo ring, and UI refresh chain.
The format test covers VMD1 compact camera curves, all VMD2 sections, optional
tail sections, byte round trips, and truncation. Windows adapter tests cover
camera and model saves plus global camera/light/shadow registration after a
file read. Model-key loading still needs an integration fixture with the full
model/undo/UI state; community VMD files and GUI A/B have not yet been run.

PMD/PMX signature recognition, PMD's fixed header, PMX 2.0 global settings,
and its four UTF-16LE text fields now use the portable `model_format_header`
reader. The Windows adapter supplies the existing file descriptor through a
read callback and maps parsed fields into the ABI-pinned model record. Text
lengths are bounded and checked before model allocations or D3D work. PMX
2.1 and UTF-8 remain rejected as in the current Windows implementation.
PMD/PMX vertex counts, per-vertex fields and face indices now pass through the
portable `model_geometry` reader. PMX variable-width bone indices remain signed,
while vertex indices are unsigned at one/two bytes; SDEF pivot rebasing and
GPU buffer creation stay in the Windows adapter. Parsing is streamed per record
so D3D resource creation and failure ordering remain unchanged. Portable tests
cover PMD fields, PMX BDEF/SDEF layouts, index widths, and truncated input.
PMD/PMX material fields, bone fields (including PMD IK chains and PMX IK
links), rigid bodies, and joints now pass through the portable `model_sections`
reader. The Windows adapters map those disk records into ABI-pinned runtime
records; material path resolution and texture caching, D3DX bone-axis and
rigid/joint transforms, and Bullet body/constraint creation remain there.
PMX UTF-16LE names, material memos, and texture-path text now use the bounded
portable text reader; the Windows adapter retains Shift-JIS conversion and
the original synthetic names for empty fields. PMD/PMX morph offsets and
display-frame entries also use portable readers. Windows still performs
PMD base-morph remapping, PMX morph deduplication and material-channel layout
mapping, display-group bookkeeping, UI warnings, and texture loading.
PMD English model/bone/morph/group names and the ten fixed-width toon fields
now use portable disk readers. The Windows adapter still applies legacy name
termination, displays the English comment, resolves toon paths, and loads
textures. PMD and PMX section counts use a portable one/two/four-byte reader
before allocating runtime tables. The PMD English-presence byte and optional
physics counts use a separate portable result-aware reader: it preserves the
legacy distinction between a zero-byte EOF and a negative read result. The
Windows callback alone supplies the CRT read result; truncated records now
fail rather than leaving partially populated runtime data.
Portable tests cover field order, index/count widths, fixed-width strings,
shuffled joint limits, morph families, display entries, and truncation.

`model_reader` now assembles those portable record readers into an ordered,
headless PMD/PMX disk document. It retains geometry, material text and memos,
bones and IK, morphs, display frames, PMD English/toon data, and physics disk
records without UI, D3D, Bullet, or Windows paths. It bounds section counts
and input size, and leaves its output unchanged when parsing fails. Synthetic
full-file tests cover both formats, optional PMD English/physics tails, PMX
physics, invalid settings, and truncated input. Separate Windows adapter
tests compare synthetic PMD and PMX disk fields against their D3D-backed
runtime adapters. Each passed 20 isolated x64 and x86 process runs. A third
synthetic PMX physics test checks joint disposal in both architectures and
now runs by default. An opt-in
`model_reader_external` test reads a locally supplied real PMX
through both memory and CRT callbacks, checking full consumption, counts,
texts and representative fields. Set `MDS_MODEL_FIXTURE` to the local PMX
path and run `ctest -R '^model_reader_external$'` to enable it; without the
variable the test skips and normal CI remains synthetic. A separate opt-in
`model_reader_runtime_external` test covers the D3D/Bullet adapter on x64.
It passed three isolated runs after the model disposal fix. The x86 run is
available with `MDS_MODEL_RUNTIME_X86_DIAGNOSTIC=1` and passed three runs;
its earlier heap failure was narrowed to deleting the first Bullet spring
constraint through the x86 virtual deleting destructor. Disposal now calls
the known spring type's destructor and frees its scalar-new storage directly.
Keep the real-model runtime test opt-in until broader fixture coverage exists.
The Sour Miku sample was verified locally, but its model and textures are not
copied into the repository. This is a headless disk reader,
not yet a portable runtime model or scene loader;
the Windows adapters still own name conversion, texture resolution, GPU
buffers, morph runtime mapping, and Bullet object creation.

Set `MIKUDANCESTUDIO_FORMATS_ONLY=ON` to build VPD/VMD formats and the PMD/PMX
disk reader without Conan or Bullet. The PMM load entry now classifies its
30-byte signature and v1/v2 version through portable `pmm_format` instead of
calling `strstr` on an unterminated read buffer. Both dialects retain their
existing Windows loader bodies and UI error handling. Portable tests cover
the bounded header, shifted signatures, invalid versions and truncated input;
a Windows test compares the same header through memory and the actual CRT read
adapter. PMM v1/v2 bone keys and shared morph keys now also use portable
record readers. The Windows layer maps their disk fields into the existing
timeline layouts; portable tests cover field order, the v2 physics byte and
truncation, and a CRT adapter test covers both bone dialects. PMM camera
records (including the v2 parent fields), light, self-shadow and gravity
records now follow the same portable reader and Windows mapping pattern.
Portable and CRT adapter tests cover the on-disk order and flag conversion.
The accessory track and v1/v2 display/IK/rigid-state key records now also use
portable readers. The Windows layer still applies model/IK/rigid remapping and
owns live scene state. The initial PMM scene settings (render dimensions,
sidebar value, FOV, six/seven option bytes) are parsed independently and
mapped into the existing v1/v2 host layout.
The per-accessory current state now uses a versioned disk reader too. Its v1
record has one trailing flag byte, while v2 has a second additive-blend byte;
tests assert the 38/39-byte lengths and truncation behavior.
Model selection metadata now has a shared v1/v2 disk reader: the display
order, load flag, selected bone and morphs, display-group flags, list position
and frame range are parsed before the Windows adapter applies name remapping.
The late scene configuration's timeline and playback prefix (current/start/
registered frames, edit and camera reference modes, loop flags and playback
range) also has a portable record reader. Truncated records leave their output
unchanged. Synthetic and CRT callback tests cover both selection dialects,
timeline settings and v1/v2 display records on x64 and x86.
The WAV, AVI and picture background records now retain their raw 256-byte
path fields and numeric placement/enabled fields in portable structs. Both
Windows loaders use these readers, then resolve paths, decode names and create
media resources in their existing adapter flow. The following view flags, FPS
limit and capture mode use a portable settings record too. Synthetic truncation
and CRT callback tests cover these records. PMM v2's accessory render order,
projected-shadow controls, playback physics mode and gravity defaults now use
a portable settings record as well. The v2 scene appearance and camera
attachment fields have a portable record reader; the following optional
per-model tail flag keeps its original gated read.

`pmm_document` reads the entire byte stream without Win32, dialogs or runtime
layouts. It exposes the signature, initial scene settings, selected model slot,
model count and v1 prepass names, and retains all later bytes verbatim for
lossless write-back. Synthetic v1/v2 round-trips, truncated prefixes and a
Windows CRT callback parity test cover this envelope. `pmm_scene_document`
now validates the ordered model, camera, light, accessory, configuration,
gravity, shadow and tail sections. It exposes the model names and layout,
key records (dense and sparse), current poses and scene settings while retaining
the original bytes for lossless write-back. Its read operation is atomic on
truncation or invalid counts; synthetic tests cover both versions, populated
v2 model/accessory sections, sparse records, full v1 gated tails and truncation.
Both Windows load entries now validate the complete scene document before
invoking their runtime loader and release it before resource creation. The v1
adapter resolves referenced PMDs with the existing Windows path search, then
uses the portable PMD reader to provide bone, morph and IK layout counts.
If a PMD is unavailable or unreadable, v1 defers to its existing locate-and-
retry dialog. Both loaders still map records to runtime fields while resolving
paths and resources.
Local MMD distribution fixtures are available for opt-in comparison; they are
not copied into the repository. Set `MDS_PMM_FIXTURE` to a PMM path and run
`pmm_document_adapter_test`. For v1 strict parsing, also set
`MDS_PMM_MODEL_ROOT` to its `UserFile` directory containing `Model/`.
The memory and CRT readers parsed three v1 distribution scenes using the
referenced PMDs for layout and one local v2 scene without a model callback.
They matched section offsets and representative fields on x64 and x86;
byte-for-byte envelope write-back also passed on both. The external adapter
test now seeks to every dense and sparse key in those files and checks the
Windows ABI mapping for bone, morph, display/IK, camera, light, accessory,
gravity and self-shadow records. A Windows save test now checks both an empty
scene and a synthetic model with bone, morph, display/IK, rigid-state and
current-pose fields against strict scene readback on x64 and x86. The new
`pmm_v1_layout_adapter_test` resolves referenced PMDs through the Windows
path adapter for three local v1 distribution scenes on both architectures; it
also checks the unavailable-model fallback. Post-load parity has since passed
for the selected scene and model fields listed below; remaining runtime fields
have not yet been compared.
For a relocation check, set `MDS_PMM_FIXTURE` to a copy under a `UserFile`
directory with its referenced `Model` files. With one referenced PMD removed,
set `MDS_PMM_EXPECT_MISSING=1`: the adapter test must report an unavailable
model instead of accepting a partial scene. Restore the PMD and clear that
variable; the full parse must pass again. This baseline/missing/restored
sequence passed on x64 and x86 with a temporary copy of `sample.pmm` and its
three referenced PMDs. It exercises path lookup and the parser fallback, not
the graphical locate-and-retry dialog.
The prefix reader also handles partial callback reads, with a three-byte-chunk
synthetic test.

PMM v1's model block omits the bone, morph and IK counts that control several
following record lengths; the Windows loader obtains them by opening each
referenced PMD. The strict headless v1 reader accepts a model-layout resolver
callback; the Windows test adapter supplies it through the portable PMD reader.
PMM v2 stores these counts and names directly, so no model callback is needed.
The legacy envelope reader still permits any tail bytes by design. Older v1
documents may legally end at optional tail gates, so EOF at those boundaries
is accepted by the strict reader. `WritePmmSceneDocument` now writes edited
scene settings, timeline settings, current light state, and each model's
current bone pose, morph values, and IK flags. It patches the corresponding
original byte ranges, reparses the result, and rejects invalid edits before
calling the output callback. The v1 writer requires a PMD layout resolver.
Fields outside this supported set retain their original bytes. The Windows v2 save
path stages its runtime serialization, validates it as a complete portable
scene document, then writes its byte-exact envelope with `WritePmmDocument`.
Validation failures leave the selected destination untouched.

1. Compare complete post-load runtime objects against strict scene fields on
   the same fixtures, including model poses and scene configuration. Exercise
   the v1 missing-model dialog with a relocated PMD. Keep encoding, path
   lookup, UI dialogs, D3D resources and runtime object layouts in the Windows
   adapter. Add a portable writer for edited typed scene fields.
2. Move animation evaluation and frame stepping onto a scene model owned by
   the portable core. Compare results against the current Windows host using
   the same authorized fixtures.
3. Put rendering commands and input events behind host interfaces. Keep the
   D3D9 and Win32 implementations as Windows adapters until a second backend
   exists.
4. Expand the non-Windows build from the Bullet slice to format, animation,
   and physics targets with headless project round-trip tests.

The M1 exit condition is a Windows application using the portable scene core
for load, edit, frame advance, and save, plus a non-Windows headless build of
that same core. GPU parity and the new graphical frontend belong to later
milestones.

The opt-in `pmm_v1_relocation_gui` test exercises the real v1 missing-model
message and Windows file dialog without Computer Use. Set `MDS_PMM_GUI_FIXTURE`
to an authorized v1 PMM under `UserFile`, set `MDS_PMM_RELOCATE_MODEL` to a
referenced PMD filename in its sibling `Model` directory, and run
`ctest --test-dir out/ci/build -C Release -R pmm_v1_relocation_gui --output-on-failure`
from an unlocked interactive Windows desktop. The test copies the complete
`UserFile` tree to a unique temporary location, moves only the copied PMD,
uses UI Automation to reselect it for each referencing model slot, then checks
that Save As produces a readable PMM with the same model count. It skips when
either variable is absent; on failure it retains the temporary copy for
inspection. It never edits the source fixture.

The original `sample.pmm` references `Dammy_Bone.pmd` in two model slots.
The first GUI test mistakenly treated the second locate dialog as a new
failure. After accepting both, loading reached the accessory section: the
test's initial Model-only fixture copy omitted the referenced `.x` asset and
produced a separate `Cannot find xfile!!` prompt. With the complete
`UserFile` tree and both model selections, the x64 GUI test loaded and
saved/read back the scene. That first run tested GUI recovery and envelope
model count; the later diagnostic and writer tests below extend coverage.
The diagnostic `model-loaded a=0` trace reports the first load attempt before
the locate dialog; it does not report whether the retry succeeded. The test
also recognizes both the legacy model Open dialog (`1148` file-name control)
and the newer Save As dialog (`1001` edit control).

For the post-load check, configure with `-DMIKUDANCESTUDIO_DIAG=ON` and rebuild
`MikuDanceStudio` and `pmm_v1_relocation_gui_test`. In this build the GUI test
sets `MDS_PMM_RUNTIME_REPORT` for the child process. After `LoadSceneV1` reaches
its success tail, the child compares its live scene and model fields against a
strict parse of the original fixture and writes `runtime_parity.txt` in the
test's temporary directory. The report covers scene dimensions, timeline,
camera FOV, light state, model slots and counts, selections, current bone
transforms and flags, morph values, and IK flags. A mismatch fails the GUI
test before Save As.

On 2026-09-27, the eight headless PMM tests, including the real-fixture v1
layout adapter, passed. The diagnostic GUI test stopped before reading the
PMM: Direct3D9 `CreateDevice` failed on all seven attempts (`0x8876086C` and
`0x8876086A`) in RDP session 2. Direct3D9 enumerated one adapter, NVIDIA
TITAN Xp. A temporary 640x480 back buffer, simplified presentation settings,
and an explicit NVIDIA selection did not change the result; these experiments
were removed. After the RDP display recovered later that day, the same
diagnostic GUI test passed twice on the real `sample.pmm`. Each run handled
both missing-model selections, reported `PASS checks=1869 failures=0` for
post-load runtime fields, and saved and read back the relocated scene. This
establishes runtime parity for the checked fields in this fixture.

The portable writer passed synthetic v1/v2 unchanged and edited round-trips.
The real `sample.pmm` test changed scene settings, timeline, light, bone pose,
morph value, and IK flag, saved a temporary PMM, and strictly reparsed it.
Every byte outside the edited fields remained identical to the original.
The source fixture was not modified. The formats-only build and test passed
without the Windows runtime.

The application's PMM v2 Save path now copies editable fields from live editor
state into `PmmSceneDocument` and commits through `WritePmmSceneDocument`.
The existing Windows serializer still supplies key tracks, references, and
other fields. The real v1 relocation GUI test passed after this change:
model reselection, strict runtime parity, and Save As readback all succeeded.

`EvaluatePmmSceneFrame` now provides stateless portable evaluation of bone
key positions and rotations (including MMD's per-channel Bezier easing and
quaternion slerp), morph values, display/IK state, and light color/direction.
It rejects broken key links. Synthetic tests cover interpolation, exact keys,
terminal holds, and malformed links. The real `sample.pmm` parses and
evaluates at frames 0, 1, 10, 30, and 100. A diagnostic GUI run compared the
portable result with `SeekModelFrame` at those frames, restoring runtime model
state afterward; the full report was `PASS checks=4641 failures=0`, followed
by successful Save As readback. Bone comparisons exclude bone types the host
does not seek and bones with selector or rigid-body overrides.

The editor's seek path now calls the portable interpolation kernels for
ordinary bone segments and morph values, using live runtime key records so
edits take effect on the next frame seek. The light panel's interpolated
state also calls a portable kernel with its original double-precision seek
rounding. Continuous playback now uses the portable morph and light
interpolation kernels with its single-precision rounding. Exact-key and
terminal copies, IK and selector transitions, physics behavior, camera, and
accessories remain in their Windows host
paths. The `pmm_scene_seek_adapter` test changed bone, morph, and light keys
and verified subsequent frame seek, playback morph advance, and light refresh
on x64 and x86. After this
integration, the real v1 GUI test again passed two missing-model selections,
five sampled frames, `PASS checks=4641 failures=0`, and Save As readback.
The portable evaluation and seek adapter tests passed on x64 and x86. The
continuous-playback morph/light changes compiled and passed these adapter
tests; a later full GUI rerun was blocked before loading by another
Direct3D9 `CreateDevice` failure in the RDP session.

The x64 continuous-playback bone blend now calls a portable kernel using
live edited keys. It preserves the playback path's float frame fraction,
per-channel Bezier easing, and reciprocal-multiply quaternion weights;
the x86 host keeps its extended-precision path. Physics and selector-window
decisions still run in the Windows adapter before the blend. The seek adapter
test now checks playback bone translation and rotation at integer and
fractional frames, including an edited key, on x64 and x86. A real
`sample.pmm` GUI run compared incremental
playback with stateless scene evaluation at frames 0, 1, 10, 30, and 100,
restored the runtime state after each sample, and passed 6946 field checks
with no failures. Both missing-model selections and Save As readback passed.
The comparison uses a 1e-5 tolerance for playback float poses and excludes
bone types and override paths that the stateless evaluator does not model.

Model visibility and IK display-key selection now share a portable linked
track selector across stateless scene evaluation, direct frame seek, playback
initialization, and incremental playback. It returns the held key, cursor,
and visibility for exact hits, between-key holds, and terminal holds. The
Windows adapter still copies the held key's IK flags and refreshes selector
windows. Synthetic tests cover these branches and edits to live visibility
and IK keys on x64 and x86. The real `sample.pmm` GUI regression again passed
two missing-model selections, five sampled frames, 6946 field checks with
zero failures, and Save As readback.

A previous GUI rerun stopped at Direct3D9 `CreateDevice` before PMM loading
when the remote display state changed; a later run on the restored display
passed. The editor still needs portable ownership of key tracks and the
remaining runtime side effects before the Windows evaluator can be retired.

Selector-window evaluation is now portable. The evaluator walks display-key
links backward and forward to determine each selector's linked model, linked
bone, start frame, and end frame. Direct seek and incremental playback apply
those results to the runtime selector table, and PMM v2 scene evaluation
returns the same windows in `PmmEvaluatedModel::selectors`. Synthetic x64
and x86 tests cover repeated references, reference changes, exact and
between-key frames, terminal holds, live edits, and broken links. The real
`test_1.pmm` v2 file parsed and yielded 185 selector-window evaluations at
five frames on both x64 and x86. All evaluated windows in that file were
unbounded, so changing-window behavior is covered by synthetic tracks. The
real `sample.pmm` v1 GUI regression passed again with 6946 checks and Save As
readback. The v1 file has no selector pairs.

The v2 selector GUI regression now constructs a temporary copy of the real
`test_1.pmm` with display keys at frames 10 and 20. Selector zero changes
from no parent to ground and back, producing windows [0,10), [10,20), and
[20,end). The fixture passed strict parsing, unchanged scene writeback, and
five-frame selector evaluation on x64 and x86. A diagnostic application
probe compares the loaded key records and the selector table after seek and
playback at frames 0, 5, 10, 15, 20, and 30, then the GUI test saves and
reparses the scene. After RDP display recovery, the x64 and x86 GUI runs
both passed 61 runtime checks with zero failures, including the two bounded
window transitions, and Save As readback. The original source PMM was not
modified.

Bone pose overrides at selector-window boundaries now use portable decisions
and pose copies. If a selector start or end falls strictly inside a bone key
segment, seek and playback hold the previous key before the crossing and
snap to the next key at or after it. After a terminal bone key, crossing the
selector start resets translation and quaternion xyz; direct seek sets
quaternion w to 1 while playback retains the terminal key's w. The scene
evaluator maps v2 `rigidSources` to bones and applies the same seek override.
The GUI fixture now gives selector slot 1 and its mapped, non-physics bone
keys at frames 15 and 30. Both x64 and x86 runs passed 291 field checks at
frames 0, 5, 10, 12, 15, 17, 20, 25, and 30, comparing seek and playback
poses and selector windows with the portable result; Save As readback also
passed. Synthetic tests cover terminal reset and the distinct quaternion w
values. The original `test_1.pmm` was not modified.

Incremental playback retains a host cursor distinction after the terminal
bone key: once an earlier tick exhausts that track, it is inactive and a
later selector-window start does not reset the pose. Starting playback and
advancing directly past that start does reset it. Both cases are pinned by
the adapter test. The stateless scene evaluator represents direct frame
evaluation and does not encode that playback history.

The portable format library now owns an explicit `PmmScenePlaybackState`.
`StartPmmScenePlayback` initializes the frame-zero pose and model track
cursors; `AdvancePmmScenePlayback` accepts the host's float-seconds clock and
advances display/IK, selector windows, bone, and morph tracks in order. It
also evaluates the light track at the resulting fractional frame. Exhausted
model tracks remain inactive until playback restarts, so a later selector
boundary cannot retroactively change an exhausted bone pose. The evaluator
reads the current scene keys on each advance, including edits made during
playback, and rejects malformed links or backward time without changing the
existing state. It is part of `mikudancestudio_formats` and has no Win32,
Direct3D, or Bullet dependency.

Synthetic tests check fractional interpolation, live edits, exact and
terminal keys, repeated rounded timestamps, inactive tracks, restart, and
the history-sensitive selector reset. The standalone formats-only build
passed all 11 tests. The real PMM
v2 GUI probe compared the portable state with the Windows model runtime at
frames 0, 5, 5.5, 10, 12, 15, 17, 20, 25, 30, and 35; both x64 and x86
passed 2326 checks with no failures and Save As readback. The portable state
currently covers scene key playback, not physics integration, runtime bone
type gates, or external-parent transforms. Light values are evaluated from
the scene at each tick; no separate light cursor is retained.

`SceneSession` now joins strict PMM v1/v2 loading, host-resolved model
documents, the saved current pose, frame seeking, stateful playback,
transactional typed edits, and validated scene saving in the portable
formats target. Loading keeps the PMM's current pose; seeking or starting
playback explicitly evaluates animation keys. The v2 writer can now patch
existing dense and sparse bone, morph, display/IK/selector, and light key
values while preserving their record links, counts, and all other bytes.
The headless test edits keys and current pose, seeks, plays, saves, reparses,
and rejects an attempted topology change without altering the session. V1
requires a PMD resolver to supply model layout counts and supports the
existing current-pose and scene-setting writeback. A two-model v2 fixture
passes the same load, seek, playback, save, and reload path. An opt-in
headless test runs the full edit/play/save/reload cycle on a real one-model
PMM v2 file through `MDS_PMM_SCENE_SESSION_FIXTURE`; the local `test_1.pmm`
passed with both MSVC and Cygwin GCC. The v1 layout adapter also runs
session load, seek, playback, and save on the real distribution `sample.pmm`
with its referenced PMDs; the x64 and x86 adapter tests passed.

The Windows v2 load dispatch uses `SceneSession` to validate the scene before
creating runtime objects. Its Save As path stages the legacy serializer,
captures live editor fields through `SceneSession::Edit`, and writes through
`SceneSession::Save`. The diagnostic GUI probe drives session seek and
playback against the existing model runtime; the real one-model PMM v2
fixture passed 2326 comparisons on each of x64 and x86, plus Save As
readback. The Windows v2 single-model timeline now retains one session for
the loaded scene. Direct model seeks read the current linked bone, morph, and
display/IK keys into the session when they change, then apply the session
pose to supported kinematic bones, morphs, visibility, IK flags, and selector
windows. Playback start initializes the session cursor, and each model tick
advances and applies its pose. The existing Windows path still handles bone
type gates, rigid-body notifications, and physics. A real v2 PMM adapter
test exercises edited key values and insertion into a linked bone track on
x64 and x86. Live key topology can change in the editor; after such a change
the session's original PMM byte envelope is stale, so Save As continues to
stage the legacy serializer before validating its output through a fresh
session.

The GUI diagnostic now checks the application timeline bridge as well as the
portable evaluator. After RDP recovered, the extended real-v2 GUI test passed
2409 checks with zero failures on each of x64 and x86. Both runs confirmed an
edited bone key at frame 15, an inserted bone key at frame 7, playback, and
Save As readback. The real-v1 missing-model relocation GUI regression also
passed on both architectures: two graphical model selections, 6946 checks
with zero failures, and Save As readback. The x86 v1 seek comparison uses a
1e-5 tolerance for sampled bone rotations because its CRT double intermediate
rounding differs slightly from the portable evaluator's float path; x64 keeps
the exact comparison. The corresponding headless bridge test passes on both
architectures.

The Windows v2 bridge now attaches a scene session when all PMM model slots
load, synchronizes each model's live bone, morph, and display keys by slot,
advances the session once per playback tick, and applies each evaluated pose
to its matching runtime model. The real `test_1.pmm` fixture is copied into
two model slots for the new adapter and GUI regressions. On both x64 and x86,
the adapter passed independent second-model key edits, insertion, seeking,
playback, and session save/reload; the GUI passed 23 runtime checks with zero
failures, edited an ordinary bone on the second model, and saved/read back
the edited two-model PMM. The original one-model v2 GUI and v1 relocation
GUI tests also passed on both architectures. The GUI test exposed a Windows
serializer bug: its header counted model combo entries while its body wrote
occupied runtime slots. The header now counts those same occupied slots.
Selector-bound and physics-controlled bone poses still follow the Windows
runtime gates.

The PMM v1 loader now creates `SceneSession` after the graphical missing-model
retry and successful runtime load. A Windows resolver opens the PMD paths
actually chosen for each occupied slot, so the session has the v1 layout
counts and model documents even when the original PMM paths are stale. The
same slot-based seek and playback bridge synchronizes live bone, morph, and
display/IK keys. V1 has no serialized selector mappings, so the bridge keeps
the PMD runtime selector table under Windows ownership. The real three-model
`sample.pmm` GUI regression passed on x64 and x86: two missing-model selections,
five sampled frames, an edited ordinary bone key, three-model playback,
6983 checks with zero failures, and Save As to PMM v2 with strict readback of
the edited key. The v2 single-model and multi-model GUI regressions also
passed on both architectures. Accessory tracks and portable physics ownership
remain future work.

A model seek now writes the evaluated pose only to the requested model slot.
Other slots keep their current runtime pose until their own seek; playback
applies all slots after their keyframe advance. This prevents a seek of one
model from changing another model's local bones ahead of its transform pass.
The bridge regression checks slot isolation and synchronization of edits in
another slot.

The portable scene evaluator now resolves PMM v1/v2 camera keys for frame
seeking and stateful playback. It evaluates six interpolation channels,
camera position and rotation, distance, field of view, perspective, and the
parent model/bone pair. The Windows bridge synchronizes live camera keys into
`SceneSession`, applies evaluated camera values before projection refresh,
and retains the existing renderer and camera controls. The real v1 `sample.pmm`
GUI regression passed on x64 and x86 with sampled camera seeks, a camera key
edit, playback application, graphical model relocation, and Save As/readback
of the edited camera key. The v2 single-model and multi-model GUI regressions
also passed on both architectures. The Linux formats-only build passed all 12
tests after the camera change, including nonlinear camera interpolation and
the real-v2 session load/edit/play/save/reload test. Camera parent transforms
still use the Windows runtime.

The portable evaluator and `SceneSession` now also carry accessory timeline
state. For each accessory slot, seek and playback hold visibility, shadow,
position, rotation, and model/bone attachment from the preceding key while
linearly interpolating scale and opacity. Exact and terminal frames copy the
key. The Windows bridge synchronizes edited accessory keys and applies the
session pose to existing accessory render objects. The PMM writer patches
editable accessory key and current-state fields; current opacity is rounded
to the format's one-percent storage step. The real v1 `sample.pmm` contains
28 accessories and passed GUI seek, edit, playback, and Save As/readback on
x64 and x86. Its saved v2 scene was loaded back through `SceneSession`, then
edited, sought, played, saved, and reread with the accessory edit intact; the
saved v2 scene also reopened in the Windows GUI with all three models. The
reopened v2 runtime passed accessory seek samples, key edit synchronization,
and playback application on both x64 and x86.
The `test_1.pmm` v2 fixture has no accessories, so its GUI regression covers
scene compatibility; a populated v2 format fixture covers accessory field
writeback. Linux formats-only passed all 12 tests, including accessory
evaluation and session writeback. Parent transforms remain host-owned.

The formats-only suite and the session test compile with both MSVC and
Cygwin GCC on Windows. On 2026-09-27, an Ubuntu Linux host with GCC 11.4
configured and built the formats-only target, then passed all 12 headless
tests. The opt-in `pmm_scene_session_external` test used the real one-model
`test_1.pmm` fixture and completed load, edit, seek, playback, save, and
reload. After the multi-model session change, the same Linux build again
passed all 12 tests. The repository's portable-formats CI workflow also
targets Linux and macOS; macOS has not yet been run in this session.

The portable scene evaluator and `SceneSession` now carry the self-shadow
track's held mode and distance through seek and playback. The Windows bridge
synchronizes edited keys and applies the result to the existing shadow state;
the PMM writer patches existing self-shadow keys and the current mode/distance
fields. Windows x64/x86 unit tests and the Linux formats-only build pass,
including real `test_1.pmm` load/edit/play/save/reload. The x64/x86 v2 single
and multi-model GUI tests pass. One x64 and one x86 v1 GUI run exposed a
saved camera head link pointing to an unused key slot, so session playback
failed. The Windows serializer now verifies the camera chain and, only when
invalid, rebuilds previous/next links in frame order while preserving key
values and indices. The real v1 graphical relocation, Save As, reread, and
playback test passed on both x64 and x86 after this fix. The portable
evaluator rejects missing camera links, covered by a regression test. The
source of the stale runtime link remains under investigation.

A follow-up camera-chain audit on the real v1 `sample.pmm` found valid links
at load, before and after the frame-0 camera edit, before Save As, and at the
Windows writer on both x64 and x86 (14 sparse camera keys; 7111 GUI checks
per architecture). The historical bad save did not recur in those runs, so
its exact event sequence is still unproven. A deterministic producer of the
same broken-head shape was found in the frame-line and selected-key deletion
path: merging a frame-1 camera key into the head left its freed slot selected
with old predecessor/successor links. If a later key deletion freed that old
successor, purging the stale selected slot could point the head to the now
unused successor. The merge now clears the freed slot's selection and links;
selected-key deletion also ignores already-free camera slots. Focused x64/x86
adapter tests cover this sequence, a legacy stale slot, and repair of a
nonzero head predecessor during save. The diagnostic GUI test now asserts
chain integrity at each stage and records whether the writer needed repair.

The graphical self-shadow regression now creates v2 keys at frames 10 and
20, compares the Windows editor against `SceneSession` at six seek frames,
edits the frame-0 mode and distance, advances playback, and verifies the
saved PMM. The real v1 `sample.pmm` regression likewise checks self-shadow
seek, edit, playback, Save As and readback. Both graphical paths pass on x64
and x86; the Linux formats-only suite and real-v2 session round trip pass.

The gravity timeline is now evaluated in the portable scene and session:
acceleration and direction interpolate linearly, the noise iteration delta
uses single-precision multiplication and integer truncation, and the seek
and playback paths retain their distinct noise-enabled selection rules.
The Windows bridge synchronizes edited gravity keys and applies the session
pose to the existing gravity state during frame seek and playback; Bullet
world stepping remains host-owned. The PMM writer patches gravity keys and
current gravity settings at their v1/v2 offsets. Synthetic interpolation,
writeback, runtime-bridge, and real-v2 session round-trip tests pass on
Windows x64/x86; the Linux formats-only suite passes all 12 tests. A
separate interactive graphical parity run with a real PMM and physics
dialog is still needed; these headless tests do not claim that coverage.
V1 stores current gravity settings behind an optional tail gate but has no
serialized gravity key track; for a missing gate the portable reader uses
the same 9.8 / 10 / downward-direction defaults as the Windows loader.

The opt-in v2 GUI regression now derives a temporary fixture from the real
`test_1.pmm` and adds gravity keys at frames 10 and 20. On the interactive
Windows desktop, x64 and x86 each passed 2526 parity checks: frame seeks at
0/5/10/15/20/25, the open physics dialog's acceleration, direction, noise
and enabled state, consecutive playback samples including frame 5.5, a
frame-0 key edit, and Save As/readback of the edited key and two sparse keys.
The original PMM remains untouched. The existing v2 multi-model GUI regression
also passed on both architectures. The real v1 `sample.pmm` relocation and
Save As/reopen regression passed on x64 and x86 with 7107 checks each,
including a comparison of loaded gravity settings against the parsed scene.
Opening the gravity dialog during this test exposed an x64 crash: its edit
subclass pointer was truncated to 32 bits, and its previous window procedure
was saved in a scratch slot that the x64 accessor did not read. Both are now
stored through pointer-width-safe application accessors; dialog text is
checked by the GUI test. These checks cover timeline and dialog state, while
Bullet stepping and rendered physical motion remain host-owned.

The portable `pmm_scene_world` boundary now builds row-vector bone world
matrices from parsed PMD/PMX rest positions and evaluated kinematic poses.
`SceneSession::KinematicWorld` exposes these by model slot when the model
resource was resolved. Camera attachment anchors use the rest bone position
transformed by the bone matrix; accessory placement composes scale, Z/X/Y
rotation, translation, then the same bone attachment matrix as the Windows
renderer. IK, rigid-body, inheritance, after-physics, external-parent, and
dependent bones return no matrix rather than an unverified transform. This is
a headless diagnostic boundary, not yet connected to rendering or the camera
reference-mode/view transform. Synthetic chain, rotation, accessory, unsupported
bone, and malformed-topology tests pass on Windows and Cygwin GCC. Real v1
`sample.pmm` and v2 `test_1.pmm` load their PMD/PMX resources and evaluate
matrices in the Windows x64/x86 headless tests; the v2 PMX currently exposes
8 of 331 bones as safe kinematic results. The Linux formats-only build passed
all 13 tests in a separate validation copy, including the real-v2 PMM session
test without the external PMX resource. Runtime matrix parity and macOS
remain to be verified.

On 2026-09-29, the opt-in `MIKUDANCESTUDIO_DIAG` GUI comparison writes
`MDS_PMM_WORLD_REPORT` before the existing GUI parity test edits the scene,
using a snapshot-only legacy bone transform and restoring runtime state. It compares the
same loaded model slot and frame with `SceneSession`'s parsed model resource,
records each matrix/attachment component delta, and never substitutes a
portable transform in rendering. The real v1 `sample.pmm` comparison on both
x64 and x86 covered 31 safe bones of 200, with zero matrix/anchor differences
at frame 0; the real v2 `test_1.pmm` covered 8 of 331, also with zero
differences. The two-model v2 GUI test covered 16 of 662 with zero
differences. The diagnostic copy of the v2 fixture attaches camera key 0 to
supported bone 0: its legacy key attachment point agrees with the portable
anchor on x64 and x86. This checks the key's attachment point, not the
rendered camera view; the camera state has not been applied at the load-tail
sample. In `sample.pmm`, 28 accessory matrices, including 27 model-bone
attachments, agreed with the independent Windows D3DX placement sequence.
Skipped bones and bindings are not counted as parity successes.

The same report records every left-side bone's runtime pose, attachment
position, and portability status. The v1 model's left wrist (slot 2, bone 22)
has a runtime quaternion near `(0.0143859, -0.0149391, -0.00467, 0.999774)`
versus the keyframe evaluator's identity at frame 0 on both architectures.
This bone is outside the conservative kinematic subset, so the comparison
does not establish an error in IK, skinning, or the renderer and does not
explain the previously observed stretched hand. Left-arm vertex skinning and
a captured anomalous frame still require direct measurement. The v1 GUI test
also now waits through transient Windows file-picker handles after a model
selection instead of treating them as a new missing-model prompt.

The real v1/v2 graphical load, selection, edit, Save As, and reopen tests
passed on both x64 and x86 in the recovered RDP session, but startup is not
yet reliably repeatable: a later x64 retry failed before PMM reading at
Direct3D9 `CreateDevice` with attempts returning `0x8876086C` and
`0x8876086A`. A separate minimal D3D9 device test succeeded in both
architectures at that time; a standalone probe also succeeded with the
application's final back-buffer/depth settings, including from `WM_CREATE`.
The diagnostic failure path now records the application window state and
tries the same parameters against a separate test window, but no failed run
with that extra instrumentation has yet been captured. This remains an
initialization-condition investigation, not evidence that PMM loading failed
or that world-matrix parity regressed.

## Resource resolution and headless scene flow

`SceneResourceResolver` accepts PMM model slot/path references and resolves
relative paths against the scene directory and optional search roots. Missing
resources retain their original slot and raw path plus attempted candidates;
`ReselectModel` records a per-slot path override without changing the PMM
reference. Hosts provide a path decoder for non-ASCII PMM paths; the portable
default accepts ASCII paths only, rather than guessing a system code page.
The Windows loader supplies user-selected paths to this resolver when it
creates the portable scene session, while its existing file chooser remains
the UI for missing resources.

`mds_scene_cli input.pmm output.pmm [--root directory]
[--reselect slot model] [--frame index] [--seconds elapsed]` runs a headless
load, model resolution, seek, editable scene-field update, playback, Save As,
and readback validation; it emits a concise JSON state. It refuses to replace
existing output. `scene_fixture` generates an original synthetic v2 PMM and
PMD at test time, including a deliberately missing model reference, so the
CTest flow checks both missing-resource detection and explicit reselection
without shipping third-party models. The fixture is not a real MMD scene and
does not establish graphical parity. The portable CI matrix runs the same
targets on Windows, Linux, and macOS; see `docs/RHI_ARCHITECTURE.md` for the
separate rendering migration plan.

While exercising the camera anchor, an accepted-but-discarded camera key edit
was found in the portable scene writer. Existing v1/v2 camera value fields
now patch their original key records; v2 additionally patches the parent model
and bone indices. The round-trip validator compares camera keys, so v1 edits
to the non-serialized parent fields fail instead of silently succeeding.
