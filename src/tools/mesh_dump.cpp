// ===========================================================================
// --mds-mesh-dump <pmm> <out-dir> <x-file>...  (wave 3 slice accgold, Windows)
// ===========================================================================
// Loads each accessory file with the native d3dx9 and writes what it made of
// it to "<out-dir>\<file name>.txt", through "<...>.txt.tmp". It is the oracle
// of rust/crates/mds-accessory (tests/fixtures/rust/accessory/README.md). The
// PMM only hosts the device: WinMain loads it before any mode runs.
//
// Three sections per file, each from its own load of the same path:
//   raw     D3DXLoadMeshFromXW(path, 544), the call of LoadAccessoryObject,
//           before LoadAccessoryObject touches the result.
//   frames  D3DXLoadMeshHierarchyFromXW(path, 544): the frame tree with each
//           frame's own matrix, and the meshes it holds.
//   record  LoadAccessoryObject (src/render/accessory.cpp) on a fresh record,
//           as LoadAccessoryFile makes it, without the slot table and the UI.
// A .vac file gets the record section only (LoadAccessoryObject reads it; D3DX
// does not). A failed load prints its HRESULT, or "record failed", and the
// dump goes on. Format, LF line ends, floats "%.9g" (reads back to the same
// float), strings in double quotes with '"', '\', and bytes outside 0x20..0x7E
// written as \xHH:
//   "mds-mesh-dump 1"
//   "file" name
//   "raw hr" 0x........                  (on failure, ends the section)
//   "raw fvf" fvf "options" o "vertices" n "faces" n "stride" bytes
//   "decl" offset type usage usageIndex  (per element of GetDeclaration)
//   "v" i values...                      (per element: FLOATn as floats,
//                                         D3DCOLOR as 8 hex digits, any other
//                                         type as its 32-bit words in hex)
//   "f" i i0 i1 i2 attribute             (the index and attribute buffers)
//   "table" n, then "t" id faceStart faceCount vertexStart vertexCount
//   "materials" n ["none"], then        ("none": D3DX returned no material buffer)
//                         "m" i diffuse.rgba ambient.rgba specular.rgba
//                         emissive.rgba power texture   (D3DXMATERIAL; texture
//                         is "-" for a null pTextureFilename)
//   "frames hr" 0x........               (on failure)
//   "frames unavailable"                 (d3dx9_43.dll lacks the two functions)
//   "frame" depth name m00 m01 .. m33    (depth first; the matrix row by row)
//   "container" name "vertices" n "faces" n "materials" n
//   "record failed" | "record fvf" fvf "options" o "vertices" ... as raw,
//   then its decl, v, f, table lines, then
//   "rm" i diffuse.rgba ambient.rgba specular.rgba emissive.rgba power type
//        primary sphere                  (record materials and textureTypes;
//                                         texture paths after the record's
//                                         directory, UTF-8)
//   "name" record.name
//   "place" visible scale pos.xyz rot.xyz shadowEnabled parentModel parentBone
//           opacity additiveBlend
// =========================================================================//
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3dx9.h> // the mirror of third_party/mmeffect/include

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <filesystem>
#include <fstream>
#include <new>
#include <string>
#include <vector>

#include "mikudancestudio/accessory_layout.hpp"
#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/ported_funcs.hpp"

#include "trace_mode.hpp"

