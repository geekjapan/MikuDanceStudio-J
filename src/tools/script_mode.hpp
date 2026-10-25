#pragma once
#include <string>
#include <vector>

#include "script_parse.hpp"

namespace mikudancestudio {
class MMDApp;
}

namespace mikudancestudio::tools {
// --mds-script <script.txt> <out-dir> (Windows; the script language is
// script_parse.hpp, the command reference tests/fixtures/rust/script/README.md).
struct ScriptRequest {
    std::wstring script; // absolute after PrepareScriptRequest
    std::wstring out;    // absolute, an existing directory
    std::vector<ScriptCommand> commands;
};

enum class ScriptArgs {
    NotRequested,
    Ready,
    Malformed
};

// Exactly three arguments after the program: the flag, the script, and the
// output directory. Anything else with the flag is Malformed.
ScriptArgs ParseScriptArgs(int argc, const wchar_t* const* argv, ScriptRequest* request);

// Runs before any window exists: makes both paths absolute, reads and parses
// the script (errors go to stderr), and installs the hooks that stand in for
// the file dialogs and message boxes. False means WinMain exits 1.
bool PrepareScriptRequest(ScriptRequest* request);

// Runs the commands after InitMainWindowAndD3D, writes the saved files and
// <out-dir>\manifest.tsv, and returns the process exit code.
int RunScriptMode(MMDApp* app, const ScriptRequest& request);
} // namespace mikudancestudio::tools
