# vkd3d-shader defects

These two cases are tracked in issues #11 (E9022) and #12 (E5027). Filing them
upstream is on hold. A search of bugs.winehq.org (product vkd3d) and of
gitlab.winehq.org/wine/vkd3d on 2026-10-24 found no report of either case.
Both reproduce with `vkd3d-compiler` 2.1 built by `tools/vkd3d/build.sh`.

## E9022 when a ps_3_0 shader reads VPOS after a TEXCOORD input

Compiling HLSL straight to SPIR-V fails when the pixel shader input list has a
`TEXCOORD` element followed by `VPOS` or `SV_Position`. The same source
compiles with `-b d3dbc`. `VPOS` as the only input compiles.

```hlsl
float4 main(float4 t0 : TEXCOORD0, float4 pos : VPOS) : COLOR
{
    return t0 + pos;
}
```

```
$ vkd3d-compiler -x hlsl -p ps_3_0 -b spirv-binary -e main -o out.spv vpos.hlsl
vpos.hlsl:1:37: E9022: Unable to resolve I/O register type 0x1, index 1, swizzle 0x3020100, to a signature element.
Failed to compile shader, ret -4.
```

With a second `TEXCOORD` input the message names index 2. Expected: the
shader compiles, as it does through d3dbc. Seen in 40 pixel shaders of the
ray-mmd effects, for example `VolumetricFogPS` in
`Lighting/DiskLight/disk_fog.fxsub`.

## E5027 when constant folding computes pow(0, y)

`pow` of a constant zero folds through `log2(0)`, which gives `-inf`, and the
compiler then rejects the infinity. It fails for both `-b spirv-binary` and
`-b d3dbc`.

```hlsl
float4 main() : COLOR
{
    float3 c = 0;
    return float4(pow(c, 2.2), 1);
}
```

```
$ vkd3d-compiler -x hlsl -p ps_3_0 -b spirv-binary -e main -o out.spv pow0.hlsl
pow0.hlsl:4:17: E5027: Infinities and NaNs are not allowed by the shader model.
Failed to compile shader, ret -4.
```

Expected: the shader compiles and `pow(0, 2.2)` folds to 0. Seen in 30
entries of the ray-mmd outline effects, for example `pow(edgeLineColor, 2.2)`
with a constant zero color in `Outline/Fixed Color x1/outline blue.fx`.
