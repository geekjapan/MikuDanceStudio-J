// The MMDApp fields UpdateModelVertexBuffers reads: the camera and the
// self-shadow switch.
#pragma once
namespace mikudancestudio {
class MMDApp {
public:
    struct {
        float cameraPosition[3];
        float cameraFov;
        unsigned char selfShadowEnabled;
    } state;
    float* CameraPosition() { return state.cameraPosition; }
    float& CameraFov() { return state.cameraFov; }
};
} // namespace mikudancestudio
