#pragma once
#include "mikudancestudio/rhi_d3d9_replay_conversion.hpp"
#include <filesystem>
#include <fstream>
#include <sstream>
#include <map>
#include <cstring>
// Read the existing diagnostic text/bytes, never reinterpret a native state
// block. Archives without texture descriptors cannot prove textured inputs.
inline bool ReadUntexturedReduction(const std::filesystem::path& stateFile,
    mikudancestudio::rhi::D3D9ReplaySnapshot& c,bool allowTextures=false) {
    std::ifstream file(stateFile);if(!file)return false;c={};unsigned matrices=0;
    struct Prepared {unsigned stage,level,width,height;std::uint64_t hash;};std::vector<Prepared> prepared;
    std::string line;bool draw=false,viewport=false,world=false,view=false,projection=false,material=false;
    try {while(std::getline(file,line)) {
        std::istringstream input(line);std::string kind,token;input>>kind;
        std::map<std::string,std::string> values;
        while(input>>token){const auto eq=token.find('=');if(eq!=std::string::npos)values[token.substr(0,eq)]=token.substr(eq+1);}
        auto u=[&](const char* key){return static_cast<unsigned>(std::stoul(values.at(key)));};
        auto floats=[&](void* data,unsigned count){for(unsigned n=0;n<count;++n){float f=std::stof(values.at("f"+std::to_string(n)));std::memcpy(static_cast<char*>(data)+n*4,&f,4);}};
        if(kind=="DRAW") {c.type=u("type");c.fvf=u("fvf");c.indexed=u("indexed")!=0;c.base=std::stoi(values.at("base"));
            c.minimum=u("minimum");c.vertices=u("vertices");c.start=u("start");c.count=u("count");c.offset=u("offset");c.stride=u("stride");draw=true;}
        else if(kind=="VIEWPORT"){c.viewport={u("x"),u("y"),u("width"),u("height"),std::stof(values.at("minZ")),std::stof(values.at("maxZ"))};viewport=true;}
        else if(kind=="WORLD"){floats(&c.world,16);world=true;}
        else if(kind=="VIEW"){floats(&c.view,16);view=true;}
        else if(kind=="PROJECTION"){floats(&c.projection,16);projection=true;}
        else if(kind=="MATERIAL"){floats(&c.material,17);material=true;}
        else if(kind=="LIGHT"){mikudancestudio::rhi::D3D9ReplaySnapshot::Light l{};l.index=u("index");l.enabled=u("enabled");l.value.Type=static_cast<D3DLIGHTTYPE>(u("type"));c.lights.push_back(l);}
        else if(kind=="LIGHT_VALUES"){if(c.lights.empty())return false;floats(&c.lights.back().value.Diffuse,25);}
        else if(kind=="RS")c.renderStates.push_back({0,u("key"),u("value")});
        else if(kind=="TSS")c.stageStates.push_back({u("stage"),u("key"),u("value")});
        else if(kind=="SAMPLER")c.samplerStates.push_back({u("stage"),u("key"),u("value")});
        else if(kind=="SCISSOR"){c.scissor={std::stoi(values.at("left")),std::stoi(values.at("top")),std::stoi(values.at("right")),std::stoi(values.at("bottom"))};}
        else if(kind=="PREPARED_MIP")prepared.push_back({u("stage"),u("level"),u("width"),u("height"),std::stoull(values.at("hash"))});
        else if(kind=="TEXTURE" && allowTextures) {
            const auto stage=u("stage");if(stage>=8)return false;
            c.textureInfo[stage]={u("present")!=0,static_cast<D3DFORMAT>(u("format")),u("width"),u("height"),u("levels"),u("lod"),u("autogen")!=0,u("filter")};
        }
        else if(kind=="TEXTURE_MATRIX"){if(matrices>=8)return false;floats(&c.textureMatrices[matrices++],16);}
    }}catch(...){return false;}
    auto stem=stateFile;stem.replace_extension();
    auto bytes=[](const std::filesystem::path& path,std::vector<unsigned char>& out){std::ifstream f(path,std::ios::binary);if(!f)return false;out.assign(std::istreambuf_iterator<char>(f),{});return !out.empty();};
    for(unsigned stage=0;stage<8;++stage) {
        const auto path=stem.string()+".texture"+std::to_string(stage);
        if(c.textureInfo[stage].present) {if(!allowTextures || !bytes(path,c.textureBytes[stage]))return false;}
        else if(std::filesystem::exists(path))return false;
    }
    for(const auto& mip:prepared) {
        if(!allowTextures || mip.stage>=8 || !c.textureInfo[mip.stage].present || !c.textureInfo[mip.stage].autogen || mip.level!=c.preparedMips[mip.stage].levels.size())return false;
        mikudancestudio::rhi::RgbaImage image{mip.width,mip.height,{}};
        if(!bytes(stem.string()+".prepared"+std::to_string(mip.stage)+"."+std::to_string(mip.level)+".rgba",image.pixels) || image.pixels.size()!=std::size_t(mip.width)*mip.height*4)return false;
        std::uint64_t hash=14695981039346656037ull;for(auto byte:image.pixels)hash=(hash^byte)*1099511628211ull;if(hash!=mip.hash)return false;
        c.preparedMips[mip.stage].levels.push_back(std::move(image));
    }
    // Legacy reduction exporter has no index-format tag: retrieve it from the
    // matching native recorder BUFFER entry, never assume 16-bit indices.
    std::ifstream log(stateFile.parent_path()/"history_replay.dx9");unsigned sequence=0;
    {std::ifstream header(stateFile);std::getline(header,line);const auto p=line.find("sequence=");if(p==std::string::npos)return false;sequence=static_cast<unsigned>(std::stoul(line.substr(p+9)));}
    while(std::getline(log,line))if(line.find("BUFFER sequence="+std::to_string(sequence)+" kind=index ")==0) {
        const auto p=line.find("format=");if(p!=std::string::npos)c.indexFormat=static_cast<D3DFORMAT>(std::stoul(line.substr(p+7)));break;
    }
    return draw && viewport && world && view && projection && material && matrices==8 &&
        bytes(stem.string()+".vertices",c.vertexBytes) &&
        (!c.indexed || (c.indexFormat!=D3DFMT_UNKNOWN && bytes(stem.string()+".indices",c.indexBytes)));
}
