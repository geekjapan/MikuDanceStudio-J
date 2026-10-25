// Oracle for rust/crates/mds-kinect: runs the real Kinect pose chain of the
// C++ on the cases of tests/fixtures/pose_cases.txt and prints, per frame,
// what the Rust crate must reproduce bit for bit.
//
// One frame is what PumpKinectSkeleton does with a tracked performer:
//   mdl::CaptureSkeletonJoints   (include/mikudancestudio/skeleton_tracking.hpp)
//   ModelVertexHistoryPush       (src/features/dialog_helpers.cpp)
//   ModelStandardPoseSetup       (src/features/dialog_helpers.cpp), which calls
//     InitStandardSkeletonQuats  (src/features/audio_pose_helpers.cpp)
// on a ModelRecord built by the real ModelInitDefaults (src/model/model_init.cpp).
// oni_skeleton_pump.cpp itself is not linked: it needs the window, menus and
// undo machinery, and its only math is the call order above.
//
// Usage: pose_check <case file>   (dump on stdout)
//
// Case file, floats as the 8 hex digits of their bits:
//   case <name>
//   config <version 13|14|15> <fps> <mirror 0|1> <lost-bone 0|1>
//   bone <key> <bind y> <trans x y z> <rot x y z w>   (model bone order)
//   ik <bone key> <enabled 0|1>
//   frame <record 0|1>
//   j <openni id> <x> <y> <z>                         (ids 0..22 per frame)
//   end
// Bone keys: center upper neck larm lelbow rarm relbow lower lleg rleg lknee
// rknee lik rik lshoulder rshoulder lankle other. (No wrist: dialog_helpers.cpp
// compares it with bytes that match no bone.)
// Dump, per frame: "frame <i> ended <0|1>", "joints <69 words>", "pose <68>",
// "cal <4>", then per bone "b <i> <trans 3> <rot 4>", then "trace <n>" and,
// while recording, "t <77 words>" (the sample just written).
#include <Windows.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "mikudancestudio/model.hpp"
#include "mikudancestudio/skeleton_tracking.hpp"

namespace mikudancestudio {
void ModelInitDefaults(unsigned char* m);
void ModelVertexHistoryPush(unsigned char* model, int samples);
char ModelStandardPoseSetup(unsigned char* model, bool recordEnable, unsigned char mirrorLeftRight,
                            unsigned char skeletonFlag);

// The undo and rigid-body hooks the other functions of the linked sources call.
void AppendBoneKeyToUndo(unsigned char*, int) {}
void NotifyBonePhysicsMode(unsigned char*, int, unsigned char) {}
} // namespace mikudancestudio

using namespace mikudancestudio;

// The pose trace buffer is allocated with operator new and not cleared, so a
// bone the model lacks leaves its slots as heap garbage. Zeroed memory gives
// the dump one value for them, which the Rust crate reproduces.
void* operator new(std::size_t size) {
    void* p = std::calloc(1, size != 0 ? size : 1);
    if (p == nullptr)
        std::abort();
    return p;
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }

