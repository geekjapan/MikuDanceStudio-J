// Object-class effect: every MmdPass, Subset ranges, explicit and wildcard
// Use* filters, a technique script with a loop, pass scripts.
float Script : STANDARDSGLOBAL <
    string ScriptOutput = "color";
    string ScriptClass = "object";
    string ScriptOrder = "standard";
> = 0.8;

float4x4 WorldViewProjMatrix : WORLDVIEWPROJECTION;
float4x4 WorldMatrix : WORLD;
float4 MaterialDiffuse : DIFFUSE < string Object = "Geometry"; >;
float4 LightDirection : DIRECTION < string Object = "Light"; >;
float3 CameraPosition : POSITION < string Object = "Camera"; >;
float2 ViewportSize : VIEWPORTPIXELSIZE;
float Time : TIME;
float4 EdgeColor : EDGECOLOR;
bool use_texture;
bool use_toon;
int Count = 2;
int Idx;

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
float4 PS(VS_OUT i) : COLOR0 { return MaterialDiffuse * float4(i.Tex, 0, 1); }

technique TexOnly < string MmdPass = "object"; bool UseTexture = true; bool UseToon = false; string Subset = "0-1,3"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique NoTex < string MmdPass = "object"; bool UseTexture = false; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique AnyObject < string MmdPass = "object"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique SelfShadow < string MmdPass = "object_ss"; bool UseSpheremap = false;
    string Script = "LoopByCount=Count; LoopGetIndex=Idx; Pass=P0; Pass=P1; LoopEnd=;"; > {
    pass P0 < string Script = "Draw=Geometry;"; > { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
    pass P1 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique Outline < string MmdPass = "edge"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique Shadow < string MmdPass = "shadow"; string Subset = "2"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique ZPlot < string MmdPass = "zplot"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique Empty < string MmdPass = "shadow"; string Subset = "9"; > {
}
