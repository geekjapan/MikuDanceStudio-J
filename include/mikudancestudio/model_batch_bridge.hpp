#pragma once
struct IDirect3DDevice9;
namespace mikudancestudio {
class MMDApp;
#ifdef MIKUDANCESTUDIO_DIAG
void BeginModelBatchCapture(MMDApp* app, IDirect3DDevice9* device);
void EndModelBatchCapture();
void CaptureModelHistoryResult(MMDApp* app, unsigned char* model,unsigned material);
bool TryModelBatchAdapter(MMDApp* app, unsigned char* model,
    unsigned materialIndex, unsigned firstIndex, unsigned indexCount,
    unsigned stride);
void ReportModelBatchComparison(IDirect3DDevice9* device);
void InvalidateModelBatchComparison();
#else
inline void BeginModelBatchCapture(MMDApp*, IDirect3DDevice9*) {}
inline void EndModelBatchCapture() {}
inline void CaptureModelHistoryResult(MMDApp*,unsigned char*,unsigned) {}
inline bool TryModelBatchAdapter(MMDApp*, unsigned char*, unsigned, unsigned,
                                 unsigned, unsigned) { return false; }
inline void ReportModelBatchComparison(IDirect3DDevice9*) {}
inline void InvalidateModelBatchComparison() {}
#endif
}
