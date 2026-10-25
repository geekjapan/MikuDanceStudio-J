# MME pass plans

What the C++ MME runtime (`third_party/mmeffect`) decides for an effect file,
written as text. One plan per effect: every `*.fx` of the ray-mmd corpus and
the small effects in `effects/`. The Rust `mds-mme` slice must produce the same
plan from the same effect.

Recorded on the Windows host `nanoha-lan` (i9-12900K, RTX 3090, driver
32.0.16.1062, Windows 11 10.0.26300) by `mme_passplan.exe`, x64 Release, built
at `c34ea35` with `tools/windows/build.ps1`. The lane `tools/oracle/mme_passplan.ps1`
ran through `tools/windows/runtask.ps1` in the console session (the tool creates
a D3D9 HAL device):

    runtask.ps1 -Script C:\mds\w2-passplan\repo\tools\oracle\mme_passplan.ps1 -TimeoutSec 7000
                -ScriptArgs '-Root C:\mds\w2-passplan\repo -Out <empty dir>'

The lane runs `mme_passplan.exe --root <dir> --out <plan> <effect.fx>` once per
file, in ordinal order of the relative path, for `-Corpus` (default
`C:\mds\corpus\ray-mmd`) and for `tests\fixtures\rust\mme\effects`. The corpus is
ray-mmd at `218a91cd1c53f49850b2772ebbcb98bf258e75b1`, the commit that
`tools/fixtures/fetch_corpus.sh` pins.

Three full runs (520 files, about four minutes each) gave the same bytes for every
plan: the three `SHA256SUMS` files are identical. The plans total 4.7 MB. All 515 corpus
effects load; there are no rejected ones and no message boxes. Of the five small
effects, `reject_script.fx` and `reject_version.fx` are rejected on purpose. The
corpus has 2,553 techniques (512 each of `object_ss`, `shadow`, `edge`, `zplot`,
505 `object`), 362 resources, and 115 plans with an `OFFSCREENRENDERTARGET`. Three
corpus effects are scene class: `ray.fx` (a scene effect with a 31-pass script),
`Extension/DummyScreen/DummyScreen.fx`, and `Extension/Debug/DebugController.fx`.
The other 512 are object class. The only `Warning` the loader logs is
`unsupported script command: ClearSetStencil` in `ray.fx`.

| Directory | Plans |
|---|---|
| `ray-mmd/ray.fx.plan.txt` | 1 |
| `ray-mmd/Extension` | 2 |
| `ray-mmd/Fog` | 11 |
| `ray-mmd/Lighting` | 162 |
| `ray-mmd/Main` | 5 |
| `ray-mmd/Materials` | 270 |
| `ray-mmd/Outline` | 25 |
| `ray-mmd/Shadow` | 15 |
| `ray-mmd/Skybox` | 24 |


## Files

- `ray-mmd/<relative path>.plan.txt`: one plan per corpus effect, 515 files.
  The name is the effect path under the corpus root plus `.plan.txt`.
- `extra/<name>.fx.plan.txt`: plans of `effects/<name>.fx`, 5 files.
- `SHA256SUMS`: `sha256sum` format, one line per plan, sorted by path. Its own
  sha256 is `8e41d3820216d4e623a39c3aaed0332f7adef35064fb85b12da298edf00eb7c2`. Check with `shasum -a 256 -c SHA256SUMS` in this directory.
- `effects/*.fx`: the small effects. `objects.fx` has every `MmdPass`, `Subset`
  ranges, explicit and wildcard `Use*` filters, a looped technique script, and a
  pass script. `post.fx` is a postprocess scene effect with viewport-ratio, fixed-size, mipmapped,
  and depth targets, clears, `ScriptExternal`, and `Draw=Buffer`. `offscreen.fx` has an
  `OFFSCREENRENDERTARGET` with `DefaultEffect` rows, a cube target addressed by face,
  `CONTROLOBJECT` parameters, and a `STANDARDSGLOBAL` `Script` that lists techniques.
  `reject_script.fx` and `reject_version.fx` are rejected by the loader.

`.gitattributes` in `tests/fixtures/rust` marks these files byte-exact.

## What a plan is

