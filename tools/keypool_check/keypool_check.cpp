// Bounded exhaustive check of the model keyframe pools.
//
// Property: after any sequence of the keyframe commands below, every key
// track is a well-formed chain: each track starts at its own head record
// (bone i / morph i at index i, display at index 0), heads stay at frame 0,
// next/previous agree, frames strictly increase, chains end, no record is
// shared by two tracks or is a head of another track, and every non-head
// record with frame != 0 is on a track. AddressSanitizer reports any pool
// access out of bounds.
//
// The functions under test are the real ones from src/model/key_registrars.cpp
// and src/model/model_keyframe_edit.cpp, linked unmodified. Each command
// replays the call order of the real UI handler named in its comment.
// The explorer does a breadth-first search over all command sequences up to
// kDepth, deduplicating states, so every reported trace is a shortest one.
// It runs once per UI configuration in kConfigs (the checkboxes and the
// physics mode the bone registrars read).
//
// Usage: keypool_check [depth] [--dump FILE]
// --dump also writes the explored sequences and the pool states they reach
// as text (format at WriteDump below); the report on stdout is unchanged.
#include <Windows.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "mikudancestudio/model.hpp"
#include "mikudancestudio/panel_controls.hpp"

namespace mikudancestudio {
void ModelInitDefaults(unsigned char* m);
void ResetBoneKeyCursor(unsigned char* model);
int ResetMorphKeyCursor(unsigned char* model);
void ResetDisplayKeyCursor(unsigned char* model);
bool RegisterBoneKey(unsigned char* model, unsigned char* rec, int frameOffset,
                     unsigned char useSelected);
bool RegisterMirroredBoneKey(unsigned char* model, unsigned char* rec, int frameOffset);
bool RegisterMorphKeyFromRecord(unsigned char* model, const unsigned char* rec,
                                int frameOffset);
void RegisterMorphKeyCurrent(unsigned char* model, int morph, int frame);
bool RegisterDisplayKeyFromRecord(unsigned char* model, int frameArg,
                                  unsigned char view, int cnt,
                                  const unsigned char* entries21, int cnt2,
                                  const unsigned char* entries28,
                                  int frameOffset);
void RegisterDisplayKeyCurrent(unsigned char* model, int frame);
void RegisterSelectedBoneKeys(unsigned char* model, int frame, int mode);
void DeleteMarkedModelKeys(unsigned char* model, int frame);
// Hands a rigid body to or from the physics engine; no key pool state.
void NotifyBonePhysicsMode(unsigned char*, int, unsigned char) {}
}  // namespace mikudancestudio

using namespace mikudancestudio;

extern "C" void __asan_set_error_report_callback(void (*)(const char*));

