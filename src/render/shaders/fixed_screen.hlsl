// Legacy screen vertices: float4 XY/Z/RHW, packed ARGB, float2 UV.
// One shared source keeps HUD transport identical across shader backends.
cbuffer Screen : register(b0) {float4 size;}
struct V {float4 p:POSITION;float4 c:COLOR;float2 uv:TEXCOORD;};
struct O {float4 p:SV_POSITION;float4 c:COLOR;float2 uv:TEXCOORD;};
O vs(V v) {
    O o;o.p=float4(v.p.x*2/size.x-1,1-v.p.y*2/size.y,v.p.z,1)/v.p.w;
    o.c=v.c.bgra;o.uv=v.uv;return o;
}
Texture2D image:register(t0);SamplerState sampling:register(s0);
float4 ps(O o):SV_TARGET {return image.Sample(sampling,o.uv)*o.c;}
