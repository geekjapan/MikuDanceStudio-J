#pragma once
// The --mds-script command line and script text (portable; the Windows
// runner is script_mode.cpp, the command reference is
// tests/fixtures/rust/script/README.md).
//
//   MikuDanceStudio.exe --mds-script <script.txt> <out-dir>
//
// A script is UTF-8 text, one command per line. Words are separated by
// spaces or tabs; a word that holds spaces is written in double quotes.
// Empty lines and lines whose first word starts with '#' are skipped. Each
// command is a fixed word sequence (the verb, sometimes a second keyword)
// followed by a fixed number of arguments; the whole script is checked
// before any window exists.
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <set>
#include <string>
#include <vector>

namespace mikudancestudio::tools {

enum class ScriptOp {
    New,
    LoadPmm,
    LoadModel,
    LoadVmd,
    LoadVpd,
    LoadAccessory,
    LoadWav,
    SavePmm,
    SaveVmd,
    SaveVpd,
    SavePmd,
    SelectCamera,
    SelectModel,
    SelectBone,
    SelectMorph,
    SelectAccessory,
    Frame,
    BonePosition,
    BoneRotation,
    MorphWeight,
    CameraPosition,
    CameraRotation,
    CameraDistance,
    CameraFov,
    LightColor,
    LightDirection,
    ShadowMode,
    ShadowRange,
    GravityOpen,
    GravityMagnitude,
    GravityDirection,
    GravityClose,
    AccessoryPosition,
    AccessoryRotation,
    AccessoryScale,
    AccessoryOpacity,
    AccessoryParent,
    RegisterBone,
    RegisterMorph,
    RegisterDisplay,
    RegisterCamera,
    RegisterLight,
    RegisterShadow,
    RegisterGravity,
    RegisterAccessory,
    Copy,
    Paste,
    PasteReverse,
    PasteDifferent,
    Delete,
    InsertBoneLine,
    DeleteBoneLine,
    InsertMorphLine,
    DeleteMorphLine,
    SelectAllBone,
    SelectAllDisplay,
    SelectAllMorph,
    SelectAllCamera,
    SelectAllLight,
    SelectAllShadow,
    SelectAllGravity,
    SelectAllAccessory,
    Undo,
    Redo,
};

struct ScriptCommandSpec {
    const char* words; // the fixed words, space separated
    ScriptOp op;
    const char* args; // one letter per argument: t text, n number, f frame, l lane
};

constexpr std::uint32_t kMaxScriptFrame = 100000;

// clang-format off
inline constexpr ScriptCommandSpec kScriptCommands[] = {
    {"new", ScriptOp::New, ""},
    {"load pmm", ScriptOp::LoadPmm, "t"},
    {"load model", ScriptOp::LoadModel, "t"},
    {"load vmd", ScriptOp::LoadVmd, "t"},
    {"load vpd", ScriptOp::LoadVpd, "t"},
    {"load accessory", ScriptOp::LoadAccessory, "t"},
    {"load wav", ScriptOp::LoadWav, "t"},
    {"save pmm", ScriptOp::SavePmm, "t"},
    {"save vmd", ScriptOp::SaveVmd, "t"},
    {"save vpd", ScriptOp::SaveVpd, "t"},
    {"save pmd", ScriptOp::SavePmd, "t"},
    {"select camera", ScriptOp::SelectCamera, ""},
    {"select model", ScriptOp::SelectModel, "t"},
    {"select bone", ScriptOp::SelectBone, "t"},
    {"select morph", ScriptOp::SelectMorph, "lt"},
    {"select accessory", ScriptOp::SelectAccessory, "t"},
    {"frame", ScriptOp::Frame, "f"},
    {"bone position", ScriptOp::BonePosition, "nnn"},
    {"bone rotation", ScriptOp::BoneRotation, "nnn"},
    {"morph", ScriptOp::MorphWeight, "ln"},
    {"camera position", ScriptOp::CameraPosition, "nnn"},
    {"camera rotation", ScriptOp::CameraRotation, "nnn"},
    {"camera distance", ScriptOp::CameraDistance, "n"},
    {"camera fov", ScriptOp::CameraFov, "n"},
    {"light color", ScriptOp::LightColor, "nnn"},
    {"light direction", ScriptOp::LightDirection, "nnn"},
    {"shadow mode", ScriptOp::ShadowMode, "f"},
    {"shadow range", ScriptOp::ShadowRange, "n"},
    {"gravity open", ScriptOp::GravityOpen, ""},
    {"gravity magnitude", ScriptOp::GravityMagnitude, "n"},
    {"gravity direction", ScriptOp::GravityDirection, "nnn"},
    {"gravity close", ScriptOp::GravityClose, ""},
    {"accessory position", ScriptOp::AccessoryPosition, "nnn"},
    {"accessory rotation", ScriptOp::AccessoryRotation, "nnn"},
    {"accessory scale", ScriptOp::AccessoryScale, "n"},
    {"accessory opacity", ScriptOp::AccessoryOpacity, "n"},
    {"accessory parent", ScriptOp::AccessoryParent, "tt"},
    {"register bone", ScriptOp::RegisterBone, ""},
    {"register morph", ScriptOp::RegisterMorph, "l"},
    {"register display", ScriptOp::RegisterDisplay, ""},
    {"register camera", ScriptOp::RegisterCamera, ""},
    {"register light", ScriptOp::RegisterLight, ""},
    {"register shadow", ScriptOp::RegisterShadow, ""},
    {"register gravity", ScriptOp::RegisterGravity, ""},
    {"register accessory", ScriptOp::RegisterAccessory, ""},
    {"copy", ScriptOp::Copy, ""},
    {"paste reverse", ScriptOp::PasteReverse, ""},
    {"paste different", ScriptOp::PasteDifferent, ""},
    {"paste", ScriptOp::Paste, ""},
    {"delete", ScriptOp::Delete, ""},
    {"line insert bone", ScriptOp::InsertBoneLine, ""},
    {"line delete bone", ScriptOp::DeleteBoneLine, ""},
    {"line insert morph", ScriptOp::InsertMorphLine, ""},
    {"line delete morph", ScriptOp::DeleteMorphLine, ""},
    {"select all bone", ScriptOp::SelectAllBone, ""},
    {"select all display", ScriptOp::SelectAllDisplay, ""},
    {"select all morph", ScriptOp::SelectAllMorph, ""},
    {"select all camera", ScriptOp::SelectAllCamera, ""},
    {"select all light", ScriptOp::SelectAllLight, ""},
    {"select all shadow", ScriptOp::SelectAllShadow, ""},
    {"select all gravity", ScriptOp::SelectAllGravity, ""},
    {"select all accessory", ScriptOp::SelectAllAccessory, ""},
    {"undo", ScriptOp::Undo, ""},
    {"redo", ScriptOp::Redo, ""},
};
// clang-format on

struct ScriptCommand {
    int line = 0; // 1-based line number in the script: the step id of manifest.tsv
    ScriptOp op = ScriptOp::New;
    std::string name;              // the fixed words, for error messages
    std::vector<std::string> args; // as written (numbers are not converted)
};

// Splits one line into words. False on an unterminated quote.
inline bool SplitScriptWords(const std::string& line, std::vector<std::string>* words) {
    words->clear();
    std::size_t i = 0;
    while (i < line.size()) {
        const char c = line[i];
        if (c == ' ' || c == '\t' || c == '\r') {
            ++i;
            continue;
        }
        std::string word;
        if (c == '"') {
            const std::size_t end = line.find('"', i + 1);
            if (end == std::string::npos)
                return false;
            word = line.substr(i + 1, end - i - 1);
            i = end + 1;
        } else {
            while (i < line.size() && line[i] != ' ' && line[i] != '\t' && line[i] != '\r')
                word += line[i++];
        }
        words->push_back(word);
    }
    return true;
}

inline bool IsScriptNumber(const std::string& text) {
    std::size_t i = (!text.empty() && (text[0] == '-' || text[0] == '+')) ? 1 : 0;
    bool digits = false, dot = false;
    for (; i < text.size(); ++i) {
        if (text[i] >= '0' && text[i] <= '9')
            digits = true;
        else if (text[i] == '.' && !dot)
            dot = true;
        else
            return false;
    }
    return digits;
}

inline bool IsScriptFrame(const std::string& text) {
    if (text.empty() || text.size() > 6)
        return false;
    std::uint32_t value = 0;
    for (const char c : text) {
        if (c < '0' || c > '9')
            return false;
        value = value * 10 + static_cast<std::uint32_t>(c - '0');
    }
    return value < kMaxScriptFrame;
}

// Parses the whole script. On failure returns false and sets *error to
// "line N: <reason>". A save target must be a plain file name (it is written
// into <out-dir>), and each target may be saved only once, so manifest.tsv
// names every file once.
inline bool ParseScript(const std::string& text, std::vector<ScriptCommand>* commands,
                        std::string* error) {
    commands->clear();
    std::size_t start = 0;
    if (text.compare(0, 3, "\xEF\xBB\xBF") == 0)
        start = 3;
    int lineNumber = 0;
    std::set<std::string> saved;
    while (start <= text.size()) {
        std::size_t end = text.find('\n', start);
        if (end == std::string::npos)
            end = text.size();
        const std::string line = text.substr(start, end - start);
        start = end + 1;
        ++lineNumber;
        const std::string where = "line " + std::to_string(lineNumber) + ": ";
        std::vector<std::string> words;
        if (!SplitScriptWords(line, &words)) {
            *error = where + "unterminated quote";
            return false;
        }
        if (words.empty() || words[0][0] == '#')
            continue;
        // The longest fixed word sequence that matches wins ("paste reverse" over "paste").
        const ScriptCommandSpec* best = nullptr;
        std::size_t bestWords = 0;
        for (const ScriptCommandSpec& spec : kScriptCommands) {
            std::vector<std::string> fixed;
            SplitScriptWords(spec.words, &fixed);
            if (fixed.size() > words.size() || fixed.size() <= bestWords)
                continue;
            bool match = true;
            for (std::size_t w = 0; w < fixed.size() && match; ++w)
                match = fixed[w] == words[w];
            if (match) {
                best = &spec;
                bestWords = fixed.size();
            }
        }
        if (best == nullptr) {
            *error = where + "unknown command \"" + words[0] + "\"";
            return false;
        }
        ScriptCommand command;
        command.line = lineNumber;
        command.op = best->op;
        command.name = best->words;
        command.args.assign(words.begin() + static_cast<std::ptrdiff_t>(bestWords), words.end());
        const std::size_t argCount = std::strlen(best->args);
        if (command.args.size() != argCount) {
            *error = where + command.name + " takes " + std::to_string(argCount) + " argument(s)";
            return false;
        }
        for (std::size_t a = 0; a < argCount; ++a) {
            const std::string& arg = command.args[a];
            const char kind = best->args[a];
            const bool ok = kind == 't'   ? !arg.empty()
                            : kind == 'n' ? IsScriptNumber(arg)
                            : kind == 'f' ? IsScriptFrame(arg)
                                          : arg.size() == 1 && arg[0] >= '0' && arg[0] <= '3';
            if (!ok) {
                *error = where + command.name + ": bad argument \"" + arg + "\"";
                return false;
            }
        }
        const bool isSave = command.op == ScriptOp::SavePmm || command.op == ScriptOp::SaveVmd ||
                            command.op == ScriptOp::SaveVpd || command.op == ScriptOp::SavePmd;
        if (isSave) {
            const std::string& file = command.args[0];
            if (file.find_first_of("\\/:") != std::string::npos || file == "." || file == ".." ||
                file == "manifest.tsv") {
                *error = where + "a save target is a plain file name other than manifest.tsv";
                return false;
            }
            if (!saved.insert(file).second) {
                *error = where + file + " is saved twice";
                return false;
            }
        }
        commands->push_back(command);
    }
    return true;
}

} // namespace mikudancestudio::tools
