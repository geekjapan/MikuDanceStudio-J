#pragma once
#include "rhi_model_pipeline.hpp"
#include "rhi_model_replay.hpp"
#include "scene_preview_ui.hpp"
namespace mikudancestudio {
class MMDApp;
namespace render {struct SceneDrawReplacement;}
#ifdef MIKUDANCESTUDIO_DIAG
// Diagnostic isolated batch only: owned live CPU geometry/textures. The legacy
// bridge can audit against native state; direct mode consumes CPU inputs only.
void SubmitCpuModelPreview(MMDApp*,unsigned char*,unsigned material,
    unsigned first,unsigned count,const rhi::HistoryDesc&,const rhi::ModelPipeline&,
    const std::array<rhi::MaterialTextureAsset,3>&,const rhi::ModelPipeline* reference=nullptr);
void FinishCpuFullSceneValidation(MMDApp*);
const rhi::ModelOptions& CpuDiagnosticModelOptions();
bool CpuSceneNativeCheckpointPending();
#endif
#ifdef MIKUDANCESTUDIO_CPU_RENDERING
// Independent CPU frame production; native recorder is an optional observer.
void BeginCpuSceneFrame(MMDApp*,unsigned clearFlags,unsigned clearColor);
void FinishCpuSceneFrame(MMDApp*);
bool CpuSceneFrameRecording();
bool CpuScenePreviewRequested();
void AppendCpuSceneFrame(render::SceneDrawReplacement);
void ObserveCpuSceneDraw(const char* pass);
void ExpectCpuSceneEmptyMesh();
bool ConsumeCpuSceneEmptyMesh();
void BlockCpuSceneFrame(const char*);
bool CopyAssembledCpuSceneFrame(rhi::ModelReplayStream&);
void PresentCpuSceneFrame(MMDApp*);
bool ValidateResidentCpuSceneFrame(MMDApp*,const rhi::RgbaImage&);
void ReleaseCpuSceneFrame();
void InvalidateCpuScenePreviewGate();
#endif
#ifndef MIKUDANCESTUDIO_DIAG
inline const rhi::ModelOptions& CpuDiagnosticModelOptions(){static const rhi::ModelOptions options;return options;}
inline bool CpuSceneNativeCheckpointPending(){return false;}
inline bool CpuMaterialSelected(unsigned){return false;}
#endif
#ifdef MIKUDANCESTUDIO_DIAG
// Bounded live diagnostic checkpoints. Requests are consumed at the normal
// scene-clear boundary; never restart a capture in the middle of a draw pass.
void BeginCpuFullSceneValidation(MMDApp*);
void ReleaseCpuModelPreview();
void ReleaseCpuModelPreview(unsigned char* model);
// A subset frame starts before the legacy material loop and finishes after it.
// Unsupported or missing selected draws block the whole ordered submission.
void BeginCpuModelMaterials(MMDApp*,unsigned char*);
void EndCpuModelMaterials(MMDApp*,unsigned char*);
void CaptureCpuMaterialHistory(MMDApp*,unsigned char*,unsigned material);
bool CpuMaterialSelected(unsigned);
void BlockCpuModelPreview(MMDApp*,unsigned char*,unsigned material,const char* reason);
#endif
}
