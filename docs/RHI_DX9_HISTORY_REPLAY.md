# Native DX9 preceding draw replay: incomplete acceptance

The new diagnostic recorder rebuilds the preceding fixed-function draws in a
fresh DX9 color/depth/stencil target with the application's actual 8x MSAA
quality. It does not replace application rendering or advertise complete
portable/DX11 replay. **The current native baseline fails: the latest valid run has 518 resolved
pixels differing before material 13 (previous run: 533). DX11 replay is NOT_RUN.**

## Capture boundary and coverage

`MDS_RHI_HISTORY_REPLAY=1` enables the diagnostic code only. Recording begins
after the actual scene clear, with clear flags/color/depth/stencil, source
attachment identity, dimensions, format, sample count/quality and viewport.
Each supported draw snapshots a native `D3DSBT_ALL` state block, viewport,
primitive/index range, FVF and vertex stride/offset. Vertex/index bytes and all
eight fixed-function texture stages are copied into immutable managed-pool
resources. Content versions are logged. Texture copies preserve visible mip
levels, format, LOD and automatic mip generation/filter settings, including
compressed DXT rows. Numeric DX9 render/stage/sampler states are logged for
diagnosis; these identifiers are not portable RHI enums.

The real `sample.pmm`, frame 5, model slot 2, material 13, first index 64731,
336 indices, has **49** preceding draws:

- 19 accessory mesh subset draws (the stage);
- 17 FVF66 projected-shadow draws;
- 13 FVF274 model material draws.

The earlier wrapper-only audit observed 30. `ID3DXMesh::DrawSubset` bypassed
those wrappers. The recorder now obtains the existing tested mesh subset plan,
snapshots its effective mesh buffer/FVF state, and restores native state before
the original `DrawSubset` executes. The actual accessory submission stays on
the original path. Its 32-bit UP fallback is unsupported and blocks capture.

This first implementation supports one unchanged target pair. Shadow-map
target switching, unexpected attachment changes/MRT, additional clears,
shader draws/MME, additional streams/instancing, unsupported texture kinds or
formats, incomplete clears and failed native submissions block acceptance.
The no-MME diagnostic setting is required. These checks are not a device-wide
COM interceptor: future direct device/D3DX calls must add capture/block hooks.
General target-change replay and a serialized portable command/resource format
remain unfinished. Resource/state objects here are DX9 baseline snapshots.

## Replay and gate

The recorder stops before the selected material's existing diagnostic probe.
It preserves the application's state/targets/viewport, clears a fresh matching
MSAA target, submits the frozen preceding draws in original order, and compares
resolved BGRA bytes inside the actual viewport to the untouched source target.
If the before comparison fails, the selected-draw replay gate stays closed.
Only a matching before image permits replay of the selected actual draw using
the rebuilt depth/stencil history, followed by an after-image comparison and
an assertion that the material changed pixels.

The latter is a **functional depth/stencil check for the selected draw**, not
per-sample depth/stencil readback or proof that every possible subsequent draw
will match. Resolved color equality alone is never labeled per-sample equality.
The diagnostic releases captured native resources through the existing model
comparison invalidation hook before device rebuilding.

## Observed results, 2026-10-01

The x64 real scene initially differed at 678,312 pixels because the accessory
stage was absent. Including its 19 draws reduced the difference to 49,117.
Preserving automatic texture mip generation reduced it to **533**, mostly at
model edges (maximum channel delta 19). This is still a failure under the
zero-difference requirement. The cause of the remaining differences has not
been established; texture mip contents, geometry/state restoration and resolve
behavior need controlled isolation rather than an inferred diagnosis.

Retained external evidence:
`exports/rhi-real-dx11-replay-x64/history_replay.dx9`,
`history_replay.before.bgra`, `history_replay.rebuilt.bgra`, and
`model_batch.same_frame`. The existing isolated native adapter probe still
reports zero differences and 241 changed pixels, with the application adapter
disabled. That does not validate the rebuilt prefix.

Subsequent attempts failed before scene loading with `CreateDevice Failed!`.
The native 8x capability probe then returned 77. The application creation log
records `0x8876086C` / `0x8876086A`, including alternate-window failure. x86
replay, opaque/translucent after-image checks and DX11 replay are **NOT_RUN**.
Both final x64/x86 application and GUI harness builds pass; the portable
`rhi_history` contract test passes. This turn did not change the portable
history contract or claim a new Linux/macOS GPU validation.

## Reproduction

```powershell
$env:MDS_PMM_GUI_FIXTURE='C:\Users\jstzw\Downloads\MikuMikuDanceE_v932\UserFile\sample.pmm'
$env:MDS_PMM_RELOCATE_MODEL='Dammy_Bone.pmd'
ctest --test-dir build-x64/build -C Release -R '^rhi_real_d3d9_history_replay_gui$' --output-on-failure
```

Repeat with `build-x86/build` sequentially on an unlocked GPU desktop. The new
CTest entry runs opaque and Alpha=0.5 copies, requires complete 49-draw state
records and exact binary before/after images, and fails on an unclosed gate.
Real textures/models remain external fixtures. The GUI harness now checks the
replay gate directly instead of accepting its older isolated-batch result.

Next: isolate the 533 residual pixels while retaining frozen resources and
exact MSAA history. After both architectures pass native replay, translate the
recorded accessory, shadow and material pipelines for DX11 and retain the
depth/blend controls. The production renderer continues on the original DX9
path throughout.

## Follow-up isolation, 2026-10-01

Fixed a recorder lifetime bug introduced with reset integration: the first
`BeginModelBatchCapture` for a new session invalidates its material comparison.
It must not also erase the prefix recorded earlier in the same frame. Native
replay resources now reset explicitly at PMM loading, device reset and shutdown,
rather than through that material-only invalidation. Diagnostic-off builds have
a no-op reset hook.

The recovered TITAN Xp initially passed the native capability probe. The next
same-frame isolation run recorded all 49 draws and reported:

| Geometry | Textures | Different resolved pixels | Gate eligible |
| --- | --- | ---: | --- |
| Frozen | Frozen | 518 | Yes, but FAIL |
| Frozen | Borrowed | 1,350 | No |
| Borrowed | Frozen | 1,582 | No |
| Borrowed | Borrowed | 2,347 | No |

These controls did not remove the difference. Borrowed resources may have
changed since their original draw; their version equality was not verified in
this run. The results therefore do not prove that copying is correct, or that
state restoration is the cause. A source-geometry version check has been added
for subsequent controls, with texture versions explicitly unverified. All
borrowed controls remain ineligible, and their target cannot feed selected-draw
acceptance. Evidence is `exports/rhi-real-dx11-replay-isolate-x64`.

`MDS_RHI_HISTORY_TRACE=1` now captures actual color before each native command
and logs `TRACE beforeSequence=N differentPixels=...` during frozen replay.
This identifies the earliest divergent draw instead of inferring its cause
from a final screenshot. It is diagnostic and has not yet been GPU-validated:
the subsequent runs again failed at device creation.

The improved capability probe identifies the failing call as
`CheckDeviceMultiSampleType`, HRESULT `0x8876086A` (`D3DERR_NOTAVAILABLE`), on
adapter `10de:1b02` / NVIDIA TITAN Xp. The input desktop was `Default`, not a
locked `Winlogon` desktop; no driver-reset cause has been established. Probe
unavailability now overwrites old capability evidence, and the replay runner
writes failed/unavailable acceptance on early GUI failure, avoiding stale PASS
reports. x86 graph replay and the after-image/Alpha=0.5 acceptance remain
unfinished. The next GPU step is the per-command trace on a stable device.

## Per-command trace results, 2026-10-01

Three consecutive native 8x checks and the x64 application successfully ran.
The complete 49-boundary trace is in
`exports/rhi-real-dx11-replay-trace-x64/opaque/history_replay.dx9`:

- Before sequences 1 through 4: zero differing pixels.
- Before sequence 5: six differences, first produced by draw 4.
- Final prefix: 545 differing pixels; acceptance FAIL.

Draw 4 is an accessory/stage subset: FVF274, base 0, minimum vertex 40,
13288 vertices, first index 1008, 1162 triangles. It has no bound textures.
This excludes texture-mip copying as the source of this particular first
six-pixel divergence, but not of later differences. The first mismatching
native/replayed images are retained as `history_replay.first_{actual,rebuilt}.bgra`.
World/view/projection and texture matrices are now logged with draw sequences.
The visible buffer properties are preserved in clones (usage, pool, FVF/format).
Matching these properties did not close the gate: draw 4 still first differed
by six pixels, final prefix 524 (`rhi-real-dx11-replay-buffer-x64`).

Further control runs first diverged after draw 7 instead, and final prefix
counts were 504/508. Source geometry version checks found zero changed geometry
draws, although borrowed texture versions remain unverified. Repeating the
same frozen resources, native state blocks and argument stream in the same
replay target produced 1427 then 722 differences versus its baseline image
(`rhi-real-dx11-replay-repeat-x64`). This is evidence of non-repeatable results
under the current diagnostic path; it is not yet proof of a driver bug or of
complete effective state equality.

The MSAA resolve read helper previously used StretchRect inside BeginScene.
It now ends the native scene before resolving/readback and resumes afterward,
with failure-aware cleanup. This is a diagnostic-only submission boundary;
it must not be attributed to production rendering changes. This corrected
path still fails (542 prefix differences; repeated results differ by 1417/745
versus baseline), evidence `rhi-real-dx11-replay-resolve-x64`. Therefore it did
not establish the cause of the residual pixels.

Matrix/material bytes are additionally captured and checked after state-block
application, blocking on a mismatch. This new check builds for x64/x86 but its
GPU validation is pending: both subsequent probes again returned
D3DERR_NOTAVAILABLE. x86 per-command trace is NOT_RUN. The remaining opaque /
Alpha=0.5, before/after zero-difference gate stays closed; DX11 stays NOT_RUN.

The runner now accepts `--probe` (three consecutive capability checks before
starting the application) and `--trace`. CTest uses the probe preflight.
Unavailability writes `preflight.json` explicitly and stops; a skipped CTest
GPU test is not acceptance. While the device is unavailable, first-difference
analysis and recorded failures remain readable without running the GPU.

```powershell
$env:MDS_PMM_GUI_FIXTURE='C:\Users\jstzw\Downloads\MikuMikuDanceE_v932\UserFile\sample.pmm'
$env:MDS_PMM_RELOCATE_MODEL='Dammy_Bone.pmd'
python tools/run_real_d3d9_history_replay.py --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe --application build-x64/build/Release/MikuDanceStudio.exe --dx9-test build-x64/build/Release/rhi_d3d9_parity_test.exe --probe build-x64/build/Release/rhi_d3d9_msaa_history_test.exe --trace --evidence exports/rhi-real-dx11-replay-state-x64
```

## State-restoration and repetition verification follow-up

The native replay now compares captured and restored world/view/projection,
material bytes, all eight texture matrices, scissor rectangle, documented
render states, 12 texture-stage states per stage and all 13 sampler states per
stage. Differences block execution and log their kind/key. Only documented
render/stage identifiers are logged: some drivers returned S_OK with poison
values for holes in the numeric enums, which were not meaningful state evidence.
This is a defined subset of native effective state; lights, clip planes and
other uncaptured categories are not claimed verified.

