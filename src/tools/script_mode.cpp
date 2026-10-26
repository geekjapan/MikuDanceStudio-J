// ===========================================================================
// --mds-script <script.txt> <out-dir>  (wave 3 slice script, Windows)
// ===========================================================================
// Runs a script of editing commands (script_parse.hpp) through the app's own
// window handlers and writes every saved file into <out-dir>, plus
// <out-dir>\manifest.tsv. It is the oracle that the Rust document and UI are
// compared with byte for byte; tests/fixtures/rust/script/README.md is the
// command reference and says which handler each command drives.
//
// A command is what a user does with the mouse or keyboard, sent to the real
// window: WM_COMMAND with the menu or control id to the main window (with the
// control HWND and its notification code, as a click or a combo selection
// sends it), a numeric edit set with WM_SETTEXT and committed with the
// VK_RETURN the edit subclass (ui_edit_commit.cpp) waits for, or a combo set
// with CB_SETCURSEL and CBN_SELCHANGE. A menu item that is grayed out, or a
// control that is disabled, fails the step, because a user could not click
// it. Bone selection is the one exception: a user picks a bone by clicking
// its row in the timeline, which needs layout-dependent mouse coordinates,
// so `select bone` calls SelectDisplayBone, the function the Up and Down keys
// and the display-list picks end in (model_query_helpers.cpp).
//
// The dialogs a handler opens are replaced in process by patching the
// executable's import table (script mode only; the normal path never patches):
//   GetOpenFileNameW / GetSaveFileNameW  return the path of the current step.
//     Load paths are passed as written in the script; the handlers call
//     SetCurrentDirectoryW(exe dir) first, so a relative path names a file
//     next to the exe, where the lane stages the fixtures. A real dialog
//     returns an absolute path; a relative one keeps the saved PMM free of
//     the checkout's location. Save paths are <out-dir>\<name>. A dialog that
//     the step did not expect, or an expected dialog that never opened, fails
//     the step. `answer file <path>` queues the answer of one more dialog of
//     the next step (the PMM 0001 loader asks for an accessory it cannot
//     open); the next step must use every queued answer.
//   MessageBoxA / MessageBoxW  an OK/Cancel question is answered OK when the
//     step's command asks one in the GUI (new, load pmm, load model, load vmd
//     onto a model of another name, paste different, delete lip, eye, and
//     eyebrow); any other box fails the step and prints its text.
//     The info boxes of `delete unused` and `register blink` (MB_OK, the
//     deleted and registered counts) are answered OK too and their text is
//     written to <out-dir>\messages.tsv.
// Any other dialog (class #32770) fails the step through a WH_CBT hook,
// except the gravity dialog, which `gravity open` creates (it is modeless),
// and the modal dialog of a bulk operation (bias, shift lip, register blink,
// the three multiply dialogs, physics frames, scale range). The handler
// blocks in DialogBoxParamA, so a WH_CALLWNDPROCRET hook fills that
// dialog's controls when its WM_INITDIALOG returns (WM_SETTEXT, BM_SETCHECK,
// or CB_SETCURSEL with CBN_SELCHANGE) and posts the OK button's BN_CLICKED,
// which the dialog's modal loop delivers as a click.
//
// Between steps the runner drains the message queue and runs FrameDriver
// (frame_driver.cpp) kSettleFrames times, as the app's own loop does between
// two user actions, so state that the frame loop consumes (the physics reset
// after a VMD or VPD load, the Enter-key poll) settles the same way. The
// VK_RETURN of an edit is a message, so GetKeyState never sees Enter down
// and the frame loop's Enter-to-register path (pump_edit_keys.cpp) does not
// fire: an edit command commits the value only, and keys are registered by
// the register commands alone. The
// frame delta is fixed at 1/30 s instead of the wall clock, so physics steps
// the same in every run. `settle <n>` changes the number of those frames for
// the steps that follow (physics scenarios use 0, so only `pump` runs
// frames). `pump <n> <ms>` runs n passes of the loop body of winmain.cpp with
// a clock that advances ms milliseconds per pass, and `trace <name>` makes
// every pump pass append the rigid-body lines of the L2 trace format
// (trace_l2.hpp) to <out-dir>\<name>. The main window stays hidden, so no
// stray mouse or keyboard input reaches it.
//
// Slice script3 adds the commands that need the mouse, the shell, or a
// modeless dialog. `drag` sends the WM_MOUSEMOVE, WM_LBUTTONDOWN,
// WM_MOUSEMOVE, WM_LBUTTONUP of a key drag in the timeline; the cell it
// presses is found in the hit maps that PanelPaint (ui_panel_paint.cpp)
// fills, the layout a user sees. `drop` sends WM_DROPFILES with an HDROP
// that holds one absolute path, as the shell does. `english open` and
// `physics model open` open the modeless dialogs of menus 259 and 262, and
// the `dialog` commands set their controls and close them. The text file
// that a VSQ lip sync writes next to the VSQ is copied into <out-dir>.
// =========================================================================//
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <bcrypt.h>
#include <commctrl.h>
#include <commdlg.h>
#include <shlobj.h> // DROPFILES

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <fstream>
#include <iterator>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "btBulletDynamicsCommon.h"

#include "mikudancestudio/menu_commands.h"
#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/model.hpp"
#include "mikudancestudio/panel_controls.hpp"
#include "mikudancestudio/ported_funcs.hpp"

#include "script_mode.hpp"
#include "trace_l2.hpp"

namespace mikudancestudio {
void SelectDisplayBone(MMDApp* app, int boneIdx); // model_query_helpers.cpp (no header)
void PanelPaint(MMDApp* app);                     // ui_panel_paint.cpp (no header)
} // namespace mikudancestudio

