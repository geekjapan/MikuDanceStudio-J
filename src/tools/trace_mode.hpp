#pragma once
#include "trace_args.hpp"

namespace mikudancestudio {
class MMDApp;
}

namespace mikudancestudio::tools {
// --mds-trace support for the x64 app (Windows only; the portable parts are
// trace_args.hpp and trace_l2.hpp).
//
// PrepareTraceRequest runs first in WinMain, before any window or D3D object
// exists. It makes both paths absolute (InitMainWindowAndD3D changes the
// current directory), and returns false if the PMM is not an existing file,
// the path does not fit the app's 256 wchar file name buffer, or <out> is the
// PMM itself. WinMain then exits 1 and nothing has been written.
bool PrepareTraceRequest(TraceRequest* request);

// Runs after InitMainWindowAndD3D loaded the PMM: steps `request.frames`
// frames without rendering or presenting and writes the L2 trace to
// "<out>.tmp", renamed to <out> only on success. Returns the process exit
// code: 0 on success, 1 on any failure (the temp file is deleted).
int RunTraceMode(MMDApp* app, const TraceRequest& request);
}  // namespace mikudancestudio::tools
