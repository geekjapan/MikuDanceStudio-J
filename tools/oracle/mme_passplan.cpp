// mme_passplan.exe - dump the MME pass plan that the C++ runtime builds for one
// effect file (wave 2 slice `passplan`). Windows x64 console tool.
//
//   mme_passplan.exe --root <corpus-root> --out <plan-file> <effect.fx>
//
// It loads the effect through the same entry point the app uses
// (MmeEngineLoadEffectFile: D3DXCreateEffectFromFile with the MME defines, then
// SasParse) on a HAL device, then writes what the runtime decided as a text
// plan. No hook inside third_party/mmeffect is needed: SasEffect is a plain
// struct (sas_exec.h) and SasSelectTechnique is public. The format is
// described in tests/fixtures/rust/mme/README.md.
//
// Rules for the output:
//   - no pointers, handles, or host paths: paths under --root are written as
//     "<root>/relative/path" with forward slashes;
//   - bytes >= 0x80 and control characters inside strings are written as \xNN
//     (effect files carry Shift-JIS text);
//   - the plan is written with fopen("wb"), LF line ends, never to stdout.
// The device is fixed (HAL, 1000x600 A8R8G8B8, D24S8) because ViewportRatio
// sizes and the default depth format come from it.
//
// Exit code: 0 plan written (a rejected effect is a plan too), 2 usage or I/O
// error, 77 no HAL device.
#include "effect_engine.h"
#include "mme_context.h"
#include "mme_globals.h"
#include "mme_log.h"
#include "mme_ui.h"
#include "pass_planner.h"
#include "sas_exec.h"

#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace {

std::string g_out;
std::string g_root; // lower case, forward slashes, no trailing '/'
std::string g_boxes;
volatile LONG g_stopWatchdog = 0;

std::string Fmt(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    va_list copy;
    va_copy(copy, args);
    const int size = std::vsnprintf(nullptr, 0, fmt, copy);
    va_end(copy);
    std::string out(static_cast<size_t>(size > 0 ? size : 0) + 1, '\0');
    std::vsnprintf(&out[0], out.size(), fmt, args);
    va_end(args);
    out.resize(static_cast<size_t>(size > 0 ? size : 0));
    return out;
}

void Line(const std::string& text) {
    g_out += text;
    g_out += '\n';
}

std::string Lower(std::string s) {
    for (char& c : s) {
        if (c >= 'A' && c <= 'Z') {
            c = static_cast<char>(c - 'A' + 'a');
        }
    }
    return s;
}

// Replace every occurrence of the root directory by "<root>" and use forward
// slashes. Text that does not mention the root is returned unchanged.
std::string Norm(const std::string& s) {
    if (g_root.empty()) {
        return s;
    }
    std::string slashed = s;
    for (char& c : slashed) {
        if (c == '\\') {
            c = '/';
        }
    }
    const std::string lower = Lower(slashed);
    std::string out;
    size_t cursor = 0;
    bool found = false;
    for (size_t pos = lower.find(g_root); pos != std::string::npos;
         pos = lower.find(g_root, cursor)) {
        const size_t end = pos + g_root.size();
        if (end < lower.size() && lower[end] != '/' && lower[end] != '"' && lower[end] != ' ' &&
            lower[end] != '(' && lower[end] != ':' && lower[end] != '\'') {
            out.append(slashed, cursor, end - cursor); // longer directory name: keep it
            cursor = end;
            continue;
        }
        out.append(slashed, cursor, pos - cursor);
        out += "<root>";
        cursor = end;
        found = true;
    }
    if (!found) {
        return s;
    }
    out.append(slashed, cursor, std::string::npos);
    return out;
}

std::string Q(const char* text) {
    const std::string norm = Norm(text ? text : "");
    std::string out = "\"";
    for (const unsigned char c : norm) {
        if (c == '"' || c == '\\') {
            out += '\\';
            out += static_cast<char>(c);
        } else if (c < 0x20 || c >= 0x7f) {
            out += Fmt("\\x%02x", c);
        } else {
            out += static_cast<char>(c);
        }
    }
    out += '"';
    return out;
}
std::string Q(const std::string& text) {
    return Q(text.c_str());
}

// One quoted line per text line (the engine log, sas logs, D3DX errors).
void TextLines(const char* tag, const std::string& indent, const std::string& text) {
    size_t cursor = 0;
    while (cursor < text.size()) {
        size_t end = text.find_first_of("\r\n", cursor);
        if (end == std::string::npos) {
            end = text.size();
        }
        if (end > cursor) {
            Line(indent + tag + " " + Q(text.substr(cursor, end - cursor)));
        }
        cursor = end + 1;
    }
}