A plan is what `MmeEngineLoadEffectFile` leaves behind (D3DX compile with the
MME defines, then `SasParse`) plus the load-time technique selection table of
`material_bind.cpp` (`MmeBuildDrawTechniqueTable`, built here without a model by
calling `SasSelectTechnique`) plus a replay of every technique script through the
real interpreter. It has no pointers, handles, or host paths. Text of the
corpus root becomes `<root>`. Strings are quoted. `\` and `"` are escaped with `\`,
and bytes below 0x20 or from 0x7f up are written as `\xNN`, so Shift-JIS text is kept
byte for byte. Lines end with LF. Indented lines belong to the line above them.

Fixed device: HAL, back buffer 1000x600 A8R8G8B8, auto depth stencil D24S8,
`MmeEngineInit(device, true)` (the MME_MIPMAP define is on). `ViewportRatio`
sizes are `int(1000 * ratio)` and `int(600 * ratio)`. The `device` line records
the shader model caps. `hardware=` on a technique is `ValidateTechnique` on this
GPU, and `created` lines are what D3D made, so they can differ on other hardware.

### Line by line

    passplan 1
    file "<root>/Main/ray.fx"
    device HAL backbuffer=1000x600 format=A8R8G8B8 depthstencil=D24S8 vs=3.0 ps=3.0 mipfilter=1
    load ok | load rejected

A rejected effect (`load rejected`) is followed by `  error "<line>"` lines, the
text the loader reports (D3DX compiler output or the `Error:` lines of the SAS
parse), and by the `enginelog` lines. Nothing else is written then.

    effect scriptclass=N scriptorder=N posteffect=0|1 drawsgeometry=0|1 errors=0|1

`SasEffect` fields. `scriptclass` 0 object, 1 scene, 2 sceneorobject.
`scriptorder` 0 standard, 1 preprocess, 2 postprocess.

    parameters N
    param "name" "SEMANTIC" class type RxC[[elements]][ literal]
      ann "Name" type<rows*columns> = value

Parameters in D3DX enumeration order. Only parameters the runtime looks at are
listed: those with a semantic, texture types, the names of the name table
(`matWorld`, `use_toon`, ...), and any with an annotation the runtime reads.
`ann` lines list only the annotations the runtime reads (`ScriptOutput`,
`ScriptClass`, `ScriptOrder`, `Script`, `ResourceName`, `ResourceType`, `Offset`,
`Speed`, `SeekVariable`, `TextureName`, `ViewportRatio`, `Dimensions`, `Width`,
`Height`, `Depth`, `Miplevels`, `Levels`, `Format`, `Description`, `DefaultEffect`,
`ClearColor`, `ClearDepth`, `AntiAlias`, `Function`, `Target`, `Name`, `Item`,
`Object`), with their raw values (floats as `%.9g`). `string0` is a string.

    resources N
    resource "name" semantic=RenderColorTarget|RenderDepthStencilTarget|Texture|AnimatedTexture|OffScreenRenderTarget|TextureValue texture=T
      request WxHxD mips=M rawsize=WxH rawmips=M format=F defaultpool=0|1
      clear color=0xAARRGGBB|- depth=Z|- antialias=0|1          (offscreen only)
      defaulteffect_row "key" "value"                           (offscreen, in order)
      resourcename "..." / function "..." target "..." / animated ... / texturevalue ...
      created texture|cube WxH levels=N format=F pool=P usage=0x..
      created depthsurface WxH format=F                         (depth targets)
      offscreendepth WxH format=F | none                        (offscreen only)

`SasResource`. `texture=T` is 5 `TEXTURE`, 7 `TEXTURE2D`, 8 `TEXTURE3D`, 9
`TEXTURECUBE` after `ResourceType`. `request` is the resolved size (the ratio
applied to the back buffer, the default being the back buffer size), `rawsize`
and `rawmips` are the unresolved values (-1 = unset). `created` is the D3D object
that exists after the parse. A depth target also has a 1x1 placeholder texture
line. Only resources the parse built appear, in parse order.

    controls N
    control "param" name="object" item="item"

The `CONTROLOBJECT` parameters, in parse order.

    technique_order "A" "B" ...
    techniques N
    technique "A" mmdpass=object|object_ss|shadow|edge|zplot usetexture=any|0|1 usespheremap=.. usetoon=.. subset=all|a-b,c-d hardware=0|1 shadercaps=0|1 shadermix=0|1 script=0|1 empty=0|1 passes=N
      script "raw technique Script annotation"
      cmd I Name param="p" value=V text="raw value"
      pass I "name" script=0|1 custom=0|1 psize15=0|1 shadermix=0|1
        script "raw pass Script annotation"
        cmd I Name ...