namespace {

const std::map<std::string, std::string>& BoneNames() {
    static const std::map<std::string, std::string> names = {
        {"center", "\x83\x5A\x83\x93\x83\x5E\x81\x5B"},
        {"upper", "\x8F\xE3\x94\xBC\x90\x67"},
        {"neck", "\x8E\xF1"},
        {"larm", "\x8D\xB6\x98\x72"},
        {"lelbow", "\x8D\xB6\x82\xD0\x82\xB6"},
        {"rarm", "\x89\x45\x98\x72"},
        {"relbow", "\x89\x45\x82\xD0\x82\xB6"},
        {"lower", "\x89\xBA\x94\xBC\x90\x67"},
        {"lleg", "\x8D\xB6\x91\xAB"},
        {"rleg", "\x89\x45\x91\xAB"},
        {"lknee", "\x8D\xB6\x82\xD0\x82\xB4"},
        {"rknee", "\x89\x45\x82\xD0\x82\xB4"},
        {"lik", "\x8D\xB6\x91\xAB\x82\x68\x82\x6A"},
        {"rik", "\x89\x45\x91\xAB\x82\x68\x82\x6A"},
        {"lshoulder", "\x8D\xB6\x8C\xA8"},
        {"rshoulder", "\x89\x45\x8C\xA8"},
        {"lankle", "\x8D\xB6\x91\xAB\x8E\xF1"},
        {"other", "other"},
    };
    return names;
}

float F(const std::string& hex) {
    const std::uint32_t bits = static_cast<std::uint32_t>(std::strtoul(hex.c_str(), nullptr, 16));
    float f;
    std::memcpy(&f, &bits, 4);
    return f;
}

void Word(float f) {
    std::uint32_t bits;
    std::memcpy(&bits, &f, 4);
    std::printf(" %08x", bits);
}

void Words(const float* p, int n) {
    for (int i = 0; i < n; ++i)
        Word(p[i]);
}

struct Frame {
    bool record = false;
    float joints[mdl::kTrackedJointCount][3] = {};
};

struct Case {
    std::string name;
    int version = 15, fps = 30;
    bool mirror = true, lost = false;
    struct BoneSpec {
        std::string key;
        float bindY, trans[3], rot[4];
    };
    std::vector<BoneSpec> bones;
    std::vector<std::pair<std::string, bool>> ik;
    std::vector<Frame> frames;
};

void Run(const Case& c) {
    unsigned char* model = static_cast<unsigned char*>(operator new(mdl::kSize));
    std::memset(model, 0, mdl::kSize);
    ModelInitDefaults(model);
    mdl::ModelRecord& m = *mdl::Mdl(model);
    const int n = static_cast<int>(c.bones.size());
    auto* bones = static_cast<mdl::BoneRecord*>(operator new(sizeof(mdl::BoneRecord) * n));
    std::memset(static_cast<void*>(bones), 0, sizeof(mdl::BoneRecord) * n);
    m.boneTable = bones;
    m.boneCount = static_cast<decltype(m.boneCount)>(n);
    for (int i = 0; i < n; ++i) {
        const auto& spec = c.bones[i];
        const std::string& name = BoneNames().at(spec.key);
        std::memcpy(bones[i].name, name.c_str(), name.size());
        bones[i].position[1] = spec.bindY;
        std::memcpy(bones[i].trans, spec.trans, sizeof spec.trans);
        std::memcpy(bones[i].rotQuat, spec.rot, sizeof spec.rot);
    }
    m.ikChainCount = static_cast<decltype(m.ikChainCount)>(c.ik.size());
    m.ikChains = new mdl::IkChain[c.ik.size() + 1]();
    for (std::size_t i = 0; i < c.ik.size(); ++i) {
        for (int b = 0; b < n; ++b)
            if (c.bones[b].key == c.ik[i].first)
                m.ikChains[i].boneIndex = b;
        m.ikChains[i].enabled = c.ik[i].second;
    }
    m.openniVersion = static_cast<std::uint8_t>(c.version);

    std::printf("case %s\n", c.name.c_str());
    int index = 0;
    for (const Frame& frame : c.frames) {
        mdl::CaptureSkeletonJoints(m.currentJoints, m.openniVersion, [&](int id, float* out) {
            std::memcpy(out, frame.joints[id], 12);
        });
        ModelVertexHistoryPush(model, c.fps / 10);
        const char ended = ModelStandardPoseSetup(model, frame.record, c.mirror, c.lost);
        std::printf("frame %d ended %d\n", index++, ended);
        std::printf("joints");
        Words(&m.currentJoints.positions[0][0], 69);
        std::printf("\npose");
        Words(m.standardPose.upperBody, 68);
        std::printf("\ncal");
        Words(m.lightDir, 1);
        Words(&m.lightDir[1], 2);
        Words(&m.legIkXOffset, 1);
        std::printf("\n");
        for (int i = 0; i < n; ++i) {
            std::printf("b %d", i);
            Words(bones[i].trans, 3);
            Words(bones[i].rotQuat, 4);
            std::printf("\n");
        }
        const int samples = m.matMisc;
        std::printf("trace %d\n", samples);
        if (mdl::PoseTraceFlag(model) != 0 && samples > 0) {
            std::printf("t");
            Words(static_cast<const float*>(mdl::PoseTraceBuffer(model)) + 77 * (samples - 1), 77);
            std::printf("\n");
        }
    }
    std::printf("end\n");
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s <case file>\n", argv[0]);
        return 2;
    }
    std::ifstream in(argv[1]);
    if (!in) {
        std::fprintf(stderr, "cannot open %s\n", argv[1]);
        return 2;
    }
    Case c;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#')
            continue;
        std::istringstream words(line);
        std::string op, a, b, d, e, f, g, h, i;
        words >> op;
        if (op == "case") {
            c = Case();
            words >> c.name;
        } else if (op == "config") {
            words >> c.version >> c.fps >> c.mirror >> c.lost;
        } else if (op == "bone") {
            Case::BoneSpec s;
            std::string v[8];
            words >> s.key >> v[0] >> v[1] >> v[2] >> v[3] >> v[4] >> v[5] >> v[6] >> v[7];
            s.bindY = F(v[0]);
            for (int k = 0; k < 3; ++k)
                s.trans[k] = F(v[1 + k]);
            for (int k = 0; k < 4; ++k)
                s.rot[k] = F(v[4 + k]);
            c.bones.push_back(s);
        } else if (op == "ik") {
            int enabled;
            words >> a >> enabled;
            c.ik.emplace_back(a, enabled != 0);
        } else if (op == "frame") {
            c.frames.emplace_back();
            int record;
            words >> record;
            c.frames.back().record = record != 0;
        } else if (op == "j") {
            int id;
            words >> id >> a >> b >> d;
            c.frames.back().joints[id][0] = F(a);
            c.frames.back().joints[id][1] = F(b);
            c.frames.back().joints[id][2] = F(d);
        } else if (op == "end") {
            Run(c);
        }
    }
    return 0;
}