const char* FormatName(D3DFORMAT f) {
    switch (static_cast<unsigned>(f)) {
#define F(x)                                                                                       \
    case D3DFMT_##x:                                                                               \
        return #x;
        F(UNKNOWN)
        F(R8G8B8)
    F(A8R8G8B8)
    F(X8R8G8B8) F(R5G6B5) F(X1R5G5B5) F(A1R5G5B5) F(A4R4G4B4) F(R3G3B2) F(A8) F(A8R3G3B2)
        F(X4R4G4B4) F(A2B10G10R10) F(A8B8G8R8) F(X8B8G8R8) F(G16R16) F(A2R10G10B10) F(A16B16G16R16)
            F(L8) F(A8L8) F(V8U8) F(Q8W8V8U8) F(V16U16) F(D16_LOCKABLE) F(D32) F(D15S1) F(D24S8)
                F(D24X8) F(D24X4S4) F(D16) F(D32F_LOCKABLE) F(D24FS8) F(L16) F(R16F) F(G16R16F)
                    F(A16B16G16R16F) F(R32F) F(G32R32F) F(A32B32G32R32F)
#undef F
                        case D3DFMT_DXT1:
        return "DXT1";
    case D3DFMT_DXT2:
        return "DXT2";
    case D3DFMT_DXT3:
        return "DXT3";
    case D3DFMT_DXT4:
        return "DXT4";
    case D3DFMT_DXT5:
        return "DXT5";
    }
    static char buffer[16];
    std::snprintf(buffer, sizeof buffer, "0x%08x", static_cast<unsigned>(f));
    return buffer;
}

const char* ClassName(D3DXPARAMETER_CLASS c) {
    switch (c) {
    case D3DXPC_SCALAR:
        return "scalar";
    case D3DXPC_VECTOR:
        return "vector";
    case D3DXPC_MATRIX_ROWS:
        return "matrix_rows";
    case D3DXPC_MATRIX_COLUMNS:
        return "matrix_columns";
    case D3DXPC_OBJECT:
        return "object";
    case D3DXPC_STRUCT:
        return "struct";
    default:
        return "?";
    }
}

const char* TypeName(D3DXPARAMETER_TYPE t) {
    switch (t) {
    case D3DXPT_VOID:
        return "void";
    case D3DXPT_BOOL:
        return "bool";
    case D3DXPT_INT:
        return "int";
    case D3DXPT_FLOAT:
        return "float";
    case D3DXPT_STRING:
        return "string";
    case D3DXPT_TEXTURE:
        return "texture";
    case D3DXPT_TEXTURE1D:
        return "texture1d";
    case D3DXPT_TEXTURE2D:
        return "texture2d";
    case D3DXPT_TEXTURE3D:
        return "texture3d";
    case D3DXPT_TEXTURECUBE:
        return "texturecube";
    case D3DXPT_SAMPLER:
    case D3DXPT_SAMPLER1D:
    case D3DXPT_SAMPLER2D:
    case D3DXPT_SAMPLER3D:
    case D3DXPT_SAMPLERCUBE:
        return "sampler";
    case D3DXPT_PIXELSHADER:
        return "pixelshader";
    case D3DXPT_VERTEXSHADER:
        return "vertexshader";
    default:
        return "?";
    }
}

bool IsTextureType(D3DXPARAMETER_TYPE t) {
    return t == D3DXPT_TEXTURE || t == D3DXPT_TEXTURE1D || t == D3DXPT_TEXTURE2D ||
           t == D3DXPT_TEXTURE3D || t == D3DXPT_TEXTURECUBE;
}

const char* SemanticName(int id) {
    switch (id) {
    case 0x26:
        return "RenderColorTarget";
    case 0x27:
        return "RenderDepthStencilTarget";
    case 0x2c:
        return "Texture";
    case 0x2d:
        return "AnimatedTexture";
    case 0x2e:
        return "OffScreenRenderTarget";
    case 0x33:
        return "TextureValue";
    default:
        return "?";
    }
}

const char* CommandName(int id) {
    static const char* const names[] = {"Pass",
                                        "RenderColorTarget0",
                                        "RenderColorTarget1",
                                        "RenderColorTarget2",
                                        "RenderColorTarget3",
                                        "RenderDepthStencilTarget",
                                        "ClearSetColor",
                                        "ClearSetDepth",
                                        "Clear",
                                        "ClearEx",
                                        "DrawGeometry",
                                        "DrawBuffer",
                                        "ScriptExternal",
                                        "LoopByCount",
                                        "LoopGetIndex",
                                        "LoopEnd"};
    return (id >= 0 && id < 16) ? names[id] : "?";
}

const char* PassModeName(int mode) {
    static const char* const names[] = {"object", "object_ss", "shadow", "edge", "zplot"};
    return (mode >= 0 && mode < 5) ? names[mode] : "?";
}

