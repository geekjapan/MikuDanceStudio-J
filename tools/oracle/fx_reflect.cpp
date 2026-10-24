// fx_reflect.exe - dump what the real D3DX effect compiler makes of .fx files
// (RM-3 lane 9). Windows x64 console tool.
//
//   fx_reflect.exe [--no-mipmap] [--software-noopt] <file.fx>... [--list <paths.txt>]
//
// Each file is loaded with D3DXCreateEffectFromFileW with the arguments MME
// uses (third_party/mmeffect/src/mmeffect/effect_engine.cpp, MmeEngineLoadEffectFile):
//   defines  {"_INDEX","PSIZE15"} and, unless --no-mipmap, {"MME_MIPMAP",""}
//            (MME adds the second one when its mip filter probe passes)
//   include  nullptr; the current directory is set to the .fx directory first,
//            like MME's ScopedChdir, so relative #include lines resolve
//   flags    0x1000 (D3DXSHADER_ENABLE_BACKWARDS_COMPATIBILITY); with
//            --software-noopt also 0xC0, which MME adds in debug mode
//   pool     nullptr (MME shares one pool; only `shared` parameters differ)
// on a hidden-window device: HAL if the machine has one, else NULLREF. The
// device type is printed in the first line.
//
// Output is JSON Lines on stdout: one header object, then one object per file.
//   {"file":...,"result":"ok","creator":...,"parameters":[...],"techniques":[...]}
//   {"file":...,"result":"error","hr":"0x8876086c","error":"<D3DX error text>"}
// A parameter is {name,semantic,class,type,rows,columns,elements,bytes,
// annotations:[...],members:[...]}. Annotations add "value". A technique is
// {name,valid,annotations,passes:[{name,annotations,vs,ps}]} where valid is the
// HRESULT of ValidateTechnique. Strings are JSON strings; bytes >= 0x80 are
// written as \u00XX per byte, so Shift-JIS text is preserved byte for byte.
// Lane 9: run it over the ray-mmd corpus and res\assets\*.fx, for example
//   powershell -c "Get-ChildItem -Recurse -Filter *.fx <ray-mmd> , res\assets |
//     %% FullName | Set-Content -Encoding utf8 fx-list.txt"
//   fx_reflect.exe --list fx-list.txt > fx-reflect.txt
// and count: every file has a line (`find /c /v "" fx-list.txt` equals the
// number of object lines minus the header line).
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <d3d9.h>
#include <fcntl.h>
#include <io.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include <d3dx9.h>

