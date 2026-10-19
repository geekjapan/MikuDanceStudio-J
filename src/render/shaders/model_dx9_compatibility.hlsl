// Opt-in DX9 measured arithmetic. Each double product of float operands is
// exact; round the product plus float accumulator back to float per step.
cbuffer Dx9CompatibilityInputs:register(b1) {row_major float4x4 dx9Combined,dx9WorldView;};
float Dx9FusedStep(float a,float b,float c) {
    precise double product=double(a)*double(b);
    precise double sum=product+double(c);return float(sum);
}
float Dx9Dot4(float4 a,float4 b) {
    float v=Dx9FusedStep(a.x,b.x,0);v=Dx9FusedStep(a.y,b.y,v);
    v=Dx9FusedStep(a.z,b.z,v);return Dx9FusedStep(a.w,b.w,v);
}
float4 Dx9Clip(float3 object) {
    float4 p=float4(object,1);
    return float4(Dx9Dot4(p,float4(dx9Combined[0][0],dx9Combined[1][0],dx9Combined[2][0],dx9Combined[3][0])),
        Dx9Dot4(p,float4(dx9Combined[0][1],dx9Combined[1][1],dx9Combined[2][1],dx9Combined[3][1])),
        Dx9Dot4(p,float4(dx9Combined[0][2],dx9Combined[1][2],dx9Combined[2][2],dx9Combined[3][2])),
        Dx9Dot4(p,float4(dx9Combined[0][3],dx9Combined[1][3],dx9Combined[2][3],dx9Combined[3][3])));
}
float Dx9Dot3(float3 a,float3 b) {
    float v=Dx9FusedStep(a.x,b.x,0);v=Dx9FusedStep(a.y,b.y,v);return Dx9FusedStep(a.z,b.z,v);
}
float4 Dx9Camera(float3 object) {
    float4 p=float4(object,1);
    return float4(Dx9Dot4(p,float4(dx9WorldView[0][0],dx9WorldView[1][0],dx9WorldView[2][0],dx9WorldView[3][0])),
        Dx9Dot4(p,float4(dx9WorldView[0][1],dx9WorldView[1][1],dx9WorldView[2][1],dx9WorldView[3][1])),
        Dx9Dot4(p,float4(dx9WorldView[0][2],dx9WorldView[1][2],dx9WorldView[2][2],dx9WorldView[3][2])),
        Dx9Dot4(p,float4(dx9WorldView[0][3],dx9WorldView[1][3],dx9WorldView[2][3],dx9WorldView[3][3])));
}
float3 Dx9Normal(float3 n,row_major float4x4 m) {
    return float3(Dx9Dot3(n,float3(m[0][0],m[1][0],m[2][0])),Dx9Dot3(n,float3(m[0][1],m[1][1],m[2][1])),Dx9Dot3(n,float3(m[0][2],m[1][2],m[2][2])));
}
float3 Dx9Lighting(float3 a,float3 b,float3 c) {
    return float3(Dx9FusedStep(a.x,b.x,c.x),Dx9FusedStep(a.y,b.y,c.y),Dx9FusedStep(a.z,b.z,c.z));
}