namespace {

constexpr int kBones = 2;
constexpr int kMorphs = 2;
constexpr int kFrames = 3;   // frames 0..2; 0 is the head frame
constexpr int kIkChains = 1;
constexpr int kSelectors = 2;
int kDepth = 4;              // commands per sequence; argv[1] overrides
constexpr int kWindow = 24;  // pool prefix the explorer tracks per pool

// The UI state the bone registrars read: the auto-interpolation checkbox
// (kPhysicsFrameCheckbox, RegisterBonePoseAtFrame and DeleteMarkedModelKeys),
// the physics checkbox (kPhysicsCheckbox) and PlaybackPhysicsMode, which
// case 500 passes as `mode`. A bone with a rigid body stores the physics pose
// in mode 1, and in modes 2 and 3 while its physicsDisabled is clear; the
// first register with the physics checkbox clear sets it. Mode 0 never
// stores the physics pose.
struct Config { bool autoInterpolation; bool physicsCheckbox; int mode; };
constexpr Config kConfigs[] = {{false, false, 2}, {true, true, 2}, {true, false, 1}, {false, true, 0}};
Config g_config = kConfigs[0];

// Shift-JIS 右 / 左: reverse paste maps "右b" and "左b" onto each other.
const char* const kBoneNames[] = {"\x89\x45" "b", "\x8D\xB6" "b"};

unsigned char* g_model = nullptr;
std::string g_asan;

void OnAsanReport(const char* report) {
    if (!g_asan.empty()) return;
    // Key by source location: one bad access can surface as overflow or
    // use-after-free depending on what the stray pointer lands on.
    const char* s = std::strstr(report, "SUMMARY: AddressSanitizer: ");
    if (s == nullptr) { g_asan = "AddressSanitizer report"; return; }
    s = std::strchr(s + 27, ' ');
    g_asan = "invalid memory access at" +
             std::string(s, std::strcspn(s, "(\n"));
}

mdl::ModelRecord& M() { return *mdl::Mdl(g_model); }

// add_model.cpp:57-63 then the pool tail of pmx_load.cpp:1672-1709.
//
// bone0 is a movable bone with a rigid body, bone1 the IK bone and a
// fixed-axis (twist) bone. The selectors are bone_sort.cpp's root entry
// (bone -1) and one for bone0.
//
// The loaders allocate exactly boneCount bone records, including no slot
// for the root selector's bone index -1.
void BuildModel() {
    g_model = static_cast<unsigned char*>(operator new(mdl::kSize));
    std::memset(g_model, 0, mdl::kSize);
    ModelInitDefaults(g_model);
    mdl::ModelRecord& m = M();
    m.physicsMode = 2;  // PMX
    m.boneCount = kBones;
    m.morphCount = kMorphs;
    m.boneTable = new mdl::BoneRecord[kBones]();
    for (int b = 0; b < kBones; ++b) {
        std::snprintf(m.boneTable[b].name, 20, "%s", kBoneNames[b]);
        m.boneTable[b].rotQuat[3] = 1.0f;
    }
    mdl::BoneRecord& rigid = m.boneTable[0];
    rigid.type = mdl::BoneType::Move;
    rigid.hasRigidBody = 1;
    mdl::BoneRecord& twist = m.boneTable[1];
    twist.type = mdl::BoneType::FixedAxis;
    twist.flags = mdl::kBoneFlagFixedAxis;
    twist.axis[0] = 0.48f;
    twist.axis[1] = 0.6f;
    twist.axis[2] = 0.64f;
    twist.trans[0] = 1.0f;
    twist.trans[1] = 0.25f;
    m.boneSelection = new unsigned char[kBones]();
    m.bonePhysicsState = new unsigned char[kBones]();
    m.morphs = new mdl::MorphRecord[kMorphs]();
    for (int i = 0; i < kMorphs; ++i)
        std::snprintf(m.morphs[i].name, 20, "morph%d", i);
    m.ikChainCount = 1;
    m.ikChains = new mdl::IkChain[1]();
    m.ikChains[0].boneIndex = 1;
    m.ikChains[0].enabled = 1;
    m.boneOrderCount = kSelectors;
    mdl::BoneOrder(g_model) = new mdl::BoneOrderEntry[kSelectors]();
    mdl::BoneOrder(g_model)[0].boneIndex = -1;
    mdl::BoneOrder(g_model)[0].linkedModel = -1;
    mdl::BoneOrder(g_model)[1].boneIndex = 0;
    mdl::BoneOrder(g_model)[1].linkedModel = 2;
    mdl::BoneOrder(g_model)[1].linkedBone = 1;

    m.boneKeys = static_cast<mdl::BoneKey*>(
        operator new(sizeof(mdl::BoneKey) * mdl::kBoneKeyCapacity));
    std::memset(m.boneKeys, 0, sizeof(mdl::BoneKey) * mdl::kBoneKeyCapacity);
    m.morphKeys = static_cast<mdl::MorphKey*>(
        operator new(sizeof(mdl::MorphKey) * mdl::kMorphKeyCapacity));
    std::memset(m.morphKeys, 0, sizeof(mdl::MorphKey) * mdl::kMorphKeyCapacity);
    m.displayKeys = static_cast<mdl::DisplayKey*>(
        operator new(sizeof(mdl::DisplayKey) * mdl::kDisplayKeyCapacity));
    std::memset(m.displayKeys, 0,
                sizeof(mdl::DisplayKey) * mdl::kDisplayKeyCapacity);
    for (std::size_t i = 0; i < mdl::kDisplayKeyCapacity; ++i) {
        mdl::DisplayKey& k = m.displayKeys[i];
        mdl::IkStates(k) = new std::uint8_t[1]{1};
        k.visible = 1;
        mdl::SelectorStates(k) = new mdl::BoneReference[kSelectors]{{-1, 0}, {-1, 0}};
    }
    for (int b = 0; b < kBones; ++b) {
        mdl::BoneKey& k = m.boneKeys[b];
        for (int c = 0; c < 4; ++c) {
            k.interpolation[c] = k.interpolation[c + 4] = 20;
            k.interpolation[c + 8] = k.interpolation[c + 12] = 107;
        }
        k.rotation[3] = 1.0f;
    }
}

template <class Key>
void ClearMarks(Key* keys, std::size_t n) {
    for (std::size_t i = 0; i < n; ++i) keys[i].allocated = 0;
}
// ClearModelKeyMarks x3, frame_clipboard.cpp:521-523. Clearing only the
// tracked window is equivalent: CheckAll rejects any state whose cursor or
// links leave the window, so no record past it is ever written.
void ClearAllMarks() {
    ClearMarks(M().boneKeys, kWindow);
    ClearMarks(M().morphKeys, kWindow);
    ClearMarks(M().displayKeys, kWindow);
}

// Undo slot the bone registrars append to (frame_clipboard.cpp:524-590).
void OpenBoneUndo(int boneRecords) {
    mdl::ModelRecord& m = M();
    m.undoState[0] = m.undoState[0] + 1 >= 30 ? 0 : m.undoState[0] + 1;
    mdl::UndoRecord& u = m.undoRings[0].slots[m.undoState[0]];
    operator delete(u.auxiliaryPose);
    u.auxiliaryPose = operator new(boneRecords * 3 * 0x40);
    std::memset(u.auxiliaryPose, 0, boneRecords * 3 * 0x40);
    u.recordCount = 0;
    std::memset(m.keyVisitMap, 0, sizeof m.keyVisitMap);
}

enum Kind { kPasteBone, kPasteMorph, kPasteDisplay, kRegisterBone,
            kRegisterMorph, kRegisterDisplay, kSelectBone, kDelete,
            kPasteMirrored, kPasteToSelected };
struct Command { Kind kind; int target; int frame; };

std::string Describe(const Command& c) {
    char s[96];
    switch (c.kind) {
    case kPasteBone: std::snprintf(s, sizeof s, "paste bone%d key at frame %d", c.target, c.frame); break;
    case kPasteMorph: std::snprintf(s, sizeof s, "paste morph%d key at frame %d", c.target, c.frame); break;
    case kPasteDisplay: std::snprintf(s, sizeof s, "paste display key at frame %d", c.frame); break;
    case kRegisterBone: std::snprintf(s, sizeof s, "register button: bone%d at frame %d", c.target, c.frame); break;
    case kRegisterMorph: std::snprintf(s, sizeof s, "register morph%d at frame %d", c.target, c.frame); break;
    case kRegisterDisplay: std::snprintf(s, sizeof s, "register display key at frame %d", c.frame); break;
    case kSelectBone: std::snprintf(s, sizeof s, "click bone%d key at frame %d", c.target, c.frame); break;
    case kDelete: std::snprintf(s, sizeof s, "delete selected keys"); break;
    case kPasteMirrored: std::snprintf(s, sizeof s, "reverse paste bone%d key at frame %d", c.target, c.frame); break;
    case kPasteToSelected: std::snprintf(s, sizeof s, "paste a bone key to selected bone%d at frame %d", c.target, c.frame); break;
    }
    return s;
}

// One copied bone key (the 0x54-byte BoneClipboardRecord) named `name`. The
// payload depends on the frame so that overwrites change it, positions
// differ between keys (auto interpolation) and the twist dot product takes
// both signs.
void BoneClip(unsigned char (&rec)[0x54], const char* name, int frame) {
    std::memset(rec, 0, sizeof rec);
    std::snprintf(reinterpret_cast<char*>(rec), 20, "%s", name);
    const float even[4] = {0.1f, 0.2f, 0.3f, 0.9273618f};
    const float odd[4] = {-0.3f, 0.1f, -0.2f, 0.9273618f};
    std::memcpy(rec + 36, frame % 2 ? odd : even, 16);
    const float position[3] = {1.5f * static_cast<float>(frame), 0.5f, -0.25f};
    std::memcpy(rec + 52, position, 12);
    rec[64] = static_cast<unsigned char>(frame & 1);
    for (int j = 0; j < 16; ++j) rec[65 + j] = static_cast<unsigned char>(7 * j + frame);
}

// PasteSelectedKeyframes (frame_clipboard.cpp:506-769): clear marks, then
// ResetBone + bone loop, ResetMorph + morph loop, ResetDisplay + display
// loop. Each paste here carries one key; the resets run unconditionally.
// The display key is what CopySelectedKeyframes makes of a key of this model
// (frame_clipboard.cpp:298-335): the IK bone's flag, selector 0 under the
// root name, selector 1 under bone0's name, pairs that need no slot fixup.
void Paste(Kind kind, int target, int frame) {
    ClearAllMarks();
    if (kind == kPasteBone) OpenBoneUndo(1);
    std::memset(M().keyVisitMap, 0, sizeof M().keyVisitMap);
    ResetBoneKeyCursor(g_model);
    if (kind == kPasteBone) {
        unsigned char rec[0x54];
        BoneClip(rec, kBoneNames[target], frame);
        RegisterBoneKey(g_model, rec, frame, 0);
    }
    ResetMorphKeyCursor(g_model);
    if (kind == kPasteMorph) {
        unsigned char rec[0x28] = {};
        std::snprintf(reinterpret_cast<char*>(rec), 30, "morph%d", target);
        const float value = 0.25f * static_cast<float>(frame + 1);
        std::memcpy(rec + 36, &value, 4);
        RegisterMorphKeyFromRecord(g_model, rec, frame);
    }
    ResetDisplayKeyCursor(g_model);
    if (kind == kPasteDisplay) {
        unsigned char ik[21] = {};
        std::snprintf(reinterpret_cast<char*>(ik), 20, "%s", kBoneNames[1]);
        ik[20] = static_cast<unsigned char>(frame & 1);
        unsigned char sel[2][28] = {{0x83, 0x8B, 0x81, 0x5B, 0x83, 0x67}, {}};  // ルート
        std::snprintf(reinterpret_cast<char*>(sel[1]), 20, "%s", kBoneNames[0]);
        for (auto& e : sel) {
            const std::int32_t pair[2] = {-2, frame};  // ground: no fixup
            std::memcpy(e + 20, pair, 8);
        }
        RegisterDisplayKeyFromRecord(g_model, 0, frame == 1 ? 0 : 1, 1, ik, kSelectors, sel[0], frame);
    }
}

// PasteMirroredBoneKeyframes (command 422, frame_clipboard.cpp:782-862) and
// the bone branch of MDS_CMD_PASTE_AT_DIFFERENT_FRAME
// (command_file_menu.cpp:1494-1593): clear marks, an undo slot, ResetBone,
// then the bone loop only. The selected-bone paste ignores the clip's name.
void PasteBonesOnly(Kind kind, int target, int frame) {
    ClearAllMarks();
    OpenBoneUndo(1);
    ResetBoneKeyCursor(g_model);
    unsigned char rec[0x54];
    if (kind == kPasteMirrored) {
        BoneClip(rec, kBoneNames[target], frame);
        RegisterMirroredBoneKey(g_model, rec, frame);
    } else {
        M().selectedBone = target;
        BoneClip(rec, kBoneNames[1 - target], frame);
        RegisterBoneKey(g_model, rec, frame, 1);
    }
}

void Apply(const Command& c) {
    switch (c.kind) {
    case kPasteBone: case kPasteMorph: case kPasteDisplay:
        Paste(c.kind, c.target, c.frame);
        break;
    case kPasteMirrored: case kPasteToSelected:
        PasteBonesOnly(c.kind, c.target, c.frame);
        break;
    case kRegisterBone: {  // HandleFrameRegisterControl case 500, command_frame_register.cpp:375
        // The pose the physics step left at this frame (ikBackup: position,
        // quaternion), which differs from the pose an earlier register
        // copied into bone0.
        const float physicsPose[7] = {0.5f + static_cast<float>(c.frame), 1.5f, -2.0f,
                                      0.0f, 0.6f, 0.0f, 0.8f};
        std::memcpy(M().boneTable[0].ikBackup, physicsPose, sizeof physicsPose);
        std::memset(M().boneSelection, 0, kBones);
        M().boneSelection[c.target] = 1;
        RegisterSelectedBoneKeys(g_model, c.frame, g_config.mode);
        break;
    }
    case kRegisterMorph:  // cases 524-527, command_frame_register.cpp:496-543
        ClearAllMarks();
        RegisterMorphKeyCurrent(g_model, c.target, c.frame);
        break;
    case kRegisterDisplay:  // case 438, command_frame_edit.cpp:1548-1561
        ClearAllMarks();
        RegisterDisplayKeyCurrent(g_model, c.frame);
        break;
    case kSelectBone: {  // a timeline click marks one key (harness stand-in)
        ClearAllMarks();
        for (int i = c.target, steps = 0; steps < kWindow; ++steps) {
            if (M().boneKeys[i].frame == static_cast<std::uint32_t>(c.frame)) {
                M().boneKeys[i].allocated = 1;
                break;
            }
            i = static_cast<int>(M().boneKeys[i].next);
            if (i == 0) break;
        }
        break;
    }
    case kDelete:
        DeleteMarkedModelKeys(g_model, 0);
        break;
    }
}

std::vector<Command> Alphabet() {
    std::vector<Command> out;
    for (int f = 0; f < kFrames; ++f) {
        for (int t = 0; t < kBones; ++t) {
            out.push_back({kPasteBone, t, f});
            out.push_back({kRegisterBone, t, f});
            out.push_back({kSelectBone, t, f});
            out.push_back({kPasteMirrored, t, f});
            out.push_back({kPasteToSelected, t, f});
        }
        for (int t = 0; t < kMorphs; ++t) {
            out.push_back({kPasteMorph, t, f});
            out.push_back({kRegisterMorph, t, f});
        }
        out.push_back({kPasteDisplay, 0, f});
        out.push_back({kRegisterDisplay, 0, f});
    }
    out.push_back({kDelete, 0, 0});
    return out;
}

// ---- state snapshot: link fields of the tracked prefix + shared cursor ----
struct Slot { std::uint32_t frame, previous, next; std::uint8_t mark; };
std::string Snapshot() {
    std::string s;
    auto put = [&](const auto& k) {
        Slot slot{k.frame, k.previous, k.next, k.allocated};
        s.append(reinterpret_cast<const char*>(&slot), sizeof slot);
    };
    for (int i = 0; i < kWindow; ++i) put(M().boneKeys[i]);
    for (int i = 0; i < kWindow; ++i) put(M().morphKeys[i]);
    for (int i = 0; i < kWindow; ++i) put(M().displayKeys[i]);
    s.append(reinterpret_cast<const char*>(&M().searchCursor), 4);
    return s;
}
void Restore(const std::string& s) {
    const Slot* slot = reinterpret_cast<const Slot*>(s.data());
    auto get = [&](auto& k) {
        k.frame = slot->frame; k.previous = slot->previous;
        k.next = slot->next; k.allocated = slot->mark; ++slot;
    };
    for (int i = 0; i < kWindow; ++i) get(M().boneKeys[i]);
    for (int i = 0; i < kWindow; ++i) get(M().morphKeys[i]);
    for (int i = 0; i < kWindow; ++i) get(M().displayKeys[i]);
    std::memcpy(&M().searchCursor, slot, 4);
}

// ---- state dump (--dump) ----------------------------------------------------
// A Window is every field of the tracked pool prefix plus the cursor and the
// timeline end, i.e. the part of the model the commands can change. In dump
// mode the explorer restores it whole, so a state's payload is the one its
// shortest trace produces from a freshly loaded model.
struct Window {
    mdl::BoneKey bone[kWindow];
    mdl::MorphKey morph[kWindow];
    struct Display {
        mdl::DisplayKey key;
        std::uint8_t ik[kIkChains];
        mdl::BoneReference selectors[kSelectors];
    } display[kWindow];
    // The bone fields the registrars change: the physics-pose path copies
    // ikBackup into the pose, the physics checkbox sets physicsDisabled.
    struct Bone {
        float trans[3], rotQuat[4];
        std::uint8_t physicsDisabled;
    } bones[kBones];
    std::int32_t cursor;
    std::uint32_t maxFrame;
};

void Capture(Window& w) {
    std::memcpy(w.bone, M().boneKeys, sizeof w.bone);
    std::memcpy(w.morph, M().morphKeys, sizeof w.morph);
    for (int i = 0; i < kWindow; ++i) {
        mdl::DisplayKey& k = M().displayKeys[i];
        w.display[i].key = k;
        std::memcpy(w.display[i].ik, mdl::IkStates(k), kIkChains);
        std::memcpy(w.display[i].selectors, mdl::SelectorStates(k), sizeof w.display[i].selectors);
    }
    for (int b = 0; b < kBones; ++b) {
        const mdl::BoneRecord& r = M().boneTable[b];
        std::memcpy(w.bones[b].trans, r.trans, sizeof r.trans);
        std::memcpy(w.bones[b].rotQuat, r.rotQuat, sizeof r.rotQuat);
        w.bones[b].physicsDisabled = r.physicsDisabled;
    }
    w.cursor = M().searchCursor;
    w.maxFrame = M().maxFrame;
}
void RestoreWindow(const Window& w) {
    std::memcpy(M().boneKeys, w.bone, sizeof w.bone);
    std::memcpy(M().morphKeys, w.morph, sizeof w.morph);
    for (int i = 0; i < kWindow; ++i) {
        mdl::DisplayKey& k = M().displayKeys[i];
        k = w.display[i].key;  // the array pointers are unchanged
        std::memcpy(mdl::IkStates(k), w.display[i].ik, kIkChains);
        std::memcpy(mdl::SelectorStates(k), w.display[i].selectors, sizeof w.display[i].selectors);
    }
    for (int b = 0; b < kBones; ++b) {
        mdl::BoneRecord& r = M().boneTable[b];
        std::memcpy(r.trans, w.bones[b].trans, sizeof r.trans);
        std::memcpy(r.rotQuat, w.bones[b].rotQuat, sizeof r.rotQuat);
        r.physicsDisabled = w.bones[b].physicsDisabled;
    }
    M().searchCursor = w.cursor;
    M().maxFrame = w.maxFrame;
}

std::string Hex(float f) {
    std::uint32_t u;
    std::memcpy(&u, &f, 4);
    char s[16];
    std::snprintf(s, sizeof s, "%x", u);
    return s;
}

// One text line per record, in a fixed order: b0..b23, m0..m23, d0..d23,
// r0..r1 (the bone records), g.
// Integers are decimal, floats are their bits in hex, a byte array is hex.
std::vector<std::string> StateLines(const Window& w) {
    std::vector<std::string> out;
    char s[256];
    for (int i = 0; i < kWindow; ++i) {
        const mdl::BoneKey& k = w.bone[i];
        int n = std::snprintf(s, sizeof s, "b%d f%u p%u n%u a%u d%u i", i, k.frame, k.previous,
                              k.next, k.allocated, k.physicsDisabled);
        for (int j = 0; j < 16; ++j) n += std::snprintf(s + n, sizeof s - n, "%02x", k.interpolation[j]);
        std::snprintf(s + n, sizeof s - n, " x%s.%s.%s q%s.%s.%s.%s", Hex(k.position[0]).c_str(),
                      Hex(k.position[1]).c_str(), Hex(k.position[2]).c_str(),
                      Hex(k.rotation[0]).c_str(), Hex(k.rotation[1]).c_str(),
                      Hex(k.rotation[2]).c_str(), Hex(k.rotation[3]).c_str());
        out.push_back(s);
    }
    for (int i = 0; i < kWindow; ++i) {
        const mdl::MorphKey& k = w.morph[i];
        std::snprintf(s, sizeof s, "m%d f%u p%u n%u a%u v%s", i, k.frame, k.previous, k.next,
                      k.allocated, Hex(k.value).c_str());
        out.push_back(s);
    }
    for (int i = 0; i < kWindow; ++i) {
        const Window::Display& d = w.display[i];
        int n = std::snprintf(s, sizeof s, "d%d f%u p%u n%u a%u v%u k", i, d.key.frame,
                              d.key.previous, d.key.next, d.key.allocated, d.key.visible);
        for (int j = 0; j < kIkChains; ++j) n += std::snprintf(s + n, sizeof s - n, "%s%u", j ? "." : "", d.ik[j]);
        n += std::snprintf(s + n, sizeof s - n, " s");
        for (int j = 0; j < kSelectors; ++j)
            n += std::snprintf(s + n, sizeof s - n, "%s%d:%d", j ? "." : "", d.selectors[j].modelIndex,
                               d.selectors[j].boneIndex);
        out.push_back(s);
    }
    for (int b = 0; b < kBones; ++b) {
        const Window::Bone& r = w.bones[b];
        std::snprintf(s, sizeof s, "r%d d%u x%s.%s.%s q%s.%s.%s.%s", b, r.physicsDisabled,
                      Hex(r.trans[0]).c_str(), Hex(r.trans[1]).c_str(), Hex(r.trans[2]).c_str(),
                      Hex(r.rotQuat[0]).c_str(), Hex(r.rotQuat[1]).c_str(),
                      Hex(r.rotQuat[2]).c_str(), Hex(r.rotQuat[3]).c_str());
        out.push_back(s);
    }
    std::snprintf(s, sizeof s, "g c%d x%u", w.cursor, w.maxFrame);
    out.push_back(s);
    return out;
}

const char* KindName(Kind k) {
    static const char* const names[] = {"paste-bone", "paste-morph", "paste-display",
                                        "register-bone", "register-morph", "register-display",
                                        "select-bone", "delete", "paste-mirrored",
                                        "paste-to-selected"};
    return names[k];
}

// What Explore records when --dump is set: the BFS tree and every transition.
struct DumpData {
    std::vector<Window> windows;       // by state id
    std::vector<int> parent, command;  // by state id; the root has -1, -1
    std::vector<std::vector<int>> next;  // by state id; successor id or -1 (cut), empty if not expanded
};
DumpData g_dump;

// Format (text, one record per line):
//   keypool-dump 2
//   depth D / bones B morphs M frames F window W
//   C <command> <kind> <target> <frame>          the command alphabet
// then one section per configuration:
//   config <auto interpolation> <physics checkbox> <mode>
//   S <id> <parent> <command>                    state <id> = <parent> after <command>
//    <record line>...                            the records that differ from the parent
//                                                (all of them for state 0)
//   T <id> <successor of command 0> ...          the successor state id of every command
//                                                ("-": cut at the window bound); only for
//                                                states shallower than the depth
// State ids are in breadth-first discovery order, so a state's shortest trace is its
// parent chain. A state's payload is what that trace gives from a freshly loaded model.
void WriteDumpHeader(std::FILE* f, const std::vector<Command>& alphabet) {
    std::fprintf(f, "keypool-dump 2\ndepth %d\nbones %d morphs %d frames %d window %d\n", kDepth,
                 kBones, kMorphs, kFrames, kWindow);
    for (std::size_t c = 0; c < alphabet.size(); ++c)
        std::fprintf(f, "C %zu %s %d %d\n", c, KindName(alphabet[c].kind), alphabet[c].target,
                     alphabet[c].frame);
}
void WriteDumpSection(std::FILE* f) {
    std::fprintf(f, "config %d %d %d\n", g_config.autoInterpolation, g_config.physicsCheckbox,
                 g_config.mode);
    std::vector<std::string> before;
    for (std::size_t id = 0; id < g_dump.windows.size(); ++id) {
        const std::vector<std::string> now = StateLines(g_dump.windows[id]);
        const int parent = g_dump.parent[id];
        if (parent < 0) {
            std::fprintf(f, "S %zu - -\n", id);
        } else {
            std::fprintf(f, "S %zu %d %d\n", id, parent, g_dump.command[id]);
            before = StateLines(g_dump.windows[parent]);
        }
        for (std::size_t i = 0; i < now.size(); ++i)
            if (parent < 0 || now[i] != before[i]) std::fprintf(f, " %s\n", now[i].c_str());
    }
    for (std::size_t id = 0; id < g_dump.next.size(); ++id) {
        if (g_dump.next[id].empty()) continue;
        std::fprintf(f, "T %zu", id);
        for (int to : g_dump.next[id]) {
            if (to < 0) std::fprintf(f, " -");
            else std::fprintf(f, " %d", to);
        }
        std::fprintf(f, "\n");
    }
}

// ---- the property ----------------------------------------------------------
template <class Key>
std::string CheckPool(const char* pool, Key* keys, int heads) {
    std::vector<int> owner(kWindow, -1);
    char e[160];
    for (int h = 0; h < heads; ++h) {
        if (keys[h].frame != 0) {
            std::snprintf(e, sizeof e, "%s track %d: head record moved off frame 0",
                          pool, h);
            return e;
        }
        owner[h] = h;
        int prev = h;
        std::uint32_t next = keys[h].next;
        for (int steps = 0; next != 0; ++steps) {
            if (next >= static_cast<std::uint32_t>(kWindow))
                return std::string(pool) + ": link left the tracked window (bound, not a finding)";
            const int i = static_cast<int>(next);
            if (i < heads) {
                std::snprintf(e, sizeof e, "%s track %d: links into the head record of track %d",
                              pool, h, i);
                return e;
            }
            if (owner[i] != -1) {
                std::snprintf(e, sizeof e, "%s track %d: record %d is already on track %d (shared or cyclic)",
                              pool, h, i, owner[i]);
                return e;
            }
            owner[i] = h;
            if (keys[i].previous != static_cast<std::uint32_t>(prev)) {
                std::snprintf(e, sizeof e, "%s track %d: previous link of record %d is wrong",
                              pool, h, i);
                return e;
            }
            if (keys[i].frame <= keys[prev].frame) {
                std::snprintf(e, sizeof e, "%s track %d: frames not increasing", pool, h);
                return e;
            }
            prev = i;
            next = keys[i].next;
        }
    }
    for (int i = heads; i < kWindow; ++i) {
        if (keys[i].frame != 0 && owner[i] == -1) {
            std::snprintf(e, sizeof e, "%s: occupied record is on no track (lost key)", pool);
            return e;
        }
    }
    return "";
}

std::string CheckAll() {
    if (!g_asan.empty()) return g_asan;
    if (M().searchCursor >= kWindow)
        return "search cursor left the tracked window (bound, not a finding)";
    std::string e = CheckPool("bone", M().boneKeys, kBones);
    if (e.empty()) e = CheckPool("morph", M().morphKeys, kMorphs);
    if (e.empty()) e = CheckPool("display", M().displayKeys, 1);
    return e;
}

bool IsBound(const std::string& e) { return e.find("(bound") != std::string::npos; }

// One breadth-first search under g_config from a freshly loaded model.
// Appends the dump section to `dump` when it is not null.
int Explore(std::FILE* dump) {
    const bool dumping = dump != nullptr;
    const std::vector<Command> alphabet = Alphabet();
    BuildModel();
    g_checked[panel::kPhysicsFrameCheckbox] = g_config.autoInterpolation;
    g_checked[panel::kPhysicsCheckbox] = g_config.physicsCheckbox;
    g_dump = DumpData();
    struct Node { std::string state; std::vector<int> trace; int id; };
    std::unordered_map<std::string, int> ids;  // snapshot -> state id, dump mode only
    std::unordered_set<std::string> seen;
    std::deque<Node> queue;
    std::map<std::string, std::vector<int>> violations;  // kind -> shortest trace
    std::map<std::string, long> hits;
    long transitions = 0, bounded = 0;

    const std::string initial = CheckAll();
    if (!initial.empty()) {
        std::printf("initial state violates the property: %s\n", initial.c_str());
        return 1;
    }
    queue.push_back({Snapshot(), {}, 0});
    seen.insert(queue.back().state);
    if (dumping) {
        g_dump.windows.resize(1);
        Capture(g_dump.windows[0]);
        g_dump.parent.push_back(-1);
        g_dump.command.push_back(-1);
        g_dump.next.emplace_back();
        ids[queue.back().state] = 0;
    }
    while (!queue.empty()) {
        Node node = std::move(queue.front());
        queue.pop_front();
        if (static_cast<int>(node.trace.size()) >= kDepth) continue;
        if (dumping) g_dump.next[node.id].assign(alphabet.size(), -1);
        for (int c = 0; c < static_cast<int>(alphabet.size()); ++c) {
            if (dumping) RestoreWindow(g_dump.windows[node.id]);
            else Restore(node.state);
            g_asan.clear();
            Apply(alphabet[c]);
            ++transitions;
            std::vector<int> trace = node.trace;
            trace.push_back(c);
            const std::string e = CheckAll();
            if (!e.empty()) {
                if (IsBound(e)) { ++bounded; continue; }
                if (!violations.count(e)) violations[e] = trace;
                ++hits[e];
                continue;  // do not explore from a broken state
            }
            std::string s = Snapshot();
            if (dumping) {
                auto [it, fresh] = ids.emplace(s, static_cast<int>(g_dump.windows.size()));
                g_dump.next[node.id][c] = it->second;
                if (fresh) {
                    g_dump.windows.emplace_back();
                    Capture(g_dump.windows.back());
                    g_dump.parent.push_back(node.id);
                    g_dump.command.push_back(c);
                    g_dump.next.emplace_back();
                }
            }
            if (seen.insert(s).second) {
                const int id = dumping ? ids[s] : 0;
                queue.push_back({std::move(s), std::move(trace), id});
            }
        }
    }
    std::printf("config auto interpolation %d, physics checkbox %d, mode %d:\n"
                "explored %zu states, %ld transitions (depth %d, %d bones, %d morphs, frames 0..%d)\n",
                g_config.autoInterpolation, g_config.physicsCheckbox, g_config.mode,
                seen.size(), transitions, kDepth, kBones, kMorphs, kFrames - 1);
    if (bounded) std::printf("cut at tracked-window bound: %ld transitions\n", bounded);
    for (const auto& [kind, trace] : violations) {
        std::printf("\nVIOLATION (%ld hits): %s\n  shortest trace from a freshly loaded model:\n",
                    hits[kind], kind.c_str());
        for (std::size_t i = 0; i < trace.size(); ++i)
            std::printf("    %zu. %s\n", i + 1, Describe(alphabet[trace[i]]).c_str());
    }
    if (dumping && violations.empty()) {
        WriteDumpSection(dump);
        std::printf("state dump: %zu states written\n", g_dump.windows.size());
    }
    std::printf("\n");
    return violations.empty() ? 0 : 1;
}

// Pool-full runs: fill a pool to capacity with its own-scan registrar, then
// paste one key, whose cursor reset stops at the capacity index.
int OverflowRuns() {
    int failures = 0;
    struct Run { const char* name; void (*fill)(); Kind paste; };
    const Run runs[] = {
        {"display pool full (1000)", [] {
             for (int f = 1; f < static_cast<int>(mdl::kDisplayKeyCapacity); ++f)
                 RegisterDisplayKeyCurrent(g_model, f);
         }, kPasteDisplay},
        {"morph pool full (20000)", [] {
             for (int f = 1; f <= static_cast<int>(mdl::kMorphKeyCapacity) - kMorphs; ++f)
                 RegisterMorphKeyCurrent(g_model, 0, f);
         }, kPasteMorph},
    };
    g_config = kConfigs[0];
    for (const Run& run : runs) {
        BuildModel();
        g_asan.clear();
        run.fill();
        const int pasteFrame = 1 << 20;
        Paste(run.paste, 0, pasteFrame);
        std::printf("\n%s, then paste one key: %s\n", run.name,
                    g_asan.empty() ? "ok" : ("VIOLATION: " + g_asan).c_str());
        failures += !g_asan.empty();
    }
    return failures;
}

}  // namespace

