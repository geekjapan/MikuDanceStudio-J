cbuffer VertexInputs : register(b0) {
    row_major float4x4 world, view, projection, normalView;
    row_major float4x4 textureTransform[3];
    float4 diffuse, ambient, specular, emissive, globalAmbient;
    float4 lightDirection[8], lightDiffuse[8], lightAmbient[8], lightSpecular[8];
    uint4 flags; // lighting, normalizeNormals, specularEnabled, localViewer
    uint4 coordinates; // logical coordinate modes, reserved
    float4 parameters; // power, viewport width, viewport height, reserved
};
struct VertexInput { float3 position:POSITION; float3 normal:NORMAL; float2 uv:TEXCOORD0; };
struct PixelInput {
    float4 position:SV_POSITION; float4 litDiffuse:COLOR0;
    float2 coordinate0:TEXCOORD0; float2 coordinate1:TEXCOORD1; float2 coordinate2:TEXCOORD2;
    float3 specular:COLOR1;
};
float2 Coordinate(uint stage, uint mode, float3 normal, float2 uv) {
    return mode == 2 ? mul(float4(normal,1),textureTransform[stage]).xy : uv;
}
PixelInput main(VertexInput input) {
    PixelInput output;
    float4 camera = mul(mul(float4(input.position,1),world),view);
    output.position = mul(camera,projection);
    // DX9 integer pixel centers versus DX11 half-integer pixel centers.
    output.position.xy += float2(1/parameters.y,-1/parameters.z)*output.position.w;
    float3 normal = mul(float4(input.normal,0),normalView).xyz;
    if(flags.y) normal=normalize(normal);
    float3 color=diffuse.rgb; float3 highlight=0;
    if(flags.x) {
        color=emissive.rgb + ambient.rgb*globalAmbient.rgb;
        for(uint i=0;i<8;++i) if(lightDirection[i].w) {
            float3 towardLight=-normalize(mul(float4(lightDirection[i].xyz,0),view).xyz);
            float facing=max(dot(normal,towardLight),0);
            color += ambient.rgb*lightAmbient[i].rgb + diffuse.rgb*lightDiffuse[i].rgb*facing;
            if(flags.z && facing>0) {
                float3 viewer=flags.w?normalize(-camera.xyz):float3(0,0,-1);
                float3 halfway=normalize(towardLight+viewer);
                highlight += specular.rgb*lightSpecular[i].rgb*pow(max(dot(normal,halfway),0),parameters.x);
            }
        }
    }
    output.litDiffuse=float4(saturate(color),diffuse.a);output.specular=saturate(highlight);
#if MDS_MODEL_VERTEX_BYTE
    output.litDiffuse=floor(output.litDiffuse*255+0.5)/255;
#endif
    output.coordinate0=Coordinate(0,coordinates.x,normal,input.uv);
    output.coordinate1=Coordinate(1,coordinates.y,normal,input.uv);
    output.coordinate2=Coordinate(2,coordinates.z,normal,input.uv);
    return output;
}
