// mmegold: CONTROLOBJECT values of morph4.pmx color the owner.
float Script : STANDARDSGLOBAL <
    string ScriptOutput = "color";
    string ScriptClass = "object";
    string ScriptOrder = "standard";
> = 0.8;

float4x4 WorldViewProjMatrix : WORLDVIEWPROJECTION;
float MorphA : CONTROLOBJECT < string name = "morph4.pmx"; string item = "あ"; >;
float3 BodyPos : CONTROLOBJECT < string name = "morph4.pmx"; string item = "上半身"; >;
float4x4 Center : CONTROLOBJECT < string name = "morph4.pmx"; string item = "センター"; >;
float3 ModelPos : CONTROLOBJECT < string name = "morph4.pmx"; >;
float4x4 ModelWorld : CONTROLOBJECT < string name = "morph4.pmx"; >;
bool Visible : CONTROLOBJECT < string name = "morph4.pmx"; >;
float Size : CONTROLOBJECT < string name = "morph4.pmx"; >;
float Missing : CONTROLOBJECT < string name = "missing.pmx"; string item = "あ"; >;

float4 VS(float4 Pos : POSITION) : POSITION { return mul(Pos, WorldViewProjMatrix); }
float4 PS() : COLOR0 { return float4(MorphA, frac(Center._41 * 0.25), Visible ? 1 : 0, 1); }

technique Main < string MMDPass = "object"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
