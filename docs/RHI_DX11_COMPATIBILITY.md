# Opt-in DX11 DX9 arithmetic compatibility

The DX11 backend now exposes the measured arithmetic as an explicit creation
option. `Default` remains the default; Windows application rendering remains
DX9. The new mode is an implementation contract whose image equivalence has
been measured on the NVIDIA TITAN Xp, not a guarantee for other drivers.

```cpp
D3D11ModelOptions options{D3D11ModelCompatibility::Dx9Measured};
auto bundle = CreateD3D11Device(description, D3D11Driver::Hardware, options);
if (!bundle) {
    // Inspect stage, creationError, creationReason and modelSupport.
}
auto support = QueryD3D11ModelSupport(*bundle.device,
                                    D3D11ModelCompatibility::Dx9Measured);
```

## Policy, capability and shader boundary

The mode combines the previously verified rules:

- CPU world/view/projection combination with sequential float32 product and
  addition rounding;
- clip X/Y/Z/W dot products with product-plus-accumulator rounding after each
  step, emulated using shader doubles;
- normal coefficients from rounded world/view, and the measured normal dot
  rule; existing native normalization and light direction expressions remain;
- the measured diffuse/ambient lighting operation order;
- pixel-center adjustment through a DX11 viewport shift of `(0.5,0.5)`, retaining
  original XY through native clipping;
- final Modulate/specular single rounding and lighting/specular-conditioned
  cascade saturation, independently checked in
  [final cascade controls](RHI_FINAL_MODULATE_COMPATIBILITY.md).

`src/render/shaders/model_dx9_compatibility.hlsl` defines the optional arithmetic
helpers. `model_material_vertex.hlsl` selects the branches only when the mode's
compiler define is enabled. The ordinary model and vertex-color layouts both
use the same option. The shared pixel shader selects its measured branch with
the same creation option; Default retains the original cascade formula.
Material input layout and owned geometry remain unchanged. The legacy diagnostic backend remains separately available
for comparison; production code has no dependency on test shader builders.

Creation queries `D3D11_FEATURE_DOUBLES`. A request without double shader
operations fails at `D3D11CreationStage::Compatibility`, with
`DXGI_ERROR_UNSUPPORTED` and `creationReason=shader_doubles_required`. Invalid
mode identifiers return `E_INVALIDARG` and `invalid_model_compatibility`.
`CheckD3D11ModelCompatibility` independently tests the unsupported capability
decision without pretending the current GPU lacks a feature. Default mode can
still be selected on a device without doubles. There is no silent precision
fallback. The backend's existing single-sample RGBA8/D24S8 and swapchain
restrictions remain in force; model shader variants are compiled lazily.

The option is immutable for a device. Swapchain/offscreen resizing retains it;
whole-device replacement explicitly supplies the option to the new factory.
Submission identity/epoch and resource handles continue to enforce the existing
device lifecycle contract.

## Real scene and resource restoration

`--dx11-compatibility-lifecycle` consumes the prior owned real PMM captures,
containing 51 draws, 195 events and 143 immutable resource versions (42 textures).
It uses the regular RHI backend, not the diagnostic adapter copy.

For each of two devices, five target sizes alternate the original extent with
larger backing targets; the captured viewport stays unchanged. The 52 original
application boundaries are checked after every rebuild. Each draw first rejects
the old epoch's submission, then submits current device/epoch commands. Handles
stay identical during resizing; all GPU uploads are retained. The second device
has a different identity and uploads from the same CPU-owned immutable bytes.
Three additional complete draws after each target rebuild must match the actual
captured final image.

| Input archive / executable | Boundaries | Old submissions rejected | Uploads across two devices | Differing pixels |
| --- | ---: | ---: | ---: | ---: |
| x64 viewport `(565,25,1032,774)` / x64 | 520 | 13260 | 286 | 0 |
| Same x64 archive / x86 | 520 | 13260 | 286 | 0 |
| Original x86 viewport `(274,25,670,503)` / x86 | 520 | 13260 | 286 | 0 |

The same-input x64/x86 runs have exact boundary metrics and forty identical
saved final/repeated images. Timing values are measured independently and are
not compared byte-for-byte. The Python audit recomputes image hashes from the
actual application captures and checks identities, epochs, resource counts,
rejections and repetitions. These are replays of prior captures, not new PMM UI
sessions or activation of application DX11 rendering.

