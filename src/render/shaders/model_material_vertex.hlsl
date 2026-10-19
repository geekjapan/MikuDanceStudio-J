cbuffer VertexInputs : register(b0) {
    row_major float4x4 world, view, projection, normalView;
    row_major float4x4 textureTransform[3];
    float4 diffuse, ambient, specular, emissive, globalAmbient;
    float4 lightDirection[8], lightDiffuse[8], lightAmbient[8], lightSpecular[8];
    uint4 flags; // lighting, normalizeNormals, specularEnabled, localViewer
    uint4 coordinates; // logical coordinate modes, reserved
    float4 parameters; // power, viewport width, viewport height, reserved
};
#if MDS_MODEL_VERTEX_COLOR
struct VertexInput { float3 position:POSITION; float4 color:COLOR0; };
#else
struct VertexInput { float3 position:POSITION; float3 normal:NORMAL; float2 uv:TEXCOORD0; };
#endif
struct PixelInput {
    float4 position:SV_POSITION; float4 litDiffuse:COLOR0;
    float2 coordinate0:TEXCOORD0; float2 coordinate1:TEXCOORD1; float2 coordinate2:TEXCOORD2;
    float3 specular:COLOR1;
};
float2 Coordinate(uint stage, uint mode, float3 normal, float2 uv) {
#if MDS_MODEL_DX9_COMPATIBILITY && MDS_MODEL_TEXTURE_FMA_DIAGNOSTIC
    if(mode!=2)return uv;
    float2 result;
    [unroll]for(uint c=0;c<2;++c) {
        float4 column=float4(textureTransform[stage][0][c],textureTransform[stage][1][c],
                             textureTransform[stage][2][c],textureTransform[stage][3][c]);
        result[c]=Dx9Dot4(float4(normal,1),column);
    }
    return result;
#else
    return mode == 2 ? mul(float4(normal,1),textureTransform[stage]).xy : uv;
#endif
}
PixelInput main(VertexInput input) {
    PixelInput output;
    float4 camera = mul(mul(float4(input.position,1),world),view);
#if MDS_MODEL_DX9_COMPATIBILITY && MDS_MODEL_SPECULAR_FMA_DIAGNOSTIC
    camera=Dx9Camera(input.position);
#endif
    output.position = mul(camera,projection);
#if MDS_MODEL_DX9_COMPATIBILITY
    output.position=Dx9Clip(input.position);
#else
    // DX9 integer pixel centers versus DX11 half-integer pixel centers.
    output.position.xy += float2(1/parameters.y,-1/parameters.z)*output.position.w;
#endif
#if MDS_MODEL_VERTEX_COLOR
    // Missing native normal/UV attributes. Never normalize zero or invert the
    // singular ground-projection matrix. Color2 is absent and uses material.
    float3 normal=0; float2 uv=0;
    float4 selectedDiffuse=(coordinates.w & 256) && (coordinates.w & 3)==1 ? input.color : diffuse;
    float3 selectedAmbient=(coordinates.w & 256) && ((coordinates.w >> 2) & 3)==1 ? input.color.rgb : ambient.rgb;
    float3 selectedEmissive=(coordinates.w & 256) && ((coordinates.w >> 6) & 3)==1 ? input.color.rgb : emissive.rgb;
    float3 color=input.color.rgb;float alpha=input.color.a;float3 highlight=0;
    if(flags.x) {
        color=selectedEmissive+selectedAmbient*globalAmbient.rgb;alpha=selectedDiffuse.a;
        for(uint i=0;i<8;++i)if(lightDirection[i].w)color+=selectedAmbient*lightAmbient[i].rgb;
    }
    output.litDiffuse=float4(saturate(color),alpha);output.specular=0;
#else
    float2 uv=input.uv;
    float3 normal = mul(float4(input.normal,0),normalView).xyz;
#if MDS_MODEL_DX9_COMPATIBILITY
    normal=Dx9Normal(input.normal,normalView);
#endif
    if(flags.y) normal=normalize(normal);
    float3 color=diffuse.rgb; float3 highlight=0;
    if(flags.x) {
        color=emissive.rgb + ambient.rgb*globalAmbient.rgb;
        for(uint i=0;i<8;++i) if(lightDirection[i].w) {
            float3 towardLight=-normalize(mul(float4(lightDirection[i].xyz,0),view).xyz);
            float facing=max(dot(normal,towardLight),0);
#if MDS_MODEL_DX9_COMPATIBILITY
            precise float3 scaledMaterial=diffuse.rgb*facing;
            float3 diffuseWithBase=Dx9Lighting(lightDiffuse[i].rgb,scaledMaterial,color);
            color=Dx9Lighting(ambient.rgb,lightAmbient[i].rgb,diffuseWithBase);
#else
            color += ambient.rgb*lightAmbient[i].rgb + diffuse.rgb*lightDiffuse[i].rgb*facing;
#endif
            if(flags.z && facing>0) {
                float3 viewer=flags.w?normalize(-camera.xyz):float3(0,0,-1);
                float3 halfway=normalize(towardLight+viewer);
#if MDS_MODEL_DX9_COMPATIBILITY && MDS_MODEL_SPECULAR_FMA_DIAGNOSTIC
                if(flags.w) {
                    float inverse=rsqrt(dot(camera.xyz,camera.xyz));
                    halfway=normalize(Dx9Lighting(-camera.xyz,inverse.xxx,towardLight));
                }
#endif
                highlight += specular.rgb*lightSpecular[i].rgb*pow(max(dot(normal,halfway),0),parameters.x);
            }
        }
    }
    output.litDiffuse=float4(saturate(color),diffuse.a);output.specular=saturate(highlight);
#endif
#if MDS_MODEL_VERTEX_BYTE
    output.litDiffuse=floor(output.litDiffuse*255+0.5)/255;
#endif
    output.coordinate0=Coordinate(0,coordinates.x,normal,uv);
    output.coordinate1=Coordinate(1,coordinates.y,normal,uv);
    output.coordinate2=Coordinate(2,coordinates.z,normal,uv);
    return output;
}