A flaw in the earlier repetition controls was corrected: the baseline read
back every preceding draw boundary, while controls stopped reading boundaries
once their first difference was found. Consequently their EndScene/BeginScene
submission patterns differed. All traced controls now keep every readback
boundary. The previously reported non-repeatability is therefore evidence
under unequal submission patterns, not proof of instability under identical
submission patterns. That earlier conclusion must remain provisional.

The isolation run additionally resolves the unchanged target twice and reports
`READBACK_REPEAT`; three fully frozen repetitions report both baseline and
previous-repetition pixel differences, plus an explicit `STABILITY` result.
Borrowed-resource controls and isolation targets still cannot open the material
acceptance gate. These checks are diagnostic, not production-renderer changes.

This follow-up's TITAN Xp capability probe passed several times, but attempted
application tests failed with CreateDevice Failed before scene capture. No new
state-restoration or matching-boundary repetition result was obtained.
`exports/rhi-real-dx11-replay-restore-x64/test.log` records the GUI failure and
`capability/msaa_history.capabilities` records the most recent probe separately.
Do not conflate a passing capability probe with successful application replay.
Both architectures build; portable history tests remain the non-GPU check.
The MSAA history gate stays closed and DX11 stays NOT_RUN.

## Device-creation reproduction and recovered GPU checks

The native capability executable now supports `--creation-matrix`. A minimal
STATIC window exercises ten parameter combinations, each repeated three times:
64x64 versus desktop-sized buffers; auto depth off/on; 8x MSAA; immediate
presentation; D24S8/D24X8/D16; hidden/visible windows; A8R8G8B8/X8R8G8B8; and
the lockable single-sample COPY fallback. Each row logs the requested values,
color/depth sample-support HRESULTs and device creation HRESULT. x64 and x86
both completed **30/30 successful creations**. Evidence is
`exports/rhi-real-dx11-device-matrix-{x64,x86}/device_creation.matrix`.

The application now logs each individual creation attempt before CreateDevice
can mutate its parameters, rather than reporting only the final fallback after
seven attempts. Both real application tests succeeded immediately with the
same combination: HAL hardware VP (64), hidden valid window, 1920x1080,
A8R8G8B8, count 1, DISCARD, automatic D24S8, samples 8 / quality 0, no flags,
immediate interval. `d3d_create.attempts.txt` in
`exports/rhi-real-dx11-device-application-{x64,x86}` records HRESULT 0.

These checks did **not** reproduce the intermittent creation failure or prove
it permanently fixed. They demonstrate that the recorded parameter combination
works on this desktop in the recovered interval; no production parameter
workaround was introduced. Earlier failures remain relevant evidence. More
per-attempt failure logs are needed when the fault recurs.

Both architectures also ran full state checks and matching-boundary repetitions:

| Check | x64 | x86 |
| --- | ---: | ---: |
| Same unchanged target, second resolve/read | 0 pixels | 0 pixels |
| Actual vs first frozen 8x prefix | 508 | 459 |
| Frozen repeat 1 vs baseline | 561 | 470 |
| Frozen repeat 2 vs baseline | 218 | 117 |
| Frozen repeat 3 vs baseline | 405 | 350 |

Matrix, material, documented render/stage/sampler states, texture matrices and
scissor checks did not report restoration mismatch. The x86 run additionally
verified known light values/enables after state-block restore. Every repeated
trace retains the same per-command readback boundaries. `STABILITY` remains
FAIL; none of these controls can open the material acceptance gate.

### Single-sample diagnostic control

`MDS_RHI_REPLAY_SINGLE_SAMPLE_CONTROL=1` is an explicitly diagnostic-only control
that disables MSAA on the copied scene. It uses ordinary native depth resources,
not INTZ history capture. The real 49-command stream, its effective states and
frozen resources otherwise follow the same path. Both x64 and x86 report:

- Prefix actual vs frozen: zero differing pixels.
- Unchanged target readback: zero differing pixels.
- All three frozen repetitions vs baseline, previous repeat and original:
  zero differing pixels; STABILITY PASS.

Evidence: `exports/rhi-real-dx11-device-single-control-{x64,x86}`. This localizes
the residual behavior to the multisampled execution/configuration path under
these controls; it does not establish the cause (sample placement, vendor
configuration, unresolved effective state or another MSAA-specific behavior).
It is not evidence that the 8x history is correct. The normal acceptance runner
removes this control flag, requires samples 8, and the diagnostic control never
opens selected-draw replay. Its GUI acceptance deliberately fails the 8x gate,
even though its control prefix/repetition checks pass. Production rendering
continues unchanged. Material 13 before/after 8x and translucent acceptance
remain incomplete, and DX11 stays NOT_RUN.

```powershell
build-x64/build/Release/rhi_d3d9_msaa_history_test.exe exports/rhi-real-dx11-device-matrix-x64 --creation-matrix
```

Next compare repeatability on matching MSAA attachments and investigate sample
placement/vendor antialiasing configuration without treating single-sample or
resolved color as equivalent 8x history. Retain the now-valid native 1x control
and the creation logs as separate gates.

## NVIDIA antialiasing settings and sample coverage investigation

`tools/inspect_nvidia_aa.py` reads the installed NVIDIA DRS database through
NVAPI. It does not call setting/profile mutation or SaveSettings. Public
NVIDIA NVAPI definitions were consulted for the setting IDs and versioned
structures; downloaded references remain under ignored `out/nvapi-inspection`.
No NVIDIA SDK source was added to the application. The diagnostic script is
Windows/NVIDIA-specific and is not a portable renderer dependency.

Both MikuDanceStudio.exe and rhi_d3d9_msaa_history_test.exe returned
NVAPI_EXECUTABLE_NOT_FOUND (-166) from the application-profile lookup. The base
and active global profile reads succeeded. Current DWORD values were:

| Setting | Value | Meaning within this inspection |
| --- | ---: | --- |
| AA mode / method | 0 / 0 | Application-controlled, no forced method |
| Gamma correction | 0 | Off |
| Transparency multisampling / supersampling | 0 / 0 | Off |
| AA behavior flags | 0 | No flags reported |
| FXAA | 0 | Off |
| MFAA sample interleaving (0x0098C1AC) | 0 | Off |

This is the DRS view at query time, not proof that all internal driver state or
vendor undocumented behavior is absent. No driver configuration was changed.
Evidence is `exports/rhi-real-dx11-nvidia-aa/profile.json`.

The native diagnostic now supports `--sample-coverage`, with a CTest entry
`rhi_d3d9_sample_coverage`. It creates an actual 8x swapchain and a matching
8x offscreen target (A8R8G8B8, quality 0), then uses each of the eight individual
D3DRS_MULTISAMPLEMASK bits. A white/black axis-aligned edge scans 17 positions
in 1/16-pixel increments horizontally and vertically, resolving outside the
scene and reading the observed pixel. Each sweep repeats three times on each
target. This is coverage-threshold evidence, not per-sample color/depth readback
or an official sample-location query.

x64 and x86 both passed: no changed threshold steps across repetitions,
no differences between swapchain and offscreen sweeps, and no differences
between architecture sweeps. The first-covered step indices (x,y), from edge
30.5 in increments of 0.0625 at pixel (31,31), were:
`(10,6), (8,12), (14,10), (6,4), (4,14), (2,8), (12,16), (16,2)`.
These threshold indices retain rasterization boundary conventions and should
not be treated as exact sample coordinates without further calibration.
Logs: `exports/rhi-real-dx11-sample-coverage-{x64,x86}/sample_coverage.log`;
summary: `exports/rhi-real-dx11-nvidia-aa/coverage-summary.json`.

The inspected settings and simple coverage sweeps do not support the suspected
MFAA/forced-AA or changing axis-aligned sample-placement explanation. They do
not close the real-scene MSAA gate. Depth/stencil interactions and per-sample
blending history remain untested by these simple sweeps. Next isolate those
operations on controlled geometry before changing the production renderer.

```powershell
python tools/inspect_nvidia_aa.py exports/rhi-real-dx11-nvidia-aa/profile.json
build-x64/build/Release/rhi_d3d9_msaa_history_test.exe exports/rhi-real-dx11-sample-coverage-x64 --sample-coverage
```

## Controlled MSAA depth/stencil/blend histories

The new `--attachment-history` diagnostic and CTest
`rhi_d3d9_attachment_history` exercise six 8x MSAA / quality-0 cases on a 96x96
A8R8G8B8 + D24S8 target:

- Depth occlusion with LessEqual and depth writes.
- Prior draw with depth writes disabled.
- Stencil Replace followed by Equal testing.
- Depth-failed fragments writing stencil, then Equal testing.
- SRCALPHA/INVSRCALPHA translucent history and selected draw.
- Combined depth, stencil and translucent history.

Fractional, diagonal geometry and a sloped prior depth cover partially filled
samples. The selected geometry is offset so stencil rejection is observable.
Each case runs on all four combinations of swapchain/offscreen color and
native-auto/new depth-stencil surfaces, three times per combination. All states
are explicitly initialized and each run clears color, depth and stencil.
Readback takes place outside BeginScene. Each comparison checks both the
prefix image and the selected-draw result against the first native baseline.
Control draws disable the relevant feature (or enable prior depth writes in
the no-write case); every control must change pixels, ruling out vacuous checks.

Both x64 and x86 passed all 72 ordinary comparisons (six cases x four target
pairs x three repetitions), plus six sensitivity controls. No prefix/after
pixel differences occurred. The control differences were respectively
2578, 2578, 691, 691, 3137 and 2578 pixels. Cross-architecture logs are identical.
Baseline images are retained for direct cross-architecture byte comparison.
Evidence: `exports/rhi-real-dx11-attachment-history-{x64,x86}`. The original
history contract test and new GPU CTest pass on both architectures, with no
skips. These fixtures are procedural; no proprietary model/texture dependency
is required.

This is functional verification using resolved images, not per-sample depth
or stencil readback. The simple controlled histories did not reproduce the
real PMM prefix instability, and do not close its zero-difference gate.
The next useful isolation is the actual first divergent accessory's geometry,
state and lighting, progressively reducing its draw history. Production DX9
rendering remains unchanged and DX11 replay remains NOT_RUN.

```powershell
build-x64/build/Release/rhi_d3d9_msaa_history_test.exe exports/rhi-real-dx11-attachment-history-x64 --attachment-history
ctest --test-dir build-x64/build -C Release -R '^rhi_(history|d3d9_attachment_history)$' --output-on-failure
```

## Real accessory batch extraction and prefix reduction

`MDS_RHI_HISTORY_REDUCE=1` now selects the draw immediately preceding the
first observed boundary difference. It exports original vertex/index bytes,
FVF/stride/ranges, viewport, world/view/projection and texture matrices,
material, captured light fields/enables, and documented render/stage/sampler
values. It also exports each preceding draw in the reduced prefix, preserving
its independent effective state and bytes. The binary buffers are external
real-scene data and remain in ignored exports; native state numbers are
DX9 diagnostic data, not a portable RHI transport. Nonempty bound textures
have their accessible level bytes exported; the divergent batches observed
here have no bound textures. In-process replay still uses frozen native state
blocks; standalone deserialization of these exports is not implemented.