namespace mikudancestudio::tools {
namespace {

constexpr int kSettleFrames = 2;
constexpr std::size_t kDialogPathLength = 0x100; // the handlers' path buffers
// ApplyFrameRangeScale reads its edits with GetWindowTextA(.., 8); the other
// dialogs read 19 characters. One limit for all keeps a value from being cut.
constexpr std::size_t kDialogTextLength = 7;
// The toon dialog reads its edits with GetWindowTextA(.., 0x100) and stores
// them with strcpy_s(.., 0x64).
constexpr std::size_t kToonNameLength = 0x63;
// The timeline layout of PanelPaint and HandleLButtonDown
// (ui_panel_paint.cpp, ui_editor_click.cpp): frame columns 13 pixels wide
// from x 100, track rows 14 pixels high from y 160, the accessory rows from
// y 216, and (sidebar - 84) / 13 visible columns.
constexpr int kTimelineLeft = 100;
constexpr int kTimelineTop = 160;
constexpr int kAccessoryTop = 216;
constexpr int kColumnWidth = 13;
constexpr int kRowHeight = 14;

// ---- text ---------------------------------------------------------------

std::wstring FromCodePage(const std::string& text, UINT codePage) {
    if (text.empty())
        return std::wstring();
    const int size =
        MultiByteToWideChar(codePage, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
    std::wstring wide(static_cast<std::size_t>(size), L'\0');
    MultiByteToWideChar(codePage, 0, text.data(), static_cast<int>(text.size()), &wide[0], size);
    return wide;
}

std::string ToCodePage(const std::wstring& text, UINT codePage) {
    if (text.empty())
        return std::string();
    const int size = WideCharToMultiByte(codePage, 0, text.data(), static_cast<int>(text.size()),
                                         nullptr, 0, nullptr, nullptr);
    std::string narrow(static_cast<std::size_t>(size), '\0');
    WideCharToMultiByte(codePage, 0, text.data(), static_cast<int>(text.size()), &narrow[0], size,
                        nullptr, nullptr);
    return narrow;
}

std::wstring Wide(const std::string& utf8) {
    return FromCodePage(utf8, CP_UTF8);
}

std::string Utf8(const std::wstring& wide) {
    return ToCodePage(wide, CP_UTF8);
}

// The UI controls and model names are Shift-JIS (code page 932), as in the
// original; the script is UTF-8.
std::string Sjis(const std::string& utf8) {
    return ToCodePage(Wide(utf8), 932);
}

std::string SjisToUtf8(const char* text) {
    return Utf8(FromCodePage(text, 932));
}

void WriteError(const std::string& line) {
    HANDLE error = GetStdHandle(STD_ERROR_HANDLE);
    DWORD written = 0;
    if (error != nullptr && error != INVALID_HANDLE_VALUE)
        WriteFile(error, line.data(), static_cast<DWORD>(line.size()), &written, nullptr);
    OutputDebugStringA(line.c_str());
}

std::wstring FullPath(const std::wstring& path) {
    wchar_t buffer[MAX_PATH * 4];
    const DWORD length = GetFullPathNameW(path.c_str(), MAX_PATH * 4, buffer, nullptr);
    if (length == 0 || length >= MAX_PATH * 4)
        return std::wstring();
    return std::wstring(buffer, length);
}

bool IsFile(const std::wstring& path) {
    const DWORD attributes = GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

// ---- the step state the hooks read ---------------------------------------

// One control of a modal dialog, as a user sets it before clicking OK.
struct DialogInput {
    enum Kind {
        Text,
        Check,
        ComboItem
    } kind;
    int id;
    std::string text; // Text: the edit's text; Check: "1" or "0"; ComboItem: the item index
};

struct StepState {
    const ScriptCommand* command = nullptr;
    std::wstring dialogPath;        // the path the next file dialog returns, empty: none expected
    bool dialogUsed = false;        // a file dialog returned dialogPath
    bool answerOkCancel = false;    // an OK/Cancel question is answered OK
    bool answerInfo = false;        // an MB_OK box is answered OK and recorded
    bool allowDialogWindow = false; // a #32770 window may open (gravity, a bulk operation)
    const std::vector<DialogInput>* dialogInputs = nullptr; // the next modal dialog's controls
    bool dialogFilled = false;                              // a modal dialog got them
    int okCancelAnswered = 0;                               // OK/Cancel questions answered
};

StepState g_step;
std::set<HWND> g_allowedDialogs;
std::vector<std::string> g_messages;     // messages.tsv lines
std::vector<std::wstring> g_fileAnswers; // `answer file` paths, oldest first

std::string StepName() {
    if (g_step.command == nullptr)
        return "mds-script: before the first step: ";
    return "mds-script: line " + std::to_string(g_step.command->line) + " (" +
           g_step.command->name + "): ";
}

// Inside a hook the app is mid-handler; leave without unwinding it (as
// trace_mode.cpp's dialog guard does).
[[noreturn]] void AbortStep(const std::string& reason) {
    WriteError(StepName() + reason + "\n");
    TerminateProcess(GetCurrentProcess(), 1);
    for (;;)
        Sleep(INFINITE);
}

// ---- import table hooks ---------------------------------------------------

using GetFileNameFn = BOOL(WINAPI*)(LPOPENFILENAMEW);
using MessageBoxAFn = int(WINAPI*)(HWND, LPCSTR, LPCSTR, UINT);
using MessageBoxWFn = int(WINAPI*)(HWND, LPCWSTR, LPCWSTR, UINT);

BOOL AnswerFileDialog(LPOPENFILENAMEW ofn, const char* kind) {
    std::wstring path;
    if (!g_step.dialogPath.empty() && !g_step.dialogUsed) {
        path = g_step.dialogPath;
    } else if (!g_fileAnswers.empty()) {
        path = g_fileAnswers.front();
        g_fileAnswers.erase(g_fileAnswers.begin());
    } else {
        AbortStep(std::string("unexpected ") + kind + " dialog");
    }
    if (ofn == nullptr || ofn->lpstrFile == nullptr || path.size() >= ofn->nMaxFile)
        AbortStep(std::string(kind) + " dialog: the path does not fit the handler's buffer");
    wcscpy_s(ofn->lpstrFile, ofn->nMaxFile, path.c_str());
    const std::size_t slash = path.find_last_of(L"\\/");
    const std::size_t nameStart = slash == std::wstring::npos ? 0 : slash + 1;
    const std::size_t dot = path.find_last_of(L'.');
    ofn->nFileOffset = static_cast<WORD>(nameStart);
    ofn->nFileExtension =
        static_cast<WORD>(dot == std::wstring::npos || dot < nameStart ? path.size() : dot + 1);
    if (ofn->lpstrFileTitle != nullptr && ofn->nMaxFileTitle > 0)
        wcsncpy_s(ofn->lpstrFileTitle, ofn->nMaxFileTitle, path.c_str() + nameStart, _TRUNCATE);
    if (path == g_step.dialogPath)
        g_step.dialogUsed = true;
    return TRUE;
}

BOOL WINAPI ScriptGetOpenFileNameW(LPOPENFILENAMEW ofn) {
    return AnswerFileDialog(ofn, "open file");
}

BOOL WINAPI ScriptGetSaveFileNameW(LPOPENFILENAMEW ofn) {
    return AnswerFileDialog(ofn, "save file");
}

bool IsDialogWindow(HWND window);

int AnswerMessageBox(HWND owner, const std::string& caption, const std::string& text, UINT type) {
    if ((type & MB_TYPEMASK) == MB_OKCANCEL && g_step.answerOkCancel) {
        ++g_step.okCancelAnswered;
        return IDOK;
    }
    // The toon dialog's "cannot find" box is owned by the dialog; the
    // reminder after a successful OK by the main window.
    if (g_step.command != nullptr && g_step.command->op == ScriptOp::Toon && owner != nullptr &&
        IsDialogWindow(owner))
        AbortStep("message box: " + caption + ": " + text);
    if ((type & MB_TYPEMASK) == MB_OK && g_step.answerInfo) {
        std::string oneLine;
        for (const char c : text)
            oneLine += c == '\n' ? std::string("\\n") : std::string(1, c);
        g_messages.push_back(std::to_string(g_step.command->line) + "\t" + caption + "\t" +
                             oneLine);
        return IDOK;
    }
    AbortStep("message box: " + caption + ": " + text);
}

int WINAPI ScriptMessageBoxA(HWND owner, LPCSTR text, LPCSTR caption, UINT type) {
    return AnswerMessageBox(owner, SjisToUtf8(caption != nullptr ? caption : ""),
                            SjisToUtf8(text != nullptr ? text : ""), type);
}

int WINAPI ScriptMessageBoxW(HWND owner, LPCWSTR text, LPCWSTR caption, UINT type) {
    return AnswerMessageBox(owner, Utf8(caption != nullptr ? caption : L""),
                            Utf8(text != nullptr ? text : L""), type);
}

// Replaces the import `function` of `dll` in the executable's import table.
// False when the executable does not import it.
bool PatchImport(const char* dll, const char* function, const void* replacement) {
    auto* base = reinterpret_cast<unsigned char*>(GetModuleHandleW(nullptr));
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    const IMAGE_DATA_DIRECTORY& directory =
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (directory.VirtualAddress == 0)
        return false;
    for (auto* import =
             reinterpret_cast<const IMAGE_IMPORT_DESCRIPTOR*>(base + directory.VirtualAddress);
         import->Name != 0; ++import) {
        if (_stricmp(reinterpret_cast<const char*>(base + import->Name), dll) != 0 ||
            import->OriginalFirstThunk == 0)
            continue;
        auto* names = reinterpret_cast<const IMAGE_THUNK_DATA*>(base + import->OriginalFirstThunk);
        auto* slots = reinterpret_cast<IMAGE_THUNK_DATA*>(base + import->FirstThunk);
        for (; names->u1.AddressOfData != 0; ++names, ++slots) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))
                continue;
            const auto* byName =
                reinterpret_cast<const IMAGE_IMPORT_BY_NAME*>(base + names->u1.AddressOfData);
            if (std::strcmp(reinterpret_cast<const char*>(byName->Name), function) != 0)
                continue;
            DWORD protection = 0;
            if (!VirtualProtect(&slots->u1.Function, sizeof(slots->u1.Function), PAGE_READWRITE,
                                &protection))
                return false;
            slots->u1.Function = reinterpret_cast<ULONG_PTR>(replacement);
            VirtualProtect(&slots->u1.Function, sizeof(slots->u1.Function), protection,
                           &protection);
            return true;
        }
    }
    return false;
}

bool IsDialogWindow(HWND window) {
    wchar_t windowClass[8] = L"";
    return GetClassNameW(window, windowClass, 8) != 0 && wcscmp(windowClass, L"#32770") == 0;
}

LRESULT CALLBACK DialogGuardProc(int code, WPARAM wParam, LPARAM lParam) {
    if (code == HCBT_ACTIVATE) {
        const HWND window = reinterpret_cast<HWND>(wParam);
        if (IsDialogWindow(window) && g_allowedDialogs.count(window) == 0) {
            if (!g_step.allowDialogWindow) {
                wchar_t caption[256] = L"";
                GetWindowTextW(window, caption, 256);
                AbortStep("dialog: " + Utf8(caption));
            }
            g_allowedDialogs.insert(window);
        }
    }
    return CallNextHookEx(nullptr, code, wParam, lParam);
}

// Fills the modal dialog of the step when its WM_INITDIALOG has returned (the
// dialog proc's prefills are in place) and clicks OK.
LRESULT CALLBACK DialogFillProc(int code, WPARAM wParam, LPARAM lParam) {
    const auto* message = reinterpret_cast<const CWPRETSTRUCT*>(lParam);
    if (code == HC_ACTION && message->message == WM_INITDIALOG && g_step.dialogInputs != nullptr &&
        !g_step.dialogFilled && IsDialogWindow(message->hwnd)) {
        const HWND dialog = message->hwnd;
        g_step.dialogFilled = true;
        for (const DialogInput& input : *g_step.dialogInputs) {
            const HWND control = GetDlgItem(dialog, input.id);
            if (control == nullptr)
                AbortStep("the dialog has no control " + std::to_string(input.id));
            if (input.kind == DialogInput::Text) {
                SetWindowTextA(control, input.text.c_str());
            } else if (input.kind == DialogInput::Check) {
                SendMessageA(control, BM_SETCHECK, input.text == "1" ? BST_CHECKED : BST_UNCHECKED,
                             0);
            } else {
                SendMessageA(control, CB_SETCURSEL, std::stoul(input.text), 0);
                SendMessageA(dialog, WM_COMMAND, MAKEWPARAM(input.id, CBN_SELCHANGE),
                             reinterpret_cast<LPARAM>(control));
            }
        }
        PostMessageA(dialog, WM_COMMAND, MAKEWPARAM(IDOK, BN_CLICKED),
                     reinterpret_cast<LPARAM>(GetDlgItem(dialog, IDOK)));
    }
    return CallNextHookEx(nullptr, code, wParam, lParam);
}

// ---- driving the window ---------------------------------------------------

struct Runner {
    MMDApp* app;
    const ScriptRequest& request;
    std::vector<std::string> manifest;
    std::map<std::string, std::string> hashes; // file name -> sha256 at its last manifest line
    std::string error;                         // set by a failed step
    int settleFrames = kSettleFrames;
    std::ofstream trace;   // the open `trace` file
    std::string traceName; // its file name, empty: no trace
    int traceLine = 0;     // the line of the `trace` command
    std::uint32_t tracePass = 0;

