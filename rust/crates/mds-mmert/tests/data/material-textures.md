# Capture the material texture fixture

Generate the PMM, its EMM, two PMX files, textures and effect without a GPU.
Run from the repository root.

```sh
MDS_MATERIAL_FIXTURE_DIR=/absolute/output \
  cargo test --manifest-path rust/Cargo.toml -p mds-mmert \
  --test material_textures write_native_fixture -- --exact
```

`materials.pmx` has two textured subsets and one subset with no texture in any
slot. `second.pmx` uses different images and the same effect. The effect writes
base red, sphere green, toon blue and base alpha. Its base image has two texels
with different red and alpha values. Sphere mode 3 retains its image.

For the C++ Windows oracle, copy the generated PMX and PNG files beside
`MikuDanceStudio.exe`, as `tools/oracle/mmegold.ps1` stages bare model paths.
Keep `materials.pmm`, `materials.emm`, `material-textures.fx` and `blink.gif`
together in the capture directory. Run in the console session.

```powershell
& $exe --mds-mme-dump "$fixture\materials.pmm" "$out" 0 30
```

Capture twice to separate output folders and compare their bytes before accepting
a native oracle. This fixture supplies inputs only. It contains no native golden
image and changes no pixel tolerance or acceptance gate.

The focused Rust GPU test also checks edge toon retention, Draw=Buffer, offscreen,
Cube/D3 rejection, absent geometry, immutable image handles after a UV morph and
animation changes only when `tick_animes` runs. The native scene uses the Geometry
technique. Edge flags are disabled so its diagnostic buffer techniques do not
cover the scene.

Shared toon resolution follows native `data/toonNN.bmp` relative to the process
working directory and then the actual embedded `res/assets/toonNN.png`. Custom
toon names use the model directory. Only exact lowercase bare `toon01.bmp` through
`toon10.bmp` are shared names. PMD255, absent toon tables, empty names and missing
custom images bind null. Native toon10 recovery requires an existing native null
cache entry. This loader records only successfully decoded images, so a missing
custom image does not create that entry.
