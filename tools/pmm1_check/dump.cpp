// Oracle for rust/crates/mds-formats (PMM version 0001): reads a 0001 scene
// with the portable reader of the `next` branch (ReadPmmSceneDocument) and
// prints it as the text that rust/crates/mds-formats/tests/pmm1.rs renders
// from its own `Pmm`.
//
// Usage: pmm1_dump <fixture dir> <scene file>      (dump on stdout)
//
// The portable reader returns the stream; the Rust reader returns the state
// that src/io/pmm_load_v1.cpp on main leaves, which `SaveSceneFile` writes as
// 0002. This tool applies main's rules to the portable result so that both
// sides print the same thing:
//   * a flag the loader tests as `b == 1` prints 0 or 1 (the portable reader
//     already does this for most flags; the tail flags are raw there);
//   * what the stream does not carry prints the fresh-application default
//     (playback mode 2, floor visible, camera parent -1, model edge scale 1,
//     toon 1, display order = combo index);
//   * a sparse record with frame 0 is a free record and is not printed;
//   * the AVI and picture record count as loaded only with a non-empty path;
//   * the camera parent list (tail gate 9) is read only when the first
//     parent is in range, the one place where main and the portable reader
//     differ (the portable reader always reads it; a scene that takes the
//     other branch is not run through this tool);
//   * the self-shadow distance of the panel is the key at or before the
//     current frame (RefreshSelfShadowPanel, FindKeyAtOrAfter).
// Floats print as the 8 hex digits of their bits. A PMD supplies the counts
// that a 0001 model block leaves out.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <vector>

#include "mikudancestudio/pmm_scene_document.hpp"

namespace f = mikudancestudio::format;

namespace {

std::string g_dir;

void I(long long v) { std::printf(" %lld", v); }
void F(float v) {
    std::uint32_t b;
    std::memcpy(&b, &v, 4);
    std::printf(" %08x", b);
}
template <class T, std::size_t N> void Fs(const std::array<T, N>& a) {
    for (float v : a) F(v);
}
template <std::size_t N> void S(const std::array<char, N>& a) {
    std::string s(a.data(), strnlen(a.data(), N));
    std::printf(" s:%s", s.c_str());
}
std::uint8_t Flag(std::uint8_t b) { return b == 1; }
std::uint8_t Nonzero(std::uint8_t b) { return b != 0; }

// Counts of a PMD as src/model/pmd_load.cpp leaves them in the model record.
bool PmdCounts(const std::string& path, f::PmmModelLayout& layout) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    std::vector<std::uint8_t> d((std::istreambuf_iterator<char>(in)),
                                std::istreambuf_iterator<char>());
    std::size_t o = 3 + 4 + 20 + 256;
    auto u32 = [&](std::uint32_t& v) {
        if (o + 4 > d.size()) return false;
        std::memcpy(&v, &d[o], 4);
        o += 4;
        return true;
    };
    auto u16 = [&](std::uint32_t& v) {
        if (o + 2 > d.size()) return false;
        std::uint16_t x;
        std::memcpy(&x, &d[o], 2);
        v = x;
        o += 2;
        return true;
    };
    if (d.size() < o || std::memcmp(d.data(), "Pmd", 3) != 0) return false;
    std::uint32_t n = 0;
    if (!u32(n)) return false;
    o += 38ull * n;
    if (!u32(n)) return false;
    o += 2ull * n;
    if (!u32(n)) return false;
    o += 70ull * n;
    if (!u16(layout.boneCount)) return false;
    o += 39ull * layout.boneCount;
    if (!u16(layout.ikCount)) return false;
    for (std::uint32_t i = 0; i < layout.ikCount; ++i) {
        if (o + 11 > d.size()) return false;
        o += 4;
        std::uint8_t links = d[o];
        o += 7 + 2ull * links;
    }
    return u16(layout.morphCount) && o <= d.size();
}

bool Resolve(void*, std::uint8_t, const std::array<char, 20>&,
             const std::array<char, 256>& path, f::PmmModelLayout& layout) {
    std::string p(path.data(), strnlen(path.data(), path.size()));
    return PmdCounts(g_dir + "/" + p, layout);
}

int Read(void* ctx, void* dst, std::size_t n) {
    auto* in = static_cast<std::ifstream*>(ctx);
    in->read(static_cast<char*>(dst), static_cast<std::streamsize>(n));
    return static_cast<int>(in->gcount());
}