`technique_order` is the selector's candidate order (`techniqueOrder`): declaration
order, or only the names of the `STANDARDSGLOBAL` `Script=Technique=...` list, with
duplicates. `techniques` are the scanned techniques in scan order. `any` is the
wildcard of a `Use*` filter without annotation. `cmd` lines are the compiled
commands (`SasCompileScript`) in order; loops are not unrolled. `Name` is one of
`Pass`, `RenderColorTarget0..3`, `RenderDepthStencilTarget`, `ClearSetColor`,
`ClearSetDepth`, `Clear`, `DrawGeometry`, `DrawBuffer`, `ScriptExternal`,
`LoopByCount`, `LoopGetIndex`, `LoopEnd`. For `Pass`, `pass="name" index=I`. For
`Clear`, `value` is the D3DCLEAR flags (1 color, 6 depth and stencil). For a
render target, `value` is the cube face or -1, and `param="-"` resets to the saved
target.

    selection subsets=N clamped=0|1
      select <mode> a-b <technique>|<technique>!|- ...

The selection table of `MmeBuildDrawTechniqueTable`: for each draw mode and
material subset, the technique `SasSelectTechnique` returns. Modes `object` and
`object_ss` list eight entries, one for each `Use*` state, indexed
`usetexture | usespheremap<<1 | usetoon<<2`. The other modes have one entry. `-`
is no technique (the raw host draw), `name!` is a technique that matched but is
invalid on this device (the original draws it anyway). Subsets 0 to one past the
largest `Subset` range end are probed, and subsets from `a` to `b` with the same
answer are one row. Later subsets answer like the last row. When `clamped=1` (a
scene effect, or a pre or postprocess order) the material count is 1, and
pre/postprocess effects list only `object`.

    runs
      run "technique"
        start|suspend|end rt0=<target> rt1=.. rt2=.. rt3=.. ds=<target> viewport=WxH+X+Y
        draw geometry|buffer pass=I "name" rt0=... ds=... viewport=...
        result suspended=0|1 draws=N hr=0x........ runfailed=0|1
        log "..."

The interpreter run of every non-empty technique, in scan order: `SasCreateRunState`,
`SasExecuteTechniqueStep` (stops at `ScriptExternal`, shown by `suspend`), then
`SasResumeTechnique`. The host draw callback records `draw` and draws nothing.
The target names are the resource names, `main` and `main.depth` (the device's
own targets), `scratch` (the 16x16 fallback target), `<name>.depth` (the depth
surface of an offscreen target), `<name>[face]` for cube faces, `other`, or `none`.
`runfailed` is cleared before each technique. `log` lines are what the run added
to the effect log.

    messagebox "text"        (a box the runtime showed; the tool closed it)
    enginelog "line"         (the runtime's log history: "Loading effect file", Info and Warning lines)
    end

## Decisions the Rust slice should know

- No `ModelData` is involved. The per-draw lookup of `MmeRefreshDrawTechnique`
  is `index = subset*8 | usetexture | usespheremap<<1 | usetoon<<2` into the
  `select` rows. Binding of semantics to values (`MmeBindSemanticParameters`, the
  `semanticFast` kinds) needs a model and a frame and is not in the plan. The
  plan gives each parameter's semantic text and read annotations, and the semantic
  id tables of `sas_interpreter.cpp` are what `mds-mme` ports.
- Resource sizes come from the 1000x600 back buffer, not from a viewport.
- `runs` replays one effect alone. A texture parameter with no annotation
  (`literal`, for example `Gbuffer5RT` in the `Materials` effects) builds no
  resource, because ray.fx supplies that texture in a scene. Its
  `RenderColorTarget0=` therefore finds no texture in `runs`, and slot 0 falls back
  to `scratch` (the 16x16 target, as the interpreter does). That is the case in
  the 270 `Materials` plans. The `draw` lines record the pass order and the target
  state the interpreter set. They do not show what a real scene binds.
- `hardware=` and the `created` lines come from this GPU. The shader models are
  3.0, so every corpus technique validates.

## ray-mmd notice

The plans under `ray-mmd/` contain parameter names, annotations, and paths from
ray-mmd, which is under this license:

```
MIT License

Copyright (C) 2016-2018 Rui. All rights reserved.

https://github.com/ray-cast/ray-mmd

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
BRIAN PAUL BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN
AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```
