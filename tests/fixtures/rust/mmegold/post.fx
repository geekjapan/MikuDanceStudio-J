// mmegold: mme/effects/post.fx with the Final pass's second target unbound (see README.md).
// Scene postprocess: viewport-ratio, fixed-size, mipmapped, and depth targets,
// clear commands, ScriptExternal, a script that binds targets and draws buffers.
float Script : STANDARDSGLOBAL <
    string ScriptOutput = "color";
    string ScriptClass = "scene";
    string ScriptOrder = "postprocess";
> = 0.8;

float2 ViewportSize : VIEWPORTPIXELSIZE;
float4 ClearColor = { 0.25, 0.5, 0.75, 1.0 };
float ClearDepth = 1.0;

texture2D Work : RENDERCOLORTARGET <
    float2 ViewportRatio = { 0.5, 0.5 };
    string Format = "A16B16G16R16F";
    int Miplevels = 1;
>;
sampler2D WorkSamp = sampler_state { texture = <Work>; MinFilter = LINEAR; MagFilter = LINEAR; };
texture2D WorkDepth : RENDERDEPTHSTENCILTARGET <
    float2 ViewportRatio = { 0.5, 0.5 };
    string Format = "D24S8";
>;
texture2D Small : RENDERCOLORTARGET <
    int Width = 64;
    int Height = 32;
    int Miplevels = 0;
    string Format = "R32F";
>;
texture2D Full : RENDERCOLORTARGET <
    float2 ViewportRatio = { 1.0, 1.0 };
    string Format = "A8R8G8B8";
>;
texture2D Third : RENDERCOLORTARGET <
    float2 ViewportRatio = { 0.3333, 0.3333 };
>;

struct VS_OUT {
    float4 Pos : POSITION;
    float2 Tex : TEXCOORD0;
};
VS_OUT VS(float4 Pos : POSITION, float2 Tex : TEXCOORD0) {
    VS_OUT o;
    o.Pos = Pos;
    o.Tex = Tex + 0.5 / ViewportSize;
    return o;
}
float4 PS(VS_OUT i) : COLOR0 { return tex2D(WorkSamp, i.Tex); }

technique Post <
    string Script =
        "RenderColorTarget0=Work;"
        "RenderDepthStencilTarget=WorkDepth;"
        "ClearSetColor=ClearColor; ClearSetDepth=ClearDepth;"
        "Clear=Color; Clear=Depth;"
        "ScriptExternal=Color;"
        "RenderColorTarget0=Small;"
        "Pass=Down;"
        "RenderColorTarget0=; RenderDepthStencilTarget=;"
        "Pass=Final;";
> {
    pass Down < string Script = "Draw=Buffer;"; > { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
    pass Final < string Script = "Draw=Buffer;"; > { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