// Dense records, then sparse ones by pool index; a record with frame 0 is
// free. The portable reader keeps the sparse list in stream order.
template <class T>
std::map<std::uint32_t, T> Pool(const f::PmmKeyTrack<T>& t) {
    std::map<std::uint32_t, T> pool;
    for (std::uint32_t i = 0; i < t.dense.size(); ++i) pool[i] = t.dense[i];
    for (const auto& s : t.sparse) {
        if (s.index < static_cast<std::int32_t>(t.dense.size()))
            pool[s.index] = s.value;
        else if (s.value.frame == 0)
            pool.erase(s.index);
        else
            pool[s.index] = s.value;
    }
    return pool;
}

template <class T, class Fn>
void Track(const char* heads, const char* rows, const f::PmmKeyTrack<T>& t,
           Fn row) {
    auto pool = Pool(t);
    std::printf("%s %zu %zu\n", heads, t.dense.size(), pool.size() - t.dense.size());
    for (auto& [index, key] : pool) {
        std::printf("%s %u", rows, index);
        row(key);
        std::printf("\n");
    }
}

template <class T> void Links(const T& k) {
    I(k.frame);
    I(k.previous);
    I(k.next);
}

// The accessory opacity byte is (100 - opacity * 100) * 2 plus visible.
std::uint8_t OpacityByte(float opacity, std::uint8_t visible) {
    return static_cast<std::uint8_t>(((100 - std::lround(opacity * 100.0f)) << 1) | visible);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: pmm1_dump <fixture dir> <scene file>\n");
        return 2;
    }
    g_dir = argv[1];
    std::ifstream in(g_dir + "/" + argv[2], std::ios::binary);
    f::PmmSceneDocument sc;
    if (!in || !f::ReadPmmSceneDocument(Read, &in, Resolve, nullptr, sc)) {
        std::fprintf(stderr, "pmm1_dump: %s: not a readable 0001 scene\n", argv[2]);
        return 1;
    }
    const int stage = sc.v1TailStage;
    const auto& st = sc.envelope.settings;

    std::printf("settings");
    I(st.renderWidth); I(st.renderHeight); I(st.editPanelWidth); F(st.cameraFov);
    for (int i = 0; i < 6; ++i) I(st.options[i]);
    I(1);
    std::printf("\nselected %d models %zu\n", sc.envelope.selectedModelSlot, sc.models.size());

    std::vector<const f::PmmSceneModel*> models;
    for (auto& m : sc.models) models.push_back(&m);
    std::sort(models.begin(), models.end(),
              [](auto* a, auto* b) { return a->slot < b->slot; });
    for (auto* mp : models) {
        const auto& m = *mp;
        std::printf("model %d bones %u morphs %u ik %u\n", m.slot, m.layout.boneCount,
                    m.layout.morphCount, m.layout.ikCount);
        std::printf("sel");
        I(m.selection.comboIndex); I(m.selection.loadComplete);
        I(m.selection.selectedBone);
        for (auto v : m.selection.selectedMorphs) I(v);
        I(m.selection.boneListPos); I(m.selection.maxFrame);
        std::printf("\ngroups");
        for (auto v : m.selection.groupFlags) I(v);
        std::printf("\nflags");
        I(stage >= 1 ? Flag(m.postLoadFlag) : 0);
        F(stage >= 2 ? m.edgeScale : 1.0f);
        I(stage >= 5 ? Flag(m.toonFlag) : 1);
        I(stage >= 12 ? m.previousDisplayOrder : m.selection.comboIndex);
        std::printf("\n");
        Track("bonekeys", "bk", m.boneKeys, [](const f::PmmBoneKey& k) {
            Links(k);
            for (auto v : k.interpolation) I(v);
            Fs(k.position);
            Fs(k.rotation);
            I(k.allocated);
        });
        Track("morphkeys", "mk", m.morphKeys, [](const f::PmmMorphKey& k) {
            Links(k);
            F(k.value);
            I(k.allocated);
        });
        Track("displaykeys", "dk", m.displayKeys, [](const f::PmmDisplayKey& k) {
            Links(k);
            I(k.visible);
            for (auto v : k.ikEnabled) I(v);
            I(k.allocated);
        });
        for (std::size_t i = 0; i < m.bonePose.size(); ++i) {
            const auto& c = m.bonePose[i].components;
            std::printf("bp %zu", i);
            F(c[0]); F(c[1]); F(c[2]);
            F(c[7]); F(c[4]); F(c[5]); F(c[6]);
            I(Flag(m.bonePose[i].flags[0]));
            I(Flag(m.bonePose[i].flags[1]));
            std::printf("\n");
        }
        for (std::size_t i = 0; i < m.morphPose.size(); ++i) {
            std::printf("mp %zu", i);
            F(m.morphPose[i]);
            std::printf("\n");
        }
        for (std::size_t i = 0; i < m.ikPose.size(); ++i)
            std::printf("ip %zu %d\n", i, Flag(m.ikPose[i]));
    }

    // Camera: a fresh key holds parent -1, bone 0; the tail may set them.
    struct Cam {
        f::PmmCameraKey key;
        std::int32_t pm = -1, pb = 0;
    };
    std::map<std::uint32_t, Cam> cam;
    for (auto& [i, k] : Pool(sc.cameraKeys)) cam[i].key = k;
    std::int32_t appPm = -1, appPb = 0;
    if (stage >= 9 && !sc.v1CameraParents.empty()) {
        auto& head = sc.v1CameraParents[0];
        cam.at(0).pm = head.model;
        cam.at(0).pb = head.bone;
        for (std::size_t i = 1; i < sc.v1CameraParents.size(); ++i) {
            auto& p = sc.v1CameraParents[i];
            cam.at(p.keyIndex).pm = p.model;
            cam.at(p.keyIndex).pb = p.bone;
        }
        appPm = sc.appearance.cameraParentModel;
        appPb = sc.appearance.cameraParentBone;
    }
    std::printf("camerakeys %zu %zu\n", sc.cameraKeys.dense.size(),
                cam.size() - sc.cameraKeys.dense.size());
    for (auto& [i, c] : cam) {
        const auto& k = c.key;
        std::printf("ck %u", i);
        Links(k);
        F(k.distance); Fs(k.eye); Fs(k.target);
        I(c.pm); I(c.pb);
        for (auto& row : k.interpolation)
            for (auto v : row) I(v);
        I(k.perspective); I(k.fov); I(k.selected);
        std::printf("\n");
    }
    std::printf("camerastate");
    Fs(sc.cameraState);
    I(Flag(sc.cameraPerspective));
    std::printf("\n");
    Track("lightkeys", "lk", sc.lightKeys, [](const f::PmmLightKey& k) {
        Links(k);
        Fs(k.color);
        Fs(k.direction);
        I(k.selected);
    });
    std::printf("lightstate");
    Fs(sc.lightState);
    std::printf("\n");

    std::printf("accessories selected %d scroll %d count %zu\n", sc.selectedAccessorySlot,
                sc.displayListScroll, sc.accessories.size());
    for (std::size_t n = 0; n < sc.accessories.size(); ++n) {
        const auto& a = sc.accessories[n];
        std::printf("acc %d", a.slot);
        S(sc.accessoryListNames[n]);
        S(a.name);
        S(a.path);
        I(a.order);
        std::printf("\n");
        Track("accessorykeys", "ak", a.keyRecords, [](const f::PmmAccessoryKey& k) {
            Links(k);
            I(OpacityByte(k.opacity, k.visible));
            I(k.parentModel); I(k.parentBone);
            Fs(k.position);
            Fs(k.rotation);
            F(k.scale);
            I(k.shadowEnabled);
            I(k.selected);
        });
        const auto& s = a.state;
        std::printf("accstate");
        I(OpacityByte(s.opacity, s.visible));
        I(s.parentModel); I(s.parentBone);
        Fs(s.rotation);
        F(s.scale);
        Fs(s.position);
        I(s.shadowEnabled);
        I(stage >= 1 ? Flag(s.additiveBlend) : 0);
        std::printf("\n");
    }

    const auto& t = sc.timeline;
    std::printf("timeline");
    I(t.currentFrame); I(t.startFrame); I(t.lastRegisteredFrame); I(t.editMode);
    I(t.cameraReferenceMode); I(t.playbackLoop); I(t.returnToStart);
    I(t.startAtCurrent); I(t.playStartFrame); I(t.playStopFrame);
    std::printf("\nwave");
    I(sc.wave.enabled);
    S(sc.wave.pathBytes);
    auto background = [](const char* tag, const f::PmmBackgroundReference& b, bool picture) {
        const bool loaded = b.pathBytes[0] != 0;
        std::printf("\n%s", tag);
        I(loaded ? b.offsetX : 0);
        I(loaded ? b.offsetY : 0);
        F(loaded ? b.scale : 1.0f);
        S(b.pathBytes);
        I(loaded ? (picture ? Nonzero(b.enabled) : b.enabled) : 0);
    };
    background("avi", sc.avi, false);
    background("picture", sc.picture, true);
    std::printf("\nview");
    I(sc.view.fpsOverlay); I(sc.view.groundGrid); I(sc.view.groundShadow);
    F(sc.view.fpsLimit);
    I(sc.view.captureMode);

    const auto& p = sc.physics;
    std::printf("\nphysics");
    I(stage >= 1 ? p.accessoryRenderOrder : 0);
    F(stage >= 1 ? p.projectedShadowAmbient : 0.0f);
    I(stage >= 2 ? Flag(p.projectedShadowBlend) : 0);
    I(stage >= 4 ? p.playbackMode : 2);
    F(stage >= 4 ? p.gravityMagnitude : 9.8f);
    I(stage >= 4 ? p.gravityNoise : 10);
    for (int i = 0; i < 3; ++i) F(stage >= 4 ? p.gravityDirection[i] : (i == 1 ? -1.0f : 0.0f));
    I(stage >= 4 ? Flag(p.gravityNoiseEnabled) : 0);

    // The self-shadow head holds mode 1 and distance 0.01125 until the stream
    // names them; the key track of gate 5 replaces the whole pool.
    f::PmmKeyTrack<f::PmmSelfShadowKey> shadow = sc.selfShadowKeys;
    std::map<std::uint32_t, f::PmmSelfShadowKey> sp;
    if (stage >= 6) {
        sp = Pool(shadow);
    } else {
        f::PmmSelfShadowKey head;
        head.mode = 1;
        head.distance = 0.01125f;
        if (stage >= 5) {
            head.mode = sc.selfShadowMode;
            head.distance = sc.physicsInterval;
        }
        sp[0] = head;
    }
    auto at = [&](std::uint32_t i) {
        auto it = sp.find(i);
        return it == sp.end() ? f::PmmSelfShadowKey{} : it->second;
    };
    // FindKeyAtOrAfter: the panel shows the key at or after the frame, and
    // the one before it when its frame differs.
    const std::uint32_t frame = static_cast<std::uint32_t>(t.currentFrame);
    std::uint32_t index = 0;
    if (at(0).frame < frame) {
        for (;;) {
            const auto next = at(index).next;
            if (next == 0) break;
            index = next;
            if (at(index).frame >= frame) break;
        }
    }
    const auto found = at(index);
    const float interval = found.frame != frame ? at(found.previous).distance : found.distance;
    std::printf("\nselfshadow %d", (stage >= 5 && sc.selfShadowMode != 0) ? 1 : 0);
    F(interval);
    std::printf("\nselfshadowkeys 1 %zu\n", sp.size() - 1);
    for (auto& [i, k] : sp) {
        std::printf("sk %u", i);
        Links(k);
        I(k.mode); F(k.distance); I(k.selected);
        std::printf("\n");
    }

    const auto& ap = sc.appearance;
    std::printf("appearance");
    for (int i = 0; i < 3; ++i) I(stage >= 7 ? ap.outlineColor[i] : 0);
    I(stage >= 8 ? Nonzero(ap.blackBackground) : 0);
    I(appPm); I(appPb);
    for (int i = 0; i < 16; ++i)
        F(stage >= 10 ? ap.cameraAttachmentBasis[i] : ((i % 5) == 0 ? 1.0f : 0.0f));
    I(stage >= 10 ? Flag(ap.followCamera) : 0);
    I(stage >= 10 ? Flag(ap.suppressCameraTransform) : 0);
    I(stage >= 11 ? Nonzero(ap.floorVisible) : 1);
    I(0);
    std::printf("\nregistrations");
    for (auto* m : models) std::printf(" %d:3", m->slot);
    std::printf("\n");
    return 0;
}