Generated CTests additionally cover real swapchain `ResizeBuffers`, minimize /
restore, an externally held backbuffer causing reset failure, retry, retained
texture caches and device retirement/replacement. Both Hardware and WARP run
the compatibility option. Explicit replacement is tested; actual driver device
removal is not forced. The 36 independent matrix/geometry cases additionally
exercise the regular backend's complete model path; observation shaders still
retain the diagnostic arithmetic controls described in
[Independent XY/W qualification](RHI_INDEPENDENT_XY.md).

## Measured cost and its limits

`ReplayD3D11ModelPrefix` accepts an optional `D3D11ReplayTiming` output. Timestamp
and timestamp-disjoint queries bracket clear/draw work, after private uploads
and target reconstruction and before readback. Invalid/disjoint results are
never reported as valid durations. The test alternates the two modes, excludes
three warmup iterations and keeps twelve measured samples per mode. Whole-call
wall time is reported separately, including uploads, reset synchronization,
state setup and readback. GPU intervals can include scheduling/CPU submission
gaps; this is not an isolated microbenchmark of one double instruction.

NVIDIA TITAN Xp, single-sample captured x64 viewport:

| Executable / mode | GPU median (ms) | Complete replay median (ms) |
| --- | ---: | ---: |
| x64 default | 0.089088 | 27.03140 |
| x64 DX9 measured | 0.114608 | 27.21035 |
| x86 default (same x64 input) | 0.087040 | 27.29275 |
| x86 DX9 measured (same x64 input) | 0.112128 | 26.53760 |

The compatible GPU interval is about 29% longer, an absolute change near
0.025 ms for this workload. For the original x86 input/viewport, the medians are
0.060880 versus 0.093152 ms (about 53% / 0.032 ms), with complete-call medians of
13.96405 versus 13.99095 ms. This is a separate input, not a cross-architecture
comparison of the same image. Whole-call timing does not establish a speedup:
CPU upload/readback and run-to-run variation dominate it. Default-mode images
retain 350 differing pixels against this capture; they are a performance
baseline, not an accepted DX9-equivalent image. The two modes differ in more
than the presence of double operations, so this ratio is not a pure FP64 cost.
Other GPUs, larger workloads, sustained application playback and MSAA need
separate acceptance. No application switch is enabled by these timings.

## Reproduction and evidence

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe --dx11-compatibility-lifecycle exports/ground-rhi-prefix-x64 exports/new-compatibility-x64
python tools/analyze_dx11_compatibility.py exports/ground-rhi-prefix-x64 exports/new-compatibility-x64
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --dx11-compatibility-lifecycle exports/ground-rhi-prefix-x64 exports/new-compatibility-x86
python tools/analyze_dx11_compatibility.py exports/ground-rhi-prefix-x64 exports/new-compatibility-x86 --compare exports/new-compatibility-x64
ctest --test-dir build-x64/build -C Release --output-on-failure -R '^rhi_d3d11_compatibility_'
```

Seventeen focused regression checks are covered on each architecture. The
complete x86 run passes 17/17 in 109.13 seconds. x64's initial regression and
corrected focused reruns cover the same checks; its final three compatibility
CTest cases pass in 48.09 seconds, without skips. Logs are under
`exports/dx11-compatibility-ctest-x86.log`,
`exports/dx11-compatibility-corrected-ctest-x64.log` and
`exports/dx11-compatibility-final-ctest-x64.log`. The initial x64 log retains the
generated fixture's wrong-backend-entry failure, which was corrected by calling
the regular replay entry for regular devices; no image tolerance was changed.

The archive command requires a fresh output folder. The generated CTest fixture
uses a fresh process-specific folder and has no external PMM dependencies.
Unsupported lifecycle devices report an explicit unavailable reason; they are
not counted as passes. Private captures and evidence remain ignored under
`exports/`. Final scene runs are `dx11-compatibility-acceptance-x64`,
`dx11-compatibility-acceptance-shared-x86` and
`dx11-compatibility-acceptance-native-x86`, with separate audit logs and
`analysis.json` files. Initial runs remain separate.

The final scene fixture also exercises a finite stream containing a singular
normal transform which the compatibility backend rejects. Its timed frame
closes active queries on the failure path, leaves the result invalid, and the
following complete draws and timestamps recover normally. A portable-invalid
stream would be rejected before starting queries and is a different boundary.