Reduction clears matching attachments and replays each suffix ending in the
suspect draw, including the suspect alone. Each suffix runs ten repetitions
with consistent readback boundaries. Single-draw controls disable lighting,
depth, stencil, blending, normal normalization or specular lighting separately.
A final control substitutes (0,1,0) for zero normals in a temporary cloned VB,
then restores the original frozen VB. These are ineligible diagnostic controls;
normalization, lighting and original source assets are unchanged in production.
The ordinary acceptance runner removes the reduction environment flag.

### Observations

The first three-repeat x64 capture chose draw 6 (2840 triangles): it alone was
stable, but suffix 5..6 differed by up to 24 pixels. More repetitions changed
the conclusion: the ten-repeat capture chose draw 7 (6680 triangles), and draw
7 alone differed by up to four pixels. Disabling lighting produced ten matching
images; disabling depth, stencil or blending did not. The x86 ten-repeat
capture chose draw 4 (1162 triangles), and draw 4 alone differed by up to 103
pixels; disabling lighting again produced ten matching images.

This reduces an observed failure to a **single actual accessory draw**, rather
than requiring model/shadow history. Which draw first differs remains variable
across runs, so suffix reduction results are observations, not a deterministic
minimality proof. Three identical runs did not suffice to prove stability.

Evidence:
- `exports/rhi-real-dx11-reduction-x64` (initial three-repeat draw 6).
- `exports/rhi-real-dx11-reduction-x64-ten` (ten-repeat draw 7).
- `exports/rhi-real-dx11-reduction-x86` (ten-repeat draw 4).

The draw-7 capture has 4468 distinct referenced vertices, no nonfinite values,
and 136 zero normals; nonzero normal lengths reach about 1.000000134. Those
facts are recorded in `normal-inspection.json` and are not themselves evidence
of corruption. Native normal normalization is enabled and the world matrix
has scale near 10.

Additional x64 controls chose draw 4 again:

| Single-draw configuration | Maximum repeat differences |
| --- | ---: |
| Original | 6 |
| Lighting off | 0 |
| Depth off | 0 (different from some earlier runs) |
| Stencil off | 11 |
| Blending off | 89 |
| Normal normalization off | 0 |
| Specular off | 6 |
| Replace zero normals only | 6 |

The temporary replacement affected 335 zero normals across the full shared VB,
not necessarily all referenced by this subset. Replacing zero normals did not
close the repetition gate; zero normals cannot be claimed the root cause.
Lighting/normalization controls suggest investigating fixed-function normal
processing under MSAA, but disabling them changes the image and may mask other
behavior. They are not a behavior-preserving fix.
Evidence: `exports/rhi-real-dx11-reduction-normals-x64`.

The first x86 extended attempt failed to reach a live main window after model
reselection; a retry succeeded for the ten-repeat reduction. This GUI failure
is separate from the successful reductions, not a skipped pass. The production
renderer and real-scene zero-difference gate remain unchanged. Next independently
reproduce the single-draw fixed-function normal/light computation with a
procedural mesh before choosing any compatibility policy. DX11 is NOT_RUN.

The final x86 expanded control run also completed
(`exports/rhi-real-dx11-reduction-normals-x86`): original single draw differed
by up to 40 pixels, lighting off was stable, depth off differed by 8, stencil
off by 16, blending off by 84, normalization off by 22, specular off by 38,
and zero-normal replacement by 86. Therefore the x64 normalization-off zero
result did not generalize to x86. Across these controls only lighting-off
consistently produced ten matching repetitions. This remains a localization
clue, not a permissible production rendering change or exact PMM acceptance.

## Standalone procedural fixed-function lighting reproduction

`--fixed-lighting` and CTest `rhi_d3d9_fixed_lighting` now generate a 24x24
wavy triangle grid, with varied unit normals or periodic zero normals. No PMM,
D3DX mesh loading, UI automation or external geometry is needed. The matrices,
material and directional light are the captured draw-4 values (including the
world scale near 10, negative light ambient components, diffuse light 10 and
power 2). Material/global ambient source and nonlocal-viewer states are set
explicitly. A native hardware-VP device renders 256x192 A8R8G8B8/D24S8, at 1x
or 8x. Lighting, normalization and specular toggles plus normal variants form
32 cases, each repeated ten times. Before each repetition state is explicitly
set and color/depth/stencil cleared; readback is outside BeginScene.

Baseline images are exported and sensitivity checks require lighting,
normalization, specular and zero-normal toggles to visibly affect images.
In 8x, these toggles changed 29503, 20116, 17653 and 5343 pixels respectively.
The first x64 and x86 manual runs passed all cases, and their 32 baseline
images matched byte-for-byte (`exports/rhi-real-dx11-fixed-lighting-{x64,x86}`).
This initially non-reproducing result did not establish stability: subsequent
x64 CTest runs failed on the **8x / periodic zero normals / normalization on /
specular off / lighting on** case, with up to five differing pixels. A later
manual run reproduced one differing pixel. The test intentionally reports
failure instead of treating small differences or occasional passes as acceptance.
The last x86 run did not reproduce a fixed-function repetition difference;
architecture-specific observation remains explicit.

An explicit DX9 vs_3_0/ps_3_0 control was added for that case at both sample
counts. It uses the captured transforms and a simplified directional diffuse /
ambient / emissive formula, with a defined zero-length normal result of zero.
It does not claim an exact implementation of every native fixed-function rule,
and specular is off for this control. Ten explicit shader repetitions on both
architectures matched exactly at both 1x and 8x. However, explicit versus fixed
baseline differed by six pixels at 1x and 4320 at 8x. `formulaEquivalence` is
explicitly NOT_VERIFIED. No shader replacement or normal repair was made in
the production renderer. This control establishes stable repeat execution
under that explicit formula, not that its images are correct or that a driver
bug is proven. Native normal handling and per-sample shading/coverage semantics
still need independent calibration.

Evidence: `exports/rhi-real-dx11-fixed-lighting-shader-{x64,x86}/fixed_lighting.log`.
The x64 run returned 2 for the reproduced fixed-function difference; x86 returned
0. Both builds and existing controlled attachment-history / portable-history
regressions pass. The new fixed-lighting CTest is a strict diagnostic and may
fail on the reproduced native behavior; its failure is not suppressed or
converted into a skip. The real PMM gate stays NOT_PASSED; DX11 stays NOT_RUN.

```powershell
build-x64/build/Release/rhi_d3d9_msaa_history_test.exe exports/rhi-real-dx11-fixed-lighting-shader-x64 --fixed-lighting
```

Next isolate zero-normal handling and fixed-function interpolation/sample
rules on a few triangles, comparing both shader and fixed-function pixel values
rather than only repeat stability. Preserve the original behavior while the
formula/image equivalence gate remains open.


## Reduction to one and two triangles: zero normals and sample masks

`--lighting-triangle` and `--lighting-pair` generate one triangle and two
triangles sharing an edge. They reuse the captured transforms, material and
light above. Four normal modes are tested: 0 = unit normals, 1 = one zero
normal, 2 = all zero normals, 3 = all normal lengths scaled by 1e-12. The log's
legacy `zeroNormals` field holds this mode number. Lighting, normalization,
specular and 1x/8x sampling produce 64 cases per shape, each repeated forty
times. CTest names are `rhi_d3d9_lighting_triangle` and
`rhi_d3d9_lighting_pair`; GPU tests run serially. Native and explicit repeat
mismatches fail the test. Fixed-versus-explicit image differences are diagnostic,
not silently accepted as formula equivalence.

The initial runs did not reproduce repeat instability. A subsequent x64
**two-triangle** run did: at 8x, mixed zero normals, normalization on, specular
off and lighting on, one pixel differed from the first repetition. The run
returned 2, with `failedCases=1`. Thus a two-triangle procedural reproduction
now exists; PMM loading and its original mesh are not necessary to trigger the
observed repeat mismatch. The corresponding x86 run remained stable. Later
CTest runs passed all four selected tests on each architecture (both reduced
shapes, attachment history and portable history); those later passes do not
invalidate the intermittent failure. Failed repetition images are now saved
as `caseN-repeatR.bgra`, with the first differing coordinate and BGRA values
recorded as `FIRST_DIFFERENCE`. The observed failure occurred before that
additional export instrumentation was added, so that first failing run has a
count and baseline, but no saved anomalous pixel coordinate. Ten bounded x64
pair runs after adding instrumentation all passed; their separate logs were
preserved under `exports/rhi-real-dx11-lighting-pair-trace-x64-{0..9}`.
A failure is never retried into an overall success result.

For normalization on / specular off / lighting on, explicit diffuse/ambient/
emissive shading with a defined zero-normal result was compared against native
fixed-function rendering. All four normal modes matched at 1x in both shapes.
At 8x, the full-zero case matched, but spatially varying lighting did not:

| Normal mode | One triangle: differing pixels | Two triangles: differing pixels |
| --- | ---: | ---: |
| Unit | 48 | 69 |
| One zero vertex | 76 | 90 |
| All zero | 0 | 0 |
| Scaled by 1e-12 | 48 | 69 |

These are baseline image comparisons, distinct from the intermittent repeat
failure. The single triangle's differences fall on partially covered edges;
the pair also has differences at pixels with combined full coverage, which
can include its shared edge. Maximum channel differences were 1 for unit
normals and the pair, and 2 for the single triangle's mixed-zero case. On this
hardware, normalized tiny normals reproduce unit-normal baseline images, and
all-zero normals agree with the explicit-zero control. This does not specify
universal zero-normal behavior, or validate every lighting/specular rule.

Replacing COLOR interpolation with explicit centroid TEXCOORD interpolation
produced the same baseline images and did not remove the 8x differences.
Controls using one enabled `D3DRS_MULTISAMPLEMASK` bit at a time were also
exported. For unit / mixed / tiny normals, bits 0-3 matched fixed versus
explicit; bits 4-7 did not. For the single triangle those differing-pixel
counts were `[740,147,687,993]` for unit/tiny normals and
`[1257,556,763,1716]` for mixed normals. For the pair they were
`[1398,883,874,1925]` and `[1915,1292,950,2648]`. All-zero normals matched
for all eight bits. These are **resolved images of masked draws**, not a
capture of the unmodified draw's individual samples: masking can affect
interpolation, and resolve quantization remains present. They do not prove
per-sample shading, an exact interpolation location, or a driver defect.

All 144 baseline/control images per shape (64 fixed, 16 explicit, 64 masked)
matched byte-for-byte between x64 and x86 in the manual baseline comparison.
Evidence: `exports/rhi-real-dx11-lighting-{triangle,pair}-{x64,x86}` and
`exports/lighting-triangle-analysis.json`. The latter records cross-architecture
and sample-mask results; previous per-shape `pixel-analysis.json` describes
coverage localization. Exported artifacts are local diagnostics, not required
copyrighted fixtures.

Next separate two questions: capture the occasional repeat mismatch's pixel
and channel values, and calibrate varying-color interpolation/quantization
using prelit vertices without lighting math. The mask observations alone do
not settle those rules. Real-PMM 8x acceptance remains NOT_PASSED, DX11 prefix
replay remains NOT_RUN, and production DX9 rendering is unchanged.


