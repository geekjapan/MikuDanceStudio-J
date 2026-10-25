// Declarations the checked sources take from the real ported_funcs.hpp, with
// the same signatures (a drift shows up as a link error). skin_check.cpp
// defines the loader callees as no-ops: textures, physics bodies, the bone
// sort order and the post-load pass do not reach the vertex buffers.
#pragma once
#include <Windows.h>
#include <cstdint>
#include "mikudancestudio/charset_conv.hpp"
namespace mikudancestudio {
class MMDApp;
class PhysicsScene;
struct PathResolutionWorkspace;
bool ModelLoadPMD(unsigned char* model, HWND hwnd, const wchar_t* path, D3DRenderer* sub, int a5,
                  std::uint8_t a6, std::uint8_t a7, PhysicsScene* a8,
                  PathResolutionWorkspace& paths);
bool LoadPMX(unsigned char* model, D3DRenderer* sub, std::uint8_t showInfo, std::uint8_t englishUI,
             PathResolutionWorkspace& paths, int fh);
void InitBoneSortOrder(unsigned char* model);
void PostLoadInit(unsigned char* model);
void SetPhysicsMode(unsigned char* model, int a2, unsigned char* const* modelSlots, int a4);
void ModelApplyMorphs(unsigned char* model);
void UpdateModelVertexBuffers(MMDApp* app, unsigned char* model, const float frameWorld[16]);
void CreateRigidBody(PhysicsScene* scene, void** out, int shape, float sx, float sy, float sz,
                     const float* matrix, int mode, float mass, float dampLin, float dampRot,
                     float restitution, float friction, char group, std::uint16_t mask);
int CreatePhysJoint(PhysicsScene* scene, void* bodyA, void* bodyB, float ax, float ay, float az,
                    float aq0, float aq1, float aq2, float aq3, float bx, float by, float bz,
                    float bq0, float bq1, float bq2, float bq3, float linUpper0, float linUpper1,
                    float linUpper2, float linLower0, float linLower1, float linLower2,
                    float angUpper0, float angUpper1, float angUpper2, float angLower0,
                    float angLower1, float angLower2, float spring0, float spring1, float spring2,
                    float spring3, float spring4, float spring5);
void TransformJointPointOriginal(float out[3], const float point[3], const float matrix[16]);
float JointRadiusBound(const float limits[6], float distA, float distB);
const wchar_t* ResolveUserFilePath(PathResolutionWorkspace& paths, const wchar_t* path);
errno_t ConvertMaterialName(unsigned char* sub, const char* mbName, wchar_t* wideOut,
                            rsize_t sizeWords, const wchar_t* dirW);
int LoadTextureShared(unsigned char* sub, wchar_t* path);
} // namespace mikudancestudio
