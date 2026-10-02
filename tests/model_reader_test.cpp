#include "mikudancestudio/model_reader.hpp"
#include "model_reader_fixture.hpp"
#include <cstdlib>
using namespace mikudancestudio::format;
using model_reader_fixture::Bytes;
namespace {
void Check(bool condition) { if (!condition) std::abort(); }
}
int main() {
    auto pmd = model_reader_fixture::Pmd();
    ModelDocument document;
    Check(ReadModelDocument(Bytes::read, &pmd, document));
    Check(pmd.position == pmd.data.size());
    Check(document.kind == ModelKind::Pmd);
    Check(document.pmd.header.name[0] == 'P');
    Check(document.pmd.vertices.size() == 1 && document.pmd.indices.size() == 3);
    Check(document.pmd.materials.size() == 1 && document.pmd.materials[0].toonReference == 2);
    Check(document.pmd.bones.size() == 1 && document.pmd.bones[0].parent == -1);
    Check(document.pmd.ikChains.size() == 1 && document.pmd.ikChains[0].links[0] == 0);
    Check(document.pmd.morphs.size() == 1 && document.pmd.morphs[0].offsets[0].offset[2] == 3);
    Check(document.pmd.facialTargets.size() == 1 && document.pmd.boneFrames.size() == 1);
    Check(document.pmd.englishPresence.hasEnglish && document.pmd.englishModel.name[0] == 'E');
    Check(document.pmd.toonNames[9][0] == 'T');
    Check(document.pmd.hasPhysicsSection && document.pmd.rigids.size() == 1);
    Check(document.pmd.joints.size() == 1 && document.pmd.joints[0].pmdName[0] == 'J');
    auto noPhysics = model_reader_fixture::Pmd(false, false);
    Check(ReadModelDocument(Bytes::read, &noPhysics, document));
    Check(noPhysics.position == noPhysics.data.size());
    Check(!document.pmd.englishPresence.hasEnglish &&
          document.pmd.englishPresence.hasToonFields);
    Check(document.pmd.englishBoneNames.empty());
    Check(document.pmd.hasPhysicsSection && document.pmd.rigids.empty() &&
          document.pmd.joints.empty());
    auto pmx = model_reader_fixture::Pmx();
    Check(ReadModelDocument(Bytes::read, &pmx, document));
    Check(pmx.position == pmx.data.size() && document.kind == ModelKind::Pmx);
    Check(document.pmx.texts.fields[0][0] == 'P');
    Check(document.pmx.vertices.size() == 1 && document.pmx.indices.size() == 3);
    Check(document.pmx.textures.size() == 1 && document.pmx.textures[0][0] == 't');
    Check(document.pmx.materials.size() == 1 &&
          document.pmx.materials[0].fields.faceVertexCount == 3);
    Check(document.pmx.materials[0].fields.memo.size() == 2 &&
          document.pmx.materials[0].fields.memo[0] == 'N');
    Check(document.pmx.bones.size() == 1 && document.pmx.bones[0].fields.parent == -1);
    Check(document.pmx.morphs.size() == 1 &&
          document.pmx.morphs[0].offsets[0].values[0] == 3);
    Check(document.pmx.frames.size() == 2 &&
          document.pmx.frames[0].entries[0].index == 0);
    Check(document.pmx.rigids.empty() && document.pmx.joints.empty());
    auto pmxPhysics = model_reader_fixture::Pmx(true);
    Check(ReadModelDocument(Bytes::read, &pmxPhysics, document));
    Check(pmxPhysics.position == pmxPhysics.data.size());
    Check(document.pmx.rigids.size() == 1 && document.pmx.joints.size() == 1);
    Check(document.pmx.rigids[0].fields.size[0] == 1);
    Check(document.pmx.joints[0].names[0][0] == 'J');
    Check(document.pmx.joints[0].fields.rigidA == 0);
    auto oversized = model_reader_fixture::Pmd();
    oversized.data[283] = 0xff;
    oversized.data[284] = 0xff;
    oversized.data[285] = 0xff;
    oversized.data[286] = 0x7f;
    Check(!ReadModelDocument(Bytes::read, &oversized, document));
    Check(document.kind == ModelKind::Pmx && document.pmx.joints.size() == 1);
    auto badWidth = model_reader_fixture::Pmx();
    badWidth.data[11] = 3;
    Check(!ReadModelDocument(Bytes::read, &badWidth, document));
    Check(document.pmx.rigids.size() == 1);
    pmd = model_reader_fixture::Pmd();
    pmd.data.pop_back();
    Check(!ReadModelDocument(Bytes::read, &pmd, document));
    Check(document.kind == ModelKind::Pmx && document.pmx.frames.size() == 2);
    pmx = model_reader_fixture::Pmx();
    pmx.data.pop_back();
    Check(!ReadModelDocument(Bytes::read, &pmx, document));
    Check(document.kind == ModelKind::Pmx && document.pmx.vertices.size() == 1);
    pmx = model_reader_fixture::Pmx();
    pmx.data[9] = 1;
    Check(!ReadModelDocument(Bytes::read, &pmx, document));
    Check(document.pmx.header.textEncoding == 0);
    Bytes invalid;
    invalid.byte('x'); invalid.byte('y'); invalid.byte('z');
    Check(!ReadModelDocument(Bytes::read, &invalid, document));
    Check(document.kind == ModelKind::Pmx);
}