namespace {
std::string g_out;

void Raw(const char* text) { g_out += text; }
void Str(const char* text) {
    g_out += '"';
    for (const unsigned char* p = reinterpret_cast<const unsigned char*>(text ? text : ""); *p; ++p) {
        char buffer[8];
        if (*p == '"' || *p == '\\') {
            g_out += '\\';
            g_out += static_cast<char>(*p);
        } else if (*p < 0x20 || *p >= 0x80) {
            std::snprintf(buffer, sizeof buffer, "\\u%04x", *p);
            g_out += buffer;
        } else {
            g_out += static_cast<char>(*p);
        }
    }
    g_out += '"';
}
void Num(unsigned long long value) { g_out += std::to_string(value); }
void Hex32(unsigned long value) {
    char buffer[16];
    std::snprintf(buffer, sizeof buffer, "\"0x%08lx\"", value);
    g_out += buffer;
}
void Key(const char* name) {
    Str(name);
    g_out += ':';
}

std::string Utf8(const std::wstring& wide) {
    if (wide.empty()) return std::string();
    const int size = WideCharToMultiByte(CP_UTF8, 0, wide.c_str(), static_cast<int>(wide.size()),
                                         nullptr, 0, nullptr, nullptr);
    std::string text(static_cast<std::size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide.c_str(), static_cast<int>(wide.size()), &text[0], size,
                        nullptr, nullptr);
    return text;
}

// Scalars of an annotation, as JSON.
void AnnotationValue(ID3DXEffect* fx, D3DXHANDLE handle, const D3DXPARAMETER_DESC& d) {
    Key("value");
    if (d.Type == D3DXPT_STRING && d.Elements == 0) {
        const char* text = nullptr;
        if (SUCCEEDED(fx->GetString(handle, &text))) Str(text);
        else Raw("null");
        return;
    }
    const unsigned count = d.Rows * d.Columns * (d.Elements ? d.Elements : 1);
    if ((d.Class != D3DXPC_SCALAR && d.Class != D3DXPC_VECTOR && d.Class != D3DXPC_MATRIX_ROWS &&
         d.Class != D3DXPC_MATRIX_COLUMNS) || count == 0 || count > 64) {
        Raw("null");
        return;
    }
    Raw("[");
    char buffer[40];
    if (d.Type == D3DXPT_FLOAT) {
        std::vector<float> values(count);
        if (FAILED(fx->GetFloatArray(handle, values.data(), count))) { Raw("null]"); return; }
        for (unsigned i = 0; i < count; ++i) {
            std::uint32_t bits;
            std::memcpy(&bits, &values[i], sizeof bits);
            std::snprintf(buffer, sizeof buffer, "%s\"0x%08x\"", i ? "," : "", bits);
            g_out += buffer;
        }
    } else if (d.Type == D3DXPT_INT || d.Type == D3DXPT_BOOL) {
        std::vector<int> values(count);
        const HRESULT hr = d.Type == D3DXPT_INT
                               ? fx->GetIntArray(handle, values.data(), count)
                               : fx->GetBoolArray(handle, reinterpret_cast<BOOL*>(values.data()), count);
        if (FAILED(hr)) { Raw("null]"); return; }
        for (unsigned i = 0; i < count; ++i) {
            std::snprintf(buffer, sizeof buffer, "%s%d", i ? "," : "", values[i]);
            g_out += buffer;
        }
    }
    Raw("]");
}

void Annotations(ID3DXEffect* fx, D3DXHANDLE owner, unsigned count);

void Parameter(ID3DXEffect* fx, D3DXHANDLE handle, bool annotation) {
    D3DXPARAMETER_DESC d{};
    Raw("{");
    if (FAILED(fx->GetParameterDesc(handle, &d))) {
        Raw("\"error\":\"GetParameterDesc\"}");
        return;
    }
    Key("name"); Str(d.Name); Raw(",");
    Key("semantic"); Str(d.Semantic); Raw(",");
    Key("class"); Num(d.Class); Raw(",");
    Key("type"); Num(d.Type); Raw(",");
    Key("rows"); Num(d.Rows); Raw(",");
    Key("columns"); Num(d.Columns); Raw(",");
    Key("elements"); Num(d.Elements); Raw(",");
    Key("bytes"); Num(d.Bytes); Raw(",");
    Key("flags"); Hex32(d.Flags);
    if (annotation) {
        Raw(",");
        AnnotationValue(fx, handle, d);
    } else {
        Raw(",");
        Key("annotations");
        Annotations(fx, handle, d.Annotations);
        if (d.Class == D3DXPC_STRUCT && d.Elements == 0) {
            Raw(",");
            Key("members");
            Raw("[");
            for (unsigned i = 0; i < d.StructMembers; ++i) {
                if (i) Raw(",");
                Parameter(fx, fx->GetParameter(handle, i), false);
            }
            Raw("]");
        }
    }
    Raw("}");
}

void Annotations(ID3DXEffect* fx, D3DXHANDLE owner, unsigned count) {
    Raw("[");
    for (unsigned i = 0; i < count; ++i) {
        if (i) Raw(",");
        Parameter(fx, fx->GetAnnotation(owner, i), true);
    }
    Raw("]");
}

void Reflect(ID3DXEffect* fx) {
    D3DXEFFECT_DESC desc{};
    fx->GetDesc(&desc);
    Key("creator"); Str(desc.Creator); Raw(",");
    Key("parameters"); Raw("[");
    for (unsigned i = 0; i < desc.Parameters; ++i) {
        if (i) Raw(",");
        Parameter(fx, fx->GetParameter(nullptr, i), false);
    }
    Raw("],");
    Key("techniques"); Raw("[");
    for (unsigned i = 0; i < desc.Techniques; ++i) {
        if (i) Raw(",");
        D3DXHANDLE technique = fx->GetTechnique(i);
        D3DXTECHNIQUE_DESC td{};
        fx->GetTechniqueDesc(technique, &td);
        Raw("{");
        Key("name"); Str(td.Name); Raw(",");
        Key("valid"); Hex32(static_cast<unsigned long>(fx->ValidateTechnique(technique))); Raw(",");
        Key("annotations"); Annotations(fx, technique, td.Annotations); Raw(",");
        Key("passes"); Raw("[");
        for (unsigned j = 0; j < td.Passes; ++j) {
            if (j) Raw(",");
            D3DXHANDLE pass = fx->GetPass(technique, j);
            D3DXPASS_DESC pd{};
            fx->GetPassDesc(pass, &pd);
            Raw("{");
            Key("name"); Str(pd.Name); Raw(",");
            Key("annotations"); Annotations(fx, pass, pd.Annotations); Raw(",");
            Key("vs"); Raw(pd.pVertexShaderFunction ? "true" : "false"); Raw(",");
            Key("ps"); Raw(pd.pPixelShaderFunction ? "true" : "false");
            Raw("}");
        }
        Raw("]}");
    }
    Raw("]");
}

void FlushLine() {
    g_out += '\n';
    std::fwrite(g_out.data(), 1, g_out.size(), stdout);
    g_out.clear();
}

struct Options {
    bool mipmap = true;
    bool softwareNoopt = false;
};

void Process(IDirect3DDevice9* device, const std::wstring& path, const Options& options) {
    Raw("{");
    Key("file"); Str(Utf8(path).c_str()); Raw(",");

    // MME's ScopedChdir: relative includes resolve against the .fx directory.
    wchar_t previous[MAX_PATH * 2] = {};
    GetCurrentDirectoryW(MAX_PATH * 2, previous);
    wchar_t full[MAX_PATH * 4];
    const DWORD fullLength = GetFullPathNameW(path.c_str(), MAX_PATH * 4, full, nullptr);
    if (fullLength == 0 || fullLength >= MAX_PATH * 4) {
        Raw("\"result\":\"error\",\"hr\":\"0x00000000\",\"error\":\"fx_reflect: path too long or invalid\"}");
        FlushLine();
        return;
    }
    std::wstring directory(full, fullLength);
    const std::size_t slash = directory.find_last_of(L"\\/");
    if (slash != std::wstring::npos) {
        directory.resize(slash + 1);
        SetCurrentDirectoryW(directory.c_str());
    }

    D3DXMACRO defines[3] = {{"_INDEX", "PSIZE15"}, {nullptr, nullptr}, {nullptr, nullptr}};
    if (options.mipmap) {
        defines[1] = {"MME_MIPMAP", ""};
    }
    unsigned long flags = 0x1000;
    if (options.softwareNoopt) flags |= 0xC0;
    ID3DXEffect* effect = nullptr;
    ID3DXBuffer* errors = nullptr;
    const HRESULT hr = D3DXCreateEffectFromFileW(device, full, defines, nullptr, flags, nullptr,
                                                 &effect, &errors);
    if (FAILED(hr) || effect == nullptr) {
        Key("result"); Str("error"); Raw(",");
        Key("hr"); Hex32(static_cast<unsigned long>(hr)); Raw(",");
        Key("error");
        if (errors != nullptr && errors->GetBufferSize() != 0)
            Str(static_cast<const char*>(errors->GetBufferPointer()));
        else
            Str("no D3DX error text");
        Raw("}");
    } else {
        Key("result"); Str("ok"); Raw(",");
        Reflect(effect);
        Raw("}");
    }
    if (effect != nullptr) effect->Release();
    if (errors != nullptr) errors->Release();
    SetCurrentDirectoryW(previous);
    FlushLine();
}

std::vector<std::wstring> ReadList(const char* path) {
    std::vector<std::wstring> lines;
    std::FILE* file = std::fopen(path, "rb");
    if (file == nullptr) return lines;
    std::string text;
    char chunk[4096];
    for (std::size_t n; (n = std::fread(chunk, 1, sizeof chunk, file)) > 0;) text.append(chunk, n);
    std::fclose(file);
    if (text.compare(0, 3, "\xEF\xBB\xBF") == 0) text.erase(0, 3);
    std::size_t start = 0;
    while (start < text.size()) {
        std::size_t end = text.find('\n', start);
        if (end == std::string::npos) end = text.size();
        std::size_t stop = end;
        while (stop > start && (text[stop - 1] == '\r' || text[stop - 1] == ' ')) --stop;
        if (stop > start) {
            const int size = MultiByteToWideChar(CP_UTF8, 0, text.data() + start,
                                                 static_cast<int>(stop - start), nullptr, 0);
            std::wstring line(static_cast<std::size_t>(size), L'\0');
            MultiByteToWideChar(CP_UTF8, 0, text.data() + start, static_cast<int>(stop - start),
                                &line[0], size);
            lines.push_back(line);
        }
        start = end + 1;
    }
    return lines;
}
}  // namespace

