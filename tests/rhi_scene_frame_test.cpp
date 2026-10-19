#include "mikudancestudio/render_scene_frame.hpp"
#include <cstdio>
using namespace mikudancestudio;
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(){
    render::ModelFrameInputs input;input.scene.frame=7;input.scene.camera.distance=-38;input.scene.camera.fov=35;
    input.scene.lightState={.6f,.7f,.8f,-.5f,-1,.5f};input.view.viewport={3,5,64,48,0,1};input.view.aspect=4.f/3;
    input.world=input.lightRotation={1,0,0,0,0,1,0,0,0,0,1,0,-4,-12,0,1};
    render::SceneFrameDesc desc;desc.target.width=80;desc.target.height=64;desc.frame=7;desc.initializedRegion=input.view.viewport;desc.clear={1,1,1,1};
    render::SceneDrawReplacement lines,plane;lines.family=render::SceneDrawFamily::GroundLines;plane.family=render::SceneDrawFamily::GroundPlane;
    CHECK(render::BuildGroundDraw(input,lines.family,{},desc.target,desc.clear,lines.cpu));
    CHECK(render::BuildGroundDraw(input,plane.family,{},desc.target,desc.clear,plane.cpu));
    render::CpuSceneFrameAssembler assembler;rhi::ModelReplayStream frame;
    assembler.Begin(desc);assembler.Append(lines);assembler.Append(plane);CHECK(assembler.Finish(frame));
    CHECK(frame.source.scene==1 && frame.source.frame==7 && !frame.source.sourceDevice && !frame.source.deviceEpoch);
    CHECK(frame.resources.size()==3 && rhi::ValidateModelReplay(frame).draws==2 && frame.events.front().op==rhi::ModelReplayOp::Clear);
    const auto lineKey=frame.events[3].draw.vertices,planeKey=frame.events.back().draw.vertices;
    CHECK(lineKey.id!=planeKey.id && lineKey.version==1 && planeKey.version==1);
    const auto bytes=assembler.Stats().residentBytes;
    // Order is supplied by the scene, independently of a capture or native IDs.
    for(unsigned n=0;n<1000;++n){assembler.Begin(desc);assembler.Append(plane);assembler.Append(lines);CHECK(assembler.Finish(frame));
        CHECK(frame.events[2].draw.vertices.id==planeKey.id && frame.events[2].draw.vertices.version==1);
        CHECK(frame.events.back().draw.vertices.id==lineKey.id && frame.events.back().draw.vertices.version==1);
        CHECK(assembler.Stats().residentBytes==bytes && assembler.Stats().identityCount==3 && assembler.Stats().publications==3);}
    auto edited=lines;edited.cpu.resources[0].bytes[12]^=1;
    assembler.Begin(desc);assembler.Append(edited);assembler.Append(plane);CHECK(assembler.Finish(frame));
    CHECK(frame.events[3].draw.vertices.id==lineKey.id && frame.events[3].draw.vertices.version==2 && assembler.Stats().publications==4);
    // Any unsupported draw or conflicting bytes blocks the entire frame and
    // consumes neither resource IDs nor versions. The prior output survives.
    const auto prior=frame.events.size();assembler.Begin(desc);assembler.Append(lines);assembler.Append(edited);
    CHECK(assembler.Finish(frame).reason=="conflicting_cpu_resource_in_frame" && frame.events.size()==prior && assembler.Stats().publications==4);
    assembler.Begin(desc);assembler.Append(plane);assembler.Block("target_switch");CHECK(assembler.Finish(frame).reason=="target_switch");
    auto wrong=lines;wrong.cpu.source.frame++;assembler.Begin(desc);assembler.Append(wrong);CHECK(!assembler.Finish(frame));
    // Hidden objects leave only tombstones. Returning with identical source
    // bytes still publishes a newer version, never a retired renderer version.
    assembler.Begin(desc);assembler.Append(plane);CHECK(assembler.Finish(frame));CHECK(assembler.Stats().residentBytes==96);
    assembler.Begin(desc);assembler.Append(lines);assembler.Append(plane);CHECK(assembler.Finish(frame));
    CHECK(frame.events[3].draw.vertices.id==lineKey.id && frame.events[3].draw.vertices.version==3);
    CHECK(assembler.Stats().identityCount==3 && assembler.Stats().residentBytes==bytes);
    assembler.Reset();CHECK(assembler.Stats().identityCount==0 && assembler.Stats().residentBytes==0);
    // Empty scenes are complete clear-only frames, rather than stale pictures.
    assembler.Begin(desc);CHECK(assembler.Finish(frame));CHECK(frame.events.size()==1 && frame.resources.empty());
    // Pending-frame ownership is bounded by unique resources, not draw count.
    assembler.Begin(desc);assembler.Append(lines);const auto staged=assembler.Stats().stagedResourceBytes;
    CHECK(staged>0);for(unsigned n=0;n<256;++n)assembler.Append(lines);
    CHECK(assembler.Stats().stagedResourceBytes==staged);
    CHECK(assembler.Finish(frame) && rhi::ValidateModelReplay(frame).draws==257 && assembler.Stats().stagedResourceBytes==0);
    // Two producers may assign different local texture keys to one immutable
    // CPU asset; remapping must retain each draw's original reference.
    render::ModelGeometry geometry(30,3);const std::uint16_t indices[]={0,1,2};
    CHECK(geometry.SetIndices(rhi::IndexFormat::UInt16,indices,sizeof(indices)) && geometry.Publish());
    render::ModelMaterialPacket packet;packet.indexCount=3;
    CHECK(render::BuildModelInputs(input,{}, {},packet.pipeline));
    auto asset=std::make_shared<rhi::MaterialTextureAsset>();asset->identity="shared-test-toon";
    asset->content={rhi::RgbaImage{1,1,{255,255,255,255}},1};packet.textureResources[0]=asset;
    render::SceneDrawReplacement first,second;first.family=second.family=render::SceneDrawFamily::ModelMaterial;
    first.textureIdentities[0]=second.textureIdentities[0]=asset->identity;second.material=1;
    render::ModelSubmissionBuilder a(100),b(200);
    CHECK(a.Build(geometry.Snapshot(),desc.target,desc.clear,{packet},first.cpu));
    CHECK(b.Build(geometry.Snapshot(),desc.target,desc.clear,{packet},second.cpu));
    first.cpu.source.frame=second.cpu.source.frame=7;assembler.Begin(desc);assembler.Append(first);assembler.Append(second);
    CHECK(assembler.Finish(frame) && frame.resources.size()==3 && rhi::ValidateModelReplay(frame).draws==2);
    std::vector<rhi::ReplayResourceKey> textureKeys;for(const auto& e:frame.events)if(e.op==rhi::ModelReplayOp::Draw)textureKeys.push_back(e.draw.textures[0]);
    CHECK(textureKeys[0].id==textureKeys[1].id && textureKeys[0].version==textureKeys[1].version);
    std::puts("Independent CPU scene frames: order, stable identities, atomic blocking, versions and unload passed");
}