const char* UseName(signed char v) {
    return v < 0 ? "any" : (v ? "1" : "0");
}

// Annotation names the runtime reads on a parameter (sas_interpreter.cpp,
// material_bind.cpp). Everything else (UIName, UIMin, ...) is not part of the
// plan.
bool IsReadAnnotation(const char* name) {
    static const char* const names[] = {
        "ScriptOutput",  "ScriptClass", "ScriptOrder", "Script",       "ResourceName",
        "ResourceType",  "Offset",      "Speed",       "SeekVariable", "TextureName",
        "ViewportRatio", "Dimensions",  "Width",       "Height",       "Depth",
        "Miplevels",     "Levels",      "Format",      "Description",  "DefaultEffect",
        "ClearColor",    "ClearDepth",  "AntiAlias",   "Function",     "Target",
        "Name",          "Item",        "Object"};
    for (const char* n : names) {
        if (_stricmp(n, name) == 0) {
            return true;
        }
    }
    return false;
}

// The parameter-name table of sas_interpreter.cpp (kNameTable), matched with
// _stricmp. Such a parameter is bound by name even without a semantic.
bool IsNameTableName(const char* name) {
    static const char* const names[] = {
        "matWorld", "matWorldViewProj", "matLightViewProj", "matRotate",
        "EgColor",  "ToonColor",        "LightDir",         "SpcColor",
        "Place",    "DifColor",         "parthf",           "spadd",
        "transp",   "use_texture",      "use_spheremap",    "use_subtexture",
        "use_toon", "VertexCount",      "SubsetCount",      "opadd",
        "TexCAdd",  "TexCMul",          "SphCAdd",          "SphCMul"};
    for (const char* n : names) {
        if (_stricmp(n, name) == 0) {
            return true;
        }
    }
    return false;
}

std::string AnnotationValue(ID3DXEffect* fx, D3DXHANDLE h, const D3DXPARAMETER_DESC& d) {
    if (d.Type == D3DXPT_STRING && d.Elements == 0) {
        const char* text = nullptr;
        return SUCCEEDED(fx->GetString(h, &text)) ? Q(text) : std::string("?");
    }
    const unsigned count = d.Rows * d.Columns * (d.Elements ? d.Elements : 1);
    if ((d.Class != D3DXPC_SCALAR && d.Class != D3DXPC_VECTOR && d.Class != D3DXPC_MATRIX_ROWS &&
         d.Class != D3DXPC_MATRIX_COLUMNS) ||
        count == 0 || count > 64) {
        return "?";
    }
    std::string out;
    if (d.Type == D3DXPT_FLOAT) {
        std::vector<float> v(count);
        if (FAILED(fx->GetFloatArray(h, v.data(), count))) {
            return "?";
        }
        for (unsigned i = 0; i < count; ++i) {
            out += Fmt("%s%.9g", i ? "," : "", v[i]);
        }
    } else if (d.Type == D3DXPT_INT) {
        std::vector<int> v(count);
        if (FAILED(fx->GetIntArray(h, v.data(), count))) {
            return "?";
        }
        for (unsigned i = 0; i < count; ++i) {
            out += Fmt("%s%d", i ? "," : "", v[i]);
        }
    } else if (d.Type == D3DXPT_BOOL) {
        std::vector<BOOL> v(count);
        if (FAILED(fx->GetBoolArray(h, v.data(), count))) {
            return "?";
        }
        for (unsigned i = 0; i < count; ++i) {
            out += Fmt("%s%d", i ? "," : "", v[i] ? 1 : 0);
        }
    } else {
        return "?";
    }
    return out;
}

std::string ParamName(ID3DXEffect* fx, D3DXHANDLE h) {
    D3DXPARAMETER_DESC d{};
    if (!h || FAILED(fx->GetParameterDesc(h, &d)) || !d.Name) {
        return "-";
    }
    return d.Name;
}

std::string RawStringAnnotation(ID3DXEffect* fx, D3DXHANDLE owner, const char* name) {
    D3DXHANDLE a = fx->GetAnnotationByName(owner, name);
    const char* text = nullptr;
    if (a && SUCCEEDED(fx->GetString(a, &text)) && text) {
        return text;
    }
    return std::string();
}

// ---- parameters ----

