float Script : STANDARDSGLOBAL < string ScriptOutput = "color"; string ScriptClass = "object"; > = 0.8;
float4x4 WVP : WORLDVIEWPROJECTION;
texture Base : mAtErIaLtExTuRe < string ResourceName = "blink.png"; >;
texture Sphere : MaterialSphereMap;
texture Toon : MATERIALTOONTEXTURE;
sampler2D BaseS = sampler_state { Texture = <Base>; MinFilter = POINT; MagFilter = POINT; AddressU = CLAMP; AddressV = CLAMP; };
sampler2D SphereS = sampler_state { Texture = <Sphere>; MinFilter = POINT; MagFilter = POINT; };
sampler2D ToonS = sampler_state { Texture = <Toon>; MinFilter = POINT; MagFilter = POINT; };
texture Bad : MaterialTexture;
samplerCUBE BadS = sampler_state { Texture = <Bad>; };
texture Volume : MaterialSphereMap;
sampler3D VolumeS = sampler_state { Texture = <Volume>; };
texture Anim : ANIMATEDTEXTURE < string ResourceName = "blink.gif"; >;
sampler AnimS = sampler_state { Texture = <Anim>; MinFilter = POINT; MagFilter = POINT; AddressU = CLAMP; AddressV = CLAMP; };
texture Turn : OFFSCREENRENDERTARGET < float2 ViewportRatio = {1, 1}; string Format = "A8R8G8B8"; float4 ClearColor = {1,1,1,1}; float ClearDepth = 1; >;
struct V { float4 pos : POSITION; float2 uv : TEXCOORD0; };
V GeometryVS(float4 pos : POSITION, float2 uv : TEXCOORD0) { V o; o.pos = mul(pos, WVP); o.uv = uv; return o; }
V BufferVS(float4 pos : POSITION, float2 uv : TEXCOORD0) { V o; o.pos = pos; o.uv = uv; return o; }
float4 PS(V i) : COLOR0 {
    float4 b = tex2D(BaseS, i.uv);
    return float4(b.r, tex2D(SphereS, i.uv).g, tex2D(ToonS, i.uv).b, b.a);
}
float4 CubePS(V i) : COLOR0 { return texCUBE(BadS, float3(1,0,0)); }
float4 VolumePS(V i) : COLOR0 { return tex3D(VolumeS, float3(i.uv,0)); }
technique Geometry < string MmdPass = "object"; > {
    pass P { CullMode = NONE; ZEnable = FALSE; AlphaBlendEnable = FALSE; VertexShader = compile vs_3_0 GeometryVS(); PixelShader = compile ps_3_0 PS(); }
}
technique BufferTechnique < string MmdPass = "edge"; > {
    pass P < string Script = "Draw=Buffer;"; > { CullMode = NONE; ZEnable = FALSE; AlphaBlendEnable = FALSE; VertexShader = compile vs_3_0 BufferVS(); PixelShader = compile ps_3_0 PS(); }
}
technique Cube {
    pass P < string Script = "Draw=Buffer;"; > { ZEnable = FALSE; VertexShader = compile vs_3_0 BufferVS(); PixelShader = compile ps_3_0 CubePS(); }
}
technique Volume {
    pass P < string Script = "Draw=Buffer;"; > { ZEnable = FALSE; VertexShader = compile vs_3_0 BufferVS(); PixelShader = compile ps_3_0 VolumePS(); }
}

float4 AnimPS(V i) : COLOR0 { return tex2D(AnimS, i.uv); }
technique Animation {
    pass P < string Script = "Draw=Buffer;"; > { ZEnable = FALSE; VertexShader = compile vs_3_0 BufferVS(); PixelShader = compile ps_3_0 AnimPS(); }
}
