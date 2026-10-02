// Fixed-function texture cascade subset. Coordinates are produced by the
// vertex stage (mesh UV or transformed camera normal), not inferred here.
// Logical stage order: Toon, Base/promoted Sphere, optional Sphere.
Texture2D textures[3] : register(t0);
SamplerState samplers[3] : register(s0);
cbuffer Cascade : register(b0) {
    // x: enabled, y: Add(3) / Modulate(2), z/w reserved.
    uint4 stages[3];
    // x: alpha-test enabled, y: portable DepthComparison, z: byte ref.
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
float4 main(PixelInput input) : SV_TARGET {
#if MDS_MODEL_FLAT
    return float4(0,0,0,1);
#endif
    float4 color = input.litDiffuse;
    if (stages[0].x) color = Combine(color, textures[0].Sample(samplers[0],input.coordinate0),stages[0].y);
    if (stages[1].x) color = Combine(color, textures[1].Sample(samplers[1],input.coordinate1),stages[1].y);
    if (stages[2].x) color = Combine(color, textures[2].Sample(samplers[2],input.coordinate2),stages[2].y);
    if(alphaTest.x) {
        // Legacy alpha-test reference is a byte. Conversion is explicit;
        // linear-filter precision can still differ from a DX9 native sampler.
        float comparedAlpha = floor(saturate(color.a) * 255.0 + 0.5);
        float reference = alphaTest.z;
        bool accepted = alphaTest.y == 7 ||
            (alphaTest.y == 1 && comparedAlpha < reference) || (alphaTest.y == 2 && comparedAlpha == reference) ||
            (alphaTest.y == 3 && comparedAlpha <= reference) || (alphaTest.y == 4 && comparedAlpha > reference) ||
            (alphaTest.y == 5 && comparedAlpha != reference) || (alphaTest.y == 6 && comparedAlpha >= reference);
        if(!accepted) discard;
    }
#ifdef MDS_MODEL_SPECULAR
    color.rgb = saturate(color.rgb + input.specular);
#endif
    return color;
}