## Prelit vertex colors: separating lighting from pixel-stage behavior

`--prelit-interpolation` / CTest `rhi_d3d9_prelit_interpolation` now render
one/two program-generated triangles using prescribed colors. There are no
normals, lights, textures, blending, depth or stencil operations. The target
is 256x256 A8R8G8B8, at 1x or 8x quality 0. Dithering, fog and sRGB write are
disabled. Both unit RHW and varying RHW (1 / 0.5) are tested. Binary fractional
screen coordinates are shared between the XYZRHW fixed path and the explicit
vertex shader's screen-to-clip conversion; the latter uses an explicit
POSITION declaration, not POSITIONT. This diagnostic does not depend on PMM.

Four palettes distinguish constant color, RGB/white gradients, adjacent byte
levels, and a gradient with a fractional-input control. Five rendering paths
are exported:

| Path | Vertex input / processing | Pixel processing |
| --- | --- | --- |
| 0 | XYZRHW, packed D3DCOLOR, fixed | Fixed SELECTARG1 diffuse |
| 1 | Same packed color, explicit VS | COLOR pass-through PS |
| 2 | Same packed color, explicit VS | Centroid TEXCOORD pass-through PS |
| 3 | Float4 color, explicit VS | COLOR pass-through PS |
| 4 | XYZRHW, packed color, fixed | COLOR pass-through PS |

For palettes 0-2, float colors equal packed bytes divided by 255. Palette 3
adds 0.49/255 to each RGB component only in path 3, intentionally changing the
input. Thus path 3's palette-3 differences measure retained fractional input,
not a failure to decode the same bytes. All other paths receive the same
packed palette. Alpha remains one and blending is off.

Full-mask draws repeat forty times; eight individual mask controls repeat
three times at 8x. Each architecture completed **800 path/case combinations**
without repeat mismatches or empty renders, and constant-color cross-path
comparisons were exact. Repetition / empty-render / constant-color failures
fail CTest; varying-color comparisons remain explicit diagnostics and do not
constitute a passing image-equivalence gate. Both builds' 800 exported
baseline images matched byte-for-byte.

Full-mask fixed versus packed explicit comparisons:

| Palette | 1x | 8x, one triangle (unit/varying RHW) | 8x, pair (unit/varying RHW) |
| --- | --- | --- | --- |
| Constant | 0 | 0 / 0 | 0 / 0 |
| RGB gradient | 0 | 126 / 150 | 262 / 250 |
| Adjacent byte levels | 0 | 1 / 2 | 2 / 3 |
| Other color gradient | 0 | 103 / 97 | 153 / 157 |

The table counts differing pixels. RGB gradients differ by at most two
channel levels, adjacent-byte gradients by at most one. Constant colors do
not differ even in individual mask controls. Centroid and ordinary explicit
outputs matched in every case. Individual-mask varying-color comparisons
again matched for bits 0-3 and differed for bits 4-7. These are resolved masked
redraws; they cannot be substituted for original per-sample history.

Crucially, **path 4 matched path 1 in every comparison**, including all masks
and varying RHW. Changing only the fixed pixel stage to an explicit
pass-through PS produces the same differences as replacing both stages.
Therefore these stable prelit differences do not require lighting, zero
normal normalization, or the explicit VS's transform arithmetic. They are
localized to behavior associated with the pixel-stage change under MSAA;
this still does not uniquely identify interpolation locations, per-sample
invocation rules, fixed-stage precision, resolve rounding, or a driver bug.

For the single triangle, every full-mask packed-color difference is at a
partially covered edge. In the pair, some pixels have combined full coverage,
which can include the shared primitive edge. The float-only 0.49/255 offset
changes 16456-29357 pixels at 1x by at most one channel level, as expected for
changed fractional input near output quantization thresholds. Retaining
fractional input matters; blindly quantizing portable colors before drawing
would alter the input contract. The observation alone does not specify a
universal rounding rule.

Evidence: `exports/prelit-interpolation-{x64,x86}/prelit.log`, raw BGRA images,
and `exports/prelit-interpolation-analysis.json`. Reproduce analysis with:

```powershell
python tools/analyze_prelit_interpolation.py exports/prelit-interpolation-x64 exports/prelit-interpolation-x86 exports/prelit-interpolation-analysis.json
```

The analyzer reports cross-architecture image differences, first mismatching
pixel values, signed channel-delta histograms and combined-coverage counts.
The probe's all-mask image comparison does not pass the varying-color gate
just because repeat stability passes. Next calibrate pixel-stage precision
and sample/interpolation locations separately, using explicit output rounding
and prescribed linear ramps; preserve the intermittent fixed-lighting
reproduction as a separate issue. Production rendering is unchanged; real
PMM 8x acceptance is NOT_PASSED and DX11 prefix replay is NOT_RUN.


## Output rounding and effective interpolation-location calibration

The prelit probe now adds path 5 (float-input PS with
`floor(saturate(rgb)*255+0.5)/255`), path 6 (float-input PS with
`floor(saturate(rgb)*255)/255`), and path 7 (analytic color from PS `VPOS`).
Paths 5/6 deliberately quantize before MSAA resolve; they are candidate
controls, not changes to the renderer. Palettes 4-11 are eight phase-shifted
ramps, with phase `k/8` byte levels:

- float R = `(screenX - 32.25 + phase)/255`;
- float G = `(screenY - 35.5 + phase)/255`;
- float B = `(64 + phase)/255`.

Packed-input paths round these vertex colors to byte values; the float paths
retain them. Path 7 computes the same expressions from VPOS rather than
interpolated colors. Consequently ramp packed-versus-float comparisons
intentionally include input quantization. Varying RHW makes vertex-color
interpolation perspective-dependent, so location calibration specifically
uses one triangle with unit RHW. Ramp cases use full masks; the original
palettes retain their eight individual-mask controls. There are now 1632
path/case combinations per architecture, with the existing forty full-mask
or three mask-control repetitions. Native repetition, empty-render and
original constant-color equivalence checks remain strict. New rounded
outputs and changed-input ramps are diagnostic comparisons.

Both x64/x86 manual runs completed all 1632 combinations without repeat
mismatches, and all 1632 baseline images matched across architectures. For
RGB-gradient single-triangle unit-RHW draws, explicit rounding did **not**
restore the native fixed output:

| Output | 1x differing pixels | 8x differing pixels |
| --- | ---: | ---: |
| Pass-through | 0 | 126 |
| Explicit half-up | 1664 | 1745 |
| Explicit floor | 15004 | 15097 |

At pixel (96,96), the eight constant-blue phases output
`[64,64,64,64,64,65,65,65]` in the unmodified float path at both sample counts.
Explicit half-up gives `[64,64,64,64,65,65,65,65]`; explicit floor gives eight
64s. The observed 64.5 result is compatible with a ties-to-even boundary, but
one even boundary and finite floating-point precision do not establish a
universal conversion rule. Pre-rounding amplifies, rather than fixes, the
observed image mismatch.

Unit-RHW interpolated ramps versus VPOS ramps match for all eight phases at
1x. At 8x their differing-pixel counts are `[41,217,33,12,16,22,231,68]`;
**all differences are at partially covered edges**, with none at combined
full-coverage pixels of this single triangle. The maximum channel difference
is two. This independently separates coverage-dependent interpolation from
lighting math and from input-color packing, but does not identify every
sample's interpolation location or invocation count.

`tools/calibrate_prelit_output.py` fits floor / half-up / ties-even candidates
and offsets on a 1/16-pixel grid, retaining every best fit rather than choosing
one silently. It samples 294 interior pixels per phase with mixed integer
parities. For the unmodified float ramps at 1x and 8x, multiple rounding/offset
pairs have zero error; no unique location is recovered. The explicit half-up
G control has 56 total channel errors even under its best simple model,
illustrating sensitivity near floating-point thresholds. Full-coverage
resolved values are inadequate to distinguish individual sample positions.
The analysis states this limit instead of calling an offset inferred from
quantized images an exact sample coordinate.

Evidence: `exports/prelit-calibration-{x64,x86}/prelit.log`, baseline images,
`fit.json`, and `exports/prelit-calibration-analysis.json`. Reproduce with:

```powershell
python tools/analyze_prelit_interpolation.py exports/prelit-calibration-x64 exports/prelit-calibration-x86 exports/prelit-calibration-analysis.json
python tools/calibrate_prelit_output.py exports/prelit-calibration-x64 exports/prelit-calibration-x64/fit.json
```

The intermittent fixed-lighting problem remains independent: five bounded
`--lighting-pair` runs on each architecture (64 cases x forty repetitions per
run) did not reproduce it this time. Their logs are preserved under
`exports/lighting-pair-calibration-trace-{x64,x86}-{0..4}`; prior failing runs
are retained and not converted to passing acceptance. Failed-pixel export
instrumentation remains active. No production normal repair, pixel shader
replacement or rounding compensation was introduced.

Next use controlled fractional edge sweeps with VPOS/ramp comparisons to
constrain partial-coverage interpolation, together with separate constant
color threshold sweeps to distinguish conversion precision from location.
Do not promote an ambiguous resolved-image fit to a per-sample rule. Real
PMM acceptance remains NOT_PASSED and DX11 prefix replay remains NOT_RUN.

Final validation: both Release builds succeeded. The expanded prelit CTest,
attachment-history CTest and portable-history CTest passed on each of x64
and x86 (3/3 per architecture); Python analysis scripts passed compilation.
These check repeat stability and diagnostic execution, not varying-color
image equivalence or real PMM acceptance.


## Fractional edge sweeps and independent output-threshold scans

`--edge-quantization` and CTest `rhi_d3d9_edge_quantization` now run two
separate experiments on 64x64 A8R8G8B8, 1x/8x quality 0. Lighting, depth,
stencil, blending, fog, dithering and sRGB write are disabled; the last state
is also read back and logged. Shader compilation uses IEEE strictness.
Each draw is repeated three times, with complete-image comparison; a repeat
mismatch saves both baseline and anomalous images and fails the diagnostic.
Constant outputs must also be nonempty and uniform in an interior region.
The final probe executes 46800 draws per architecture.

**Constant output thresholds.** A PS constant bypasses vertex-color
interpolation. Bases 63,64,65 and 120 through 128 are scanned with fractional
byte offsets 0 through 1 at steps of 1/64. Each requested float's raw bits
are recorded. Pass-through, explicit half-up and explicit floor are separate
paths. The original pass-through's first higher output occurs at:

| Base byte | First higher step / 64 |
| --- | --- |
| 63, 123, 124, 125, 126 | 33 / 64 |
| 120, 121, 122 | 34 / 64 |
| 64, 65, 127, 128 | 36 / 64 |

All tested bases remain at the lower byte for the exact requested half-byte
input. 1x and 8x fully covered results match. This refines the earlier
single-even-boundary observation: it does **not** establish ties-to-even or
an exact 0.5 threshold. These are measured end-to-end PS/target conversion
thresholds on this device, including finite precision; the responsible
internal precision stage remains unproven. The result must not be generalized
to every format or backend.