namespace mikudancestudio::tools {
namespace {

constexpr DWORD kAccessoryMeshOptions = 544; // LoadAccessoryObject's D3DXLoadMeshFromXW options

void Add(std::string& out, const char* format, ...) {
    char buffer[512];
    va_list args;
    va_start(args, format);
    std::vsnprintf(buffer, sizeof buffer, format, args);
    va_end(args);
    out += buffer;
}

void AddFloats(std::string& out, const float* values, int count) {
    for (int i = 0; i < count; ++i)
        Add(out, " %.9g", values[i]);
}

void AddQuoted(std::string& out, const char* text, std::size_t length) {
    out += " \"";
    for (std::size_t i = 0; i < length; ++i) {
        const auto c = static_cast<unsigned char>(text[i]);
        if (c < 0x20 || c > 0x7E || c == '"' || c == '\\')
            Add(out, "\\x%02X", c);
        else
            out += static_cast<char>(c);
    }
    out += '"';
}

void AddQuoted(std::string& out, const char* text) {
    if (text == nullptr)
        out += " -";
    else
        AddQuoted(out, text, std::strlen(text));
}

void AddQuotedWide(std::string& out, const wchar_t* text) {
    const int size = WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
    std::string utf8(size > 1 ? static_cast<std::size_t>(size) : 1, '\0');
    if (size > 1)
        WideCharToMultiByte(CP_UTF8, 0, text, -1, &utf8[0], size, nullptr, nullptr);
    AddQuoted(out, utf8.c_str(), std::strlen(utf8.c_str()));
}

void AddColor(std::string& out, const D3DCOLORVALUE& c) {
    const float v[4] = {c.r, c.g, c.b, c.a};
    AddFloats(out, v, 4);
}

void AddMaterial(std::string& out, const D3DMATERIAL9& m) {
    AddColor(out, m.Diffuse);
    AddColor(out, m.Ambient);
    AddColor(out, m.Specular);
    AddColor(out, m.Emissive);
    Add(out, " %.9g", m.Power);
}

// The size of one element of a vertex declaration (d3d9types.h D3DDECLTYPE).
UINT ElementBytes(BYTE type) {
    switch (type) {
    case D3DDECLTYPE_FLOAT1:
        return 4;
    case D3DDECLTYPE_FLOAT2:
        return 8;
    case D3DDECLTYPE_FLOAT3:
        return 12;
    case D3DDECLTYPE_FLOAT4:
        return 16;
    case D3DDECLTYPE_SHORT4:
    case D3DDECLTYPE_SHORT4N:
    case D3DDECLTYPE_USHORT4N:
    case D3DDECLTYPE_FLOAT16_4:
        return 8;
    default:
        return 4;
    }
}

// The fvf, decl, v, f, and table lines of a mesh. False if a buffer cannot be
// locked.
bool AddMesh(std::string& out, const char* section, ID3DXMesh* mesh) {
    const DWORD vertices = mesh->GetNumVertices();
    const DWORD faces = mesh->GetNumFaces();
    const DWORD stride = mesh->GetNumBytesPerVertex();
    const DWORD options = mesh->GetOptions();
    Add(out, "%s fvf %lu options %lu vertices %lu faces %lu stride %lu\n", section, mesh->GetFVF(),
        options, vertices, faces, stride);
    D3DVERTEXELEMENT9 decl[65] = {}; // MAX_FVF_DECL_SIZE
    if (FAILED(mesh->GetDeclaration(decl)))
        return false;
    std::vector<D3DVERTEXELEMENT9> elements;
    for (const D3DVERTEXELEMENT9& e : decl) {
        if (e.Stream == 0xFF)
            break;
        elements.push_back(e);
        Add(out, "decl %u %u %u %u\n", e.Offset, e.Type, e.Usage, e.UsageIndex);
    }

    void* locked = nullptr;
    if (FAILED(mesh->LockVertexBuffer(D3DLOCK_READONLY, &locked)))
        return false;
    const auto* vb = static_cast<const unsigned char*>(locked);
    for (DWORD i = 0; i < vertices; ++i) {
        const unsigned char* vertex = vb + static_cast<std::size_t>(i) * stride;
        Add(out, "v %lu", i);
        for (const D3DVERTEXELEMENT9& e : elements) {
            const unsigned char* p = vertex + e.Offset;
            if (e.Type <= D3DDECLTYPE_FLOAT4) {
                float values[4];
                std::memcpy(values, p, 4u * (e.Type + 1u));
                AddFloats(out, values, e.Type + 1);
            } else {
                for (UINT k = 0; k < ElementBytes(e.Type); k += 4) {
                    std::uint32_t word;
                    std::memcpy(&word, p + k, 4);
                    Add(out, " %08x", word);
                }
            }
        }
        out += '\n';
    }
    mesh->UnlockVertexBuffer();

    void* ib = nullptr;
    if (FAILED(mesh->LockIndexBuffer(D3DLOCK_READONLY, &ib)))
        return false;
    DWORD* attributes = nullptr;
    if (FAILED(mesh->LockAttributeBuffer(D3DLOCK_READONLY, &attributes))) {
        mesh->UnlockIndexBuffer();
        return false;
    }
    const bool wide = (options & 1) != 0; // D3DXMESH_32BIT
    for (DWORD f = 0; f < faces; ++f) {
        std::uint32_t index[3];
        for (int k = 0; k < 3; ++k)
            index[k] = wide ? static_cast<const std::uint32_t*>(ib)[f * 3 + k]
                            : static_cast<const std::uint16_t*>(ib)[f * 3 + k];
        Add(out, "f %lu %u %u %u %lu\n", f, index[0], index[1], index[2], attributes[f]);
    }
    mesh->UnlockAttributeBuffer();
    mesh->UnlockIndexBuffer();

    DWORD tableSize = 0;
    mesh->GetAttributeTable(nullptr, &tableSize);
    std::vector<D3DXATTRIBUTERANGE> table(tableSize);
    if (tableSize != 0 && FAILED(mesh->GetAttributeTable(table.data(), &tableSize)))
        return false;
    Add(out, "table %lu\n", tableSize);
    for (const D3DXATTRIBUTERANGE& t : table)
        Add(out, "t %lu %lu %lu %lu %lu\n", t.AttribId, t.FaceStart, t.FaceCount, t.VertexStart,
            t.VertexCount);
    return true;
}

bool AddRaw(std::string& out, IDirect3DDevice9* device, const std::wstring& path) {
    ID3DXBuffer* materialBuffer = nullptr;
    DWORD materialCount = 0;
    ID3DXMesh* mesh = nullptr;
    const HRESULT hr = D3DXLoadMeshFromXW(path.c_str(), kAccessoryMeshOptions, device, nullptr,
                                          &materialBuffer, nullptr, &materialCount, &mesh);
    if (FAILED(hr)) {
        Add(out, "raw hr 0x%08lx\n", static_cast<unsigned long>(hr));
        return true;
    }
    bool ok = AddMesh(out, "raw", mesh);
    Add(out, "materials %lu%s\n", materialCount, materialBuffer == nullptr ? " none" : "");
    if (materialBuffer != nullptr) {
        const auto* materials =
            static_cast<const D3DXMATERIAL*>(materialBuffer->GetBufferPointer());
        for (DWORD i = 0; i < materialCount; ++i) {
            Add(out, "m %lu", i);
            AddMaterial(out, materials[i].MatD3D);
            AddQuoted(out, materials[i].pTextureFilename);
            out += '\n';
        }
        materialBuffer->Release();
    }
    mesh->Release();
    return ok;
}

// The d3dx9anim.h types of the June 2010 SDK. The mirror header
// (third_party/mmeffect/include/d3dx9.h) has none of them, and the import
// library has neither function, so both come from the loaded d3dx9_43.dll.
struct MeshContainer;
struct Frame {
    char* name;
    D3DMATRIX matrix;
    MeshContainer* containers;
    Frame* sibling;
    Frame* firstChild;
};
struct MeshData {
    DWORD type; // D3DXMESHTYPE_MESH = 1
    ID3DXMesh* mesh;
};
struct MeshContainer {
    char* name;
    MeshData data;
    D3DXMATERIAL* materials;
    void* effects;
    DWORD materialCount;
    DWORD* adjacency;
    IUnknown* skinInfo;
    MeshContainer* next;
};
struct AllocateHierarchy {
    virtual HRESULT __stdcall CreateFrame(const char* name, Frame** frame) = 0;
    virtual HRESULT __stdcall CreateMeshContainer(const char* name, const MeshData* data,
                                                  const D3DXMATERIAL* materials,
                                                  const void* effects, DWORD materialCount,
                                                  const DWORD* adjacency, IUnknown* skinInfo,
                                                  MeshContainer** container) = 0;
    virtual HRESULT __stdcall DestroyFrame(Frame* frame) = 0;
    virtual HRESULT __stdcall DestroyMeshContainer(MeshContainer* container) = 0;
};
using LoadMeshHierarchyFromXW = HRESULT(WINAPI*)(LPCWSTR, DWORD, IDirect3DDevice9*,
                                                 AllocateHierarchy*, void*, Frame**, IUnknown**);
using FrameDestroy = HRESULT(WINAPI*)(Frame*, AllocateHierarchy*);

// Keeps what the dump prints; D3DX fills the rest.
struct Hierarchy final : AllocateHierarchy {
    static char* Copy(const char* name) {
        if (name == nullptr)
            return nullptr;
        const std::size_t size = std::strlen(name) + 1;
        char* copy = new char[size];
        std::memcpy(copy, name, size);
        return copy;
    }
    HRESULT __stdcall CreateFrame(const char* name, Frame** frame) override {
        auto* created = new Frame{};
        created->name = Copy(name);
        *frame = created;
        return S_OK;
    }
    HRESULT __stdcall CreateMeshContainer(const char* name, const MeshData* data,
                                          const D3DXMATERIAL*, const void*, DWORD materialCount,
                                          const DWORD*, IUnknown*,
                                          MeshContainer** container) override {
        auto* created = new MeshContainer{};
        created->name = Copy(name);
        created->data = *data;
        if (data->mesh != nullptr)
            data->mesh->AddRef();
        created->materialCount = materialCount;
        *container = created;
        return S_OK;
    }
    HRESULT __stdcall DestroyFrame(Frame* frame) override {
        delete[] frame->name;
        delete frame;
        return S_OK;
    }
    HRESULT __stdcall DestroyMeshContainer(MeshContainer* container) override {
        delete[] container->name;
        if (container->data.mesh != nullptr)
            container->data.mesh->Release();
        delete container;
        return S_OK;
    }
};

void AddFrames(std::string& out, const Frame* frame, int depth) {
    for (; frame != nullptr; frame = frame->sibling) {
        Add(out, "frame %d", depth);
        AddQuoted(out, frame->name);
        AddFloats(out, &frame->matrix.m[0][0], 16);
        out += '\n';
        for (const MeshContainer* c = frame->containers; c != nullptr; c = c->next) {
            out += "container";
            AddQuoted(out, c->name);
            ID3DXMesh* mesh = c->data.type == 1 ? c->data.mesh : nullptr;
            Add(out, " vertices %lu faces %lu materials %lu\n",
                mesh != nullptr ? mesh->GetNumVertices() : 0ul,
                mesh != nullptr ? mesh->GetNumFaces() : 0ul, c->materialCount);
        }
        AddFrames(out, frame->firstChild, depth + 1);
    }
}

void AddHierarchy(std::string& out, IDirect3DDevice9* device, const std::wstring& path) {
    const HMODULE d3dx = GetModuleHandleW(L"d3dx9_43.dll");
    const auto load = d3dx == nullptr ? nullptr
                                      : reinterpret_cast<LoadMeshHierarchyFromXW>(
                                            GetProcAddress(d3dx, "D3DXLoadMeshHierarchyFromXW"));
    const auto destroy =
        d3dx == nullptr ? nullptr
                        : reinterpret_cast<FrameDestroy>(GetProcAddress(d3dx, "D3DXFrameDestroy"));
    if (load == nullptr || destroy == nullptr) {
        out += "frames unavailable\n";
        return;
    }
    Hierarchy allocator;
    Frame* root = nullptr;
    IUnknown* animation = nullptr;
    const HRESULT hr =
        load(path.c_str(), kAccessoryMeshOptions, device, &allocator, nullptr, &root, &animation);
    if (FAILED(hr)) {
        Add(out, "frames hr 0x%08lx\n", static_cast<unsigned long>(hr));
        return;
    }
    AddFrames(out, root, 0);
    if (animation != nullptr)
        animation->Release();
    destroy(root, &allocator);
}

// The texture path LoadOneTexture stored, after the record's directory.
const wchar_t* AfterDirectory(const wchar_t* path, const wchar_t* directory) {
    const std::size_t length = std::wcslen(directory);
    return _wcsnicmp(path, directory, length) == 0 ? path + length : path;
}

bool AddRecord(std::string& out, MMDApp* app, const std::wstring& path) {
    void* accessory = ::operator new(sizeof(mdl::AccessoryRecord), std::nothrow);
    if (accessory == nullptr)
        return false;
    std::memset(accessory, 0, sizeof(mdl::AccessoryRecord));
    InitAccessoryRecord(accessory); // as LoadAccessoryFile
    mdl::AccessoryRecord& record = *mdl::Accessory(accessory);
    bool ok = true;
    if (!LoadAccessoryObject(app, accessory, path.c_str())) {
        out += "record failed\n";
    } else {
        ok = AddMesh(out, "record", static_cast<ID3DXMesh*>(record.mesh));
        Add(out, "materials %u\n", record.materialCount);
        const auto* materials = static_cast<const D3DMATERIAL9*>(record.materials);
        for (std::uint32_t i = 0; i < record.materialCount; ++i) {
            Add(out, "rm %u", i);
            AddMaterial(out, materials[i]);
            Add(out, " %u", record.textureTypes[i]);
            AddQuotedWide(out, AfterDirectory(record.texturePaths[i].primary, record.directory));
            AddQuotedWide(out, AfterDirectory(record.texturePaths[i].sphere, record.directory));
            out += '\n';
        }
        out += "name";
        AddQuoted(out, record.name, strnlen(record.name, sizeof record.name));
        out += '\n';
        Add(out, "place %u", record.visible);
        AddFloats(out, &record.scale, 1);
        AddFloats(out, record.position, 3);
        AddFloats(out, record.rotation, 3);
        Add(out, " %u %d %d %.9g %u\n", record.shadowEnabled, record.parentModel, record.parentBone,
            record.opacity, record.additiveBlend);
    }
    DisposeAccessory(accessory);
    ::operator delete(accessory);
    return ok;
}

void WriteError(const std::string& line) {
    HANDLE error = GetStdHandle(STD_ERROR_HANDLE);
    DWORD written = 0;
    if (error != nullptr && error != INVALID_HANDLE_VALUE)
        WriteFile(error, line.data(), static_cast<DWORD>(line.size()), &written, nullptr);
    OutputDebugStringA(line.c_str());
}

bool IsVac(const std::wstring& path) {
    // LoadAccessoryObject: wcsstr(meshPath, L".vac")
    return std::wcsstr(path.c_str(), L".vac") != nullptr;
}
} // namespace

int RunMeshDump(MMDApp* app, const TraceRequest& request) {
    D3DRenderer* r = app->Renderer();
    if (r == nullptr || r->device == nullptr)
        return 1;
    for (const std::wstring& path : request.meshFiles) {
        const std::filesystem::path file(path);
        std::string out = "mds-mesh-dump 1\nfile";
        const std::string name = file.filename().u8string();
        AddQuoted(out, name.c_str(), name.size());
        out += '\n';
        bool ok = true;
        if (!IsVac(path)) {
            ok = AddRaw(out, r->device, path);
            AddHierarchy(out, r->device, path);
        }
        ok = AddRecord(out, app, path) && ok;
        if (!ok) {
            WriteError("mds-mesh-dump: a buffer could not be read: " + name + "\n");
            return 1;
        }
        const std::wstring target = request.out + L"\\" + file.filename().wstring() + L".txt";
        const std::wstring temp = target + L".tmp";
        {
            std::ofstream stream(std::filesystem::path(temp), std::ios::binary | std::ios::trunc);
            stream << out;
            if (!stream.flush()) {
                DeleteFileW(temp.c_str());
                return 1;
            }
        }
        if (!MoveFileExW(temp.c_str(), target.c_str(),
                         MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
            DeleteFileW(temp.c_str());
            return 1;
        }
    }
    return 0;
}
} // namespace mikudancestudio::tools
