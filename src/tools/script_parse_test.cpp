// Checks the --mds-script parser of script_parse.hpp. Portable:
//   c++ -std=c++17 -I src/tools src/tools/script_parse_test.cpp && ./a.out
#include "script_parse.hpp"

#include <cstdio>
#include <string>
#include <vector>

using namespace mikudancestudio::tools;

namespace {
int g_failures = 0;

#define CHECK(condition)                                                                           \
    do {                                                                                           \
        if (!(condition)) {                                                                        \
            std::fprintf(stderr, "%s:%d: CHECK(%s)\n", __FILE__, __LINE__, #condition);            \
            ++g_failures;                                                                          \
        }                                                                                          \
    } while (0)

std::string Error(const std::string& text) {
    std::vector<ScriptCommand> commands;
    std::string error;
    return ParseScript(text, &commands, &error) ? std::string() : error;
}
} // namespace

int main() {
    std::vector<ScriptCommand> commands;
    std::string error;
    const std::string text = "\xEF\xBB\xBF# comment\r\n"
                             "\n"
                             "load model \"my model.pmx\"\r\n"
                             "  select bone \xE3\x82\xBB\xE3\x83\xB3\xE3\x82\xBF\xE3\x83\xBC\n"
                             "bone rotation 0 -12.5 +3\n"
                             "morph 2 0.5\n"
                             "paste\n"
                             "paste reverse\n"
                             "frame 30\n"
                             "save vmd out.vmd";
    CHECK(ParseScript(text, &commands, &error));
    CHECK(error.empty());
    CHECK(commands.size() == 8);
    if (commands.size() == 8) {
        CHECK(commands[0].line == 3 && commands[0].op == ScriptOp::LoadModel &&
              commands[0].args.size() == 1 && commands[0].args[0] == "my model.pmx");
        CHECK(commands[1].line == 4 && commands[1].op == ScriptOp::SelectBone &&
              commands[1].args[0] == "\xE3\x82\xBB\xE3\x83\xB3\xE3\x82\xBF\xE3\x83\xBC");
        CHECK(commands[2].op == ScriptOp::BoneRotation && commands[2].args[1] == "-12.5");
        CHECK(commands[3].op == ScriptOp::MorphWeight && commands[3].args[0] == "2");
        CHECK(commands[4].op == ScriptOp::Paste && commands[4].args.empty());
        CHECK(commands[5].op == ScriptOp::PasteReverse);
        CHECK(commands[6].op == ScriptOp::Frame && commands[6].args[0] == "30");
        CHECK(commands[7].line == 10 && commands[7].op == ScriptOp::SaveVmd &&
              commands[7].name == "save vmd");
    }

    CHECK(Error("jump 3") == "line 1: unknown command \"jump\"");
    CHECK(Error("\nframe") == "line 2: frame takes 1 argument(s)");
    CHECK(Error("frame -1").find("bad argument") != std::string::npos);
    CHECK(Error("frame 100000").find("bad argument") != std::string::npos);
    CHECK(Error("morph 4 0.5").find("bad argument") != std::string::npos);
    CHECK(Error("bone position 1 2 x").find("bad argument") != std::string::npos);
    CHECK(Error("bone position 1 2 1.2.3").find("bad argument") != std::string::npos);
    CHECK(Error("load model \"a.pmx").find("unterminated quote") != std::string::npos);
    CHECK(Error("save pmm sub\\a.pmm").find("plain file name") != std::string::npos);
    CHECK(Error("save pmm manifest.tsv").find("plain file name") != std::string::npos);
    CHECK(Error("save pmm a.pmm\nsave pmm a.pmm") == "line 2: a.pmm is saved twice");
    CHECK(Error("paste 3").find("takes 0") != std::string::npos);
    CHECK(Error("").empty());
    CHECK(Error("save pmm messages.tsv").find("plain file name") != std::string::npos);
    CHECK(Error("trace a.trace\nsave pmm a.trace") == "line 2: a.trace is saved twice");
    CHECK(Error("loop 1").find("bad argument") != std::string::npos);
    CHECK(Error("physics mode 4").find("bad argument") != std::string::npos);
    CHECK(Error("scale range 0 30 2 on off maybe").find("bad argument") != std::string::npos);
    CHECK(Error("pump 3 -1").find("bad argument") != std::string::npos);
    CHECK(
        ParseScript("delete unused\ndelete\nregister all morph\nshift lip -5", &commands, &error) &&
        commands.size() == 4 && commands[0].op == ScriptOp::DeleteUnused &&
        commands[1].op == ScriptOp::Delete && commands[2].op == ScriptOp::RegisterAllMorph &&
        commands[3].op == ScriptOp::ShiftLip && commands[3].args[0] == "-5");

    CHECK(ParseScript("delete model\ndrag 10 -3\ndialog text 667 \"a b\"\ncamera reference 2",
                      &commands, &error) &&
          commands.size() == 4 && commands[0].op == ScriptOp::DeleteModel &&
          commands[1].op == ScriptOp::DragKeys && commands[1].args[1] == "-3" &&
          commands[2].op == ScriptOp::DialogText && commands[2].args[1] == "a b" &&
          commands[3].op == ScriptOp::CameraReference);
    CHECK(Error("drag -1 3").find("bad argument") != std::string::npos);

    // Every command spec is reachable by its own words.
    for (const ScriptCommandSpec& spec : kScriptCommands) {
        std::string line = spec.words;
        for (const char* kind = spec.args; *kind != '\0'; ++kind)
            line += *kind == 't' ? " x.pmm" : *kind == 'o' ? " on" : " 1";
        CHECK(ParseScript(line, &commands, &error) && commands.size() == 1 &&
              commands[0].op == spec.op);
    }

    if (g_failures == 0)
        std::puts("script_parse: ok");
    return g_failures == 0 ? 0 : 1;
}
