// Declarations the two checked sources take from the real ported_funcs.hpp.
// A signature drift there shows up here as a link error.
#pragma once
namespace mikudancestudio {
void AppendBoneKeyToUndo(unsigned char* model, int index);
void NotifyBonePhysicsMode(unsigned char* model, int boneIdx, unsigned char mode);
}  // namespace mikudancestudio