int wmain(int argc, wchar_t** argv) {
    _setmode(_fileno(stdout), _O_BINARY);  // LF line ends
    Options options;
    std::vector<std::wstring> files;
    for (int i = 1; i < argc; ++i) {
        const std::wstring arg = argv[i];
        if (arg == L"--no-mipmap") {
            options.mipmap = false;
        } else if (arg == L"--software-noopt") {
            options.softwareNoopt = true;
        } else if (arg == L"--list" && i + 1 < argc) {
            char narrow[MAX_PATH * 4];
            WideCharToMultiByte(CP_UTF8, 0, argv[++i], -1, narrow, sizeof narrow, nullptr, nullptr);
            const std::vector<std::wstring> lines = ReadList(narrow);
            if (lines.empty()) {
                std::fprintf(stderr, "fx_reflect: cannot read list %s\n", narrow);
                return 2;
            }
            files.insert(files.end(), lines.begin(), lines.end());
        } else {
            files.push_back(arg);
        }
    }
    if (files.empty()) {
        std::fprintf(stderr,
                     "usage: fx_reflect [--no-mipmap] [--software-noopt] <file.fx>... [--list paths.txt]\n");
        return 2;
    }

    WNDCLASSA wc{};
    wc.lpfnWndProc = DefWindowProcA;
    wc.hInstance = GetModuleHandleA(nullptr);
    wc.lpszClassName = "fx_reflect_window";
    RegisterClassA(&wc);
    HWND window = CreateWindowExA(0, wc.lpszClassName, "fx_reflect", WS_OVERLAPPED, 0, 0, 64, 64,
                                  nullptr, nullptr, wc.hInstance, nullptr);
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (window == nullptr || d3d == nullptr) {
        std::fprintf(stderr, "fx_reflect: cannot create window or Direct3D 9\n");
        return 3;
    }
    D3DPRESENT_PARAMETERS pp{};
    pp.Windowed = TRUE;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.BackBufferFormat = D3DFMT_UNKNOWN;
    pp.hDeviceWindow = window;
    IDirect3DDevice9* device = nullptr;
    const char* devtype = "hal";
    HRESULT hr = d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, window,
                                   D3DCREATE_SOFTWARE_VERTEXPROCESSING, &pp, &device);
    if (FAILED(hr)) {
        devtype = "nullref";
        hr = d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_NULLREF, window,
                               D3DCREATE_SOFTWARE_VERTEXPROCESSING, &pp, &device);
    }
    if (FAILED(hr) || device == nullptr) {
        std::fprintf(stderr, "fx_reflect: CreateDevice failed 0x%08lx\n", static_cast<unsigned long>(hr));
        return 3;
    }
    Raw("{");
    Key("fx_reflect"); Num(1); Raw(",");
    Key("device"); Str(devtype); Raw(",");
    Key("flags"); Hex32(options.softwareNoopt ? 0x10C0 : 0x1000); Raw(",");
    Key("mipmap"); Raw(options.mipmap ? "true" : "false");
    Raw("}");
    FlushLine();
    for (const std::wstring& file : files) Process(device, file, options);
    device->Release();
    d3d->Release();
    return 0;
}
