#include "mikudancestudio/render_scene_passes.hpp"
#include <cstdio>
#include <cstring>
using namespace mikudancestudio;
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(){
    render::ModelFrameInputs frame;frame.scene.frame=7;frame.scene.camera.distance=-38;frame.scene.camera.fov=35;
    frame.scene.lightState={.6f,.7f,.8f,-.5f,-1,.5f};frame.view.viewport={3,5,64,48,0,1};frame.view.aspect=4.f/3;
    frame.world=frame.lightRotation={1,0,0,0,0,1,0,0,0,0,1,0,-4,-12,0,1};
    render::ScenePassSettings settings;rhi::HistoryDesc target;target.width=80;target.height=64;
    rhi::ModelReplayStream lines,plane,joined;CHECK(render::BuildGroundDraw(frame,render::SceneDrawFamily::GroundLines,settings,target,{1,1,1,1},lines));
    CHECK(render::BuildGroundDraw(frame,render::SceneDrawFamily::GroundPlane,settings,target,{1,1,1,1},plane));
    CHECK(rhi::ComposeModelReplay(lines,plane,joined));CHECK(rhi::ValidateModelReplay(joined).draws==2);
    CHECK(lines.resources[0].bytes.size()==1440 && lines.resources[1].bytes.size()==180 && plane.resources[0].bytes.size()==96);
    const auto& bytes=lines.resources[0].bytes;CHECK(bytes[12]==0 && bytes[13]==0 && bytes[14]==255 && bytes[15]==255);
    CHECK(plane.resources[0].bytes[15]==0); // Transparent ground still writes depth.
    CHECK(plane.events.back().draw.pipeline.raster.depthWrite && !plane.events.back().draw.pipeline.shader.alphaTest);
    // Frame-to-frame HUD history is a CPU input; it must affect only the
    // ground blend state while retaining transparent-plane depth writes.
    auto nextFrame=frame;nextFrame.groundAlphaBlend=true;rhi::ModelReplayStream nextPlane;
    CHECK(render::BuildGroundDraw(nextFrame,render::SceneDrawFamily::GroundPlane,settings,target,{1,1,1,1},nextPlane));
    CHECK(nextPlane.events.back().draw.pipeline.raster.alphaBlend && nextPlane.events.back().draw.pipeline.raster.depthWrite);
    auto nextReference=plane;nextReference.events.back().draw.pipeline.raster.alphaBlend=true;
    CHECK(render::CompareModelInputs(nextPlane.events.back().draw.pipeline,nextReference.events.back().draw.pipeline).empty());
    rhi::ModelPipeline shadow;CHECK(render::BuildScenePassInputs(frame,render::SceneDrawFamily::ProjectedModelShadow,settings,shadow));
    CHECK(shadow.stencilReference==2 && shadow.stencilCompare==rhi::DepthComparison::Greater && shadow.raster.depthCompare==rhi::DepthComparison::Less);
    CHECK(shadow.shader.world[5]==0 && shadow.shader.world[13]==-11.9f);
    auto invalid=frame;invalid.scene.lightState[4]=0;CHECK(!render::BuildScenePassInputs(invalid,render::SceneDrawFamily::ProjectedModelShadow,settings,shadow));
    rhi::ModelPipeline outline;CHECK(render::BuildScenePassInputs(frame,render::SceneDrawFamily::ModelOutline,settings,outline));
    CHECK(outline.vertexLayout==rhi::VertexLayout::PositionColor && !outline.shader.lighting && outline.raster.alphaBlend);
    CHECK(outline.raster.cull==rhi::BatchCull::Clockwise && outline.raster.depthCompare==rhi::DepthComparison::Less);
    render::AccessoryPassInputs accessory;accessory.material.diffuse={.1f,.2f,.3f,.8f};accessory.opacity=.5f;
    rhi::ModelPipeline ap;CHECK(render::BuildAccessoryPassInputs(frame,accessory,settings,ap));
    CHECK(ap.shader.nativeDiffuse[3]==.4f && ap.shader.normalizeNormals && ap.shader.lights[0].diffuse[0]==10);
    auto tailFrame=frame;tailFrame.scene.lightState[0]=.1f;accessory.afterModelPass=true;
    CHECK(render::BuildAccessoryPassInputs(tailFrame,accessory,settings,ap));
    float tailAmbient=.1f;tailAmbient-=.300000011920929f;tailAmbient+=.300000011920929f;tailAmbient-=.300000011920929f;
    CHECK(ap.shader.lights[0].ambient[0]==tailAmbient);accessory.afterModelPass=false;
    accessory.primaryTexture=true;accessory.sphereTexture=true;accessory.textureType=5;accessory.additive=true;
    CHECK(render::BuildAccessoryPassInputs(frame,accessory,settings,ap));
    CHECK(ap.raster.destinationBlend==rhi::BlendFactor::One && ap.shader.layout.stages[1].color==rhi::MaterialCombine::Add);
    CHECK(ap.shader.textureTransforms[1][5]==-.5f && ap.shader.textureTransforms[1][13]==.5f);
    auto inactiveUv=ap;inactiveUv.shader.textureTransforms[0][0]=123;
    CHECK(render::CompareModelInputs(ap,inactiveUv).empty());
    auto activeUv=ap;activeUv.shader.textureTransforms[1][0]=123;
    CHECK(!render::CompareModelInputs(ap,activeUv).empty());
    accessory.textureType=3;CHECK(!render::BuildAccessoryPassInputs(frame,accessory,settings,ap));
    accessory.primaryTexture=accessory.sphereTexture=false;accessory.unboundScreen=true;
    CHECK(render::BuildAccessoryPassInputs(frame,accessory,settings,ap));
    CHECK(ap.shader.layout.stages[0].role==rhi::MaterialTextureRole::None);
    accessory.primaryTexture=true;CHECK(!render::BuildAccessoryPassInputs(frame,accessory,settings,ap));
    accessory.textureType=0;accessory.opacity=-.1f;CHECK(!render::BuildAccessoryPassInputs(frame,accessory,settings,ap));
    using Replacement=render::SceneDrawReplacement;
    std::vector<Replacement> replacements{{1,render::SceneDrawFamily::GroundLines,0,0,lines},{2,render::SceneDrawFamily::GroundPlane,0,0,plane}};
    rhi::ModelReplayStream output;CHECK(render::ReplaceSceneDraws(joined,replacements,output));CHECK(rhi::ValidateModelReplay(output).draws==2);
    // A baseline mismatch is rejected atomically, even when output aliases it.
    auto wrong=replacements;wrong[0].cpu.events.back().draw.pipeline.raster.depthWrite=false;
    const auto count=output.events.size();const auto saved=output.events.back().draw.vertices;
    CHECK(!render::ReplaceSceneDraws(joined,wrong,output));CHECK(output.events.size()==count && output.events.back().draw.vertices.id==saved.id);
    wrong=replacements;wrong[0].cpu.resources[0].bytes[12]^=1;
    CHECK(render::ReplaceSceneDraws(joined,wrong,output).reason=="scene_geometry_bytes");
    wrong=replacements;wrong[0].cpu.source.frame++;CHECK(!render::ReplaceSceneDraws(joined,wrong,output));
    wrong=replacements;wrong[0].boundary=2;CHECK(!render::ReplaceSceneDraws(joined,wrong,output));
    wrong=replacements;wrong[1].boundary=3;CHECK(!render::ReplaceSceneDraws(joined,wrong,output));
    auto baseline=joined;baseline.events.back().draw.pipeline.shader.nativeDiffuse={.2f,.3f,.4f,.5f};
    CHECK(render::ReplaceSceneDraws(baseline,replacements,output)); // Unlit color comes from CPU vertices.
    baseline=joined;baseline.events.back().draw.pipeline.raster.depthCompare=rhi::DepthComparison::Less;
    CHECK(!render::ReplaceSceneDraws(baseline,replacements,baseline));CHECK(baseline.events.back().draw.pipeline.raster.depthCompare==rhi::DepthComparison::Less);
    CHECK(render::ReplaceSceneDraws(joined,replacements,joined));return 0;
}
