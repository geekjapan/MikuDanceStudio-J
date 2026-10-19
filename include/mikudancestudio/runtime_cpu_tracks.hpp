#pragma once
#include "mikudancestudio/pmm_scene_evaluation.hpp"
#include <string>

namespace mikudancestudio {
// CPU compatibility adapter. Publication preserves the linked indices used by
// the existing seek/advance/physics-arming code; it never owns GPU resources.
bool ValidateCpuPmmTracks(unsigned char*,const format::PmmSceneModel&,
                          format::PmmVersion,std::string& reason);
bool PublishCpuPmmTracks(unsigned char*,const format::PmmSceneModel&,
                         format::PmmVersion,std::string& reason);
// Shared with the editor: rigid/selector bones retain native arming and backup
// semantics. Portable evaluation overrides only the same eligible bones.
void ApplyCpuPmmPose(unsigned char*,const format::PmmEvaluatedModel&,bool selectors);
bool ApplyMappedCpuPmmPose(unsigned char*,const format::PmmSceneModel&,
                           const format::PmmEvaluatedModel&,format::PmmVersion);
}