void DumpParameters(ID3DXEffect* fx, const D3DXEFFECT_DESC& ed) {
    Line(Fmt("parameters %u", ed.Parameters));
    for (UINT i = 0; i < ed.Parameters; ++i) {
        D3DXHANDLE h = fx->GetParameter(nullptr, i);
        D3DXPARAMETER_DESC d{};
        if (!h || FAILED(fx->GetParameterDesc(h, &d))) {
            continue;
        }
        const char* semantic = d.Semantic ? d.Semantic : "";
        bool read = false;
        for (UINT a = 0; a < d.Annotations && !read; ++a) {
            D3DXPARAMETER_DESC ad{};
            read = SUCCEEDED(fx->GetParameterDesc(fx->GetAnnotation(h, a), &ad)) && ad.Name &&
                   IsReadAnnotation(ad.Name);
        }
        if (!semantic[0] && !IsTextureType(d.Type) && !IsNameTableName(d.Name) && !read) {
            continue; // inert: the runtime never looks at it
        }
        // param NAME SEMANTIC CLASS TYPE ROWSxCOLUMNS[ [ELEMENTS] ][ literal]
        Line(Fmt("param %s %s %s %s %ux%u%s%s", Q(d.Name).c_str(), Q(semantic).c_str(),
                 ClassName(d.Class), TypeName(d.Type), d.Rows, d.Columns,
                 d.Elements ? Fmt("[%u]", d.Elements).c_str() : "",
                 (d.Flags & 1) ? " literal" : ""));
        for (UINT a = 0; a < d.Annotations; ++a) {
            D3DXHANDLE ah = fx->GetAnnotation(h, a);
            D3DXPARAMETER_DESC ad{};
            if (!ah || FAILED(fx->GetParameterDesc(ah, &ad)) || !ad.Name ||
                !IsReadAnnotation(ad.Name)) {
                continue;
            }
            Line(Fmt("  ann %s %s%u = %s", Q(ad.Name).c_str(), TypeName(ad.Type),
                     ad.Rows * ad.Columns, AnnotationValue(fx, ah, ad).c_str()));
        }
    }
}

// ---- resources and controls ----

void DumpResources(const mme::SasEffect* sas) {
    Line(Fmt("resources %zu", sas->resources.size()));
    for (const mme::SasResource& r : sas->resources) {
        Line(Fmt("resource %s semantic=%s texture=%d", Q(r.name).c_str(),
                 SemanticName(r.semanticId), r.textureType));
        Line(Fmt("  request %dx%dx%d mips=%d rawsize=%dx%d rawmips=%d format=%s defaultpool=%d",
                 r.reqWidth, r.reqHeight, r.reqDepth, r.mipLevels, r.texWidth, r.texHeight,
                 r.texMips, FormatName(r.format), r.defaultPool ? 1 : 0));
        if (r.semanticId == 0x2e) {
            Line("  clear color=" +
                 (r.hasClearColor ? Fmt("0x%08lx", r.clearColorArgb) : std::string("-")) +
                 " depth=" + (r.hasClearDepth ? Fmt("%.9g", r.clearDepth) : std::string("-")) +
                 Fmt(" antialias=%d", r.antiAlias ? 1 : 0));
            for (const auto& row : r.defaultEffectMap) {
                Line("  defaulteffect_row " + Q(row.first) + " " + Q(row.second));
            }
        }
        if (!r.resourceName.empty()) {
            Line("  resourcename " + Q(r.resourceName));
        }
        if (!r.functionName.empty()) {
            Line("  function " + Q(r.functionName) + " target " + Q(r.functionTarget));
        }
        if (r.semanticId == 0x2d) {
            Line(Fmt("  animated offset=%.9g speed=%.9g seekvariable=%s", r.offset, r.speed,
                     Q(r.seekVariable).c_str()));
        }
        if (r.semanticId == 0x33) {
            Line(Fmt("  texturevalue texture=%s elements=%d", Q(r.textureValueName).c_str(),
                     r.textureValueElements));
        }
        // What the runtime created for it (device dependent: format fallbacks).
        // A depth target keeps a 1x1 placeholder texture next to its surface.
        if (r.texture) {
            D3DSURFACE_DESC sd{};
            const D3DRESOURCETYPE type = r.texture->GetType();
            HRESULT hr = E_FAIL;
            if (type == D3DRTYPE_TEXTURE) {
                hr = static_cast<IDirect3DTexture9*>(r.texture)->GetLevelDesc(0, &sd);
            } else if (type == D3DRTYPE_CUBETEXTURE) {
                hr = static_cast<IDirect3DCubeTexture9*>(r.texture)->GetLevelDesc(0, &sd);
            }
            if (SUCCEEDED(hr)) {
                Line(Fmt("  created %s %ux%u levels=%lu format=%s pool=%d usage=0x%lx",
                         type == D3DRTYPE_CUBETEXTURE ? "cube" : "texture", sd.Width, sd.Height,
                         r.texture->GetLevelCount(), FormatName(sd.Format),
                         static_cast<int>(sd.Pool), sd.Usage));
            } else {
                Line(Fmt("  created type=%d", static_cast<int>(type)));
            }
        }
        if (r.surface && r.semanticId == 0x27) {
            D3DSURFACE_DESC sd{};
            if (SUCCEEDED(r.surface->GetDesc(&sd))) {
                Line(Fmt("  created depthsurface %ux%u format=%s", sd.Width, sd.Height,
                         FormatName(sd.Format)));
            }
        }
        if (!r.texture && !r.surface) {
            Line("  created none");
        }
        if (r.semanticId == 0x2e) {
            if (r.offscreenDepth) {
                D3DSURFACE_DESC sd{};
                if (SUCCEEDED(r.offscreenDepth->GetDesc(&sd))) {
                    Line(Fmt("  offscreendepth %ux%u format=%s", sd.Width, sd.Height,
                             FormatName(sd.Format)));
                }
            } else {
                Line("  offscreendepth none");
            }
        }
    }
    Line(Fmt("controls %zu", sas->controls.size()));
    for (const mme::SasControlObject& c : sas->controls) {
        Line(Fmt("control %s name=%s item=%s", Q(ParamName(sas->effect, c.param)).c_str(),
                 Q(c.objectName).c_str(), Q(c.itemName).c_str()));
    }
}

