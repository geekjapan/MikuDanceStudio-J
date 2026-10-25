// An offscreen carrier: chain*.pmx draws with draw.fx, Miku.pmx with its main effect, the
// owner is hidden, and everything else is the host's own draw.
float Script : STANDARDSGLOBAL <
    string ScriptOutput = "color";
    string ScriptClass = "sceneorobject";
    string ScriptOrder = "standard";
> = 0.8;

texture TurnRT : OFFSCREENRENDERTARGET <
    string Description = "Turn";
    int Width = 64;
    int Height = 32;
    float4 ClearColor = { 0, 0, 1, 1 };
    float ClearDepth = 1.0;
    string DefaultEffect = "self = hide; CHAIN*.pmx = draw.fx; Miku.pmx = main_default; * = none;";
>;
sampler TurnSamp = sampler_state { texture = <TurnRT>; };

float4x4 WorldViewProjMatrix : WORLDVIEWPROJECTION;
float4 VS(float4 Pos : POSITION) : POSITION { return mul(Pos, WorldViewProjMatrix); }
float4 PS() : COLOR0 { return tex2D(TurnSamp, float2(0.5, 0.5)); }

technique Main < string MMDPass = "object"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
