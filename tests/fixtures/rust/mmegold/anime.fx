// mmegold: blink.gif (rust/crates/mds-mmert/tests/data) on the owner.
float Script : STANDARDSGLOBAL <
    string ScriptOutput = "color";
    string ScriptClass = "object";
    string ScriptOrder = "standard";
> = 0.8;

float4x4 WorldViewProjMatrix : WORLDVIEWPROJECTION;
float Time : TIME;
texture Anim : ANIMATEDTEXTURE < string ResourceName = "blink.gif"; >;
sampler AnimSamp = sampler_state {
    texture = <Anim>;
    MinFilter = POINT; MagFilter = POINT; MipFilter = NONE;
    AddressU = CLAMP; AddressV = CLAMP;
};

struct VS_OUT {
    float4 Pos : POSITION;
    float2 Tex : TEXCOORD0;
};
VS_OUT VS(float4 Pos : POSITION, float2 Tex : TEXCOORD0) {
    VS_OUT o;
    o.Pos = mul(Pos, WorldViewProjMatrix);
    o.Tex = Tex;
    return o;
}
float4 PS(VS_OUT i) : COLOR0 { return tex2D(AnimSamp, i.Tex); }

technique Main < string MMDPass = "object"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