// ---- techniques ----

void DumpCommands(ID3DXEffect* fx, const mme::SasTechnique& tech,
                  const std::vector<mme::SasScriptCmd>& cmds, const char* indent) {
    for (size_t i = 0; i < cmds.size(); ++i) {
        const mme::SasScriptCmd& c = cmds[i];
        std::string operand;
        if (c.id == mme::kSasCmdPass) {
            std::string name = "?";
            for (const mme::SasPass& p : tech.passes) {
                if (p.index == c.value) {
                    name = p.name;
                }
            }
            operand = Fmt("pass=%s index=%d", Q(name).c_str(), c.value);
        } else {
            operand = Fmt("param=%s value=%d", Q(ParamName(fx, c.param)).c_str(), c.value);
        }
        Line(Fmt("%scmd %zu %s %s text=%s", indent, i, CommandName(c.id), operand.c_str(),
                 Q(c.text).c_str()));
    }
}

std::string SubsetText(const mme::SasTechnique& t) {
    if (t.allSubsets) {
        return "all";
    }
    std::string out;
    for (const auto& range : t.subsets) {
        out += Fmt("%s%d-%d", out.empty() ? "" : ",", range.first, range.second);
    }
    return out.empty() ? "none" : out;
}

void DumpTechniques(const mme::SasEffect* sas) {
    ID3DXEffect* fx = sas->effect;
    std::string order;
    for (D3DXHANDLE h : sas->techniqueOrder) {
        const int index = mme::SasFindTechniqueIndex(sas, h);
        order += " " + Q(index >= 0 ? sas->techniques[static_cast<size_t>(index)].name : "?");
    }
    Line("technique_order" + order);
    Line(Fmt("techniques %zu", sas->techniques.size()));
    for (const mme::SasTechnique& t : sas->techniques) {
        Line(Fmt("technique %s mmdpass=%s usetexture=%s usespheremap=%s usetoon=%s subset=%s "
                 "hardware=%d shadercaps=%d shadermix=%d script=%d empty=%d passes=%zu",
                 Q(t.name).c_str(), PassModeName(t.mmdPass), UseName(t.useTexture),
                 UseName(t.useSpheremap), UseName(t.useToon), SubsetText(t).c_str(),
                 t.hardwareOk ? 1 : 0, t.shaderCapsOk ? 1 : 0, t.shaderMixOk ? 1 : 0,
                 t.hasScript ? 1 : 0, t.empty ? 1 : 0, t.passes.size()));
        if (t.hasScript) {
            Line("  script " + Q(RawStringAnnotation(fx, t.handle, "Script")));
        }
        DumpCommands(fx, t, t.cmds, "  ");
        for (const mme::SasPass& p : t.passes) {
            Line(Fmt("  pass %d %s script=%d custom=%d psize15=%d shadermix=%d", p.index,
                     Q(p.name).c_str(), p.hasScript ? 1 : 0, p.hasCustomShaders ? 1 : 0,
                     p.needsPsize15 ? 1 : 0, p.shaderMixOk ? 1 : 0));
            if (p.hasScript) {
                Line("    script " + Q(p.scriptText));
            }
            DumpCommands(fx, t, p.cmds, "    ");
        }
    }
}

// The load-time selection table of MmeBuildDrawTechniqueTable (material_bind.cpp):
// one query per (mode, subset, Use* combination). Subsets from 0 to one past
// the largest Subset range end are probed; later subsets select like the last
// one. Consecutive subsets with the same answer are written as one row.
std::string TechName(const mme::SasEffect* sas, D3DXHANDLE h, bool valid) {
    if (!h) {
        return "-";
    }
    const int index = mme::SasFindTechniqueIndex(sas, h);
    std::string name = Q(index >= 0 ? sas->techniques[static_cast<size_t>(index)].name : "?");
    return valid ? name : name + "!";
}