    HWND Main() const { return static_cast<HWND>(app->Hwnd()); }

    bool Fail(const std::string& reason) {
        error = reason;
        return false;
    }

    // A panel control: on the main window, or on the floating window that
    // takes over ids 536..557 when the separate-window option is on.
    HWND Control(int id) const {
        HWND control = GetDlgItem(Main(), id);
        if (control == nullptr && app->FloatingWindow() != nullptr)
            control = GetDlgItem(app->FloatingWindow(), id);
        return control;
    }

    bool Menu(int id) {
        const UINT state = GetMenuState(GetMenu(Main()), static_cast<UINT>(id), MF_BYCOMMAND);
        if (state == static_cast<UINT>(-1))
            return Fail("menu item " + std::to_string(id) + " does not exist");
        if ((state & (MF_GRAYED | MF_DISABLED)) != 0)
            return Fail("menu item " + std::to_string(id) + " is disabled");
        SendMessageA(Main(), WM_COMMAND, MAKEWPARAM(id, 0), 0);
        return true;
    }

    HWND EnabledControl(int id) {
        const HWND control = Control(id);
        if (control == nullptr) {
            Fail("control " + std::to_string(id) + " does not exist");
            return nullptr;
        }
        if (!IsWindowEnabled(control)) {
            Fail("control " + std::to_string(id) + " is disabled");
            return nullptr;
        }
        return control;
    }

    // A button click: BN_CLICKED with the button's HWND.
    bool Click(int id) {
        const HWND control = EnabledControl(id);
        if (control == nullptr)
            return false;
        SendMessageA(Main(), WM_COMMAND, MAKEWPARAM(id, BN_CLICKED),
                     reinterpret_cast<LPARAM>(control));
        return true;
    }

    // Types `text` into a numeric edit and presses Enter.
    bool Edit(int id, const std::string& text) {
        const HWND control = EnabledControl(id);
        if (control == nullptr)
            return false;
        SetWindowTextA(control, text.c_str());
        SendMessageA(control, WM_KEYDOWN, VK_RETURN, 0);
        return true;
    }

    // Picks the combo item `item` (CB_ERR: the item whose text is `text`).
    bool Combo(int id, const std::string& text, LRESULT item = CB_ERR) {
        const HWND control = EnabledControl(id);
        if (control == nullptr)
            return false;
        if (item == CB_ERR) {
            const std::string sjis = Sjis(text);
            item = SendMessageA(control, CB_FINDSTRINGEXACT, static_cast<WPARAM>(-1),
                                reinterpret_cast<LPARAM>(sjis.c_str()));
            if (item == CB_ERR)
                return Fail("combo " + std::to_string(id) + " has no item \"" + text + "\"");
        }
        SendMessageA(control, CB_SETCURSEL, static_cast<WPARAM>(item), 0);
        SendMessageA(Main(), WM_COMMAND, MAKEWPARAM(id, CBN_SELCHANGE),
                     reinterpret_cast<LPARAM>(control));
        return true;
    }

    bool Edits(const int (&ids)[3], const std::vector<std::string>& values) {
        for (int axis = 0; axis < 3; ++axis)
            if (!Edit(ids[axis], values[static_cast<std::size_t>(axis)]))
                return false;
        return true;
    }

    // The app's message loop between two user actions (winmain.cpp), with
    // a fixed frame delta.
    static void DrainMessages() {
        MSG msg;
        while (PeekMessageA(&msg, nullptr, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT)
                continue;
            TranslateMessage(&msg);
            DispatchMessageA(&msg);
        }
    }

    void Settle() {
        for (int frame = 0; frame < settleFrames; ++frame) {
            DrainMessages();
            app->DeltaTime() = 1.0f / 30.0f;
            app->TimeNowLow() += 33;
            FrameDriver(app);
        }
    }

    // `passes` passes of the winmain.cpp loop body, with the timeGetTime
    // reading advanced by `ms` per pass and DeltaTime derived from it the way
    // that loop derives it. The frame-rate limit's Sleep is not modelled:
    // DeltaTime is what the clock says.
    bool Pump(std::uint32_t passes, std::uint32_t ms) {
        for (std::uint32_t pass = 0; pass < passes; ++pass) {
            DrainMessages();
            std::uint64_t now =
                (static_cast<std::uint64_t>(app->TimeNowHigh()) << 32) | app->TimeNowLow();
            now += ms;
            app->DeltaTime() = static_cast<float>(static_cast<std::int64_t>(ms)) * 0.001f;
            app->TimeNowLow() = static_cast<std::uint32_t>(now);
            app->TimeNowHigh() = static_cast<std::uint32_t>(now >> 32);
            FrameDriver(app);
            if (!traceName.empty() && !WriteRigidBlock(++tracePass))
                return false;
        }
        return true;
    }

    bool StartTrace(const std::string& name) {
        if (!traceName.empty())
            return Fail("a trace is already open (one trace per script)");
        trace.open((request.out + L"\\" + Wide(name)).c_str(), std::ios::binary | std::ios::trunc);
        if (!trace)
            return Fail("cannot create " + name);
        traceName = name;
        traceLine = g_step.command->line;
        l2::WriteHeader(trace);
        return WriteRigidBlock(0);
    }

    // The "rigid" lines of one trace block: every rigid body of every loaded
    // model, by slot, then by the model's rigid body order.
    bool WriteRigidBlock(std::uint32_t block) {
        for (int slot = 0; slot < kModelSlotCount; ++slot) {
            unsigned char* model = app->ModelSlot(slot);
            if (model == nullptr)
                continue;
            const mdl::ModelRecord* record = mdl::Mdl(model);
            const mdl::RigidRecord* rigids = mdl::Rigids(model);
            for (std::uint32_t i = 0; i < record->rigidCount; ++i) {
                const auto* body = static_cast<const btRigidBody*>(rigids[i].body);
                if (body == nullptr)
                    return Fail("model slot " + std::to_string(slot) + " rigid body " +
                                std::to_string(i) + " has no Bullet body");
                const btTransform& transform = body->getWorldTransform();
                const btVector3& origin = transform.getOrigin();
                const btQuaternion rotation = transform.getRotation();
                const float position[3] = {origin.x(), origin.y(), origin.z()};
                const float quaternion[4] = {rotation.x(), rotation.y(), rotation.z(),
                                             rotation.w()};
                if (!l2::WriteRigidLine(trace, block, static_cast<unsigned>(slot), i, position,
                                        quaternion))
                    return Fail("a rigid body transform is not finite");
            }
        }
        if (!trace)
            return Fail("cannot write " + traceName);
        return true;
    }

    // Closes the trace and adds its manifest line (step: the `trace` line).
    bool FinishTrace() {
        if (traceName.empty())
            return true;
        trace.close();
        std::string hash;
        if (!trace || !Sha256(request.out + L"\\" + Wide(traceName), &hash))
            return Fail("cannot write " + traceName);
        manifest.push_back(std::to_string(traceLine) + "\t" + traceName + "\t" + hash);
        return true;
    }