int main(int argc, char** argv) {
    const char* dumpPath = nullptr;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--dump") == 0 && i + 1 < argc) dumpPath = argv[++i];
        else kDepth = std::atoi(argv[i]);
    }
    __asan_set_error_report_callback(OnAsanReport);
    // The dump is written to a temporary file and renamed only on a pass.
    const std::string tmpPath = dumpPath != nullptr ? std::string(dumpPath) + ".tmp" : "";
    std::FILE* dump = nullptr;
    if (dumpPath != nullptr) {
        dump = std::fopen(tmpPath.c_str(), "w");
        if (dump == nullptr) {
            std::fprintf(stderr, "cannot write %s\n", tmpPath.c_str());
            return 1;
        }
        WriteDumpHeader(dump, Alphabet());
    }
    int status = 0;
    for (const Config& c : kConfigs) {
        g_config = c;
        if (Explore(dump) != 0) status = 1;
    }
    if (dump != nullptr) {
        std::fclose(dump);
        if (status == 0 && std::rename(tmpPath.c_str(), dumpPath) == 0)
            std::printf("state dump written to %s\n", dumpPath);
        else
            std::remove(tmpPath.c_str());
    }
    if (OverflowRuns() != 0) status = 1;
    if (status != 0) std::printf("\nresult: FAIL\n");
    else std::printf("\nresult: PASS\n");
    return status;
}
