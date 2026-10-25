// The technique script names a pass that does not exist: the loader rejects it.
float Script : STANDARDSGLOBAL < string ScriptOutput = "color"; string ScriptClass = "object"; string ScriptOrder = "standard"; > = 0.8;
float4x4 WorldViewProjMatrix : WORLDVIEWPROJECTION;
float4 VS(float4 Pos : POSITION) : POSITION { return mul(Pos, WorldViewProjMatrix); }
float4 PS() : COLOR0 { return 1; }
technique T < string MmdPass = "object"; string Script = "Pass=Nope;"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
