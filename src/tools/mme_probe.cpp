// The MME probe of --mds-mme-dump (format: trace_mode.cpp). A TU of its own
// because it reads the effect engine through the MMEffect headers, whose
// d3dx9.h must not meet the app's d3dx_dyn.hpp.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <ios>
#include <string>
#include <vector>

#include "effect_engine.h"
#include "mme_context.h"
#include "mme_log.h"
#include "model_data.h"
#include "sas_exec.h"

#include "trace_mode.hpp"

namespace mikudancestudio::tools {
namespace {

std::string Ansi(const std::wstring& text) {
    const int size = WideCharToMultiByte(CP_ACP, 0, text.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1)
        return std::string();
    std::string ansi(static_cast<std::size_t>(size), '\0');
    WideCharToMultiByte(CP_ACP, 0, text.c_str(), -1, &ansi[0], size, nullptr, nullptr);
    ansi.pop_back();
    return ansi;
}

// `path` below `base` (case-insensitive, as the file system) with '/'
// separators, so the probe does not name the host's directories.
std::string Relative(const std::string& path, const std::string& base) {
    std::string out = path;
    if (!base.empty() && out.size() > base.size() &&
        _strnicmp(out.c_str(), base.c_str(), base.size()) == 0 &&
        (out[base.size()] == '\\' || out[base.size()] == '/'))
        out = out.substr(base.size() + 1);
    std::replace(out.begin(), out.end(), '\\', '/');
    return out;
}

void Append(std::string& line, const char* format, double value) {
    char text[40];
    std::snprintf(text, sizeof text, format, value);
    line += ' ';
    line += text;
}

// One line per top-level bool, int, or float parameter, or an empty string
// for any other parameter.
std::string ParameterLine(ID3DXEffect* effect, D3DXHANDLE handle, const D3DXPARAMETER_DESC& d) {
    if (d.Class == D3DXPC_OBJECT || d.Class == D3DXPC_STRUCT ||
        (d.Type != D3DXPT_BOOL && d.Type != D3DXPT_INT && d.Type != D3DXPT_FLOAT))
        return std::string();
    const unsigned elements = d.Elements > 0 ? d.Elements : 1;
    std::string line = std::string("param ") + d.Name + ' ' +
                       (d.Semantic != nullptr && d.Semantic[0] != '\0' ? d.Semantic : "-");
    char shape[48];
    std::snprintf(shape, sizeof shape, " %d %d %ux%ux%u", static_cast<int>(d.Class),
                  static_cast<int>(d.Type), d.Rows, d.Columns, d.Elements);
    line += shape;
    if (d.Type == D3DXPT_FLOAT &&
        (d.Class == D3DXPC_MATRIX_ROWS || d.Class == D3DXPC_MATRIX_COLUMNS)) {
        // GetMatrix gives row-major m[row][column] for either class.
        std::vector<D3DMATRIX> m(elements);
        const HRESULT hr = d.Elements > 0 ? effect->GetMatrixArray(handle, m.data(), elements)
                                          : effect->GetMatrix(handle, m.data());
        if (FAILED(hr))
            return line + " ?";
        for (const D3DMATRIX& one : m)
            for (unsigned r = 0; r < d.Rows; ++r)
                for (unsigned c = 0; c < d.Columns; ++c)
                    Append(line, "%.9g", one.m[r][c]);
        return line;
    }
    const unsigned count = d.Rows * d.Columns * elements;
    if (d.Type == D3DXPT_FLOAT) {
        std::vector<float> v(count);
        if (FAILED(effect->GetFloatArray(handle, v.data(), count)))
            return line + " ?";
        for (float x : v)
            Append(line, "%.9g", x);
    } else if (d.Type == D3DXPT_INT) {
        std::vector<int> v(count);
        if (FAILED(effect->GetIntArray(handle, v.data(), count)))
            return line + " ?";
        for (int x : v)
            Append(line, "%.0f", x);
    } else {
        std::vector<BOOL> v(count);
        if (FAILED(effect->GetBoolArray(handle, v.data(), count)))
            return line + " ?";
        for (BOOL x : v)
            Append(line, "%.0f", x != FALSE ? 1 : 0);
    }
    return line;
}

bool Collect(void* user, mme::SasEffect* sas) {
    static_cast<std::vector<mme::SasEffect*>*>(user)->push_back(sas);
    return true;
}
} // namespace

void WriteMmeLog() {
    const char* text = mme::MmeGetLogDialogText();
    HANDLE error = GetStdHandle(STD_ERROR_HANDLE);
    DWORD written = 0;
    if (text != nullptr && error != nullptr && error != INVALID_HANDLE_VALUE)
        WriteFile(error, text, static_cast<DWORD>(std::strlen(text)), &written, nullptr);
}

int WriteMmeProbe(const std::wstring& path, std::uint32_t frame, float frameTime,
                  const std::wstring& base) {
    std::vector<mme::SasEffect*> effects;
    mme::MmeEngineForEachSas(Collect, &effects);
    std::stable_sort(effects.begin(), effects.end(),
                     [](const mme::SasEffect* a, const mme::SasEffect* b) {
                         return _stricmp(a->path.c_str(), b->path.c_str()) < 0;
                     });
    const std::string baseAnsi = Ansi(base);
    const std::wstring temp = path + L".tmp";
    int listed = 0;
    {
        std::ofstream out(std::filesystem::path(temp), std::ios::binary | std::ios::trunc);
        if (!out)
            return -1;
        char line[96];
        std::snprintf(line, sizeof line, "mds-mme-probe 1\nframe %u %.9g\n", frame, frameTime);
        out << line;
        if (const mme::MmeContext* context = mme::MmeGetContext()) {
            for (const mme::ModelData* model : context->models) {
                if (model == nullptr)
                    continue;
                const std::string& file = model->effectFile();
                std::snprintf(line, sizeof line, " class %d render %d shown %d\n",
                              model->scriptClass(), model->renderClass(), model->shown() ? 1 : 0);
                out << "object "
                    << Relative(model->filename() != nullptr ? model->filename() : "", baseAnsi)
                    << " effect " << (file.empty() ? "-" : Relative(file, baseAnsi)) << line;
            }
        }
        for (const mme::SasEffect* sas : effects) {
            ID3DXEffect* effect = sas->effect;
            D3DXEFFECT_DESC desc{};
            if (effect == nullptr || FAILED(effect->GetDesc(&desc)))
                continue;
            ++listed;
            std::snprintf(line, sizeof line, " class %d order %d errors %d\n", sas->scriptClass,
                          sas->scriptOrder, sas->hasErrors || sas->runFailed ? 1 : 0);
            out << "effect " << Relative(sas->path, baseAnsi) << line;
            for (unsigned i = 0; i < desc.Parameters; ++i) {
                const D3DXHANDLE handle = effect->GetParameter(nullptr, i);
                D3DXPARAMETER_DESC d{};
                if (handle == nullptr || FAILED(effect->GetParameterDesc(handle, &d)))
                    continue;
                const std::string text = ParameterLine(effect, handle, d);
                if (!text.empty())
                    out << text << '\n';
            }
        }
        out.flush();
        if (!out.good())
            listed = -1;
    }
    if (listed < 0 || !MoveFileExW(temp.c_str(), path.c_str(),
                                   MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileW(temp.c_str());
        return -1;
    }
    return listed;
}
} // namespace mikudancestudio::tools
