#include "mikudancestudio/rhi_model_replay.hpp"
#include <cstdio>
#include <cstring>
#include <limits>
using namespace mikudancestudio::rhi;
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
ModelReplayStream Fixture() {
    ModelReplayStream s;s.complete=true;s.target.width=s.target.height=64;
    ModelReplayResource v;v.key={1,1};v.bytes.resize(3*32);s.resources.push_back(v);
    ModelReplayResource i;i.key={2,1};i.kind=ReplayResourceKind::Indices;i.bytes={0,0,1,0,2,0};s.resources.push_back(i);
    ModelReplayResource t;t.key={3,1};t.kind=ReplayResourceKind::Texture;t.texture.levels.push_back({1,1,{255,0,0,255}});s.resources.push_back(t);
    t.key.version=2;t.texture.levels[0].pixels={0,255,0,255};s.resources.push_back(t);
    s.events.push_back({1,ModelReplayOp::Clear});
    for(auto key:{ReplayResourceKey{1,1},{2,1},{3,1}}){ModelReplayEvent e;e.sequence=s.events.size()+1;e.op=ModelReplayOp::PublishResource;e.resource=key;s.events.push_back(e);}
    ModelReplayEvent e;e.sequence=5;e.op=ModelReplayOp::Draw;e.draw.vertices={1,1};e.draw.indices={2,1};
    e.draw.vertexCount=e.draw.indexCount=3;e.draw.textures[0]={3,1};
    auto& p=e.draw.pipeline;p.raster.alphaBlend=false;
    for(auto* m:{&p.shader.world,&p.shader.view,&p.shader.projection,&p.shader.normalView})*m={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    p.shader.nativeDiffuse={1,1,1,1};auto& stage=p.shader.layout.stages[0];stage.role=MaterialTextureRole::Base;
    stage.color=MaterialCombine::Modulate;stage.colorArg2=MaterialColorSource::LitDiffuse;s.events.push_back(e);
    ModelReplayEvent update;update.sequence=6;update.op=ModelReplayOp::PublishResource;update.resource={3,2};s.events.push_back(update);
    e.sequence=7;e.draw.textures[0].version=2;s.events.push_back(e);return s;
}
int main() {
    const auto original=Fixture();auto result=ValidateModelReplay(original);CHECK(result && result.draws==2);
    auto colored=original;colored.resources[0].vertexLayout=VertexLayout::PositionColor;colored.resources[0].bytes.resize(3*16);
    for(auto& event:colored.events)if(event.op==ModelReplayOp::Draw) {
        event.draw.pipeline.vertexLayout=VertexLayout::PositionColor;
        event.draw.pipeline.shader.world[10]=0; // singular projection with no normal input
    }
    CHECK(ValidateModelReplay(colored).draws==2);
    auto malformed=colored;malformed.resources[0].bytes.pop_back();CHECK(ValidateModelReplay(malformed).reason=="invalid_vertex_layout");
    malformed=colored;malformed.events[4].draw.pipeline.vertexLayout=VertexLayout::PositionNormalUv;CHECK(ValidateModelReplay(malformed).reason=="vertex_layout_mismatch");
    malformed=colored;malformed.events[4].draw.pipeline.shader.layout.stages[0].coordinates=MaterialCoordinates::CameraNormal;
    CHECK(ValidateModelReplay(malformed).reason=="position_color_has_no_normal_coordinates");
    auto regional=original;regional.initializedRegion=ModelViewport{8,6,40,48,0,1};
    for(auto& e:regional.events)if(e.op==ModelReplayOp::Draw)e.draw.pipeline.viewport=ModelViewport{8,6,40,48,.25f,.75f};
    CHECK(ValidateModelReplay(regional));
    auto reject=[&](ModelReplayStream s,const char* why,std::uint64_t sequence){auto r=ValidateModelReplay(s);return !r && r.reason==why && r.sequence==sequence;};
    auto lines=colored;lines.resources[1].bytes.resize(4);
    for(auto& e:lines.events)if(e.op==ModelReplayOp::Draw){e.draw.pipeline.topology=PrimitiveTopology::LineList;e.draw.indexCount=2;}
    CHECK(ValidateModelReplay(lines).draws==2);
    malformed=lines;malformed.events[4].draw.indexCount=3;CHECK(reject(malformed,"invalid_draw_range",5));
    malformed=lines;malformed.events[4].draw.pipeline.topology=static_cast<PrimitiveTopology>(99);CHECK(reject(malformed,"unsupported_topology",5));
    malformed=lines;malformed.events[4].draw.firstVertex=1;CHECK(reject(malformed,"mixed_draw_ranges",5));
    auto direct=colored;direct.resources[0].bytes.resize(6*16);
    for(auto& e:direct.events)if(e.op==ModelReplayOp::Draw) {
        e.draw.indexed=false;e.draw.indices={};e.draw.firstIndex=e.draw.indexCount=e.draw.vertexCount=0;
        e.draw.firstVertex=3;e.draw.drawVertexCount=3;
    }
    CHECK(ValidateModelReplay(direct).draws==2);
    malformed=direct;malformed.events[4].draw.firstVertex=4;CHECK(reject(malformed,"invalid_draw_range",5));
    malformed=direct;malformed.events[4].draw.firstVertex=0xffffffffu;CHECK(reject(malformed,"invalid_draw_range",5));
    malformed=direct;malformed.events[4].draw.drawVertexCount=0xffffffffu;CHECK(reject(malformed,"invalid_draw_range",5));
    malformed=direct;malformed.events[4].draw.drawVertexCount=0;CHECK(reject(malformed,"invalid_draw_range",5));
    malformed=direct;malformed.events[4].draw.indices={2,1};CHECK(reject(malformed,"mixed_draw_ranges",5));
    malformed=direct;malformed.events[4].draw.vertices.version=2;CHECK(reject(malformed,"missing_or_stale_geometry",5));
    // A nonindexed draw needs no index resource or publication at all.
    direct.resources.erase(direct.resources.begin()+1);direct.events.erase(direct.events.begin()+2);
    for(std::size_t n=0;n<direct.events.size();++n)direct.events[n].sequence=n+1;
    CHECK(ValidateModelReplay(direct).draws==2);
    for(auto& e:direct.events)if(e.op==ModelReplayOp::Draw){e.draw.pipeline.topology=PrimitiveTopology::LineList;e.draw.drawVertexCount=2;}
    CHECK(ValidateModelReplay(direct).draws==2);
    auto bad=original;bad.complete=false;CHECK(reject(bad,"incomplete_stream",0));
    bad=regional;bad.events[4].draw.pipeline.viewport.reset();CHECK(reject(bad,"draw_outside_initialized_region",5));
    bad=regional;bad.initializedRegion->width=0;CHECK(reject(bad,"invalid_initialized_region",0));
    bad=regional;bad.events[4].draw.pipeline.viewport->x=~std::uint32_t(0);CHECK(reject(bad,"invalid_viewport",5));
    bad=regional;bad.events[4].draw.pipeline.viewport->maxDepth=(std::numeric_limits<float>::infinity)();CHECK(reject(bad,"invalid_viewport",5));
    bad=regional;bad.events[4].draw.pipeline.viewport->minDepth=.9f;CHECK(reject(bad,"invalid_viewport",5));
    bad=regional;bad.events[4].draw.pipeline.viewport->maxDepth=.25f;CHECK(ValidateModelReplay(bad));
    bad=original;bad.target.samples=8;CHECK(reject(bad,"unsupported_target",0));
    bad=original;bad.events[0].op=ModelReplayOp::Draw;CHECK(reject(bad,"missing_initial_clear",0));
    bad=original;bad.events[5].sequence=99;CHECK(reject(bad,"non_contiguous_sequence",6));
    bad=original;bad.events[5].op=ModelReplayOp::Unsupported;CHECK(reject(bad,"unsupported_event",6));
    bad=original;bad.events[5].op=ModelReplayOp::Clear;CHECK(reject(bad,"unsupported_additional_clear",6));
    bad=original;bad.events[6].draw.textures[0].version=1;CHECK(reject(bad,"missing_stale_or_mismatched_texture",7));
    bad=original;bad.events[4].draw.textures[0].version=2;CHECK(reject(bad,"missing_stale_or_mismatched_texture",5));
    bad=original;bad.events[5].resource.version=1;CHECK(reject(bad,"non_increasing_resource_version",6));
    bad=original;bad.resources.pop_back();CHECK(reject(bad,"missing_snapshot",6));
    bad=original;bad.resources.push_back(bad.resources.back());CHECK(reject(bad,"duplicate_or_invalid_resource_key",0));
    bad=original;bad.resources[2].texture.levels[0].pixels.pop_back();CHECK(reject(bad,"invalid_mip_data",0));
    bad=original;bad.resources[1].bytes[4]=3;CHECK(reject(bad,"index_out_of_range",5));
    bad=original;bad.events[4].draw.firstIndex=0xffffffffu;CHECK(reject(bad,"invalid_draw_range",5));
    bad=original;bad.events[4].draw.pipeline.shader.layout.stages[0].coordinates=MaterialCoordinates::MeshUv1;CHECK(reject(bad,"unsupported_sampling",5));
    bad=original;bad.events[4].draw.vertices.version=2;CHECK(reject(bad,"missing_or_stale_geometry",5));
    bad=original;bad.resources[2].texture.srgb=true;CHECK(reject(bad,"missing_stale_or_mismatched_texture",5));
    // Copying the stream owns its bytes; later producer edits cannot change it.
    auto snapshot=original;bad=original;bad.resources[2].texture.levels[0].pixels[0]=0;
    CHECK(snapshot.resources[2].texture.levels[0].pixels[0]==255 && ValidateModelReplay(snapshot));
    // Independent producers intentionally collide on all resource IDs. Join
    // preserves versions/order and exactly one clear, without borrowing bytes.
    ModelReplayStream joined;CHECK(ComposeModelReplay(original,original,joined).draws==4);
    CHECK(joined.resources.size()==8 && joined.events.size()==13);
    CHECK(joined.events[7].resource.id==4 && joined.events.back().draw.textures[0].id==6);
    CHECK(joined.events.back().draw.textures[0].version==2 && joined.events[6].draw.textures[0].id==3);
    CHECK(joined.events.back().draw.pipeline.shader.nativeDiffuse==original.events.back().draw.pipeline.shader.nativeDiffuse);
    auto retained=joined;bad=original;bad.target.width++;
    CHECK(ComposeModelReplay(original,bad,joined).reason=="history_target_mismatch" && joined.events.size()==retained.events.size());
    bad=original;bad.source.frame=1;CHECK(ComposeModelReplay(original,bad,joined).reason=="history_scene_or_frame_mismatch");
    bad=original;bad.source.scene=1;CHECK(!ComposeModelReplay(original,bad,joined));
    bad=original;bad.events.back().op=ModelReplayOp::Unsupported;CHECK(!ComposeModelReplay(original,bad,joined));
    CHECK(!ComposeModelReplay(regional,original,joined)); // suffix draws outside known pixels
    CHECK(ComposeModelReplay(regional,regional,joined) && joined.initializedRegion->x==8);
    auto aliased=original;CHECK(ComposeModelReplay(aliased,original,aliased).draws==4);
    CHECK(aliased.resources.back().texture.levels[0].pixels[1]==255);
    // Index versions are interpreted using their explicit width, not native ABI.
    auto wide=original;wide.resources[1].indexFormat=IndexFormat::UInt32;
    wide.resources[1].bytes={0,0,0,0,1,0,0,0,2,0,0,0};CHECK(ValidateModelReplay(wide));
    std::puts("versioned model replay validation passed");return 0;
}
