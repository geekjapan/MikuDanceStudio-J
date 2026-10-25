// Offscreen render target with DefaultEffect rows, a cube target addressed by
// face, CONTROLOBJECT parameters, name-table parameters, and a STANDARDSGLOBAL
// Script that lists techniques (one of them unknown).
float Script : STANDARDSGLOBAL <
    string ScriptOutput = "color";
    string ScriptClass = "sceneorobject";
    string ScriptOrder = "standard";
    string Script = "Technique=Main?Used:Missing:Other;";
> = 0.8;

float4x4 matWorld;
float4 DifColor;
bool transp;
int SubsetCount;
float Morph : CONTROLOBJECT < string name = "ctrl.pmx"; string item = "Morph"; >;
float4x4 Bone : CONTROLOBJECT < string name = "(self)"; string item = "Root"; >;
float4x4 WorldViewProjMatrix : WORLDVIEWPROJECTION;

texture MirrorRT : OFFSCREENRENDERTARGET <
    string Description = "Mirror";
    float2 ViewportRatio = { 1.0, 1.0 };
    float4 ClearColor = { 1, 0.5, 0, 1 };
    float ClearDepth = 1.0;
    bool AntiAlias = false;
    string DefaultEffect = "self=hide; *=none; ";
>;
texture CubeRT : RENDERCOLORTARGET <
    int Width = 128;
    int Height = 128;
    string ResourceType = "Cube";
    string Format = "A8R8G8B8";
>;

struct VS_OUT { float4 Pos : POSITION; };
VS_OUT VS(float4 Pos : POSITION) { VS_OUT o; o.Pos = mul(Pos, WorldViewProjMatrix); return o; }
float4 PS(VS_OUT i) : COLOR0 { return DifColor * Morph; }

technique Main < string MmdPass = "object"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique Used < string MmdPass = "object"; string Script = "RenderColorTarget0=CubeRT[2]; Clear=Color; Pass=P0; RenderColorTarget0=;"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique Other < string MmdPass = "edge"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
technique Unlisted < string MmdPass = "shadow"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
