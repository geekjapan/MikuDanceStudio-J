# mds-mme

The planning layer of the MME runtime of `third_party/mmeffect`, ported to Rust on top of the
`mds-fx` parser. For one effect file it decides what `MmeEngineLoadEffectFile` decides:

- `fx.rs`: what `ID3DXEffect` reports. Parameters in declaration order (non-`static` globals),
  their descriptions, `shared` flag, annotations and initial values, with the D3DX getter
  conversions. Techniques and passes with their shader profiles.
- `sas.rs`: `SasParse` (`sas_interpreter.cpp`). The STANDARDSGLOBAL scan and its `Script`, the
  semantic and parameter-name tables, resource objects (render, depth, and offscreen targets,
  file, animated, and value textures) with the D3D objects the runtime creates, CONTROLOBJECT
  parameters, the technique and pass scans, and the script compiler of `sas_exec.cpp`.
- `run.rs`: the technique walk of `sas_exec.cpp` (step to `ScriptExternal`, resume) against a
  model of the device's render targets, depth stencil, and viewport.
- `plan.rs`: the technique selector (`SasSelectTechnique`) and the plan text of
  `tools/oracle/mme_passplan.cpp`.
- `texfile.rs`: size, mip count, and format of a texture file from its header, as
  `D3DXCreateTextureFromFileEx` creates it.

`mds_mme::plan(effect, root)` returns the plan text.

## Gate

`cargo test -p mds-mme` regenerates every plan under `tests/fixtures/rust/mme/` and compares it
byte for byte. The `extra/` plans always run. The `ray-mmd/` plans need the corpus of
`tools/fixtures/fetch_corpus.sh` and print `SKIP` without it. Plans that do not match yet are
listed in `tests/mismatches.txt`, and the test fails when that list is not exact. The list is
empty: all 520 plans match.

No line kinds are excluded. The device-dependent values are modelled for the oracle's device
(HAL, shader model 3.0, 1000x600 back buffer, D24S8):

- `hardware=1` for every technique (`ValidateTechnique` passes on an SM 3.0 device), so the
  selection table has no `name!` entries.
- `shadercaps` and `shadermix` come from the `compile` profiles.
- `created` lines: render targets keep the requested size and format, `Miplevels=0` gives one
  reported level with `D3DUSAGE_AUTOGENMIPMAP`, and file textures take the file size rounded up
  to a power of two, the full mip chain unless `Miplevels` limits it, and the file's format.

## Not ported

Nothing in the corpus or the small effects reaches these, so they are left out:

- texture shaders (`Function`/`Target` on a texture): no texture is created;
- decoding the GIF/PNG of an ANIMATEDTEXTURE: an existing file counts as decodable;
- D3DX compiler error texts and the message boxes;
- semantic binding per model and frame, device reset, effect pools across effects.

Strings with non-ASCII text are written in Shift-JIS, the encoding of the corpus files.