**Coverage and interpolation sweep.** A rectangle's right or bottom boundary
moves from 30.5 to 31.5 at 1/64-pixel steps. Pixel (31,31) is observed. White
constant-output draws use one enabled mask bit at a time; ramps use the full
mask. Ordinary COLOR, centroid TEXCOORD and direct VPOS ramps use eight
fractional-color phases. RGB varies at four byte levels per pixel, so the
measurements more strongly constrain position than the earlier one-level
ramps. The interior pixel (16,16) is logged as a control. Individual-mask
images remain **resolved redraw controls**, not direct original-sample data.

All coverage sweeps are monotonic. The first nonzero mask steps are:

| Sample index | X first-covered step | Y first-covered step |
| --- | ---: | ---: |
| 0 | 37 | 21 |
| 1 | 29 | 45 |
| 2 | 53 | 37 |
| 3 | 21 | 13 |
| 4 | 13 | 53 |
| 5 | 5 | 29 |
| 6 | 45 | 61 |
| 7 | 61 | 5 |

A first-covered step `n` brackets the coverage transition between offsets
`-0.5+(n-1)/64` and `-0.5+n/64` from pixel coordinate 31. These are observed
coverage brackets; exact inclusivity, rasterizer snapping and interpolation
locations are not implied.

**Resolve is not a linear byte average on this setup.** One enabled white
sample produces byte 99, not 32. For covered sample counts 0 through 8, white
outputs are `[0,99,137,165,188,207,225,241,255]`. Standard sRGB encoding of
covered-count/8 matches within one byte (seven samples predicts 240 rather
than 241). sRGB write is disabled, so that state alone does not explain the
observed resolve behavior. This is evidence of a nonlinear, sRGB-like resolve
on the tested path; it does not prove which driver option or internal stage
causes it, or justify changing driver settings. Previous linear-average
inversions must not be used at partial coverage. The earlier full-coverage
fits remain limited to their stated full-coverage region.

Constant outputs 0,32,64,120 through 128 and 255 were additionally resolved
at every swept boundary, establishing an **empirical color/coverage lookup**.
`tools/analyze_edge_quantization.py` uses this lookup plus the measured
constant-output thresholds to fit a model of one uniform color across covered
samples. It scans effective offsets at 1/64-pixel intervals, preserving all
best candidates rather than promoting a guessed offset to an exact location.
The single-sample midpoint conversion and resolve predictions are therefore
measured separately from the varying-color interpolation experiment.

For both ramp axes, 112 partial-coverage states per path have exact fits over
all eight color phases. Ordinary COLOR and centroid TEXCOORD match in all
rows. For these two paths, **zero of the 112 states admit pixel-center offset
zero**. All 112 are compatible with the coverage bracket's lower-end offset
for the lowest-index covered sample. Direct VPOS admits center offset zero
in all 112 states and that lowest-index offset in none. This is substantial
support for coverage-dependent interpolation consistent with a lowest-index
covered-sample choice, but it is only model compatibility. Every case retains
multiple exact candidates; we have not directly measured pixel-shader
invocation count or proven the backend's internal sample-selection algorithm.
For example, on the X sweep with one covered sample at step 8, COLOR offsets
`[-0.453125,-0.4375]` fit while VPOS admits `[-0.015625,0]`; at step 40 with
five covered samples, COLOR fits `[0.046875,0.0625]`.

Evidence: `exports/edge-quantization-{x64,x86}/{quantization,coverage,edges,resolve}.csv`
and `scan.log`, plus `exports/edge-quantization-analysis.json`. All four CSV
files match byte-for-byte between x64 and x86. Both manual runs completed
without repeat or uniformity failures. Reproduce analysis with:

```powershell
python tools/analyze_edge_quantization.py exports/edge-quantization-x64 exports/edge-quantization-x86 exports/edge-quantization-analysis.json
```

Next carry the measured resolve and coverage constraints into a controlled
fixed-pixel-stage versus explicit-pixel-stage comparison, including individual
mask controls, before treating any shader compensation as equivalent. The
intermittent fixed-lighting failure is still independent and unresolved;
this scan does not establish its cause. Production rendering and driver
configuration are unchanged. Real PMM acceptance remains NOT_PASSED and DX11
prefix replay remains NOT_RUN.

Final validation: expanded scan, attachment-history and portable-history
CTest checks passed 3/3 on each architecture. Both scan logs confirm
`sRGBWrite=0` at 1x and 8x, with 46800 draws and zero failures. The analyzer
passed Python compilation. These passes verify controlled execution and
repeat stability, not full-scene image equivalence.


## Applying measured resolve to fixed versus explicit pixel stages

The edge/quantization probe now adds packed D3DCOLOR controls using identical
positions and input bytes:

| Path | Vertex processing | Pixel processing |
| --- | --- | --- |
| 6 | XYZRHW fixed | Fixed SELECTARG1 diffuse/alpha |
| 7 | XYZRHW fixed | Explicit COLOR pass-through |
| 8 | Explicit screen-to-clip VS | Explicit COLOR pass-through |

Generated float colors are clamped and rounded once to the same packed bytes
for all three paths. Endpoint bytes are recorded in `comparison.csv`, so
analysis uses the actual affine packed-color planes rather than assuming
the earlier float-input ramps were unchanged. No normals, lights, textures,
blend, depth or stencil are involved. Full masks cover both sample counts;
individual mask controls cover 8x with phase zero. Every draw repeats three
times and compares full images. In addition to prior checks, 1x fixed-versus-
explicit images must match and paths 7/8 must match full images at both sample
counts; those checks fail the probe on mismatch. MSAA fixed-versus-explicit
image differences are recorded as diagnostics, not converted to acceptance.

Both architecture runs execute 74880 draws without repetition or enforced
control failures. All five CSV files, including `comparison.csv`, match
byte-for-byte across x64/x86. Baseline whole images are compared within the
process and saved on repetition failure; these CSV matches alone do not
claim that every cross-architecture image byte was exported and compared.

| Comparison to fixed path 6 | Cases per explicit path | Different whole images | Sum of differing pixels across cases | Max channel delta |
| --- | ---: | ---: | ---: | ---: |
| 1x full mask | 1040 | 0 | 0 | 0 |
| 8x full mask | 1040 | 1040 | 83028 | 2 |
| 8x individual mask | 1040 | 520 | 791524 | 1 |

Paths 7 and 8 have identical results and zero differences in their direct
whole-image check. The stage change, rather than the explicit VS transform,
therefore accounts for the observed image difference in these controls.
Summed counts include repeated locations across distinct cases and must not
be read as unique scene pixels. Full-image differences can exist even when
the selected pixel (31,31) is not covered.

`tools/analyze_resolve_comparison.py` now applies measured controls to the
selected pixel. It verifies that constant-color resolve outputs are unique
for each covered-count/source-byte pair before using the empirical lookup.
It derives affine input colors from the recorded endpoint bytes, and uses
the independently scanned PS conversion thresholds to predict the byte
before resolve. The conversion scan resolution is 1/64 byte; both nearest
scan-point predictions and neighboring scan-point output brackets are
reported. Exact conversion arithmetic is not assumed.

For each path there are 896 selected-axis channel observations at partial
coverage (112 axis/boundary states x eight color phases). All are within the
measured color range:

| Path / location model | Nearest-point prediction mismatches | Outside neighboring-threshold predictions |
| --- | ---: | ---: |
| Fixed / pixel center | 0 | 0 |
| Fixed / lowest-index covered sample bracket lower bound | 338 | 318 |
| Explicit PS / pixel center | 340 | 332 |
| Explicit PS / lowest-index covered sample bracket lower bound | 2 | 0 |

The explicit result applies to both paths 7 and 8. Its two one-level residuals
are the Y boundary at step 44, phases 6 and 7: the nearest scan-point model
predicts 100 while the observed resolved byte is 99. The underlying candidate
color lies between measured conversion inputs, allowing resolved values
`[99,100]`. Thus those two observations are compatible with the finite scan
interval. This does not justify silently reporting exact point prediction:
the residuals and interval ambiguity remain in the analysis JSON.

The data strongly distinguishes the two tested location models: selected
fixed output is compatible with pixel-center interpolation, while explicit
PS output is compatible with coverage-dependent interpolation at the
lowest-index covered sample's bracket lower bound. Nonlinear measured resolve
explains how the pre-resolve color difference becomes a small final-byte
difference. This remains a controlled model comparison, not proof of the
driver's full internal algorithm, original per-sample readback, shader
invocation count, or zero-difference full-scene rendering. The earlier float
ramp's unresolved position ambiguity is not retroactively removed.

Evidence: `exports/edge-resolve-comparison-{x64,x86}` and
`exports/edge-resolve-comparison-analysis.json`. Reproduce with:

```powershell
python tools/analyze_resolve_comparison.py exports/edge-resolve-comparison-x64 exports/edge-resolve-comparison-x86 exports/edge-resolve-comparison-analysis.json
```

Next validate an explicitly pixel-centered analytic ramp as an image control
against fixed rendering, then extend the justified contract to independent
triangles and perspective interpolation. Do not insert a guessed rounding or
centroid compensation into production shaders. The intermittent lighting
repeat failure remains separate and unresolved. Production rendering and
driver configuration are unchanged; real PMM acceptance is NOT_PASSED and
DX11 prefix replay is NOT_RUN.

Final validation: both Release builds succeeded; expanded edge/resolve,
attachment-history and portable-history CTest checks passed 3/3 per
architecture. Python analysis compilation and whitespace checks passed.
These successes do not pass MSAA image-equivalence acceptance.


## Scoped pixel-center correction control (GPU execution blocked)

Path 9 now computes the packed-input affine color plane from PS VPOS at the
pixel center. It uses the same geometry and actual clamped/rounded endpoint
bytes as paths 6-8, including full and individual masks. Only the generated
axis-aligned, unit-RHW rectangle is supported by this analytic control; it is
not a general material shader or a perspective-correct triangle replacement.
The existing fixed and explicit paths and their enforcement checks remain.
Path 9 comparisons are diagnostic and do not fail on image differences;
repeat stability continues to be enforced. No production shader, shared RHI
contract, resource workflow, driver setting, or application path is changed.

Both builds succeeded before the final diagnostic-gate adjustment. Manual
runs on x64 and x86 returned 77 because CreateDevice failed with
`0x8876086C` (D3DERR_INVALIDCALL), before any draw. Evidence is preserved in
`exports/pixel-center-control-{x64,x86}/scan.log`. This does not identify a
specific desktop, RDP or driver cause. CTest confirmed the graphics probe was
SKIPPED on both architectures, while portable history passed. A CTest zero
exit in this situation must not be reported as graphics acceptance. Path 9
pixel equivalence is NOT_RUN and its correction is not enabled in the app.


## Pixel-center control after restored GPU environment

The restored environment allowed both manual x64/x86 runs of path 9 to
complete: 84240 draws each, no repeat, constant uniformity or enforced control
failures. Both logs read back `sRGBWrite=0`, with 8x quality 0. All five CSV
files match byte-for-byte between architectures. Previous unavailable logs
are a historical observation; successful new logs are in
`exports/pixel-center-control-{x64,x86}`.

The analytic pixel-center control substantially improves equivalence, but
**does not pass the image gate**:

| Path 9 versus fixed | Cases | Different images | Sum of differing pixels | Maximum channel delta |
| --- | ---: | ---: | ---: | ---: |
| 1x full mask | 1040 | 304 | 38304 | 1 |
| 8x full mask | 1040 | 304 | 38616 | 2 |
| 8x individual masks | 1040 | 0 | 0 | 0 |

For comparison, original explicit pass-through has 1040 differing 8x
full-mask images with 83028 summed differing pixels, and 520 differing
individual-mask images with 791524 summed differing pixels. Each of these
counts sums distinct cases, not unique scene pixels. All direct fixed-VS /
explicit-VS pixel-stage control image checks still match.

The 304 failing full-mask case classifications are identical at 1x and 8x;
the analytic center calculation therefore introduces a precision discrepancy
that is observable without MSAA. This is compatible with affine-expression /
interpolation precision near output thresholds, but does not yet isolate the
responsible arithmetic operation. Exact individual-mask agreement also does
not prove raw per-sample equality: nonlinear resolve and byte quantization
can conceal smaller differences. No production shader correction is enabled.

`tools/analyze_resolve_comparison.py` now includes path 9 image counts and
1x/8x failing-case classification in its JSON. Evidence:
`exports/pixel-center-control-analysis.json`. The measured-resolve model for
paths 6-8 remains intact, with two nearest-scan-point residuals contained by
conversion brackets. Those interval predictions are not exact image matches.

Next isolate the analytic color-plane precision discrepancy first at 1x,
exporting failing control images and using output-threshold controls, then repeat 8x
full-mask comparisons. This order avoids attributing a single-sample
calculation discrepancy to sample selection or changing unrelated renderer
behavior. Real PMM acceptance remains NOT_PASSED; the intermittent lighting
repeat issue remains unresolved and separate.

Final validation: x64/x86 graphics probes ran successfully rather than
skipping. Expanded edge/quantization, attachment-history and portable-history
CTest checks passed 3/3 on each architecture. The control precision residual
remains diagnostic, so CTest success is not an image-equivalence pass.


## Single-sample center-color precision localization and 8x recheck

The diagnostic now exports fixed/analytic failing images for phase 4, step 0
at 1x and logs the first differing pixel. Paths 10/11 add two arithmetic
controls beside path 9: normalized origins/slopes before evaluating the
plane, and separated multiply/add with shader optimization disabled.
All use the same packed endpoints and VPOS center. No production code changed.

At axis X, pixel (0,28), fixed BGRA is `[64,113,2,255]` while every analytic
variant gives `[64,114,2,255]`. Axis Y gives the transposed counterpart at
(28,0): `[64,2,113,255]` versus `[64,2,114,255]`. The relevant plane is
0-to-255 over 64 pixels: ideal center value is `28.5*255/64=113.5546875`.
A direct PS constant set to `113.5546875/255` outputs 114 at both 1x and 8x.
Thus it agrees with the analytic evaluation, while native interpolated color
outputs 113. This narrows the discrepancy to the interpolated-color path or
its input/intermediate precision, rather than showing an arithmetic-order
fix. It does not prove a specific interpolator bit width or rounding mode.

The added base-113 constant scan gives 113 at steps 32-35/64 and 114 at
36/64. The exact-value control sits between those scan points and outputs
114, illustrating why scan brackets cannot be collapsed to a precise
threshold. Precision changes between constant, arithmetic and interpolated
paths still need careful treatment; a universal byte compensation is not
justified.

Paths 9/10/11 have identical image mismatch counts:

| Sample/mask mode | Cases per path | Different images | Sum differing pixels | Max channel delta |
| --- | ---: | ---: | ---: | ---: |
| 1x full | 1040 | 304 | 38304 | 1 |
| 8x full | 1040 | 304 | 38616 | 2 |
| 8x individual | 1040 | 0 | 0 | 0 |

All 1x failures are in phases 4-7 (76 cases each), and their failing case
classification matches 8x. This supports keeping the precision discrepancy
separate from coverage-location correction. Individual-mask equality is
resolved-image equality only. Raw original samples were not captured.

Evidence: `exports/center-precision-{x64,x86}`, failing BGRA pairs, and
`exports/center-precision-analysis.json`. Five CSVs match between architectures.
The final exact-constant control and full regression logs are also available
in `build-{x64,x86}/build/edge-quantization/scan.log`. Final tests execute
104136 draws per architecture with zero repeated-image/enforced-control
failures. Both Release builds and all three selected CTests per architecture
(edge/quantization, attachment history, portable history) passed. Analytic
image differences remain diagnostic; CTest passing does not waive them.

Next measure interpolated color at greater precision, if the format/device
supports it, or sweep native interpolation around this threshold to constrain
its precision independently of 8-bit output. A speculative global rounding
adjustment would alter already-matching colors and is not enabled. Real PMM
acceptance remains NOT_PASSED; the occasional lighting repeat mismatch is
still a separate unresolved issue.


## Float target interpolation and adjacent-ULP conversion control

`--float-interpolation` / CTest `rhi_d3d9_float_interpolation` checks the
adapter's display format before querying render-target support. A8R8G8B8,
A16B16G16R16F and A32B32G32R32F are all supported on the tested TITAN Xp.
An initial query incorrectly used A8R8G8B8 as AdapterFormat and reported
NOTAVAILABLE even for the byte target; querying the actual display format
X8R8G8B8 corrected the probe. This was a diagnostic query error, not evidence
that the device lacked float support.

The probe uses the same packed failing rectangle/endpoints at unit RHW and
single sampling. It directly calls GetRenderTargetData on same-format
surfaces, without StretchRect or MSAA resolve. Paths 0/1/2 are fixed pixel,
fixed VS plus pass-through PS, and explicit VS plus pass-through PS. Path 3
is analytic VPOS; path 4 is a direct 113.5546875/255 constant; paths 5/6 are
that constant decreased/increased by one float32 ULP via nextafter. Each
format/axis/path repeats ten times (42 cases, 420 draws). Raw 64x64 images
are saved. Float channel order is RGBA; the byte format is BGRA.

At the first failing channel (G at (0,28), R at (28,0)):

| Path | A32 float value | Value in byte units | A16 value in byte units | A8 byte |
| --- | ---: | ---: | ---: | ---: |
| Interpolated, paths 0-2 | 0.4453124701976776 | 113.55467990040779 | 113.492431640625 | 113 |
| Analytic VPOS | 0.4453125298023224 | 113.55469509959221 | 113.5546875 | 114 |
| Exact constant | 0.4453125 | 113.5546875 | 113.5546875 | 114 |
| Constant one ULP below | 0.4453124701976776 | 113.55467990040779 | 113.492431640625 | 113 |
| Constant one ULP above | 0.4453125298023224 | 113.55469509959221 | 113.5546875 | 114 |

Paths 0-2 agree at the observed pixels across targets. Interpolation and
analytic evaluation differ by two float32 ULPs, or approximately 0.0000152
byte levels. The direct adjacent-ULP constants reproduce the same A16 and A8
split, independently of interpolation. Therefore a pre-output floating-point
discrepancy is present, and the target conversion boundary amplifies it into
a whole byte difference. This is stronger localization than the earlier
8-bit-only observation; it does not identify a particular hardware instruction
or prove the entire interpolation unit's precision. Changing target format
can itself affect internal processing, so the A32 capture must not be treated
as a literal read of the A8 pipeline's hidden intermediate. Likewise, this
local conversion boundary does not define a universal rounding rule.

All 42 raw baseline images match between x64/x86. Both manual runs and
float-interpolation, attachment-history, portable-history CTests passed 3/3
per architecture, with zero repeat mismatches. No MSAA was used in the float
probe. Evidence: `exports/float-interpolation-{x64,x86}` and
`exports/float-interpolation-analysis.json`. Reproduce decoding with:

```powershell
python tools/analyze_float_interpolation.py exports/float-interpolation-x64 exports/float-interpolation-x86 exports/float-interpolation-analysis.json
```

Next constrain native affine interpolation arithmetic on more pixels and
slopes, preserving matched controls, before implementing any local shader
correction. An unconditional bias could fix this pixel while damaging
already-matching colors. Production rendering remains unchanged; real PMM
8x acceptance is NOT_PASSED and the intermittent repetition issue remains
separate.


## Expanded native interpolation sweep: no universal color bias

`--float-sweep` and CTest `rhi_d3d9_float_sweep` extend the float probe across
square spans 32,48,64,63.75 pixels, and four packed RGB endpoint palettes:
constant 64, increasing 0-to-255, decreasing 255-to-0, and narrow 63-to-65.
Blue remains 64 and alpha 255. Unit RHW and axis-aligned rectangles keep
coverage/perspective outside the precision hypothesis. Paths are fixed,
fixed VS plus explicit pass-through, explicit VS plus pass-through, and
analytic VPOS with endpoint origins/slopes. The prior failing-pixel probe
remains available. The sweep's legacy axis loop produces duplicate square
inputs; the two labels are controls, not independent geometry samples.

Each case is rendered to all three supported formats and repeated ten times:
384 baseline images / 3840 draws per architecture. Both manual runs completed
without repeat failures, and all 384 raw images matched byte-for-byte across
architectures. The analyzer samples interior pixels at least two pixels from
edges and compares RGB channels without any resolve. There are 58806
channel observations per palette/format/path after including both axis labels.

For analytic minus fixed A32 output:

| Palette | Positive differences | Negative differences | Equal channels | Maximum difference in byte units |
| --- | ---: | ---: | ---: | ---: |
| Constant | 0 | 0 | 58806 | 0 |
| Increasing | 36554 | 598 | 21654 | 0.00004560 |
| Decreasing | 29266 | 4022 | 25518 | 0.00004560 |
| Narrow | 33598 | 0 | 25208 | 0.00001520 |

Both ordinary pass-through paths agree with fixed output over all interior
channels in all formats. Analytic versus fixed byte output differs in 182
sampled interior channel observations. Constant-color analytic controls
remain exact. Error changes with slope, position and geometry, and can have
either sign even within increasing/decreasing palettes. Consequently the
single failing pixel's downward native discrepancy does not support a
universal negative bias or unconditional nextafter adjustment. Such a change
could damage already-matching controls.

The expanded C++ diagnostic subsequently added strict whole-image controls
for pass-through equivalence and constant-palette analytic equivalence.
Both final builds succeeded. However the final CTest run encountered
CreateDevice `0x8876086C`: float sweep, original float probe and attachment
history were SKIPPED on both architectures; portable history passed. This
means the successful manual measurement precedes the final control-gate
addition, and the added gates have not executed successfully on GPU in this
turn. Do not report the final CTest exit zero as graphics acceptance. Earlier
manual raw images were preserved under `exports/float-sweep-{x64,x86}`.

Evidence / repeatable analysis:

```powershell
python tools/analyze_float_sweep.py exports/float-sweep-x64 exports/float-sweep-x86 exports/float-sweep-analysis.json
```

The JSON includes signed ULP histograms, first mismatching coordinates and
interior precision comparisons. Changing target format can alter internal
arithmetic, so the float target observations constrain a model rather than
expose every hidden intermediate of the byte target. Next test specific
native affine-arithmetic candidates against these saved A32 values, keeping
constant and pass-through controls; enable no renderer correction until
those candidates survive the matched-input comparisons. Real PMM 8x
acceptance remains NOT_PASSED and the intermittent lighting issue remains
independent.


