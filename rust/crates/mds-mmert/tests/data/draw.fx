// Draws every object solid red.
float4x4 WorldViewProjMatrix : WORLDVIEWPROJECTION;
float4 VS(float4 Pos : POSITION) : POSITION { return mul(Pos, WorldViewProjMatrix); }
float4 PS() : COLOR0 { return float4(1, 0, 0, 1); }

technique Main < string MMDPass = "object"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