    // A modal dialog step: `open` makes the handler open it, the hook fills
    // `inputs` and clicks OK.
    template <class Open>
    bool WithModalDialog(const std::vector<DialogInput>& inputs, Open open,
                         std::size_t maxLength = kDialogTextLength) {
        for (const DialogInput& input : inputs)
            if (input.text.size() > maxLength)
                return Fail("\"" + input.text + "\" is longer than " + std::to_string(maxLength) +
                            " characters");
        g_step.dialogInputs = &inputs;
        g_step.dialogFilled = false;
        const bool ok = open();
        const bool filled = g_step.dialogFilled;
        g_step.dialogInputs = nullptr;
        if (ok && !filled)
            return Fail("the handler did not open its dialog");
        return ok;
    }

    // Edits `first`, `first + 1`, ... set to `values`.
    static std::vector<DialogInput> TextInputs(int first, const std::vector<std::string>& values) {
        std::vector<DialogInput> inputs;
        for (std::size_t i = 0; i < values.size(); ++i)
            inputs.push_back({DialogInput::Text, first + static_cast<int>(i), values[i]});
        return inputs;
    }

    // A checkbox click when its state differs from `on`: the check mark and
    // the BN_CLICKED a click sends.
    bool SetCheckbox(int id, bool on, bool current) {
        if (on == current)
            return true;
        const HWND control = EnabledControl(id);
        if (control == nullptr)
            return false;
        SendMessageA(control, BM_SETCHECK, on ? BST_CHECKED : BST_UNCHECKED, 0);
        return Click(id);
    }

    HWND GravityDialog() {
        const HWND dialog = app->GravitySettingDialog();
        if (dialog == nullptr)
            Fail("the gravity dialog is not open (gravity open)");
        return dialog;
    }

    // Writes `text` into a gravity dialog edit: one EN_UPDATE with the whole text.
    bool GravityEdit(int id, const std::string& text) {
        const HWND dialog = GravityDialog();
        if (dialog == nullptr)
            return false;
        SetWindowTextA(GetDlgItem(dialog, id), text.c_str());
        return true;
    }

    // A file dialog step: arms the path, runs `action`, and checks that the
    // handler asked for a file.
    template <class Action> bool WithDialog(const std::wstring& path, Action action) {
        g_step.dialogPath = path;
        g_step.dialogUsed = false;
        const bool ok = action();
        const bool used = g_step.dialogUsed;
        g_step.dialogPath.clear();
        if (ok && !used)
            return Fail("the handler did not open a file dialog");
        return ok;
    }

    // "out/<name>" names a file that an earlier step saved into <out-dir>;
    // any other relative path names a file next to the exe. Sets *wide to
    // the path the file dialog returns.
    bool InputPath(const std::string& path, std::wstring* wide, std::wstring* full = nullptr) {
        const bool fromOut = path.compare(0, 4, "out/") == 0;
        *wide = fromOut ? request.out + L"\\" + Wide(path.substr(4)) : Wide(path);
        const bool absolute = wide->size() > 1 && ((*wide)[1] == L':' || (*wide)[0] == L'\\');
        std::wstring exeDir = app->ExeDir();
        if (!exeDir.empty() && exeDir.back() != L'\\')
            exeDir += L'\\';
        const std::wstring resolved = absolute ? *wide : exeDir + *wide;
        if (!IsFile(resolved))
            return Fail("input file not found: " + Utf8(resolved));
        if (full != nullptr)
            *full = FullPath(resolved);
        if (wide->size() >= kDialogPathLength)
            return Fail("the path is longer than the handler's buffer");
        return true;
    }

    bool Load(const std::string& path, int id, bool isMenu) {
        std::wstring wide;
        if (!InputPath(path, &wide))
            return false;
        return WithDialog(wide, [&] { return isMenu ? Menu(id) : Click(id); });
    }

    // A PMD is saved as .\<name>, next to the exe, and then moved into
    // <out-dir>: the saved path becomes the model's path, which later PMM
    // saves record, and a relative one keeps them free of <out-dir>.
    bool Save(const std::string& name, int menu) {
        const std::wstring path = request.out + L"\\" + Wide(name);
        if (path.size() >= kDialogPathLength)
            return Fail("the output path is longer than the handler's buffer");
        DeleteFileW(path.c_str());
        const bool besideExe = menu == MDS_CMD_SAVE_ENHANCED_MODEL;
        std::wstring exeDir = app->ExeDir();
        if (!exeDir.empty() && exeDir.back() != L'\\')
            exeDir += L'\\';
        const std::wstring written = besideExe ? exeDir + Wide(name) : path;
        if (besideExe && IsFile(written))
            return Fail(Utf8(written) +
                        " exists (an input or a leftover); save under another name");
        if (!WithDialog(besideExe ? L".\\" + Wide(name) : path, [&] { return Menu(menu); }))
            return false;
        Settle();
        if (!IsFile(written))
            return Fail("the handler wrote no file " + Utf8(written));
        if (besideExe && !MoveFileExW(written.c_str(), path.c_str(), MOVEFILE_COPY_ALLOWED))
            return Fail("cannot move " + Utf8(written) + " into <out-dir>");
        if (menu == MDS_CMD_SAVE_MOTION && !ZeroVmdSignatureTail(path))
            return Fail("cannot rewrite " + Utf8(path));
        return RecordOutputs(name);
    }

    // The VMD writer (vmd_save.cpp) writes the 30-byte signature field from
    // a 256-byte stack buffer that sprintf_s filled with the 25 characters
    // and a NUL only, so bytes 26..29 are whatever the stack held and differ
    // between runs. The runner sets them to 0, the value a zero-filled
    // buffer gives.
    static bool ZeroVmdSignatureTail(const std::wstring& path) {
        std::fstream file(path.c_str(), std::ios::binary | std::ios::in | std::ios::out);
        const char zeros[4] = {};
        file.seekp(26);
        file.write(zeros, sizeof zeros);
        return static_cast<bool>(file);
    }

