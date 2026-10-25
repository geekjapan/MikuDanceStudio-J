#pragma once
#include "trace_args.hpp"

namespace mikudancestudio {
class MMDApp;
}

namespace mikudancestudio::tools {
// --mds-trace and --mds-frame-dump support for the x64 app (Windows only; the
// portable parts are trace_args.hpp and trace_l2.hpp).
//
// PrepareTraceRequest runs first in WinMain, before any window or D3D object
// exists. It makes both paths absolute (InitMainWindowAndD3D changes the
// current directory), and returns false if the PMM is not an existing file,
// the path does not fit the app's 256 wchar file name buffer, <out> is the
// PMM itself, or, for a frame dump, <out-dir> is not an existing directory.
// WinMain then exits 1 and nothing has been written.
bool PrepareTraceRequest(TraceRequest* request);

// Called right after PrepareTraceRequest, still before any window exists.
// Installs a thread-local WH_CBT hook: the first dialog (a MessageBox from an
// MMD-port loader on a corrupt file, for one) writes its caption and text to
// stderr, deletes "<out>.tmp", and ends the process with exit code 1 instead
// of blocking on the modal loop. Returns false if the hook cannot be installed;
// WinMain then exits 1.
bool ArmTraceDialogGuard(const TraceRequest& request);

// Runs after InitMainWindowAndD3D loaded the PMM: steps `request.frames`
// frames without presenting. A trace writes the L2 trace to "<out>.tmp",
// renamed to <out> only on success. A frame dump renders each requested frame
// at 640x360 and writes "<out-dir>\<pmm stem>-<frame>.png" the same way.
// Returns the process exit code: 0 on success, 1 on any failure (the temp
// file is deleted; the PNGs already written stay).
int RunTraceMode(MMDApp* app, const TraceRequest& request);
} // namespace mikudancestudio::tools