void DumpSelection(const mme::SasEffect* sas) {
    int materials = 1;
    bool clamped =
        sas->scriptClass == mme::kSasClassScene || sas->scriptOrder != mme::kSasOrderStandard;
    if (!clamped) {
        int maxEnd = 0;
        for (const mme::SasTechnique& t : sas->techniques) {
            for (const auto& range : t.subsets) {
                if (range.second > maxEnd) {
                    maxEnd = range.second;
                }
            }
        }
        materials = maxEnd + 2;
        if (materials > 256) {
            materials = 256;
        }
    }
    Line(Fmt("selection subsets=%d clamped=%d", materials, clamped ? 1 : 0));
    Line("  # name! = the technique matched but is invalid (fallback); - = no technique");
    Line("  # modes 0 and 1 list the eight Use* states: index = usetexture | usespheremap<<1 | "
         "usetoon<<2");
    for (int mode = 0; mode < 5; ++mode) {
        if (mode != 0 && sas->scriptOrder != mme::kSasOrderStandard) {
            continue; // pre/post effects never draw the other four modes
        }
        std::string previous;
        int runStart = 0;
        for (int subset = 0; subset <= materials; ++subset) {
            std::string row;
            if (subset < materials) {
                const int combos = mode <= 1 ? 8 : 1;
                for (int combo = 0; combo < combos; ++combo) {
                    bool valid = true;
                    D3DXHANDLE h = mme::SasSelectTechnique(
                        sas, mode, subset, mode <= 1 && (combo & 1), mode <= 1 && (combo & 2),
                        mode <= 1 && (combo & 4), &valid);
                    row += (combo ? " " : "") + TechName(sas, h, valid);
                }
            }
            if (subset == 0) {
                previous = row;
                continue;
            }
            if (row != previous || subset == materials) {
                Line(Fmt("  select %s %d-%d %s", PassModeName(mode), runStart, subset - 1,
                         previous.c_str()));
                runStart = subset;
                previous = row;
            }
        }
    }
}

// ---- execution ----

struct Known {
    IDirect3DSurface9* surface;
    std::string name;
    bool owned;
};

struct RunContext {
    IDirect3DDevice9* device = nullptr;
    std::vector<Known> known;
    const mme::SasTechnique* tech = nullptr;
    int draws = 0;
};
RunContext g_run;

std::string SurfaceName(IDirect3DSurface9* s) {
    if (!s) {
        return "none";
    }
    for (const Known& k : g_run.known) {
        if (k.surface == s) {
            return k.name;
        }
    }
    return "other";
}

std::string Bindings() {
    std::string out;
    for (UINT i = 0; i < 4; ++i) {
        IDirect3DSurface9* s = nullptr;
        g_run.device->GetRenderTarget(i, &s);
        out += Fmt("rt%u=%s ", i, SurfaceName(s).c_str());
        if (s) {
            s->Release();
        }
    }
    IDirect3DSurface9* ds = nullptr;
    g_run.device->GetDepthStencilSurface(&ds);
    out += "ds=" + SurfaceName(ds);
    if (ds) {
        ds->Release();
    }
    D3DVIEWPORT9 vp{};
    g_run.device->GetViewport(&vp);
    out += Fmt(" viewport=%lux%lu+%lu+%lu", vp.Width, vp.Height, vp.X, vp.Y);
    return out;
}

void AddKnown(IDirect3DSurface9* s, const std::string& name, bool owned) {
    if (s) {
        g_run.known.push_back({s, name, owned});
    }
}

void ClearKnown() {
    for (Known& k : g_run.known) {
        if (k.owned) {
            k.surface->Release();
        }
    }
    g_run.known.clear();
}

void CollectKnown(const mme::SasEffect* sas, IDirect3DSurface9* mainRt, IDirect3DSurface9* mainDs) {
    ClearKnown();
    AddKnown(mainRt, "main", false);
    AddKnown(mainDs, "main.depth", false);
    AddKnown(mme::g_offscreenSurface, "scratch", false);
    for (const mme::SasResource& r : sas->resources) {
        if (r.surface && r.semanticId == 0x27) {
            AddKnown(r.surface, r.name, false);
        }
        if (r.offscreenDepth) {
            AddKnown(r.offscreenDepth, r.name + ".depth", false);
        }
        if (!r.texture) {
            continue;
        }
        const D3DRESOURCETYPE type = r.texture->GetType();
        if (type == D3DRTYPE_TEXTURE) {
            IDirect3DSurface9* s = nullptr;
            if (SUCCEEDED(static_cast<IDirect3DTexture9*>(r.texture)->GetSurfaceLevel(0, &s))) {
                AddKnown(s, r.name, true);
            }
        } else if (type == D3DRTYPE_CUBETEXTURE) {
            for (int face = 0; face < 6; ++face) {
                IDirect3DSurface9* s = nullptr;
                if (SUCCEEDED(static_cast<IDirect3DCubeTexture9*>(r.texture)->GetCubeMapSurface(
                        static_cast<D3DCUBEMAP_FACES>(face), 0, &s))) {
                    AddKnown(s, Fmt("%s[%d]", r.name.c_str(), face), true);
                }
            }
        }
    }
}

