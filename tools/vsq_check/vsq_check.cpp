// Runs the real LoadVsqFile (src/io/vsq_load.cpp) on one VSQ file and dumps
// what the C++ does, so the Rust port can be compared with it.
//
// Usage: vsq_check <file.vsq> <model> <jp|en> <out-prefix>
//   <model> names one of the morph tables below.
//   <out-prefix>.dump  outcome, message boxes, the morph keys, the frame
//   <out-prefix>.txt   the sibling .txt exactly as LoadVsqFile leaves it
//
// Dump format, one line each, in this order:
//   status: ok | rejected | hang | fault
//   box: <caption hex> <text hex>      once per MessageBoxA call
//   fault: <reason>                    status fault only
//   keys: <n>
//   <frame> <morph index> <weight bits hex> <weight>   n lines
//   current_frame: <n> | unchanged
//   timeline_start: <n> | unchanged
//   last_registered: <n>
//   seek: <frame> <physics mode> | none
#include <Windows.h>

#include <csetjmp>
#include <csignal>
#include <string>
#include <vector>

#include "mikudancestudio/mmd_app.hpp"
#include "mikudancestudio/model.hpp"

#undef fgets

namespace mikudancestudio {
void LoadVsqFile(MMDApp* app, const wchar_t* path);
}
using namespace mikudancestudio;

namespace {

struct Key {
    int frame, morph;
    float weight;
};
struct Box {
    std::string caption, text;
};

std::vector<Key> g_keys;
std::vector<Box> g_boxes;
bool g_seeked;
int g_seekFrame, g_seekMode;
std::string g_fault;
sigjmp_buf g_jmp;
int g_nullStreak;
constexpr int kUnset = -0x40000000;

std::string Hex(const char* s) {
    std::string out;
    char b[3];
    for (; *s; ++s) {
        std::snprintf(b, sizeof b, "%02x", static_cast<unsigned char>(*s));
        out += b;
    }
    return out.empty() ? "-" : out;
}

void OnSignal(int) {
    g_fault = "signal";
    siglongjmp(g_jmp, 1);
}

// Morph names are Shift-JIS: あ 82A0, い 82A2, う 82A4, え 82A6, お 82A8,
// まばたき 82DC 82CE 82BD 82AB.
const char kBlink[] = "\x82\xdc\x82\xce\x82\xbd\x82\xab";
const char kA[] = "\x82\xa0", kI[] = "\x82\xa2", kU[] = "\x82\xa4",
           kE[] = "\x82\xa6", kO[] = "\x82\xa8";
const char kAA[] = "\x82\xa0\x82\xa0", kII[] = "\x82\xa2\x82\xa2",
           kUU[] = "\x82\xa4\x82\xa4", kOO[] = "\x82\xa8\x82\xa8";

struct Model {
    const char* name;
    std::vector<const char*> morphs;
};
// full lists the faces out of order with a repeated あ so a wrong index or a
// last-match search shows.
const Model kModels[] = {
    {"full", {kBlink, kO, kU, kI, kA, kE, kA}},
    {"no-a", {kBlink, kO, kU, kI, kE}},
    {"no-i", {kBlink, kO, kU, kA, kE}},
    {"no-u", {kBlink, kO, kI, kA, kE}},
    {"no-o", {kBlink, kU, kI, kA, kE}},
    {"no-a-no-o", {kBlink, kU, kI, kE}},
    {"lookalike", {kAA, kII, kUU, kOO}},
    {"empty", {}},
};

unsigned char* BuildModel(const Model& m) {
    auto* model = static_cast<unsigned char*>(operator new(mdl::kSize));
    std::memset(model, 0, mdl::kSize);
    mdl::ModelRecord& r = *mdl::Mdl(model);
    r.morphCount = static_cast<int>(m.morphs.size());
    r.morphs = new mdl::MorphRecord[m.morphs.size() + 1]();
    for (std::size_t i = 0; i < m.morphs.size(); ++i)
        std::snprintf(r.morphs[i].name, sizeof r.morphs[i].name, "%s", m.morphs[i]);
    r.boneKeys = static_cast<mdl::BoneKey*>(
        std::calloc(mdl::kBoneKeyCapacity, sizeof(mdl::BoneKey)));
    r.morphKeys = static_cast<mdl::MorphKey*>(
        std::calloc(mdl::kMorphKeyCapacity, sizeof(mdl::MorphKey)));
    r.displayKeys = static_cast<mdl::DisplayKey*>(
        std::calloc(mdl::kDisplayKeyCapacity, sizeof(mdl::DisplayKey)));
    return model;
}

}  // namespace