## Offline tests of explicit affine arithmetic models

`tools/fit_native_interpolation.py` now evaluates 17 parameter-free arithmetic
candidates against saved A32 fixed outputs. It rounds explicitly to float32
after named operations. Candidates cover division versus float32 reciprocal
multiplication for endpoint decoding, slope versus weight evaluation,
separate multiply/add versus single-round multiply/add, barycentric
one-dimensional weighting, byte-domain planes and coordinate-space intercepts.
The single-round multiply/add uses binary64 before final float32 rounding;
this is sufficient for these bounded inputs and is not a general-purpose
IEEE FMA implementation. No per-pixel parameters or compensating biases are
fitted. Float target format 116, interior R/G only, is the comparison scope.

Each candidate is checked on 156816 channel observations across the saved
spans/palettes and duplicate axis controls. The leading candidates are:

| Candidate | Exact channels | Total channels | Maximum absolute ULP residual |
| --- | ---: | ---: | ---: |
| Ideal affine result rounded once | 114142 | 156816 | 15 |
| Byte-domain separate plane, then divide by 255 | 113066 | 156816 | 15 |
| Decoded endpoints, float32 weight, separate multiply/add | 106510 | 156816 | 20 |
| Decoded endpoints, weight, single-round multiply/add | 106212 | 156816 | 20 |
| Decoded endpoints, slope, separate multiply/add | 103456 | 156816 | 32 |

**None is universally exact.** The leading model matches 72.79% of the
observations; that percentage includes constant controls and duplicated axis
inputs, so it must not be presented as independent scene coverage. Constant
palettes match the leading candidate exactly. The 32/64 spans with 0-to-255
or 255-to-0 ramps also match its ideal result exactly, while spans 48/63.75
and narrow-color ramps retain errors. Ranking does not justify selecting the
best-scoring candidate as an equivalent rendering implementation.

A separate check groups native R by the same X while varying Y, and native G
by the same Y while varying X. Seven span/palette/channel groups show changes
in the perpendicular coordinate; maximum spread is **16 ULP**. For example,
span 48's increasing R ramp varies at 43 of 44 tested X positions as Y
changes. At X=2 the recorded native float bits range from 1029002580 to
1029002596. Such variation cannot be generated by any strictly one-dimensional
function of X alone. Native triangle setup / two-dimensional interpolation
and evaluation must therefore be included in the next model family; the
specific internal operation or precision is not yet identified. Varying Y
also crosses the shared triangle boundary, so triangle identity is a
necessary independent control rather than something to average away.

Evidence: `exports/native-interpolation-model-{x64,x86}.{json,log}`.
The two JSON reports are identical. They contain signed ULP histograms,
per-span/palette statistics, first mismatch coordinates, and perpendicular
coordinate spread. The original raw images remain unchanged; this turn did
not require live GPU execution or alter rendering code. Python compilation
and CMake whitespace checks passed.

```powershell
python tools/fit_native_interpolation.py exports/float-sweep-x64 exports/native-interpolation-model-x64.json
```

Next test two-dimensional triangle-plane/barycentric candidates and separate
pixels by triangle ownership; then validate on independently captured
single triangles when GPU access is available. No universal bias, guessed
rounding correction or production shader substitution is enabled. Real PMM
8x acceptance remains NOT_PASSED and the intermittent repeat mismatch is
still separate.


## Triangle ownership and two-dimensional arithmetic candidates

`tools/fit_triangle_interpolation.py` partitions the saved A32 square images
using the shared line `x+y+1=span`. Strictly smaller sums belong to triangle
0; strictly larger sums belong to triangle 1. Exact shared-line pixels are
excluded, so no top-left rasterization tie rule is inferred. Only axis label
0 is read, eliminating the duplicated axis controls. Samples remain at least
two pixels inside the square boundary. Across palettes/spans, there are
19456 triangle-0 pixels and 19220 triangle-1 pixels; 528 shared-line pixels
are excluded. R/G give 77352 channel observations.

The new candidates use each triangle's actual vertex order/endpoints:
float32 determinant-based weights, independently evaluated edge areas,
reconstructed weights, anchor-relative interpolation, left/right summation,
single-round summation, and gradient-plane setup with anchor-relative or
global intercept evaluation. Division and reciprocal endpoint decoding are
separate. These are 24 parameter-free two-dimensional candidates plus an
ideal-affine single-round baseline. No per-triangle or per-pixel coefficients
are fitted to output data.

None matches all observations. Rankings on the same partitioned samples:

| Model | Exact channels / 77352 | Max ULP residual |
| --- | ---: | ---: |
| Ideal affine single-round baseline | 56252 | 15 |
| Decoded endpoint global plane, separate operations | 51200 | 32 |
| Decoded endpoint anchor interpolation, separate operations | 50255 | 32 |
| Decoded endpoint anchor interpolation, single round | 50046 | 24 |

The ideal baseline matches 29248/38912 triangle-0 channels and 27004/38440
triangle-1 channels. For span 48's increasing palette it matches 0/1892
triangle-0 channels (max 2 ULP) versus 584/1892 triangle-1 channels (max 7 ULP).
This records distinct triangle residuals without choosing one as correct.
Fused/single-round candidates again use bounded binary64 evaluation before
float32 rounding, not a general FMA emulator.

**The earlier perpendicular-coordinate variation is entirely absent within
each triangle in these data.** Grouping native R by X and G by Y separately
inside triangle 0/1 gives zero varying groups, zero ULP spread. The previously
observed 16-ULP range across a full square therefore reflects crossing the
shared triangle boundary in these inputs, rather than demonstrating
perpendicular-position dependence inside an individual triangle. This
refines the previous interpretation: triangle-specific setup/evaluation
precision is relevant, but a generic two-dimensional pixel perturbation is
not established. Independent single-triangle captures and changed vertex
orders are needed to distinguish triangle setup from evaluation behavior.

Evidence: `exports/triangle-interpolation-model-{x64,x86}.{json,log}`; the two
JSON reports are identical. Per-model triangle/span/palette statistics and
first mismatch coordinates are retained. Endpoint sanity checks for the
anchor/plane formulas and Python compilation passed. No GPU calls or renderer
changes were made during this offline analysis.

```powershell
python tools/fit_triangle_interpolation.py exports/float-sweep-x64 exports/triangle-interpolation-model-x64.json
```

Next independently draw each triangle and permute its vertex order at the
same positions/colors, then compare A32 output and ordinary byte output.
This provides evidence for a specific triangle-setup hypothesis before any
correction is introduced. No candidate model has earned image-equivalence
acceptance. Production rendering remains unchanged, real PMM 8x acceptance
is NOT_PASSED, and the intermittent repeat mismatch remains separate.


## Independent triangles and vertex-order permutations

`--triangle-orders` / CTest `rhi_d3d9_triangle_orders` now extend the float
probe with paired drawing and independently drawn triangles. For each of the
four spans and four endpoint palettes, order case 0 draws both original
triangles. Cases 1-6 draw triangle 0, and cases 7-12 draw triangle 1; each
uses permutations `[0,1,2]`, `[1,2,0]`, `[2,0,1]`, `[0,2,1]`, `[2,1,0]`,
`[1,0,2]`. Each vertex carries its unchanged position and packed color.
Backface culling remains disabled. Three target formats and four pixel/vertex
paths are captured, at single sampling. Only one axis label is used.

There are 2496 baseline images and 24960 draws per architecture, with ten
repetitions per case. Both x64/x86 manual runs completed successfully with
zero repetition or existing constant/pass-through control failures. The
384-image sweep and original precision probe remain separate modes.

`tools/analyze_triangle_orders.py` compares each order against its triangle's
original order, and independently drawn interior pixels against the paired
baseline. It excludes shared-line pixels from interior color comparisons,
but checks the whole coverage mask for order changes. Across all three
formats and all four paths:

- No vertex permutation changes any compared interior color.
- No vertex permutation changes the coverage mask.
- Independently drawn triangles match their paired-draw interior output.
- All 2496 raw baseline images match byte-for-byte across architectures.

Thus the earlier native precision differences between triangle 0/1 are not
caused by these vertex permutations or by issuing both primitives in one
DrawPrimitiveUP call. These observations do not exclude all internal setup
canonicalization, indexed rendering differences, perspective dependence or
other drivers. The two native triangles have different geometry/vertex
color-plane representations, so their geometric setup remains a relevant
hypothesis. The analytic VPOS path is likewise invariant to these changes;
its known native-color mismatch is not eliminated by reordering vertices.

Evidence: `exports/triangle-orders-{x64,x86}`, `float.log`, raw images and
`exports/triangle-orders-analysis.json`. Reproduce with:

```powershell
python tools/analyze_triangle_orders.py exports/triangle-orders-x64 exports/triangle-orders-x86 exports/triangle-orders-analysis.json
```

Both final builds succeeded and Python compilation passed. A later x64
original float-probe CTest was SKIPPED after CreateDevice returned
`0x8876086C`; portable history passed on both architectures. The successful
full manual triangle-order captures are retained, while that skipped
regression is not described as a GPU pass. The new triangle-order CTest is
registered; the complete manual executions exercised the same entry point.

Next hold the affine color plane fixed while changing the triangulation
(diagonal and triangle aspect), to constrain geometry-dependent coefficient
setup. A vertex-order or batch workaround is not supported by these data.
Production rendering remains unchanged, real PMM 8x acceptance is NOT_PASSED,
and the occasional lighting repeat failure remains separate.


## Equal-color-plane geometry controls (execution unavailable)

`--geometry-planes` / CTest `rhi_d3d9_geometry_planes` now add four geometry
cases to the float probe: full square with the original descending diagonal,
full square with the other diagonal, half-height rectangle with the original
diagonal, and half-height rectangle with the other diagonal. Four spans,
four palettes, three formats and four paths produce 768 baseline cases,
repeated ten times if the GPU execution completes. Unit RHW, packed bytes,
single sampling and disabled culling remain explicit. No production changes.

The geometry-only palette uses constant 64, 0-to-254, 254-to-0 and 63-to-65.
The even endpoint differences ensure half-height endpoints are exact integer
midpoints. Colors are evaluated from the original full-span affine plane,
not rescaled to the shorter rectangle. Thus the slope and intercept remain
unchanged when height changes. Using 255 would require rounding a half-height
127.5 endpoint and would confound geometry with input-color quantization;
the geometry control deliberately avoids that. Exact rational CPU checks
confirmed all sixteen span/palette planes remain identical after shortening.
Switching diagonals uses the same four corner positions/colors.

`tools/analyze_geometry_planes.py` is ready to compare the two diagonals for
each aspect ratio and the two aspect ratios for each diagonal. It uses the
common interior, excludes both involved diagonal lines, and records first
mismatches, maximum ULP/byte differences and cross-architecture image
comparisons. It rejects an incomplete capture instead of generating a
comparison from missing images.

Both initial code builds succeeded, but manual x64/x86 execution returned 77
at CreateDevice `0x8876086C`. No new baseline images were generated. Evidence:
`exports/geometry-planes-{x64,x86}/float.log`. This is an unavailable GPU
execution, not a geometry-equivalence result. Python compilation and exact
plane checks pass. The prior successful vertex-order captures remain intact.
The cause of the changing device availability is not established here.