// The host pass-draw callback: record it, draw nothing.
long RunPass(void*, mme::SasEffect*, int kind, int passIndex) {
    std::string passName = "?";
    for (const mme::SasPass& p : g_run.tech->passes) {
        if (p.index == passIndex) {
            passName = p.name;
        }
    }
    ++g_run.draws;
    Line(Fmt("    draw %s pass=%d %s %s", kind == 0 ? "geometry" : "buffer", passIndex,
             Q(passName).c_str(), Bindings().c_str()));
    return S_OK;
}

void DumpRuns(mme::SasEffect* sas, IDirect3DDevice9* device) {
    g_run.device = device;
    mme::SasHostCallbacks callbacks = {};
    callbacks.RunPass = RunPass;
    mme::SasSetHostCallbacks(callbacks);
    Line("runs");
    for (mme::SasTechnique& t : sas->techniques) {
        if (t.empty) {
            continue;
        }
        sas->runFailed = false;
        const size_t logBefore = sas->log.size();
        g_run.draws = 0;
        g_run.tech = &t;
        Line(Fmt("  run %s", Q(t.name).c_str()));
        device->BeginScene();
        mme::SasRunState* state = mme::SasCreateRunState(device);
        Line("    start " + Bindings());
        const bool suspended = mme::SasExecuteTechniqueStep(sas, &t, device, state);
        if (suspended) {
            Line("    suspend " + Bindings());
        }
        HRESULT hr = sas->runFailed ? E_FAIL : mme::SasResumeTechnique(sas, &t, device, state);
        Line("    end " + Bindings());
        mme::SasDestroyRunState(state);
        device->EndScene();
        Line(Fmt("    result suspended=%d draws=%d hr=0x%08lx runfailed=%d", suspended ? 1 : 0,
                 g_run.draws, static_cast<unsigned long>(hr), sas->runFailed ? 1 : 0));
        TextLines("log", "    ", sas->log.substr(logBefore));
    }
    mme::SasSetHostCallbacks({});
    ClearKnown();
}

// ---- message boxes (the runtime shows one on a shader version mix) ----

DWORD WINAPI Watchdog(LPVOID) {
    while (!g_stopWatchdog) {
        HWND box = FindWindowA("#32770", "MikuMikuEffect");
        if (box) {
            DWORD pid = 0;
            GetWindowThreadProcessId(box, &pid);
            if (pid == GetCurrentProcessId()) {
                char text[2048] = {};
                GetDlgItemTextA(box, 0xFFFF, text, sizeof text);
                g_boxes += text;
                g_boxes += '\n';
                PostMessageA(box, WM_COMMAND, IDOK, 0);
                PostMessageA(box, WM_CLOSE, 0, 0);
            }
        }
        Sleep(20);
    }
    return 0;
}

struct Runtime {
    explicit Runtime(IDirect3DDevice9* device) {
        mme::g_context = new mme::MmeContext(device);
        mme::MmeEngineInit(device, true);
    }
    ~Runtime() {
        mme::SasSetHostCallbacks({});
        mme::MmeEngineTerm();
        if (mme::g_effectPool) {
            mme::g_effectPool->Release();
            mme::g_effectPool = nullptr;
        }
        if (mme::g_offscreenSurface) {
            mme::g_offscreenSurface->Release();
            mme::g_offscreenSurface = nullptr;
        }
        delete mme::g_context;
        mme::g_context = nullptr;
    }
};

bool WriteFile(const char* path) {
    FILE* f = std::fopen(path, "wb");
    if (!f) {
        return false;
    }
    const bool ok = std::fwrite(g_out.data(), 1, g_out.size(), f) == g_out.size();
    return std::fclose(f) == 0 && ok;
}

} // namespace

