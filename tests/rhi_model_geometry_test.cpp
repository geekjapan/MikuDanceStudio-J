#include "mikudancestudio/render_model_geometry.hpp"
#include <cstdio>
#include <cstring>
using namespace mikudancestudio;
using namespace rhi;
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
ModelReplayStream Stream(const render::ModelGeometrySnapshot& geometry,bool edge=false){
    ModelReplayStream stream;stream.target.width=stream.target.height=64;stream.events.push_back({1,ModelReplayOp::Clear});
    ModelReplayDraw draw;draw.indexCount=3;draw.pipeline.vertexLayout=edge?VertexLayout::PositionColor:VertexLayout::PositionNormalUv;
    for(auto* m:{&draw.pipeline.shader.world,&draw.pipeline.shader.view,&draw.pipeline.shader.projection,&draw.pipeline.shader.normalView})*m={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    if(!render::AppendModelGeometry(stream,geometry,draw,edge))return {};
    stream.complete=true;return stream;
}
int main(){
    const std::uint16_t indices[]={0,1,2};render::ModelGeometry geometry(101,3);
    auto* vertices=static_cast<render::ModelVertex*>(geometry.MainData());
    const render::ModelVertex triangle[]={{{-.5f,.5f,.5f},{0,0,1},{0,0}},{{.5f,.5f,.5f},{0,0,1},{1,0}},{{0,-.5f,.5f},{0,0,1},{.5f,1}}};
    std::memcpy(vertices,triangle,sizeof(triangle));for(auto& edge:geometry.Edges())edge.diffuse=0x7f123456;
    CHECK(!geometry.Publish());CHECK(geometry.SetIndices(IndexFormat::UInt16,indices,sizeof(indices)) && geometry.Publish());
    const auto saved=geometry.Snapshot();CHECK(saved.main.key.id==101 && saved.edge.key.id==102 && saved.indices.key.id==103);
    CHECK(saved.main.bytes.size()==96 && saved.edge.bytes.size()==48 && saved.indices.key.version==1);
    const unsigned char rgba[]={0x12,0x34,0x56,0x7f};CHECK(!std::memcmp(saved.edge.bytes.data()+12,rgba,4));
    CHECK(geometry.Publish() && geometry.Snapshot().main.key.version==1);
    vertices[0].position[0]+=.125f;CHECK(geometry.Publish() && geometry.Snapshot().main.key.version==2 && saved.main.key.version==1);
    CHECK(saved.main.bytes!=geometry.Snapshot().main.bytes && geometry.Snapshot().edge.key.version==1);
    geometry.Edges()[0].diffuse=0xffabcdef;CHECK(geometry.Publish() && geometry.Snapshot().edge.key.version==2);
    const std::uint16_t invalid[]={0,1,3};CHECK(!geometry.SetIndices(IndexFormat::UInt16,invalid,sizeof(invalid)) && geometry.Snapshot().indices.bytes==saved.indices.bytes);
    const std::uint32_t wide[]={0,1,2};CHECK(!geometry.SetIndices(IndexFormat::UInt32,wide,sizeof(wide)));
    auto stream=Stream(geometry.Snapshot());CHECK(ValidateModelReplay(stream));
    for(unsigned n=0;n<100;++n){CHECK(geometry.Publish());CHECK(ValidateModelReplay(Stream(geometry.Snapshot())));}
    CHECK(geometry.Snapshot().main.key.version==2);
    geometry.Edges().pop_back();CHECK(!geometry.Publish());geometry.Edges().emplace_back();
    vertices[1].position[1]-=.125f;CHECK(geometry.Publish() && geometry.Snapshot().main.key.version==3);
    CHECK(ValidateModelReplay(Stream(geometry.Snapshot(),true)));
    auto duplicate=Stream(geometry.Snapshot());const auto before=duplicate.events.size();auto draw=duplicate.events.back().draw;
    CHECK(render::AppendModelGeometry(duplicate,geometry.Snapshot(),draw) && duplicate.events.size()==before+1 && duplicate.resources.size()==2 && ValidateModelReplay(duplicate));
    auto collision=geometry.Snapshot();collision.main.bytes[0]^=1;CHECK(!render::AppendModelGeometry(duplicate,collision,draw) && duplicate.events.size()==before+1);
    for(unsigned uv=1;uv<=4;++uv){render::ModelGeometry extended(1001+3*uv,3,uv);CHECK(extended.MainSize()==3*(32+16*uv));
        CHECK(extended.SetIndices(IndexFormat::UInt32,wide,sizeof(wide)) && extended.Publish());
        ModelReplayStream rejected;rejected.events.push_back({1,ModelReplayOp::Clear});CHECK(render::AppendModelGeometry(rejected,extended.Snapshot(),draw).reason=="unsupported_additional_uv_layout" && rejected.events.size()==1 && rejected.resources.empty());}
    std::puts("CPU geometry ownership, immutable versions, ARGB conversion, repeated publication and unsupported layouts passed");return 0;
}
