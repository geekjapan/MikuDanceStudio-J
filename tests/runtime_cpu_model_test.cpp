#include "mikudancestudio/runtime_cpu_model.hpp"
#include "model_reader_fixture.hpp"
#define WIN32_LEAN_AND_MEAN
#include <Windows.h>
#include <filesystem>
#include <fstream>
#include <cstdio>
#include <limits>
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s reason=%s\n",__LINE__,#x,reason.c_str());return 1;}}while(0)
using namespace mikudancestudio;
int main(){
    std::string reason;
    const auto root=std::filesystem::temp_directory_path()/("mds-cpu-import-"+std::to_string(GetCurrentProcessId()));
    std::filesystem::create_directories(root);
    struct Cleanup {std::filesystem::path root;~Cleanup(){std::error_code e;std::filesystem::remove_all(root,e);}}cleanup{root};
    const auto cwd=std::filesystem::current_path();
    for(bool pmx:{false,true}){
        const auto bytes=pmx?model_reader_fixture::Pmx(true,true):model_reader_fixture::Pmd(true,true);
        const auto path=root/(pmx?"fixture.pmx":"fixture.pmd");
        {std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(bytes.data.data()),bytes.data.size());CHECK(out);}
        RuntimeCpuModel model;CHECK(model.Load(path,reason));CHECK(std::filesystem::current_path()==cwd);
        auto* geometry=model.Geometry();CHECK(geometry && geometry->vertexCount==1 && geometry->indices.bytes.size()==6);
        const auto index=geometry->indices.bytes;const auto identity=geometry->indices.key.id;
        std::vector<render::ModelMatrix> matrices(1,{1,0,0,0,0,1,0,0,0,0,1,0,2,0,0,1});
        std::vector<float> morphs(1);
        for(unsigned n=0;n<10;++n){CHECK(model.Deform(matrices,morphs,0,false,reason));
            const auto& result=*model.Geometry();render::ModelVertex vertex;std::memcpy(&vertex,result.main.bytes.data(),sizeof(vertex));
            CHECK(vertex.position[0]==(pmx?3.f:5.f));CHECK(result.indices.bytes==index && result.indices.key.id==identity);
            const auto version=result.main.key.version;CHECK(model.Deform(matrices,morphs,0,false,reason) && model.Geometry()->main.key.version==version);
        }
        if(pmx){morphs[0]=.5f;CHECK(model.Deform(matrices,morphs,.01f,false,reason));
            render::ModelVertex vertex;std::memcpy(&vertex,model.Geometry()->main.bytes.data(),sizeof(vertex));
            CHECK(vertex.position[0]==4.5f);morphs[0]=0;CHECK(model.Deform(matrices,morphs,0,false,reason));}
        const auto before=model.Geometry()->main.bytes;
        matrices[0][12]=std::numeric_limits<float>::quiet_NaN();CHECK(!model.Deform(matrices,morphs,0,false,reason) && model.Geometry()->main.bytes==before);
        CHECK(!model.Load(root/"missing.pmd",reason) && model.Geometry()->main.bytes==before && std::filesystem::current_path()==cwd);
        {std::ofstream malformed(root/"truncated.pmx",std::ios::binary);malformed.write(reinterpret_cast<const char*>(bytes.data.data()),32);}
        CHECK(!model.Load(root/"truncated.pmx",reason) && model.Geometry()->main.bytes==before && std::filesystem::current_path()==cwd);
    }
    std::puts("PASS: PMD/PMX CPU-only import with physics records, legacy deformation, stable indices, rejected invalid updates and atomic reload; no native device created");return 0;
}