```powershell
build-x64/build/Release/rhi_d3d9_msaa_history_test.exe exports/geometry-planes-x64 --geometry-planes
build-x86/build/Release/rhi_d3d9_msaa_history_test.exe exports/geometry-planes-x86 --geometry-planes
python tools/analyze_geometry_planes.py exports/geometry-planes-x64 exports/geometry-planes-x86 exports/geometry-planes-analysis.json
```

The immediate next action is to execute these prepared controls once device
creation succeeds, then judge geometry-dependent setup from measured A32
outputs. No correction is enabled before that comparison. Real PMM 8x
acceptance remains NOT_PASSED and this geometry comparison is NOT_RUN.

Final validation: both Release builds and CTest registration completed.
Geometry CTest was SKIPPED on both architectures after the same device
creation failure; portable history passed on each. No geometry image
comparison has been performed.


## Geometry validation retry: device gate failed before drawing

The requested device-stability gate was rerun on both architectures using
`--creation-matrix`: thirty attempts each (ten parameter variants repeated
three times). All sixty failed with `0x8876086C`; each matrix reports
`attempts=30 failures=30`. This includes the minimal 64x64 single-sample
variant, not only MSAA or full-screen-sized buffers. The geometry probe was
then explicitly retried and returned 77 on both architectures before any
draw. Logs are preserved in `exports/geometry-device-check-{x64,x86}` and
`exports/geometry-recheck-{x64,x86}`. No new geometry images exist, so neither
geometry-dependent setup nor geometry-independent evaluation can be selected
as the next evidence-backed branch.

Read-only session inspection showed RDP session 2 Active, and the executing
PowerShell process in session 2. An active RDP connection is therefore not
sufficient to establish DX9 device availability on this setup; this inspection
does not establish the particular desktop/driver cause. No driver, desktop,
session, rendering parameters or application path were changed. No additional
interpolation models were introduced. The prepared geometry/analysis entry
points remain ready; graphics acceptance is blocked at device creation.


## Geometry controls after restored device availability

Device checks now succeeded continuously: both architectures completed all
thirty `--creation-matrix` attempts with zero failures. Evidence is preserved
in `exports/geometry-device-restored-{x64,x86}`. The prepared geometry probe
then completed on both architectures with zero repeat or enforced-control
failures, capturing 768 baseline images / 7680 draws per architecture. All
768 raw images match byte-for-byte across architectures. These successful
captures supersede the unavailable status for this execution, while earlier
failure evidence remains historical.

The common-interior geometry analysis finds:

| Path | A8 differing geometry cases / 64 | A16 differing cases / 64 | A32 differing cases / 64 | Max A32 ULP |
| --- | ---: | ---: | ---: | ---: |
| Fixed | 0 | 0 | 29 | 16 |
| Fixed VS + explicit pass-through PS | 0 | 0 | 29 | 16 |
| Explicit VS + pass-through PS | 0 | 0 | 29 | 16 |
| Analytic VPOS plane | 0 | 0 | 0 | 0 |

For native A32, full-square diagonal changes differ in 8/16 span/palette
cases, half-height diagonal changes in 8/16, shortening with original
diagonal in 9/16, and shortening with alternate diagonal in 4/16. Maximum
normalized difference is approximately 1.51991844e-5 byte levels; ULP size
varies with the channel magnitude, so this maximum and the 16-ULP maximum
need not refer to the same pixel. Constant and pass-through controls remain
valid. All comparisons exclude both relevant diagonal lines.

The equal affine plane therefore produces geometry-dependent native float
outputs, while the analytic plane remains geometry-invariant in the tested
common interior. This supports prioritizing triangle-geometry-dependent
coefficient setup/evaluation, rather than a geometry-independent output
bias. It does not isolate setup from evaluation or reveal exact hardware
precision. Unlike previous threshold-sensitive tests, none of these geometry
perturbations changes the captured A8/A16 images. The measured A32 differences
must not be claimed to explain all earlier byte or MSAA residuals.

Evidence: `exports/geometry-planes-{x64,x86}`, `float.log`, raw images and
`exports/geometry-planes-analysis.json`. No new interpolation candidates or
production changes were introduced. Next constrain coefficient setup against
these changed-diagonal/aspect outputs, retaining the analytic invariant and
constant-color controls. Real PMM 8x acceptance remains NOT_PASSED; the
occasional lighting repeat issue remains independent.

Final regression: geometry planes, original float interpolation and portable
history CTests ran and passed 3/3 on both architectures, without skips.
This verifies diagnostic stability and existing controls, not full-scene
image equivalence.


## Coefficient establishment versus evaluation: held-out coordinate checks

`tools/fit_geometry_coefficients.py` analyzes saved geometry A32 images,
partitioned by diagonal ownership and excluding shared-edge pixels. It uses
one axis label, native fixed path, R/G only. All 256 span/palette/geometry/
triangle/channel planes have zero perpendicular-coordinate spread: within
a triangle, native R depends only on X and native G only on Y in these inputs.
This justifies testing one-dimensional effective coefficients per triangle
for this restricted family, without assuming general perspective behavior.

One in every three coordinate positions trains an affine slope/intercept
via binary64 least squares. The other coordinate positions are held out.
Only the first value at each coordinate is used after verifying perpendicular
invariance; the reported scores do not count repeated pixel values as
independent samples. These are **data-fitted descriptive coefficients**, not
parameter-free native arithmetic models or recovered hardware coefficients.

| Evaluation from inferred coefficients | Held-out exact / 6740 | Maximum ULP | Entirely exact planes / 256 |
| --- | ---: | ---: | ---: |
| Binary64 coefficients, one final float32 round | 6293 | 2 | 83 |
| Float32 coefficients, one final float32 round | 5622 | 11 | 104 |
| Float32 coefficients, separate multiply/add | 5067 | 9 | 80 |

Changing the training coordinate phase gives 6366/6832 exact with max 3 ULP
and 6365/6908 exact with max 3 ULP for the binary64-coefficient model.
The first model's stable 92-93% scores therefore do not depend on one chosen
split, but none is exact on all held-out coordinates. Coefficient rounding
can increase maximum error even where it improves the number of individually
exact planes; there is no single universally superior evaluation model.

The inferred slope deviations from the ideal input plane are small but
geometry-dependent: maximum magnitude about 6.21e-7 byte units per pixel.
Inferred intercept deviations reach about 2.60e-5 byte units for decreasing
ramps. These estimates include output quantization and fitting uncertainty.
For span 48/increasing R, changing diagonal exchanges triangle-specific
coefficient patterns; shortening height changes those patterns again. This
is compatible with geometry-dependent setup, while remaining residuals leave
native evaluation/quantization precision unresolved. Constant-color slope
estimates are exactly zero; their intercept deviation is the expected float
representation difference from ideal byte/255, not geometry corruption.

The two architecture reports are identical for the initial split. Evidence:
`exports/geometry-coefficients-{x64,x86}.json` and
`exports/geometry-coefficients-phase{1,2}.json`. This analysis uses saved data
only; no GPU availability claim, new render path or global bias is introduced.
Python compilation and whitespace checks pass.

```powershell
python tools/fit_geometry_coefficients.py exports/geometry-planes-x64 exports/geometry-coefficients-x64.json
python tools/fit_geometry_coefficients.py exports/geometry-planes-x64 exports/geometry-coefficients-phase1.json --train-phase 1
```

Next constrain specific coefficient representation and block/tile evaluation
hypotheses, retaining held-out coordinates and independent captures. Directly
uploading the fitted coefficients as a shader fix is not justified by these
scores. Real PMM 8x image acceptance remains NOT_PASSED; the intermittent
lighting repeat issue remains independent.


## Finite coefficients, block origins and targeted independent recapture

`tools/test_block_interpolation.py` evaluates 26 candidates on held-out
coordinates from the coefficient training split: direct binary64 evaluation,
coefficient mantissas rounded to 16/20/24/28/32 significant binary bits, and
float32 accumulated evaluation in blocks of 1/2/4/8/16 pixels with origins
0/1 and binary64 versus float32 block-start calculation. Coefficients remain
training-data estimates; this does not claim parameter-free hardware recovery.
Block size 1 has no accumulation and duplicates direct rounding by design.
Model family and offsets are explicit, bounded hypotheses, not an exhaustive
search over arbitrary per-pixel adjustments.

Best held-out scores out of 6740 coordinate observations:

| Candidate | Exact | Max ULP |
| --- | ---: | ---: |
| 32-significant-bit coefficients, direct | 6301 | 2 |
| Binary64 direct | 6293 | 2 |
| 28-significant-bit coefficients, direct | 6262 | 2 |
| Block 2 / origin 0 / binary64 block start | 6076 | 2 |
| Block 2 / origin 1 / binary64 block start | 5995 | 2 |
| 24-significant-bit coefficients, direct | 5622 | 11 |

No universally exact candidate exists. This dataset does not establish a
particular block size or fixed coefficient representation. Selecting the
highest score after comparing candidates is model selection, not proof of
that model's arithmetic or precision.

Before new GPU capture, the script recorded 32 held-out coordinates where
at least five distinct predictions occur. Selection is deterministic and
limited to the first qualifying records: five geometry/palette inputs at
span 32, so these points are not representative coverage of every span.
Frozen predictions are in `exports/block-interpolation-models.json`.
`--geometry-targeted` reads `capture_targets.txt` in its output directory
and captures only requested geometry/span/palette inputs through the same
existing probe; all formats and four paths are retained with ten repetitions.
It refuses an empty target list.

Both x64/x86 targeted runs succeeded: 60 raw images / 600 draws each, no
repeat or control failures. All 60 images match across architectures, and
all 32 selected channel values match the saved capture exactly on both.
The leading coefficient32 and binary64 candidates match only 16/32 selected
values. Thus recapture confirms the stable discriminating residuals; it does
not supply a model that warrants correction. This is a new execution of the
same selected geometry, not an independent geometry-generalization test.
The analyzer fails if selected images are missing or values change, keeping
capture completeness separate from candidate matching.

Evidence: `exports/block-targeted-{x64,x86}`, target lists, raw images,
`exports/block-targeted-validation-{x64,x86}.json`, plus the frozen model file.
Reproduce offline verification with:

```powershell
python tools/test_block_interpolation.py exports/geometry-planes-x64 exports/geometry-coefficients-x64.json exports/block-targeted-validation-x64.json --capture exports/block-targeted-x64
```

Both builds succeeded. Original float interpolation and portable history
CTest checks ran and passed 2/2 per architecture. Python compilation and
CMake whitespace checks pass. Targeted runs exercised existing constant and
pass-through whole-image gates; candidate mismatch is diagnostic, not waived.

**Decision under the requested fallback:** retain native interpolation for
application rendering. Analytic formulas and fitted coefficients stay in
tools/tests; no global bias or speculative shader compensation is enabled.
Full 8x image equivalence remains unpassed. Further interpolation research
is isolated from portable RHI progress. The next migration review should
focus on resource/device lifecycle and explicit backend capability boundaries
using established inputs, without claiming DX11 fixed-function pixel parity
or enabling its material path based on these fits. The occasional lighting
repeat issue remains a separate open diagnostic.