int main(int argc, char** argv) {
    const char *rootArg = nullptr, *outArg = nullptr, *fileArg = nullptr;
    for (int i = 1; i < argc; ++i) {
        if (!std::strcmp(argv[i], "--root") && i + 1 < argc) {
            rootArg = argv[++i];
        } else if (!std::strcmp(argv[i], "--out") && i + 1 < argc) {
            outArg = argv[++i];
        } else if (!fileArg) {
            fileArg = argv[i];
        } else {
            fileArg = nullptr;
            break;
        }
    }
    if (!rootArg || !outArg || !fileArg) {
        std::fprintf(stderr, "usage: mme_passplan --root <corpus-root> --out <plan> <effect.fx>\n");
        return 2;
    }
    char root[MAX_PATH] = {}, path[MAX_PATH] = {};
    if (!GetFullPathNameA(rootArg, sizeof root, root, nullptr) ||
        !GetFullPathNameA(fileArg, sizeof path, path, nullptr) ||
        GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) {
        std::fprintf(stderr, "cannot resolve the root or the effect path\n");
        return 2;
    }
    g_root = Lower(std::string(root));
    for (char& c : g_root) {
        if (c == '\\') {
            c = '/';
        }
    }
    while (g_root.size() > 1 && g_root.back() == '/') {
        g_root.pop_back();
    }
    const std::string rel = Norm(path);

    HWND window = CreateWindowW(L"STATIC", L"mme_passplan", WS_OVERLAPPED, 0, 0, 1000, 600, nullptr,
                                nullptr, GetModuleHandleW(nullptr), nullptr);
    IDirect3D9* d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (!window || !d3d) {
        return 77;
    }
    D3DPRESENT_PARAMETERS pp = {};
    pp.BackBufferWidth = 1000;
    pp.BackBufferHeight = 600;
    pp.BackBufferFormat = D3DFMT_A8R8G8B8;
    pp.BackBufferCount = 1;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = window;
    pp.Windowed = TRUE;
    pp.EnableAutoDepthStencil = TRUE;
    pp.AutoDepthStencilFormat = D3DFMT_D24S8;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9* device = nullptr;
    HRESULT hr = d3d->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, window,
                                   D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &device);
    if (FAILED(hr)) {
        std::fprintf(stderr, "HAL device unavailable: 0x%08lx\n", static_cast<unsigned long>(hr));
        return 77;
    }
    D3DCAPS9 caps = {};
    device->GetDeviceCaps(&caps);
    HANDLE watchdog = CreateThread(nullptr, 0, Watchdog, nullptr, 0, nullptr);

    int exitCode = 0;
    mme::MmeUiInitializeRuntime(GetModuleHandleW(nullptr)); // GDI+ for animated GIF/PNG textures
    {
        Runtime runtime(device);
        IDirect3DSurface9 *mainRt = nullptr, *mainDs = nullptr;
        device->GetRenderTarget(0, &mainRt);
        device->GetDepthStencilSurface(&mainDs);

        Line("passplan 1");
        Line("file " + Q(rel));
        Line(Fmt(
            "device HAL backbuffer=1000x600 format=A8R8G8B8 depthstencil=D24S8 vs=%lu.%lu ps=%lu.%lu "
            "mipfilter=1",
            D3DSHADER_VERSION_MAJOR(caps.VertexShaderVersion),
            D3DSHADER_VERSION_MINOR(caps.VertexShaderVersion),
            D3DSHADER_VERSION_MAJOR(caps.PixelShaderVersion),
            D3DSHADER_VERSION_MINOR(caps.PixelShaderVersion)));

        std::shared_ptr<mme::LoadedEffect> loaded = mme::MmeEngineLoadEffectFile(device, path);
        const bool ok = loaded && loaded->effect && loaded->sas;
        Line(std::string("load ") + (ok ? "ok" : "rejected"));
        if (!ok) {
            TextLines("error", "  ", loaded ? loaded->errorText : std::string("no entry"));
        } else {
            mme::SasEffect* sas = loaded->sas;
            D3DXEFFECT_DESC ed{};
            loaded->effect->GetDesc(&ed);
            Line(
                Fmt("effect scriptclass=%d scriptorder=%d posteffect=%d drawsgeometry=%d errors=%d",
                    sas->scriptClass, sas->scriptOrder, sas->postEffect ? 1 : 0,
                    sas->drawsGeometry ? 1 : 0, sas->hasErrors ? 1 : 0));
            DumpParameters(loaded->effect, ed);
            DumpResources(sas);
            DumpTechniques(sas);
            DumpSelection(sas);
            CollectKnown(sas, mainRt, mainDs);
            DumpRuns(sas, device);
        }
        g_stopWatchdog = 1;
        WaitForSingleObject(watchdog, 2000);
        CloseHandle(watchdog);
        TextLines("messagebox", "", g_boxes);
        TextLines("enginelog", "", mme::MmeGetLogDialogText());
        Line("end");
        if (mainRt) {
            mainRt->Release();
        }
        if (mainDs) {
            mainDs->Release();
        }
    }

    mme::MmeUiShutdownRuntime();
    device->Release();
    d3d->Release();
    DestroyWindow(window);
    if (!WriteFile(outArg)) {
        std::fprintf(stderr, "cannot write %s\n", outArg);
        return 2;
    }
    return exitCode;
}