extern "C" {
void vsq_shim_fail(const char* what) {
    g_fault = what;
    siglongjmp(g_jmp, 1);
}
int vsq_shim_msgbox(const char* text, const char* caption) {
    g_boxes.push_back({caption, text});
    return 1;
}
char* vsq_shim_fgets(char* buf, int n, FILE* f) {
    char* r = ::fgets(buf, n, f);
    g_nullStreak = r ? 0 : g_nullStreak + 1;
    // At end of file the line buffer stops changing, so a scan that has not
    // matched by now never will: the original loops forever.
    if (g_nullStreak > 1000) {
        g_fault = "hang";
        siglongjmp(g_jmp, 1);
    }
    return r;
}
}

namespace mikudancestudio {
void RegisterMorphKeyCurrent(unsigned char* model, int morph, int frame) {
    g_keys.push_back({frame, morph, mdl::Morphs(model)[morph].value});
}
int SeekModelFrame(mdl::ModelRecord&, int frame, int physicsMode) {
    g_seeked = true;
    g_seekFrame = frame;
    g_seekMode = physicsMode;
    return 0;
}
void TimelineDrawTicks(int, int) {}
void AviBgOverlayRefresh(MMDApp*) {}
void PanelPaint(MMDApp*) {}
}  // namespace mikudancestudio

int main(int argc, char** argv) {
    if (argc != 5) {
        std::fprintf(stderr, "usage: vsq_check <file.vsq> <model> <jp|en> <out-prefix>\n");
        return 2;
    }
    const Model* model = nullptr;
    for (const Model& m : kModels)
        if (std::strcmp(m.name, argv[2]) == 0) model = &m;
    if (!model) {
        std::fprintf(stderr, "unknown model %s\n", argv[2]);
        return 2;
    }
    // The file rewrites its path argument in place (.vsq -> .txt).
    std::vector<wchar_t> path;
    for (const char* c = argv[1]; *c; ++c) path.push_back(static_cast<wchar_t>(*c));
    path.push_back(0);
    std::string txtPath = argv[1];
    txtPath.replace(txtPath.find(".vsq"), 4, ".txt");
    std::remove(txtPath.c_str());

    MMDApp app{};
    app.englishUI = std::strcmp(argv[3], "en") == 0;
    app.model = BuildModel(*model);
    app.state.currentFrame = kUnset;
    app.state.timelineStartFrame = kUnset;

    struct sigaction sa {};
    sa.sa_handler = OnSignal;
    sigaction(SIGSEGV, &sa, nullptr);
    sigaction(SIGBUS, &sa, nullptr);

    const char* status = "ok";
    if (sigsetjmp(g_jmp, 1) == 0) {
        LoadVsqFile(&app, path.data());
        if (!g_boxes.empty()) status = "rejected";
    } else {
        status = g_fault == "hang" ? "hang" : "fault";
    }

    const std::string prefix = argv[4];
    FILE* d = std::fopen((prefix + ".dump").c_str(), "wb");
    std::fprintf(d, "status: %s\n", status);
    for (const Box& b : g_boxes)
        std::fprintf(d, "box: %s %s\n", Hex(b.caption.c_str()).c_str(), Hex(b.text.c_str()).c_str());
    if (!std::strcmp(status, "fault")) std::fprintf(d, "fault: %s\n", g_fault.c_str());
    std::fprintf(d, "keys: %zu\n", g_keys.size());
    for (const Key& k : g_keys) {
        std::uint32_t bits;
        std::memcpy(&bits, &k.weight, 4);
        std::fprintf(d, "%d %d %08x %.9g\n", k.frame, k.morph, bits, static_cast<double>(k.weight));
    }
    auto field = [&](const char* name, int v) {
        if (v == kUnset) std::fprintf(d, "%s: unchanged\n", name);
        else std::fprintf(d, "%s: %d\n", name, v);
    };
    field("current_frame", app.state.currentFrame);
    field("timeline_start", app.state.timelineStartFrame);
    std::fprintf(d, "last_registered: %u\n", app.lastRegisteredFrame);
    if (g_seeked) std::fprintf(d, "seek: %d %d\n", g_seekFrame, g_seekMode);
    else std::fprintf(d, "seek: none\n");
    std::fclose(d);

    // A stop in the middle of the call leaves the .txt open; flush before
    // copying it out.
    std::fflush(nullptr);
    FILE* in = std::fopen(txtPath.c_str(), "rb");
    FILE* out = std::fopen((prefix + ".txt").c_str(), "wb");
    if (in) {
        char buf[4096];
        std::size_t n;
        while ((n = std::fread(buf, 1, sizeof buf, in)) > 0) std::fwrite(buf, 1, n, out);
        std::fclose(in);
    }
    std::fclose(out);
    return 0;
}