    // Adds every file of <out-dir> that is new or changed since the last
    // save to the manifest: the target first, then the files the save wrote
    // beside it (the PMM save writes <name>.emm, the MME effect map), by name.
    bool RecordOutputs(const std::string& target) {
        std::vector<std::string> names{target};
        WIN32_FIND_DATAW found;
        const HANDLE find = FindFirstFileW((request.out + L"\\*").c_str(), &found);
        if (find != INVALID_HANDLE_VALUE) {
            std::set<std::string> others;
            do {
                const std::string name = Utf8(found.cFileName);
                if ((found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0 &&
                    name != "manifest.tsv" && name != target && name != traceName)
                    others.insert(name);
            } while (FindNextFileW(find, &found));
            FindClose(find);
            names.insert(names.end(), others.begin(), others.end());
        }
        for (const std::string& name : names) {
            std::string hash;
            if (!Sha256(request.out + L"\\" + Wide(name), &hash))
                return Fail("cannot read " + name);
            std::string& known = hashes[name];
            if (known == hash)
                continue;
            known = hash;
            manifest.push_back(std::to_string(g_step.command->line) + "\t" + name + "\t" + hash);
        }
        return true;
    }

    static bool Sha256(const std::wstring& path, std::string* hex) {
        std::ifstream file(path.c_str(), std::ios::binary);
        if (!file)
            return false;
        const std::string bytes((std::istreambuf_iterator<char>(file)),
                                std::istreambuf_iterator<char>());
        unsigned char digest[32];
        if (!BCRYPT_SUCCESS(BCryptHash(BCRYPT_SHA256_ALG_HANDLE, nullptr, 0,
                                       reinterpret_cast<PUCHAR>(const_cast<char*>(bytes.data())),
                                       static_cast<ULONG>(bytes.size()), digest, sizeof digest)))
            return false;
        char text[65];
        for (int i = 0; i < 32; ++i)
            std::snprintf(text + 2 * i, 3, "%02x", digest[i]);
        *hex = text;
        return true;
    }

    unsigned char* Model() {
        unsigned char* model = app->SelectedModel();
        if (model == nullptr || app->CameraMode() != 0) {
            Fail("no model is selected (select model)");
            return nullptr;
        }
        return model;
    }

    bool SelectBone(const std::string& name) {
        unsigned char* model = Model();
        if (model == nullptr)
            return false;
        const std::string sjis = Sjis(name);
        const mdl::ModelRecord* record = mdl::Mdl(model);
        for (std::uint32_t i = 0; i < record->boneCount; ++i) {
            const mdl::BoneRecord& bone = record->boneTable[i];
            if (sjis == bone.name || sjis == bone.nameEn) {
                SelectDisplayBone(app, static_cast<int>(i));
                return true;
            }
        }
        return Fail("the selected model has no bone \"" + name + "\"");
    }

    // ---- script3 ------------------------------------------------------------

    // The y of a track row whose key is selected in timeline column
    // `column`, -1 when none: the cell a user presses to drag the marked keys.
    int SelectedKeyRow(int column) {
        const auto& st = app->state;
        if (app->CameraMode() == 0) {
            unsigned char* model = app->SelectedModel();
            if (model == nullptr)
                return -1;
            // A cell holds the record index, -10 for record 0, 0 or below
            // for no key or a group row.
            auto record = [](std::int32_t v) { return v == -10 ? 0 : v > 0 ? v : -1; };
            for (int row = 0; row < 200; ++row) {
                const int cell = row + 200 * column;
                // A folded group row holds -1 where one of its keys is
                // marked; a press there starts the drag too (StageRangeRow).
                if (st.rowHitMorph[cell] == -1 || st.rowHitBone[cell] == -1)
                    return kTimelineTop + kRowHeight * row;
                const int display = record(st.rowHitIk[cell]);
                const int morph = record(st.rowHitMorph[cell]);
                const int bone = record(st.rowHitBone[cell]);
                if ((display >= 0 && mdl::DisplayKeys(model)[display].allocated != 0) ||
                    (morph >= 0 && mdl::MorphKeys(model)[morph].allocated != 0) ||
                    (bone >= 0 && mdl::BoneKeys(model)[bone].allocated != 0))
                    return kTimelineTop + kRowHeight * row;
            }
            return -1;
        }
        const std::int32_t* bands[4] = {st.rowHitBand0, st.rowHitBand1, st.rowHitBand2,
                                        st.rowHitBand3};
        for (int band = 0; band < 4; ++band) {
            const int key = bands[band][column];
            if (key < 0)
                continue;
            const std::uint8_t selected = band == 0   ? app->CameraKeys()[key].selected
                                          : band == 1 ? app->LightKeys()[key].selected
                                          : band == 2 ? app->ShadowKeys()[key].selected
                                                      : app->GravityKeys()[key].selected;
            if (selected != 0)
                return kTimelineTop + kRowHeight * band;
        }
        // Read through a pointer: the accessory map runs past the 800 ints
        // the layout names (see ui_panel_paint.cpp).
        const std::int32_t* accessoryMap = st.rowHitAcc;
        for (int row = 0; row < 200 && st.jointLineMap[row] >= 0; ++row) {
            const int key = accessoryMap[column * 200 + row];
            if (key >= 0 && app->AccessoryKeys(st.jointLineMap[row])[key].selected != 0)
                return kAccessoryTop + kRowHeight * row;
        }
        return -1;
    }

    void Mouse(UINT message, WPARAM buttons, int x, int y) {
        SendMessageA(Main(), message, buttons,
                     MAKELPARAM(static_cast<WORD>(x & 0xFFFF), static_cast<WORD>(y & 0xFFFF)));
    }

    // Presses a selected key at `frame` in the timeline, moves the mouse by
    // `frames` columns, and releases it.
    bool DragKeys(const std::string& frameText, const std::string& framesText) {
        if (framesText.find('.') != std::string::npos)
            return Fail("the drag distance is a whole number of frames");
        const int frame = std::stoi(frameText);
        const int frames = std::stoi(framesText);
        PanelPaint(app); // the timeline as it is on screen: fills the hit maps
        const int column = frame - app->state.timelineStartFrame;
        const int columns = (app->SidebarWidth() - 84) / kColumnWidth;
        if (column < 0 || column >= columns)
            return Fail("frame " + frameText + " is not among the " + std::to_string(columns) +
                        " timeline columns from frame " +
                        std::to_string(app->state.timelineStartFrame));
        const int top = SelectedKeyRow(column);
        if (top < 0)
            return Fail("no selected key at frame " + frameText + " in the timeline");
        const int x = kTimelineLeft + kColumnWidth * column + kColumnWidth / 2;
        const int y = top + kRowHeight / 2;
        RECT client;
        GetClientRect(Main(), &client);
        Mouse(WM_MOUSEMOVE, 0, x, y);
        Mouse(WM_LBUTTONDOWN, MK_LBUTTON, x, y);
        if (app->TimelineSelectionChanged() == 0) {
            Mouse(WM_LBUTTONUP, 0, x, y);
            return Fail("the press at (" + std::to_string(x) + ", " + std::to_string(y) +
                        ") started no drag (client " + std::to_string(client.right) + "x" +
                        std::to_string(client.bottom) + ", sidebar " +
                        std::to_string(app->SidebarWidth()) + ")");
        }
        Mouse(WM_MOUSEMOVE, MK_LBUTTON, x + kColumnWidth * frames, y);
        Mouse(WM_LBUTTONUP, 0, x + kColumnWidth * frames, y);
        return true;
    }

    // Check boxes 412 (model) and 531 (bone); 0 clears the checked one.
    bool CameraReference(int mode) {
        if (mode > 2)
            return Fail("the camera reference is 0, 1, or 2");
        const HWND model = EnabledControl(panel::kCameraRefModelCheckbox);
        const HWND bone =
            model != nullptr ? EnabledControl(panel::kCameraRefBoneCheckbox) : nullptr;
        if (bone == nullptr)
            return false;
        const bool modelOn = SendMessageA(model, BM_GETCHECK, 0, 0) == BST_CHECKED;
        const bool boneOn = SendMessageA(bone, BM_GETCHECK, 0, 0) == BST_CHECKED;
        if (mode == 1)
            return SetCheckbox(panel::kCameraRefModelCheckbox, true, modelOn);
        if (mode == 2)
            return SetCheckbox(panel::kCameraRefBoneCheckbox, true, boneOn);
        return SetCheckbox(panel::kCameraRefModelCheckbox, false, modelOn) &&
               SetCheckbox(panel::kCameraRefBoneCheckbox, false, boneOn);
    }

    // The lip sync text LoadVsqFile writes in place of the VSQ (vsq_load.cpp):
    // deleted before the step, copied into <out-dir> after it.
    static std::wstring LipSyncText(const std::wstring& vsq) {
        const std::size_t dot = vsq.find_last_of(L'.');
        return vsq.substr(0, dot) + L".txt";
    }

    bool KeepLipSyncText(const std::wstring& vsq) {
        const std::wstring text = LipSyncText(vsq);
        if (!IsFile(text))
            return true; // the handler refused the file before it read it
        const std::size_t slash = text.find_last_of(L'\\');
        const std::string name = Utf8(text.substr(slash + 1));
        if (hashes.count(name) != 0 || IsFile(request.out + L"\\" + Wide(name)))
            return Fail(name + " is already in <out-dir>; lip sync another VSQ file");
        if (!CopyFileW(text.c_str(), (request.out + L"\\" + Wide(name)).c_str(), TRUE))
            return Fail("cannot copy " + Utf8(text));
        std::string hash;
        if (!Sha256(request.out + L"\\" + Wide(name), &hash))
            return Fail("cannot read " + name);
        hashes[name] = hash;
        manifest.push_back(std::to_string(g_step.command->line) + "\t" + name + "\t" + hash);
        return true;
    }

    bool LoadLipSync(const std::string& path) {
        std::wstring wide, full;
        if (!InputPath(path, &wide, &full))
            return false;
        DeleteFileW(LipSyncText(full).c_str());
        return WithDialog(wide, [&] { return Menu(MDS_CMD_LOAD_LIP_SYNC); }) &&
               KeepLipSyncText(full);
    }

    // WM_DROPFILES with the absolute path, as the shell sends a drop; the
    // handler frees the HDROP (DragFinish).
    bool Drop(const std::string& path) {
        std::wstring wide, full;
        if (!InputPath(path, &wide, &full))
            return false;
        const bool vsq = full.size() > 4 && _wcsicmp(full.c_str() + full.size() - 4, L".vsq") == 0;
        if (vsq)
            DeleteFileW(LipSyncText(full).c_str());
        const std::size_t bytes = sizeof(DROPFILES) + (full.size() + 2) * sizeof(wchar_t);
        const HGLOBAL drop = GlobalAlloc(GHND, bytes);
        auto* files = static_cast<DROPFILES*>(GlobalLock(drop));
        if (files == nullptr)
            return Fail("cannot allocate the HDROP");
        files->pFiles = sizeof(DROPFILES);
        files->fWide = TRUE;
        std::memcpy(reinterpret_cast<unsigned char*>(files) + sizeof(DROPFILES), full.c_str(),
                    full.size() * sizeof(wchar_t));
        GlobalUnlock(drop);
        SendMessageA(Main(), WM_DROPFILES, reinterpret_cast<WPARAM>(drop), 0);
        return !vsq || KeepLipSyncText(full);
    }

    // The open modeless dialog of `english open` or `physics model open`.
    HWND ModelessDialog() {
        const HWND english = app->EnglishNameDialog();
        const HWND physics = app->state.frameCopyDialog;
        if ((english != nullptr) == (physics != nullptr)) {
            Fail(english != nullptr ? "both the English name and the physics model dialogs are open"
                                    : "no dialog is open (english open, physics model open)");
            return nullptr;
        }
        return english != nullptr ? english : physics;
    }

    HWND DialogControl(HWND dialog, const std::string& idText) {
        const HWND control = GetDlgItem(dialog, std::stoi(idText));
        if (control == nullptr)
            Fail("the dialog has no control " + idText);
        else if (!IsWindowEnabled(control))
            Fail("dialog control " + idText + " is disabled");
        else
            return control;
        return nullptr;
    }

    // A click: an auto check box toggles and an auto radio button checks
    // itself before the dialog gets BN_CLICKED, as with the mouse.
    bool DialogClick(const std::string& idText) {
        const HWND dialog = ModelessDialog();
        const HWND control = dialog != nullptr ? DialogControl(dialog, idText) : nullptr;
        if (control == nullptr)
            return false;
        char windowClass[16] = "";
        GetClassNameA(control, windowClass, sizeof windowClass);
        const LONG_PTR type = GetWindowLongPtrA(control, GWL_STYLE) & BS_TYPEMASK;
        if (_stricmp(windowClass, "Button") == 0 && type == BS_AUTOCHECKBOX)
            SendMessageA(control, BM_SETCHECK,
                         SendMessageA(control, BM_GETCHECK, 0, 0) == BST_CHECKED ? BST_UNCHECKED
                                                                                 : BST_CHECKED,
                         0);
        else if (_stricmp(windowClass, "Button") == 0 && type == BS_AUTORADIOBUTTON)
            SendMessageA(control, BM_SETCHECK, BST_CHECKED, 0);
        SendMessageA(dialog, WM_COMMAND, MAKEWPARAM(std::stoi(idText), BN_CLICKED),
                     reinterpret_cast<LPARAM>(control));
        return true;
    }

    bool DialogSelect(const std::string& idText, const std::string& item) {
        const HWND dialog = ModelessDialog();
        const HWND control = dialog != nullptr ? DialogControl(dialog, idText) : nullptr;
        if (control == nullptr)
            return false;
        if (SendMessageA(control, CB_SETCURSEL, std::stoul(item), 0) == CB_ERR)
            return Fail("combo " + idText + " has no item " + item);
        SendMessageA(dialog, WM_COMMAND, MAKEWPARAM(std::stoi(idText), CBN_SELCHANGE),
                     reinterpret_cast<LPARAM>(control));
        return true;
    }

    bool DialogClose(int id) {
        const HWND dialog = ModelessDialog();
        if (dialog == nullptr)
            return false;
        SendMessageA(dialog, WM_COMMAND, MAKEWPARAM(id, BN_CLICKED),
                     reinterpret_cast<LPARAM>(GetDlgItem(dialog, id)));
        if (app->EnglishNameDialog() != nullptr || app->state.frameCopyDialog != nullptr)
            return Fail("the dialog is still open");
        return true;
    }

    static int MorphLane(const std::string& lane) { return lane[0] - '0'; }

    bool Run(const ScriptCommand& c) {
        const std::vector<std::string>& a = c.args;
        static const int kReadoutPosition[3] = {panel::kReadoutPosXEdit, panel::kReadoutPosYEdit,
                                                panel::kReadoutPosZEdit};
        static const int kReadoutRotation[3] = {panel::kReadoutRotXEdit, panel::kReadoutRotYEdit,
                                                panel::kReadoutRotZEdit};
        static const int kMorphEdits[4] = {panel::kMorphEdit0, panel::kMorphEdit1,
                                           panel::kMorphEdit2, panel::kMorphEdit3};
        static const int kMorphCombos[4] = {panel::kMorphCombo0, panel::kMorphCombo1,
                                            panel::kMorphCombo2, panel::kMorphCombo3};
        static const int kMorphRegister[4] = {
            panel::kRegisterMorphButton0, panel::kRegisterMorphButton1,
            panel::kRegisterMorphButton2, panel::kRegisterMorphButton3};
        static const int kLightColor[3] = {panel::kLightColorEditR, panel::kLightColorEditG,
                                           panel::kLightColorEditB};
        static const int kLightDirection[3] = {panel::kLightDirEditX, panel::kLightDirEditY,
                                               panel::kLightDirEditZ};
        static const int kAccPosition[3] = {panel::kAccPosXEdit, panel::kAccPosYEdit,
                                            panel::kAccPosZEdit};
        static const int kAccRotation[3] = {panel::kAccRotXEdit, panel::kAccRotYEdit,
                                            panel::kAccRotZEdit};
        static const int kShadowModes[3] = {panel::kEditOffCheckbox, panel::kEditMode1Checkbox,
                                            panel::kEditMode2Checkbox};
        switch (c.op) {
        case ScriptOp::New:
            return Menu(MDS_CMD_NEW_PROJECT);
        case ScriptOp::LoadPmm:
            return Load(a[0], MDS_CMD_OPEN_PROJECT, true);
        case ScriptOp::LoadModel:
            return Load(a[0], panel::kLoadModelButton, false);
        case ScriptOp::LoadVmd:
            return Load(a[0], MDS_CMD_LOAD_MOTION, true);
        case ScriptOp::LoadVpd:
            return Load(a[0], MDS_CMD_LOAD_POSE, true);
        case ScriptOp::LoadAccessory:
            return Load(a[0], panel::kLoadAccessoryButton, false);
        case ScriptOp::LoadWav:
            return Load(a[0], MDS_CMD_LOAD_WAVE, true);
        case ScriptOp::SavePmm:
            return Save(a[0], MDS_CMD_SAVE_PROJECT_AS);
        case ScriptOp::SaveVmd:
            return Save(a[0], MDS_CMD_SAVE_MOTION);
        case ScriptOp::SaveVpd:
            return Save(a[0], MDS_CMD_SAVE_POSE);
        case ScriptOp::SavePmd:
            return Save(a[0], MDS_CMD_SAVE_ENHANCED_MODEL);
        case ScriptOp::SelectCamera:
            return Combo(panel::kMainComboModel, std::string(), 0);
        case ScriptOp::SelectModel:
            return Combo(panel::kMainComboModel, a[0]);
        case ScriptOp::SelectBone:
            return SelectBone(a[0]);
        case ScriptOp::SelectMorph:
            return Model() != nullptr && Combo(kMorphCombos[MorphLane(a[0])], a[1]);
        case ScriptOp::SelectAccessory:
            return Combo(panel::kAccessoryCombo, a[0]);
        case ScriptOp::Frame:
            return Edit(panel::kCurrentFrameEdit, a[0]);
        case ScriptOp::BonePosition:
            return Model() != nullptr && Edits(kReadoutPosition, a);
        case ScriptOp::BoneRotation:
            return Model() != nullptr && Edits(kReadoutRotation, a);
        case ScriptOp::MorphWeight:
            return Model() != nullptr && Edit(kMorphEdits[MorphLane(a[0])], a[1]);
        case ScriptOp::CameraPosition:
            return Edits(kReadoutPosition, a);
        case ScriptOp::CameraRotation:
            return Edits(kReadoutRotation, a);
        case ScriptOp::CameraDistance:
            return Edit(panel::kReadoutDistEdit, a[0]);
        case ScriptOp::CameraFov:
            return Edit(panel::kFovEdit, a[0]);
        case ScriptOp::LightColor:
            return Edits(kLightColor, a);
        case ScriptOp::LightDirection:
            return Edits(kLightDirection, a);
        case ScriptOp::ShadowMode:
            if (a[0].size() != 1 || a[0][0] > '2')
                return Fail("the self-shadow mode is 0, 1, or 2");
            return Click(kShadowModes[a[0][0] - '0']);
        case ScriptOp::ShadowRange:
            return Edit(panel::kSelfShadowRangeEdit, a[0]);
        case ScriptOp::GravityOpen:
            return Menu(MDS_CMD_GRAVITY_SETTINGS) && (GravityDialog() != nullptr);
        case ScriptOp::GravityMagnitude:
            return GravityEdit(panel::kGravityAccelEdit, a[0]);
        case ScriptOp::GravityDirection:
            return GravityEdit(panel::kGravityDirXEdit, a[0]) &&
                   GravityEdit(panel::kGravityDirYEdit, a[1]) &&
                   GravityEdit(panel::kGravityDirZEdit, a[2]);
        case ScriptOp::GravityClose:
        case ScriptOp::RegisterGravity: {
            const HWND dialog = GravityDialog();
            if (dialog == nullptr)
                return false;
            const int id = c.op == ScriptOp::RegisterGravity ? IDOK : IDCANCEL;
            SendMessageA(dialog, WM_COMMAND, MAKEWPARAM(id, BN_CLICKED),
                         reinterpret_cast<LPARAM>(GetDlgItem(dialog, id)));
            return true;
        }
        case ScriptOp::AccessoryPosition:
            return Edits(kAccPosition, a);
        case ScriptOp::AccessoryRotation:
            return Edits(kAccRotation, a);
        case ScriptOp::AccessoryScale:
            return Edit(panel::kAccScaleEdit, a[0]);
        case ScriptOp::AccessoryOpacity:
            return Edit(panel::kAccOpacityEdit, a[0]);
        case ScriptOp::AccessoryParent:
            // "ground" is the first item of the parent-model combo (index 0).
            return (a[0] == "ground" ? Combo(panel::kMainComboGround, std::string(), 0)
                                     : Combo(panel::kMainComboGround, a[0])) &&
                   (a[1] == "-" || Combo(panel::kAttachBoneCombo, a[1]));
        case ScriptOp::RegisterBone:
            return Click(panel::kRegisterFrameButton);
        case ScriptOp::RegisterMorph:
            return Model() != nullptr && Click(kMorphRegister[MorphLane(a[0])]);
        case ScriptOp::RegisterDisplay:
            return Model() != nullptr && Click(panel::kRegisterModelDisplayButton);
        case ScriptOp::RegisterCamera:
            return Click(panel::kRegisterCameraButton);
        case ScriptOp::RegisterLight:
            return Click(panel::kRegisterLightButton);
        case ScriptOp::RegisterShadow:
            return Click(panel::kRegisterSelfShadowButton);
        case ScriptOp::RegisterAccessory:
            return Click(panel::kRegisterAccessoryButton);
        case ScriptOp::Copy:
            return Click(panel::kCopyFramesButton);
        case ScriptOp::Paste:
            return Click(panel::kPasteButton);
        case ScriptOp::PasteReverse:
            return Click(panel::kReversePasteButton);
        case ScriptOp::PasteDifferent:
            return Menu(MDS_CMD_PASTE_AT_DIFFERENT_FRAME);
        case ScriptOp::Delete:
            return Click(panel::kDeleteFramesButton);
        case ScriptOp::InsertBoneLine:
            return Menu(MDS_CMD_INSERT_BONE_CAMERA_FRAME_LINE);
        case ScriptOp::DeleteBoneLine:
            return Menu(MDS_CMD_DELETE_BONE_CAMERA_FRAME_LINE);
        case ScriptOp::InsertMorphLine:
            return Menu(MDS_CMD_INSERT_MORPH_LIGHT_FRAME_LINE);
        case ScriptOp::DeleteMorphLine:
            return Menu(MDS_CMD_DELETE_MORPH_LIGHT_FRAME_LINE);
        case ScriptOp::SelectAllBone:
            return Menu(MDS_CMD_SELECT_ALL_BONE_FRAMES);
        case ScriptOp::SelectAllDisplay:
            return Menu(MDS_CMD_SELECT_ALL_DISPLAY_FRAMES);
        case ScriptOp::SelectAllMorph:
            return Menu(MDS_CMD_SELECT_ALL_MORPH_FRAMES);
        case ScriptOp::SelectAllCamera:
            return Menu(MDS_CMD_SELECT_ALL_CAMERA_FRAMES);
        case ScriptOp::SelectAllLight:
            return Menu(MDS_CMD_SELECT_ALL_LIGHT_FRAMES);
        case ScriptOp::SelectAllShadow:
            return Menu(MDS_CMD_SELECT_ALL_SELF_SHADOW_FRAMES);
        case ScriptOp::SelectAllGravity:
            return Menu(MDS_CMD_SELECT_ALL_GRAVITY_FRAMES);
        case ScriptOp::SelectAllAccessory:
            return Menu(MDS_CMD_SELECT_ALL_ACCESSORY_FRAMES);
        case ScriptOp::Undo:
            return Click(panel::kUndoButton);
        case ScriptOp::Redo:
            return Click(panel::kRedoButton);
        case ScriptOp::CenterBias:
            return WithModalDialog(TextInputs(panel::kBiasXEdit, a),
                                   [&] { return Menu(MDS_CMD_CENTER_POSITION_BIAS); });
        case ScriptOp::DeleteUnused:
            return Menu(MDS_CMD_DELETE_UNUSED_FRAMES);
        case ScriptOp::ShiftLip:
            return WithModalDialog(TextInputs(panel::kShiftFramesEdit, a),
                                   [&] { return Menu(MDS_CMD_SHIFT_MOUTH_FRAMES); });
        case ScriptOp::DeleteLip:
            return Menu(MDS_CMD_DELETE_MOUTH_FRAMES);
        case ScriptOp::RegisterBlink:
            return WithModalDialog(TextInputs(panel::kBlinkStartEdit, a),
                                   [&] { return Menu(MDS_CMD_REGISTER_BLINKING); });
        case ScriptOp::DeleteEye:
            return Menu(MDS_CMD_DELETE_EYE_FRAMES);
        case ScriptOp::RegisterAllMorph:
            return Menu(MDS_CMD_REGISTER_ALL_MORPH_FRAMES);
        case ScriptOp::ResetMorphs:
            return Menu(MDS_CMD_RESET_MORPHS);
        case ScriptOp::DeleteEyebrow:
            return Menu(MDS_CMD_DELETE_EYEBROW_FRAMES);
        // The multiply dialogs: (scale, add) edit pairs from id 686 on.
        case ScriptOp::MultiplyCamera:
            return WithModalDialog(TextInputs(panel::kCamMulPosXScaleEdit, a),
                                   [&] { return Menu(MDS_CMD_MULTIPLY_CAMERA_FRAMES); });
        case ScriptOp::MultiplyBone:
            return WithModalDialog(TextInputs(panel::kBoneMulPosXScaleEdit, a),
                                   [&] { return Menu(MDS_CMD_MULTIPLY_BONE_FRAMES); });
        case ScriptOp::MultiplyMorph:
            return WithModalDialog(TextInputs(panel::kMorphMulScaleEdit, a),
                                   [&] { return Menu(MDS_CMD_MULTIPLY_MORPH_FRAMES); });
        case ScriptOp::PhysicsFrames: // combo item 0 is "ON (X)", item 1 "OFF"
            return WithModalDialog(
                {{DialogInput::ComboItem, panel::kBoneNameCombo, a[0] == "on" ? "0" : "1"}},
                [&] { return Menu(MDS_CMD_TOGGLE_FRAME_PHYSICS); });
        case ScriptOp::ScaleRange: {
            std::vector<DialogInput> inputs = {{DialogInput::Text, panel::kScaleFromEdit, a[0]},
                                               {DialogInput::Text, panel::kScaleToEdit, a[1]},
                                               {DialogInput::Text, panel::kScaleRateEdit, a[2]}};
            const int checks[3] = {panel::kScaleBoneCheckbox, panel::kScaleMorphCheckbox,
                                   panel::kScaleDispIkCheckbox};
            for (int i = 0; i < 3; ++i)
                inputs.push_back({DialogInput::Check, checks[i], a[3 + i] == "on" ? "1" : "0"});
            return WithModalDialog(inputs, [&] { return Click(panel::kExpandShrinkButton); });
        }
        case ScriptOp::Settle:
            settleFrames = std::stoi(a[0]);
            return true;
        case ScriptOp::Pump:
            return Pump(static_cast<std::uint32_t>(std::stoul(a[0])),
                        static_cast<std::uint32_t>(std::stoul(a[1])));
        case ScriptOp::Play: {
            if (app->PlaybackActive() != 0)
                return Fail("playback is already running (stop)");
            const HWND start = EnabledControl(panel::kPlayStartFrameEdit);
            const HWND stop =
                start != nullptr ? EnabledControl(panel::kPlayStopFrameEdit) : nullptr;
            if (stop == nullptr)
                return false;
            SetWindowTextA(start, a[0].c_str());
            SetWindowTextA(stop, a[1].c_str());
            return Click(panel::kPlayButton);
        }
        case ScriptOp::Stop:
            if (app->PlaybackActive() == 0)
                return Fail("playback is not running (play)");
            return Click(panel::kPlayButton);
        case ScriptOp::Loop:
            return SetCheckbox(panel::kPlaybackLoopCheckbox, a[0] == "on",
                               app->PlaybackLoopEnabled() != 0);
        case ScriptOp::StepForward:
            return Click(panel::kNextFrameButton);
        case ScriptOp::StepBack:
            return Click(panel::kPreviousFrameButton);
        case ScriptOp::PhysicsReset:
            return Menu(MDS_CMD_RESET_PHYSICS_BODIES);
        case ScriptOp::PhysicsMode: {
            static const int kModes[4] = {MDS_CMD_PHYSICS_DISABLED, MDS_CMD_PHYSICS_ALWAYS,
                                          MDS_CMD_PHYSICS_ON_OFF, MDS_CMD_PHYSICS_TRACE};
            return Menu(kModes[a[0][0] - '0']);
        }
        case ScriptOp::PhysicsPlaybackToggle:
            return Menu(MDS_CMD_TOGGLE_PLAYBACK_PHYSICS_ON_OFF);
        case ScriptOp::Trace:
            return StartTrace(a[0]);
        case ScriptOp::AnswerFile: {
            std::wstring wide;
            if (!InputPath(a[0], &wide))
                return false;
            g_fileAnswers.push_back(wide);
            return true;
        }
        case ScriptOp::DragKeys:
            return DragKeys(a[0], a[1]);
        case ScriptOp::DeleteModel:
            if (!Click(panel::kDeleteModelButton))
                return false;
            if (g_step.okCancelAnswered == 0)
                return Fail("the handler asked no question (no model in the combo, or a dialog "
                            "is open)");
            return true;
        case ScriptOp::CameraReference:
            return CameraReference(a[0][0] - '0');
        case ScriptOp::LoadLipSync:
            return LoadLipSync(a[0]);
        case ScriptOp::Drop:
            return Drop(a[0]);
        case ScriptOp::EnglishOpen:
            if (!Menu(MDS_CMD_EDIT_ENGLISH_NAMES))
                return false;
            return app->EnglishNameDialog() != nullptr ||
                   Fail("the English name dialog did not open (camera mode?)");
        case ScriptOp::PhysicsModelOpen:
            if (!Menu(MDS_CMD_PHYSICS_MODEL))
                return false;
            return app->state.frameCopyDialog != nullptr ||
                   Fail("the physics model dialog did not open (camera mode?)");
        case ScriptOp::DialogText: {
            const HWND dialog = ModelessDialog();
            const HWND control = dialog != nullptr ? DialogControl(dialog, a[0]) : nullptr;
            if (control == nullptr)
                return false;
            SetWindowTextA(control, Sjis(a[1]).c_str());
            return true;
        }
        case ScriptOp::DialogClick:
            return DialogClick(a[0]);
        case ScriptOp::DialogSelect:
            return DialogSelect(a[0], a[1]);
        case ScriptOp::DialogOk:
            return DialogClose(IDOK);
        case ScriptOp::DialogCancel:
            return DialogClose(IDCANCEL);
        case ScriptOp::Toon: {
            const int slot = std::stoi(a[0]);
            if (slot < 1 || slot > 10)
                return Fail("the toon slot is 1..10");
            // Edits 709..718 hold toon01..toon10 (CollectToonFileNames).
            return WithModalDialog(
                {{DialogInput::Text, 708 + slot, Sjis(a[1])}},
                [&] { return Menu(MDS_CMD_TOON_TEXTURES); }, kToonNameLength);
        }
        }
        return Fail("unhandled command");
    }
};

bool AnswersOkCancel(ScriptOp op) {
    return op == ScriptOp::New || op == ScriptOp::LoadPmm || op == ScriptOp::LoadModel ||
           op == ScriptOp::LoadVmd || op == ScriptOp::PasteDifferent || op == ScriptOp::DeleteLip ||
           op == ScriptOp::DeleteEye || op == ScriptOp::DeleteEyebrow ||
           op == ScriptOp::DeleteModel;
}

bool OpensDialogWindow(ScriptOp op) {
    return op == ScriptOp::GravityOpen || op == ScriptOp::CenterBias || op == ScriptOp::ShiftLip ||
           op == ScriptOp::RegisterBlink || op == ScriptOp::MultiplyCamera ||
           op == ScriptOp::MultiplyBone || op == ScriptOp::MultiplyMorph ||
           op == ScriptOp::PhysicsFrames || op == ScriptOp::ScaleRange ||
           op == ScriptOp::EnglishOpen || op == ScriptOp::PhysicsModelOpen || op == ScriptOp::Toon;
}

} // namespace

ScriptArgs ParseScriptArgs(int argc, const wchar_t* const* argv, ScriptRequest* request) {
    if (argv == nullptr || argc < 2 || argv[1] == nullptr ||
        std::wcscmp(argv[1], L"--mds-script") != 0)
        return ScriptArgs::NotRequested;
    if (argc != 4 || argv[2][0] == L'\0' || argv[3][0] == L'\0')
        return ScriptArgs::Malformed;
    request->script = argv[2];
    request->out = argv[3];
    return ScriptArgs::Ready;
}

bool PrepareScriptRequest(ScriptRequest* request) {
    request->script = FullPath(request->script);
    request->out = FullPath(request->out);
    while (!request->out.empty() && (request->out.back() == L'\\' || request->out.back() == L'/'))
        request->out.pop_back();
    const DWORD outAttributes = GetFileAttributesW(request->out.c_str());
    if (request->script.empty() || !IsFile(request->script) ||
        outAttributes == INVALID_FILE_ATTRIBUTES ||
        (outAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0) {
        WriteError("mds-script: the script must be a file and <out-dir> an existing directory\n");
        return false;
    }
    std::ifstream file(request->script.c_str(), std::ios::binary);
    std::ostringstream text;
    text << file.rdbuf();
    std::string error;
    if (!file || !ParseScript(text.str(), &request->commands, &error)) {
        WriteError("mds-script: " +
                   (error.empty() ? std::string("cannot read the script") : error) + "\n");
        return false;
    }
    if (!PatchImport("comdlg32.dll", "GetOpenFileNameW",
                     reinterpret_cast<const void*>(&ScriptGetOpenFileNameW)) ||
        !PatchImport("comdlg32.dll", "GetSaveFileNameW",
                     reinterpret_cast<const void*>(&ScriptGetSaveFileNameW)) ||
        !PatchImport("user32.dll", "MessageBoxA",
                     reinterpret_cast<const void*>(&ScriptMessageBoxA))) {
        WriteError("mds-script: cannot hook the file dialogs and message boxes\n");
        return false;
    }
    // Not every build imports MessageBoxW; the dialog guard covers it then.
    PatchImport("user32.dll", "MessageBoxW", reinterpret_cast<const void*>(&ScriptMessageBoxW));
    if (SetWindowsHookExW(WH_CBT, DialogGuardProc, nullptr, GetCurrentThreadId()) == nullptr ||
        SetWindowsHookExW(WH_CALLWNDPROCRET, DialogFillProc, nullptr, GetCurrentThreadId()) ==
            nullptr) {
        WriteError("mds-script: cannot install the dialog hooks\n");
        return false;
    }
    return true;
}

int RunScriptMode(MMDApp* app, const ScriptRequest& request) {
    ShowWindow(static_cast<HWND>(app->Hwnd()), SW_HIDE);
    Runner runner{app, request, {}, {}, {}};
    runner.Settle();
    for (const ScriptCommand& command : request.commands) {
        g_step = StepState{};
        g_step.command = &command;
        g_step.answerOkCancel = AnswersOkCancel(command.op);
        // The boxes that come with a queued file answer (the 0001 loader's
        // "cannot open" notes) are answered too.
        const bool queuing = command.op == ScriptOp::AnswerFile;
        // The "save enhanced model" reminder after the OK of the PMD edit
        // dialogs, and the drop refusal in camera mode, are answered too.
        g_step.answerInfo = command.op == ScriptOp::DeleteUnused ||
                            command.op == ScriptOp::RegisterBlink ||
                            command.op == ScriptOp::DialogOk || command.op == ScriptOp::Toon ||
                            command.op == ScriptOp::Drop || (!queuing && !g_fileAnswers.empty());
        g_step.allowDialogWindow = OpensDialogWindow(command.op);
        WriteError(StepName() + "start\n"); // the last line names the step of a crash
        const bool ok = runner.Run(command);
        g_step.answerOkCancel = false;
        g_step.answerInfo = false;
        g_step.allowDialogWindow = false;
        if (ok && !queuing && !g_fileAnswers.empty())
            runner.error = std::to_string(g_fileAnswers.size()) + " queued file answer(s) unused";
        if (!ok || !runner.error.empty()) {
            WriteError(StepName() + runner.error + "\n");
            return 1;
        }
        runner.Settle();
    }
    g_step = StepState{};
    if (!runner.FinishTrace()) {
        WriteError("mds-script: " + runner.error + "\n");
        return 1;
    }
    if (!g_messages.empty()) {
        std::string lines = "step\tcaption\ttext\n";
        for (const std::string& line : g_messages)
            lines += line + "\n";
        std::ofstream messages((request.out + L"\\messages.tsv").c_str(),
                               std::ios::binary | std::ios::trunc);
        messages << lines;
        messages.close();
        if (!messages) {
            WriteError("mds-script: cannot write messages.tsv\n");
            return 1;
        }
    }
    std::string text = "step\tfile\tsha256\n";
    for (const std::string& line : runner.manifest)
        text += line + "\n";
    std::ofstream manifest((request.out + L"\\manifest.tsv").c_str(),
                           std::ios::binary | std::ios::trunc);
    manifest << text;
    manifest.close();
    if (!manifest) {
        WriteError("mds-script: cannot write manifest.tsv\n");
        return 1;
    }
    return 0;
}
} // namespace mikudancestudio::tools
