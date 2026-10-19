// Fixed-function texture cascade subset. Coordinates are produced by the
// vertex stage (mesh UV or transformed camera normal), not inferred here.
// Logical stage order: Toon, Base/promoted Sphere, optional Sphere.
Texture2D textures[3] : register(t0);
SamplerState samplers[3] : register(s0);
cbuffer Cascade : register(b0) {
    // x: enabled, y: Add(3) / Modulate(2), z/w reserved.
    uint4 stages[3];
    // x: alpha-test enabled, y: portable DepthComparison, z: byte ref,
    // w: native specular-stage enabled (measured compatibility only).
    uint4 alphaTest;
};
struct PixelInput {
    float4 position : SV_POSITION;
#if MDS_MODEL_CENTROID
    centroid float4 litDiffuse : COLOR0;
    centroid float2 coordinate0 : TEXCOORD0;
    centroid float2 coordinate1 : TEXCOORD1;
    centroid float2 coordinate2 : TEXCOORD2;
#else
    float4 litDiffuse : COLOR0;
    float2 coordinate0 : TEXCOORD0;
    float2 coordinate1 : TEXCOORD1;
    float2 coordinate2 : TEXCOORD2;
#endif
#ifdef MDS_MODEL_SPECULAR
    float3 specular : COLOR1;
#endif
};
float4 Combine(float4 previous, float4 sampled, uint operation) {
    float3 rgb = operation == 3 ? previous.rgb + sampled.rgb : previous.rgb * sampled.rgb;
    return float4(saturate(rgb), previous.a * sampled.a);
}
#if MDS_MODEL_DX9_COMPATIBILITY && defined(MDS_MODEL_SPECULAR)
// The last Modulate followed by specular uses one float32 rounding on the
// measured DX9 path. Double operands express the float product/add without
// early rounding. This is an opt-in measured policy, not generic material math.
float3 MeasuredFinalModulate(float3 previous, float3 sampled, float3 specular) {
    precise double3 product = double3(previous) * double3(sampled);
    precise double3 combined = product + double3(specular);
    return saturate(float3(combined));
}
#endif
float4 main(PixelInput input) : SV_TARGET {
#if MDS_MODEL_FLAT
    return float4(0,0,0,1);
#endif
    float4 color = input.litDiffuse;
#if MDS_MODEL_DX9_COMPATIBILITY && defined(MDS_MODEL_SPECULAR)
    float3 measuredFinal = 0;
    bool measured = false;
    // Only the final active Modulate shares rounding with specular. On the
    // measured native path, enabling the specular stage also postpones RGB
    // saturation until the final output; alpha multiplication is unchanged.
    [unroll] for (uint stage = 0; stage < 3; ++stage) if (stages[stage].x) {
        float2 coordinate = stage == 0 ? input.coordinate0 : stage == 1 ? input.coordinate1 : input.coordinate2;
        float4 sampled = textures[stage].Sample(samplers[stage],coordinate);
        bool last = stage == 2 || (stage == 1 ? !stages[2].x : !stages[1].x && !stages[2].x);
        if (last && stages[stage].y == 2) {
            measuredFinal = MeasuredFinalModulate(color.rgb,sampled.rgb,input.specular);
            measured = true;
        }
        precise float3 rgb = stages[stage].y == 3 ? color.rgb + sampled.rgb : color.rgb * sampled.rgb;
        color = float4(alphaTest.w ? rgb : saturate(rgb),color.a * sampled.a);
    }
#else
    if (stages[0].x) color = Combine(color, textures[0].Sample(samplers[0],input.coordinate0),stages[0].y);
    if (stages[1].x) color = Combine(color, textures[1].Sample(samplers[1],input.coordinate1),stages[1].y);
    if (stages[2].x) color = Combine(color, textures[2].Sample(samplers[2],input.coordinate2),stages[2].y);
#endif
    if(alphaTest.x) {
        // Legacy alpha-test reference is a byte. Conversion is explicit;
        // linear-filter precision can still differ from a DX9 native sampler.
#if MDS_MODEL_ALPHA12_DIAGNOSTIC
        // Frozen measured candidate 8994: input truncation, exact power-of-two
        // scaling, then nearest-even byte conversion. Alpha output is unchanged.
        float fixedAlpha = floor(saturate(color.a) * 4096.0) / 4096.0;
        float comparedAlpha = round(fixedAlpha * 255.0);
#else
        float comparedAlpha = floor(saturate(color.a) * 255.0 + 0.5);
#endif
        float reference = alphaTest.z;
        bool accepted = alphaTest.y == 7 ||
            (alphaTest.y == 1 && comparedAlpha < reference) || (alphaTest.y == 2 && comparedAlpha == reference) ||
            (alphaTest.y == 3 && comparedAlpha <= reference) || (alphaTest.y == 4 && comparedAlpha > reference) ||
            (alphaTest.y == 5 && comparedAlpha != reference) || (alphaTest.y == 6 && comparedAlpha >= reference);
        if(!accepted) discard;
    }
#ifdef MDS_MODEL_SPECULAR
#if MDS_MODEL_DX9_COMPATIBILITY
    color.rgb = measured ? measuredFinal : saturate(color.rgb + input.specular);
#else
    color.rgb = saturate(color.rgb + input.specular);
#endif
#endif
    return color;
}
