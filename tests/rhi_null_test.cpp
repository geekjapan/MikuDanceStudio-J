#include "mikudancestudio/rhi_swapchain.hpp"
#include <array>
#include <cstdint>
using namespace mikudancestudio::rhi;
int main() {
    auto device = CreateNullDevice();
    if (!device || device->BackendType() != Backend::Null ||
        device->Features().shaders || device->Present() ||
        device->CreateBuffer({BufferUsage::Index, 0, false}) ||
        device->CreateBuffer({BufferUsage::Index, 3, false}) ||
        device->CreateBuffer({BufferUsage::Uniform, 16, false})) return 1;
    const auto initialStatus = device->Status();
    const auto lifecycle = device->ResourceLifecycleFeatures();
    const SubmissionIdentity oldSubmission{initialStatus.identity, initialStatus.epoch};
    if (!IsCurrentSubmission(initialStatus, oldSubmission) ||
        IsCurrentSubmission(initialStatus, {}) || !lifecycle.resetProtocol ||
        !lifecycle.retainsStaticBuffers || !lifecycle.retainsTextures ||
        !lifecycle.invalidatesDynamicBuffers || lifecycle.ownsNativeReset) return 20;
    std::array<std::uint16_t, 3> indices{0, 1, 2};
    auto vertices = device->CreateBuffer({BufferUsage::Vertex, 36, true});
    auto index = device->CreateBuffer({BufferUsage::Index, sizeof(indices), false},
                                      indices.data());
    const auto texture = device->CreateTexture({64, 64});
    if (!vertices || !index || !texture ||
        device->DrawIndexed(device->Record(IndexedDraw{vertices, index, 0, 3, 1})) ||
        device->Upload(index, 0, indices.data(), sizeof(indices)) ||
        !device->Upload(vertices, 0, indices.data(), sizeof(indices)) ||
        !device->BeginFrame({}) || device->BeginFrame({}) ||
        device->Destroy(vertices) ||
        device->DrawIndexed(device->Record(IndexedDraw{texture, index, 0, 3, 1})) ||
        device->DrawIndexed(device->Record(IndexedDraw{vertices, index, 1, 3, 1})) ||
        device->DrawIndexed(device->Record(IndexedDraw{vertices, index, 0, 3, 1,
                             VertexLayout::ScreenPositionColor})) ||
        !device->DrawIndexed(device->Record(IndexedDraw{vertices, index, 0, 3, 1})) ||
        !device->EndFrame() || device->BeginFrame({}) ||
        !device->Present() || device->Present() ||
        !device->Destroy(index)) return 2;
    auto replacement = device->CreateBuffer({BufferUsage::Index, 6, false});
    if (!replacement || replacement.index != index.index ||
        replacement.generation == index.generation ||
        !device->BeginFrame({}) ||
        device->DrawIndexed(device->Record(IndexedDraw{vertices, index, 0, 3, 1})) ||
        !device->DrawIndexed(device->Record(IndexedDraw{vertices, replacement, 0, 3, 1})) ||
        !device->EndFrame() || !device->Present()) return 3;
    auto lines = device->CreateBuffer({BufferUsage::Vertex, 160, true});
    auto persistent = device->CreateBuffer({BufferUsage::Vertex, 160, false});
    const auto oldDraw = device->Record(NonIndexedDraw{persistent, 0, 8});
    auto wrongLayout=device->Record(NonIndexedDraw{lines,0,8});wrongLayout.layout=VertexLayout::PositionColor;
    auto explicitLayout=wrongLayout;explicitLayout.layout=VertexLayout::ScreenPositionColor;
    const auto oldIndexed = device->Record(IndexedDraw{persistent,replacement,0,3,1});
    if (!lines || !persistent || device->SetFixedPipeline({}) ||
        !device->BeginFrame({}) ||
        device->SetFixedPipeline({PrimitiveTopology::TriangleList}) ||
        !device->SetFixedPipeline({}) ||
        device->Draw(wrongLayout) || !device->Draw(explicitLayout) ||
        device->Draw(device->Record(NonIndexedDraw{lines, 0, 7})) ||
        device->Draw(device->Record(NonIndexedDraw{lines, 1, 8})) ||
        !device->Draw(device->Record(NonIndexedDraw{lines, 0, 8})) ||
        device->DrawIndexed(device->Record(IndexedDraw{vertices, replacement, 0, 3, 1})) ||
        device->PrepareForReset() || !device->EndFrame() ||
        !device->Present() || !device->PrepareForReset() ||
        device->BeginFrame({}) ||
        device->CreateBuffer({BufferUsage::Vertex, 160, true}) ||
        device->Destroy(lines) || !device->RestoreAfterReset() ||
        device->RestoreAfterReset() ||
        !device->BeginFrame({}) || !device->SetFixedPipeline({}) ||
        device->Draw(device->Record(NonIndexedDraw{lines, 0, 8})) ||
        device->Draw(oldDraw) ||
        !device->Draw(device->Record(NonIndexedDraw{persistent, 0, 8})) ||
        !device->EndFrame() || !device->Present()) return 4;
    const auto restoredStatus = device->Status();
    if (restoredStatus.identity != initialStatus.identity ||
        restoredStatus.epoch != initialStatus.epoch + 1 ||
        IsCurrentSubmission(restoredStatus, oldSubmission) ||
        !IsCurrentSubmission(restoredStatus, {restoredStatus.identity, restoredStatus.epoch}) ||
        !device->PrepareForReset()) return 21;
    const auto pending = device->Status();
    if (pending.state != DeviceState::ResetPending ||
        pending.epoch != restoredStatus.epoch || IsCurrentSubmission(pending, oldSubmission) ||
        device->PrepareForReset() || !device->RestoreAfterReset() ||
        device->Status().epoch != restoredStatus.epoch + 1) return 22;
    if (!device->BeginFrame({}) || device->DrawIndexed(oldIndexed) ||
        !device->DrawIndexed(device->Record(IndexedDraw{persistent,replacement,0,3,1})) ||
        !device->EndFrame() || !device->Present()) return 24;
    auto newLines = device->CreateBuffer({BufferUsage::Vertex, 160, true});
    auto secondLine = device->CreateBuffer({BufferUsage::Vertex, 160, true});
    if (!newLines || !secondLine || secondLine.index != lines.index ||
        secondLine.generation == lines.generation) return 5;
    auto anotherDevice = CreateNullDevice();
    if (ClassifyTexture(device->Status(), initialStatus, {true,true,false,true,false}) != TextureResidency::Reupload ||
        ClassifyTexture(anotherDevice->Status(), device->Status(), device->ResourceLifecycleFeatures()) != TextureResidency::DeviceReplaced) return 23;
    auto foreignVertex = anotherDevice->CreateBuffer(
        {BufferUsage::Vertex, 160, false});
    if (!foreignVertex || foreignVertex.index != vertices.index ||
        foreignVertex.generation != vertices.generation ||
        foreignVertex.device == vertices.device ||
        device->Destroy(foreignVertex) ||
        !device->BeginFrame({}) || !device->SetFixedPipeline({}) ||
        device->Draw(device->Record(NonIndexedDraw{foreignVertex, 0, 2})) ||
        !device->EndFrame() || !device->Present()) return 6;
    const std::array<std::uint8_t, 16> rgba{
        0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,
        0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x12};
    const auto atlas = device->CreateTexture({2, 2});
    const auto sprite = device->CreateBuffer({BufferUsage::Vertex, 84});
    if (!atlas || !sprite ||
        !device->BeginFrame({}) ||
        !device->SetFixedPipeline(HudSpritePipeline()) ||
        device->BindTexture(0, atlas) ||
        !device->EndFrame() || !device->Present() ||
        device->UploadTexture(atlas, {rgba.data(), 7, rgba.size()}) ||
        !device->UploadTexture(atlas, {rgba.data(), 8, rgba.size()}) ||
        device->BindTexture(0, atlas) || !device->BeginFrame({}) ||
        !device->SetFixedPipeline(HudSpritePipeline()) ||
        device->Draw(device->Record(NonIndexedDraw{sprite, 0, 3})) ||
        device->BindTexture(1, atlas) ||
        !device->BindTexture(0, atlas) ||
        device->Destroy(atlas) ||
        !device->Draw(device->Record(NonIndexedDraw{sprite, 0, 3})) ||
        !device->EndFrame() || !device->Present() ||
        !device->Destroy(atlas) ||
        device->UploadTexture(atlas, {rgba.data(), 8, rgba.size()}) ||
        !device->BeginFrame({}) ||
        !device->SetFixedPipeline(HudSpritePipeline()) ||
        device->BindTexture(0, atlas) ||
        !device->EndFrame() || !device->Present()) return 7;
    return 0;
}
