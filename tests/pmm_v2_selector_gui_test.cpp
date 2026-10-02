#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <ole2.h>
#include <UIAutomation.h>
#include <wrl/client.h>
#include <chrono>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <thread>
#include <tuple>
#include <vector>
#include "mikudancestudio/pmm_scene_document.hpp"
#include "mikudancestudio/pmm_scene_evaluation.hpp"

namespace {
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
using Microsoft::WRL::ComPtr;
struct Input { const std::vector<std::uint8_t>& bytes; std::size_t offset = 0; };
int Read(void* context, void* output, std::size_t size) {
    auto& input = *static_cast<Input*>(context);
    const auto count = std::min(size, input.bytes.size() - input.offset);
    if (count) std::memcpy(output, input.bytes.data() + input.offset, count);
    input.offset += count;
    return static_cast<int>(count);
}
void Put32(std::vector<std::uint8_t>& bytes, std::size_t offset,
           std::int32_t value) {
    std::memcpy(bytes.data() + offset, &value, sizeof value);
}
void PutFloat(std::vector<std::uint8_t>& bytes, std::size_t offset,
              float value) {
    std::memcpy(bytes.data() + offset, &value, sizeof value);
}
bool BuildFixture(const fs::path& source, const fs::path& output) {
    std::ifstream stream(source, std::ios::binary);
    if (!stream) return false;
    std::vector<std::uint8_t> bytes(std::istreambuf_iterator<char>{stream}, {});
    Input input{bytes};
    mikudancestudio::format::PmmSceneDocument scene;
    if (!mikudancestudio::format::ReadPmmSceneDocument(
            Read, &input, nullptr, nullptr, scene) || scene.models.size() != 1)
        return false;
    const auto& model = scene.models[0];
    if (model.rigidSources.size() < 2 || model.rigidSources[0] != -1 ||
        model.rigidSources[1] != 0 ||
        model.layout.boneCount < 1 ||
        model.boneKeys.dense.size() != model.layout.boneCount ||
        model.boneKeys.dense[0].next != 0 ||
        !model.boneKeys.sparse.empty() ||
        model.displayKeys.dense.size() != 1 ||
        !model.displayKeys.sparse.empty() ||
        model.displayKeys.dense[0].next != 0 ||
        model.displayKeys.dense[0].rigidStates.empty() ||
        model.displayKeys.dense[0].rigidStates[0].modelIndex != -1 ||
        model.displayKeys.dense[0].rigidStates[0].boneIndex != 0 ||
        !fs::is_regular_file(fs::path(model.path.data()))) return false;
    constexpr std::size_t boneRecordSize = 58;
    const std::size_t boneHeadOffset = model.boneKeys.denseRecordOffsets[0];
    const std::size_t boneCountOffset =
        model.boneKeys.denseRecordOffsets.back() + boneRecordSize;
    if (boneCountOffset + 4 > bytes.size()) return false;
    std::int32_t boneSparseCount = -1;
    std::memcpy(&boneSparseCount, bytes.data() + boneCountOffset, 4);
    if (boneSparseCount != 0) return false;
    std::vector<std::uint8_t> boneHead(bytes.begin() + boneHeadOffset,
                                       bytes.begin() + boneHeadOffset +
                                           boneRecordSize);
    const int bone15Index = static_cast<int>(model.layout.boneCount);
    const int bone30Index = bone15Index + 1;
    const auto makeBoneKey = [&](int index, int frame, int previous,
                                 int next, float x) {
        auto key = boneHead;
        Put32(key, 0, frame);
        Put32(key, 4, previous);
        Put32(key, 8, next);
        PutFloat(key, 28, x);
        key[56] = 1;
        std::vector<std::uint8_t> record(4 + key.size());
        Put32(record, 0, index);
        std::copy(key.begin(), key.end(), record.begin() + 4);
        return record;
    };
    const auto bone15 = makeBoneKey(bone15Index, 15, 0,
                                    bone30Index, 15.0f);
    const auto bone30 = makeBoneKey(bone30Index, 30,
                                    bone15Index, 0, 30.0f);
    Put32(bytes, boneHeadOffset + 8, bone15Index);
    PutFloat(bytes, boneHeadOffset + 28, 0.0f);
    Put32(bytes, boneCountOffset, 2);
    bytes.insert(bytes.begin() + boneCountOffset + 4,
                 bone15.begin(), bone15.end());
    bytes.insert(bytes.begin() + boneCountOffset + 4 + bone15.size(),
                 bone30.begin(), bone30.end());
    const std::size_t boneInsertion = bone15.size() + bone30.size();
    const std::size_t recordSize = 14 + model.layout.ikCount +
                                   8 * model.rigidCount;
    const std::size_t headOffset =
        model.displayKeys.denseRecordOffsets[0] + boneInsertion;
    const std::size_t countOffset = headOffset + recordSize;
    if (countOffset + 4 > bytes.size()) return false;
    std::int32_t sparseCount = -1;
    std::memcpy(&sparseCount, bytes.data() + countOffset, 4);
    if (sparseCount != 0) return false;
    std::vector<std::uint8_t> head(bytes.begin() + headOffset,
                                   bytes.begin() + countOffset);
    const auto makeKey = [&](int index, int frame, int previous, int next,
                             int linkedModel) {
        auto key = head;
        Put32(key, 0, frame);
        Put32(key, 4, previous);
        Put32(key, 8, next);
        Put32(key, 13 + model.layout.ikCount, linkedModel);
        Put32(key, 17 + model.layout.ikCount, 0);
        Put32(key, 21 + model.layout.ikCount, linkedModel);
        Put32(key, 25 + model.layout.ikCount, 0);
        key.back() = 1;
        std::vector<std::uint8_t> record(4 + key.size());
        Put32(record, 0, index);
        std::copy(key.begin(), key.end(), record.begin() + 4);
        return record;
    };
    const auto key10 = makeKey(1, 10, 0, 2, -2);
    const auto key20 = makeKey(2, 20, 1, 0, -1);
    Put32(bytes, headOffset + 8, 1);
    Put32(bytes, countOffset, 2);
    bytes.insert(bytes.begin() + countOffset + 4,
                 key10.begin(), key10.end());
    bytes.insert(bytes.begin() + countOffset + 4 + key10.size(),
                 key20.begin(), key20.end());
    Input edited{bytes};
    mikudancestudio::format::PmmSceneDocument checked;
    if (!mikudancestudio::format::ReadPmmSceneDocument(
            Read, &edited, nullptr, nullptr, checked)) return false;
    for (const auto [frame, linkedModel, start, end, x] :
         {std::tuple{0u, -1, 0u, 10u, 0.0f},
          std::tuple{5u, -1, 0u, 10u, 0.0f},
          std::tuple{12u, -2, 10u, 20u, 15.0f},
          std::tuple{17u, -2, 10u, 20u, 15.0f},
          std::tuple{25u, -1, 20u, 0u, 30.0f}}) {
        mikudancestudio::format::PmmSceneEvaluation evaluated;
        if (!mikudancestudio::format::EvaluatePmmSceneFrame(
                checked, frame, evaluated) || evaluated.models.size() != 1 ||
            evaluated.models[0].selectors.empty()) return false;
        const auto& selector = evaluated.models[0].selectors[0];
        if (selector.linkedModel != linkedModel ||
            selector.windowStart != start || selector.windowEnd != end ||
            evaluated.models[0].bones[0].translation[0] != x)
            return false;
    }
    if (checked.selfShadowKeys.dense.size() != 1 ||
        !checked.selfShadowKeys.sparse.empty()) return false;
    constexpr std::size_t shadowRecordSize = 18;
    const auto shadowHeadOffset =
        checked.selfShadowKeys.denseRecordOffsets[0];
    const auto shadowCountOffset = shadowHeadOffset + shadowRecordSize;
    if (shadowCountOffset + 4 > bytes.size()) return false;
    auto shadowHead = std::vector<std::uint8_t>(
        bytes.begin() + shadowHeadOffset,
        bytes.begin() + shadowCountOffset);
    const auto makeShadowKey = [&](int index, int frame, int previous,
                                   int next, std::uint8_t mode,
                                   float distance) {
        auto key = shadowHead;
        Put32(key, 0, frame);
        Put32(key, 4, previous);
        Put32(key, 8, next);
        key[12] = mode;
        PutFloat(key, 13, distance);
        std::vector<std::uint8_t> record(4 + key.size());
        Put32(record, 0, index);
        std::copy(key.begin(), key.end(), record.begin() + 4);
        return record;
    };
    const auto shadow10 = makeShadowKey(1, 10, 0, 2, 2, 0.02f);
    const auto shadow20 = makeShadowKey(2, 20, 1, 0, 1, 0.03f);
    Put32(bytes, shadowHeadOffset + 8, 1);
    Put32(bytes, shadowCountOffset, 2);
    bytes.insert(bytes.begin() + shadowCountOffset + 4,
                 shadow10.begin(), shadow10.end());
    bytes.insert(bytes.begin() + shadowCountOffset + 4 + shadow10.size(),
                 shadow20.begin(), shadow20.end());
    Input shadowInput{bytes};
    mikudancestudio::format::PmmSceneDocument shadowScene;
    if (!mikudancestudio::format::ReadPmmSceneDocument(
            Read, &shadowInput, nullptr, nullptr, shadowScene) ||
        shadowScene.selfShadowKeys.sparse.size() != 2) return false;
    for (const auto [frame, mode, distance] :
         {std::tuple{5u, 1u, 0.01125f},
          std::tuple{10u, 2u, 0.02f},
          std::tuple{15u, 2u, 0.02f},
          std::tuple{20u, 1u, 0.03f}}) {
        mikudancestudio::format::PmmSceneEvaluation pose;
        if (!mikudancestudio::format::EvaluatePmmSceneFrame(
                shadowScene, frame, pose) ||
            pose.selfShadowMode != mode ||
            pose.selfShadowDistance != distance) return false;
    }
    if (shadowScene.gravityKeys.dense.size() != 1 ||
        !shadowScene.gravityKeys.sparse.empty()) return false;
    constexpr std::size_t gravityRecordSize = 34;
    const auto gravityHeadOffset = shadowScene.gravityKeys.denseRecordOffsets[0];
    const auto gravityCountOffset = gravityHeadOffset + gravityRecordSize;
    if (gravityCountOffset + 4 > bytes.size()) return false;
    auto gravityHead = std::vector<std::uint8_t>(
        bytes.begin() + gravityHeadOffset, bytes.begin() + gravityCountOffset);
    const auto makeGravityKey = [&](int index, int frame, int previous,
                                    int next, std::uint8_t noiseEnabled,
                                    int noise, float acceleration,
                                    float directionX, float directionY,
                                    float directionZ) {
        auto key = gravityHead;
        Put32(key, 0, frame);
        Put32(key, 4, previous);
        Put32(key, 8, next);
        key[12] = noiseEnabled;
        Put32(key, 13, noise);
        PutFloat(key, 17, acceleration);
        PutFloat(key, 21, directionX);
        PutFloat(key, 25, directionY);
        PutFloat(key, 29, directionZ);
        std::vector<std::uint8_t> record(4 + key.size());
        Put32(record, 0, index);
        std::copy(key.begin(), key.end(), record.begin() + 4);
        return record;
    };
    const auto gravity10 = makeGravityKey(1, 10, 0, 2, 1, 10, 12.0f,
                                          1.0f, 0.0f, 0.0f);
    const auto gravity20 = makeGravityKey(2, 20, 1, 0, 0, 4, 6.0f,
                                          0.0f, -1.0f, 1.0f);
    const auto gravity0 = makeGravityKey(0, 0, 0, 1, 0, 2, 4.0f,
                                         0.0f, -1.0f, 0.0f);
    std::copy(gravity0.begin() + 4, gravity0.end(),
              bytes.begin() + gravityHeadOffset);
    Put32(bytes, gravityCountOffset, 2);
    bytes.insert(bytes.begin() + gravityCountOffset + 4,
                 gravity10.begin(), gravity10.end());
    bytes.insert(bytes.begin() + gravityCountOffset + 4 + gravity10.size(),
                 gravity20.begin(), gravity20.end());
    Input gravityInput{bytes};
    mikudancestudio::format::PmmSceneDocument gravityScene;
    if (!mikudancestudio::format::ReadPmmSceneDocument(
            Read, &gravityInput, nullptr, nullptr, gravityScene) ||
        gravityScene.gravityKeys.sparse.size() != 2) return false;
    for (const auto [frame, noise, acceleration] :
         {std::tuple{5u, 6, 8.0f}, std::tuple{10u, 10, 12.0f},
          std::tuple{15u, 7, 9.0f}, std::tuple{20u, 4, 6.0f}}) {
        mikudancestudio::format::PmmSceneEvaluation pose;
        if (!mikudancestudio::format::EvaluatePmmSceneFrame(
                gravityScene, frame, pose) || pose.gravity.noise != noise ||
                pose.gravity.acceleration != acceleration) return false;
    }
    if (_wgetenv(L"MDS_PMM_WORLD_REPORT")) {
        if (gravityScene.cameraKeys.dense.empty()) return false;
        const auto cameraOffset = gravityScene.cameraKeys.denseRecordOffsets[0];
        Put32(bytes, cameraOffset + 40, model.slot);
        Put32(bytes, cameraOffset + 44, 0);
    }
    std::ofstream written(output, std::ios::binary);
    written.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    return written.good();
}
bool BuildMultiFixture(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) return false;
    std::vector<std::uint8_t> bytes(std::istreambuf_iterator<char>{stream}, {});
    Input input{bytes};
    mikudancestudio::format::PmmSceneDocument scene;
    if (!mikudancestudio::format::ReadPmmSceneDocument(
            Read, &input, nullptr, nullptr, scene) ||
        scene.models.size() != 1 || scene.models[0].slot >= 254 ||
        scene.sections.size() < 3 || scene.sections[1].kind !=
            mikudancestudio::format::PmmSceneSectionKind::Model ||
        scene.modelRegistrations.size() != 1) return false;
    const auto section = scene.sections[1];
    const auto slot = static_cast<std::uint8_t>(scene.models[0].slot + 1);
    std::vector<std::uint8_t> copy(bytes.begin() + section.offset,
                                   bytes.begin() + section.offset + section.size);
    copy[0] = slot;
    bytes[54] = 2;
    bytes.insert(bytes.begin() + section.offset + section.size,
                 copy.begin(), copy.end());
    bytes.push_back(slot);
    const auto selection = scene.modelRegistrations[0].selection;
    for (int shift = 0; shift < 32; shift += 8)
        bytes.push_back(static_cast<std::uint8_t>(selection >> shift));
    Input checkedInput{bytes};
    mikudancestudio::format::PmmSceneDocument checked;
    if (!mikudancestudio::format::ReadPmmSceneDocument(
            Read, &checkedInput, nullptr, nullptr, checked) ||
        checked.models.size() != 2 || checked.models[1].slot != slot)
        return false;
    std::ofstream written(path, std::ios::binary | std::ios::trunc);
    written.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    return written.good();
}
bool CheckSavedScene(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) return false;
    std::vector<std::uint8_t> bytes(std::istreambuf_iterator<char>{stream}, {});
    Input input{bytes};
    mikudancestudio::format::PmmSceneDocument scene;
    if (!mikudancestudio::format::ReadPmmSceneDocument(
            Read, &input, nullptr, nullptr, scene) || scene.models.size() != 1 ||
        scene.models[0].displayKeys.sparse.size() != 2 ||
        scene.models[0].boneKeys.sparse.size() != 2 ||
        scene.selfShadowKeys.sparse.size() != 2 ||
        scene.selfShadowKeys.dense[0].mode != 2 ||
        std::fabs(scene.selfShadowKeys.dense[0].distance - 0.01225f) >
            0.000001f ||
        scene.gravityKeys.sparse.size() != 2 ||
        scene.gravityKeys.dense[0].noise != 3 ||
        scene.gravityKeys.dense[0].noiseEnabled != 1 ||
        scene.gravityKeys.dense[0].acceleration != 4.25f ||
        scene.gravityKeys.dense[0].direction[0] != 0.125f) return false;
    for (const auto [frame, linkedModel, start, end, x] :
         {std::tuple{0u, -1, 0u, 10u, 0.0f},
          std::tuple{12u, -2, 10u, 20u, 15.0f},
          std::tuple{17u, -2, 10u, 20u, 15.0f},
          std::tuple{25u, -1, 20u, 0u, 30.0f}}) {
        mikudancestudio::format::PmmSceneEvaluation evaluated;
        if (!mikudancestudio::format::EvaluatePmmSceneFrame(
                scene, frame, evaluated) || evaluated.models.size() != 1 ||
            evaluated.models[0].selectors.empty()) return false;
        const auto& selector = evaluated.models[0].selectors[0];
        if (selector.linkedModel != linkedModel ||
            selector.windowStart != start || selector.windowEnd != end ||
            evaluated.models[0].bones[0].translation[0] != x)
            return false;
    }
    return true;
}
bool CheckSavedMultiScene(const fs::path& path, const fs::path& fixture) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) return false;
    std::vector<std::uint8_t> bytes(std::istreambuf_iterator<char>{stream}, {});
    Input input{bytes};
    mikudancestudio::format::PmmSceneDocument scene;
    if (!mikudancestudio::format::ReadPmmSceneDocument(
            Read, &input, nullptr, nullptr, scene) || scene.models.size() != 2)
        return false;
    std::ifstream originalStream(fixture, std::ios::binary);
    if (!originalStream) return false;
    std::vector<std::uint8_t> originalBytes(
        std::istreambuf_iterator<char>{originalStream}, {});
    Input originalInput{originalBytes};
    mikudancestudio::format::PmmSceneDocument original;
    if (!mikudancestudio::format::ReadPmmSceneDocument(
            Read, &originalInput, nullptr, nullptr, original) ||
        original.models.size() != 2 ||
        scene.selfShadowKeys.sparse.size() != 2 ||
        scene.models[0].boneKeys.dense.size() !=
            original.models[0].boneKeys.dense.size() ||
        scene.models[1].boneKeys.dense.size() !=
            original.models[1].boneKeys.dense.size()) return false;
    bool edited = false;
    for (std::size_t i = 0; i < scene.models[0].boneKeys.dense.size(); ++i)
        if (scene.models[0].boneKeys.dense[i].position[0] !=
            original.models[0].boneKeys.dense[i].position[0]) return false;
    for (std::size_t i = 0; i < scene.models[1].boneKeys.dense.size(); ++i) {
        const float delta = scene.models[1].boneKeys.dense[i].position[0] -
            original.models[1].boneKeys.dense[i].position[0];
        if (delta == 4.0f) edited = true;
        else if (delta != 0.0f) return false;
    }
    return edited;
}
struct Windows { DWORD processId; HWND main = nullptr, dialog = nullptr; };
BOOL CALLBACK FindWindow(HWND window, LPARAM context) {
    auto& found = *reinterpret_cast<Windows*>(context);
    DWORD owner = 0;
    GetWindowThreadProcessId(window, &owner);
    if (owner != found.processId || !IsWindowVisible(window)) return TRUE;
    wchar_t name[64]{};
    GetClassNameW(window, name, 64);
    if (wcscmp(name, L"Polygon Movie Maker") == 0) found.main = window;
    if (wcscmp(name, L"#32770") == 0) found.dialog = window;
    return TRUE;
}
BOOL CALLBACK PrintDialogChild(HWND window, LPARAM) {
    wchar_t name[64]{}, label[512]{};
    GetClassNameW(window, name, 64);
    GetWindowTextW(window, label, 512);
    if (*label) std::fprintf(stderr, "dialog child id=%d class=%ls text=%ls\n",
                             GetDlgCtrlID(window), name, label);
    return TRUE;
}
BOOL CALLBACK FindFileNameEdit(HWND window, LPARAM context) {
    const int id = GetDlgCtrlID(window);
    if (id != 1148 && id != 1001) return TRUE;
    wchar_t name[32]{};
    GetClassNameW(window, name, 32);
    if (wcscmp(name, L"Edit") == 0)
        *reinterpret_cast<HWND*>(context) = window;
    return TRUE;
}
HWND FileNameEdit(HWND dialog) {
    HWND edit = nullptr;
    EnumChildWindows(dialog, FindFileNameEdit,
                     reinterpret_cast<LPARAM>(&edit));
    return edit;
}
bool SetFileName(IUIAutomation* automation, HWND dialog,
                 const std::wstring& path) {
    const HWND editWindow = FileNameEdit(dialog);
    if (!editWindow) return false;
    ComPtr<IUIAutomationElement> edit;
    if (FAILED(automation->ElementFromHandle(editWindow, &edit))) return false;
    ComPtr<IUIAutomationValuePattern> value;
    if (FAILED(edit->GetCurrentPatternAs(UIA_ValuePatternId,
                                         IID_PPV_ARGS(&value)))) return false;
    BSTR filename = SysAllocString(path.c_str());
    const HRESULT changed = value->SetValue(filename);
    SysFreeString(filename);
    return SUCCEEDED(changed);
}
int Run(const fs::path& app, const fs::path& source) {
    if (!fs::is_regular_file(app) || !fs::is_regular_file(source)) return 77;
    const bool multi = _wgetenv(L"MDS_PMM_V2_MULTI_GUI") != nullptr;
    const bool materials = _wgetenv(L"MDS_RHI_MATERIAL_SNAPSHOT") != nullptr;
    const fs::path root = fs::temp_directory_path() /
        (L"mds-v2-selector-" + std::to_wstring(GetCurrentProcessId()) + L"-" +
         std::to_wstring(GetTickCount64()));
    fs::create_directories(root);
    if (materials) {
        SetEnvironmentVariableW(L"MDS_RHI_MODEL_AB", L"1");
        SetEnvironmentVariableW(L"MDS_RHI_LIVE_COMPARE_DIR", root.c_str());
    }
    const fs::path fixture = root / L"selector_change.pmm";
    const fs::path report = root / L"selector_report.txt";
    const fs::path saved = root / L"selector_saved.pmm";
    if (!BuildFixture(source, fixture) ||
        (multi && !BuildMultiFixture(fixture))) {
        std::fprintf(stderr, "could not build v2 selector fixture: %ls\n",
                     root.c_str());
        return 1;
    }
    SetEnvironmentVariableW(L"MDS_PMM_V2_SELECTOR_FIXTURE", fixture.c_str());
    SetEnvironmentVariableW(L"MDS_PMM_V2_SELECTOR_REPORT", report.c_str());
    if (multi) SetEnvironmentVariableW(L"MDS_PMM_V2_MULTI_FIXTURE", L"1");
    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) return 2;
    ComPtr<IUIAutomation> automation;
    if (FAILED(CoCreateInstance(CLSID_CUIAutomation, nullptr,
                                CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&automation)))) return 2;
    std::wstring command = L"\"" + app.wstring() + L"\" \"" +
                           fixture.wstring() + L"\"";
    std::vector<wchar_t> commandBuffer(command.begin(), command.end());
    commandBuffer.push_back(0);
    STARTUPINFOW startup{};
    startup.cb = sizeof startup;
    PROCESS_INFORMATION process{};
    const auto workdir = app.parent_path().wstring();
    if (!CreateProcessW(app.c_str(), commandBuffer.data(), nullptr, nullptr,
                        FALSE, 0, nullptr, workdir.c_str(), &startup, &process))
        return 2;
    int status = 3;
    const auto deadline = Clock::now() + std::chrono::seconds(90);
    while (Clock::now() < deadline) {
        Windows windows{process.dwProcessId};
        EnumWindows(FindWindow, reinterpret_cast<LPARAM>(&windows));
        if (fs::exists(report)) {
            // Startup diagnostics can finish before the main window becomes
            // visible. Wait for that window rather than failing valid parity.
            if (!windows.main && WaitForSingleObject(process.hProcess, 0) == WAIT_TIMEOUT) {
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
                continue;
            }
            std::ifstream stream(report);
            const std::string text(std::istreambuf_iterator<char>{stream}, {});
            if (text.find("checks=") == std::string::npos) {
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
                continue;
            }
            std::printf("v2 selector runtime parity:\n%s", text.c_str());
            const wchar_t* worldReport = _wgetenv(L"MDS_PMM_WORLD_REPORT");
            if (worldReport && *worldReport) {
                std::ifstream worldStream(worldReport);
                const std::string world(std::istreambuf_iterator<char>{worldStream}, {});
                if (world.find("WORLD SUMMARY") == std::string::npos ||
                    world.find("mismatches=0") == std::string::npos ||
                    world.find("camera=1") == std::string::npos ||
                    world.find(multi ? "supported=16" : "supported=8") ==
                        std::string::npos ||
                    world.find("WORLD MISMATCH") != std::string::npos) {
                    std::fprintf(stderr, "world parity report failed:\n%s\n",
                                 world.c_str());
                    status = 8;
                    break;
                }
            }
            status = multi ?
                (windows.main && text.find("PASS checks=") != std::string::npos &&
                 text.find("FAIL") == std::string::npos &&
                 text.find("MULTI edit second.bone=") != std::string::npos &&
                 text.find("MULTI playback models=2") != std::string::npos ? 0 : 4) :
                (windows.main && text.find("PASS checks=") != std::string::npos &&
                     text.find("FAIL") == std::string::npos &&
                     text.find("FRAME 12 expected=(-2,0,10,20) bone0.x=15") != std::string::npos &&
                     text.find("FRAME 17 expected=(-2,0,10,20) bone0.x=15") != std::string::npos &&
                     text.find("FRAME 25 expected=(-1,0,20,0) bone0.x=30") != std::string::npos &&
                     text.find("SEQUENCE frame=5.5") != std::string::npos &&
                     text.find("SEQUENCE frame=35") != std::string::npos &&
                     text.find("BRIDGE edit frame=15 bone0.x=19") != std::string::npos &&
                     text.find("BRIDGE insert frame=7 bone0.x=7") != std::string::npos &&
                     text.find("BRIDGE shadow edit frame=0") != std::string::npos &&
                     text.find("BRIDGE gravity edit frame=0") != std::string::npos &&
                     text.find("BRIDGE gravity dialog frame=5") != std::string::npos &&
                     text.find("BRIDGE gravity playback frame=25") != std::string::npos &&
                     text.find("FRAME 10 expected=(-2,0,10,20)") != std::string::npos &&
                     text.find("FRAME 20 expected=(-1,0,20,0)") != std::string::npos ? 0 : 4);
            if (status == 0) {
                if (materials) {
                    HWND radio = GetDlgItem(windows.main, 491);
                    if (!radio) { status = 10; break; }
                    SendMessageW(radio, BM_SETCHECK, BST_CHECKED, 0);
                    SendMessageW(windows.main, WM_COMMAND, MAKEWPARAM(491, BN_CLICKED),
                        reinterpret_cast<LPARAM>(radio));
                    const auto captureDeadline = Clock::now() + std::chrono::seconds(20);
                    std::string states;
                    while (Clock::now() < captureDeadline) {
                        std::ifstream input(root / L"model_material.snapshot");
                        states.assign(std::istreambuf_iterator<char>{input}, {});
                        if (states.find("SUMMARY") != std::string::npos) break;
                        std::this_thread::sleep_for(std::chrono::milliseconds(100));
                    }
                    std::printf("v2 material snapshot:\n%s\n", states.c_str());
                    if (const auto* evidence = _wgetenv(L"MDS_RHI_EVIDENCE_DIR")) {
                        fs::create_directories(evidence);
                        if (fs::exists(root / L"model_material.snapshot"))
                            fs::copy_file(root / L"model_material.snapshot",
                                fs::path(evidence) / L"model_material.snapshot",
                                fs::copy_options::overwrite_existing);
                    }
                    if (states.find("SUMMARY status=PASS") == std::string::npos ||
                        states.find("mismatches=0") == std::string::npos) {
                        status = 10;
                        break;
                    }
                }
                PostMessageW(windows.main, WM_COMMAND, 0xD0, 0);
                HWND dialog = nullptr;
                const auto dialogDeadline = Clock::now() + std::chrono::seconds(20);
                while (Clock::now() < dialogDeadline) {
                    Windows snapshot{process.dwProcessId};
                    EnumWindows(FindWindow, reinterpret_cast<LPARAM>(&snapshot));
                    if (snapshot.dialog && FileNameEdit(snapshot.dialog)) {
                        dialog = snapshot.dialog;
                        break;
                    }
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                }
                if (!dialog || !SetFileName(automation.Get(), dialog,
                                            saved.wstring())) status = 6;
                else {
                    HWND button = GetDlgItem(dialog, IDOK);
                    if (!button) status = 6;
                    else {
                        PostMessageW(button, BM_CLICK, 0, 0);
                        const auto saveDeadline = Clock::now() +
                            std::chrono::seconds(40);
                        while (Clock::now() < saveDeadline) {
                            if (fs::exists(saved) &&
                                (multi ? CheckSavedMultiScene(saved, fixture) :
                                         CheckSavedScene(saved))) break;
                            Windows snapshot{process.dwProcessId};
                            EnumWindows(FindWindow,
                                        reinterpret_cast<LPARAM>(&snapshot));
                            if (snapshot.dialog &&
                                !FileNameEdit(snapshot.dialog)) break;
                            std::this_thread::sleep_for(std::chrono::milliseconds(200));
                        }
                        if (!fs::exists(saved) ||
                            !(multi ? CheckSavedMultiScene(saved, fixture) :
                                       CheckSavedScene(saved))) {
                            Windows snapshot{process.dwProcessId};
                            EnumWindows(FindWindow,
                                        reinterpret_cast<LPARAM>(&snapshot));
                            if (snapshot.dialog)
                                EnumChildWindows(snapshot.dialog,
                                                 PrintDialogChild, 0);
                            std::fprintf(stderr, "saved exists=%d\n",
                                         fs::exists(saved) ? 1 : 0);
                            status = 7;
                        }
                        else std::puts(multi ? "v2 multi-model Save As readback passed" :
                                               "v2 selector Save As readback passed");
                    }
                }
            }
            if (windows.main) PostMessageW(windows.main, WM_CLOSE, 0, 0);
            break;
        }
        if (windows.dialog || WaitForSingleObject(process.hProcess, 0) != WAIT_TIMEOUT) {
            DWORD exitCode = STILL_ACTIVE;
            GetExitCodeProcess(process.hProcess, &exitCode);
            std::fprintf(stderr, "v2 application dialog or exit before parity report; exit=0x%08lx\n",
                         exitCode);
            if (windows.dialog) EnumChildWindows(windows.dialog,
                                                 PrintDialogChild, 0);
            status = 5;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    if (WaitForSingleObject(process.hProcess, 3000) == WAIT_TIMEOUT) {
        TerminateProcess(process.hProcess, 1);
        WaitForSingleObject(process.hProcess, 3000);
    }
    CloseHandle(process.hProcess);
    CloseHandle(process.hThread);
    if (status == 0) {
        std::error_code error;
        fs::remove_all(root, error);
        if (error) std::fprintf(stderr, "temporary cleanup failed: %s\n",
                                error.message().c_str());
    } else {
        std::fprintf(stderr, "failed fixture retained: %ls\n", root.c_str());
    }
    return status;
}
}

int wmain(int argc, wchar_t** argv) {
    const wchar_t* fixture = _wgetenv(L"MDS_PMM_V2_GUI_FIXTURE");
    if (argc != 2 || !fixture || !*fixture) return 77;
    try { return Run(argv[1], fixture); }
    catch (const fs::filesystem_error& error) {
        std::fprintf(stderr, "fixture operation failed: %s\n", error.what());
        return 6;
    }
}
