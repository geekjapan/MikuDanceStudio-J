#include "model_reader_fixture.hpp"
#include "model_format_win.hpp"
#include "mikudancestudio/model_reader.hpp"
#include <fcntl.h>
#include <io.h>
#include <share.h>
#include <sys/stat.h>
#include <cstdio>
#include <cstdlib>
namespace {
void Check(bool condition, const char* reason) {
    if (!condition) {
        std::fprintf(stderr, "%s\n", reason);
        std::exit(1);
    }
}
}
int main() {
    const wchar_t* path = _wgetenv(L"MDS_MODEL_FIXTURE");
    if (!path || !*path) return 77;
    int file = -1;
    Check(_wsopen_s(&file, path, _O_BINARY | _O_RDONLY,
                    _SH_DENYNO, _S_IREAD) == 0, "open external PMX");
    const long length = _filelength(file);
    Check(length > 0, "external PMX length");
    model_reader_fixture::Bytes bytes;
    bytes.data.resize(static_cast<std::size_t>(length));
    Check(_read(file, bytes.data.data(), length) == length, "read external PMX");
    Check(_lseek(file, 0, SEEK_SET) == 0, "rewind external PMX");
    mikudancestudio::format::ModelDocument memory, stream;
    Check(mikudancestudio::format::ReadModelDocument(
              model_reader_fixture::Bytes::read, &bytes, memory), "parse PMX memory");
    Check(mikudancestudio::format::ReadModelDocument(
              mikudancestudio::ReadModelFileBytesResult, &file, stream), "parse PMX CRT");
    Check(memory.kind == mikudancestudio::format::ModelKind::Pmx &&
          stream.kind == memory.kind, "PMX kind");
    Check(bytes.position == bytes.data.size() && _tell(file) == length,
          "PMX consumed length");
    Check(memory.pmx.texts.fields == stream.pmx.texts.fields &&
          memory.pmx.vertices.size() == stream.pmx.vertices.size() &&
          memory.pmx.indices.size() == stream.pmx.indices.size() &&
          memory.pmx.materials.size() == stream.pmx.materials.size() &&
          memory.pmx.bones.size() == stream.pmx.bones.size() &&
          memory.pmx.morphs.size() == stream.pmx.morphs.size() &&
          memory.pmx.frames.size() == stream.pmx.frames.size() &&
          memory.pmx.rigids.size() == stream.pmx.rigids.size() &&
          memory.pmx.joints.size() == stream.pmx.joints.size(), "PMX sections");
    if (!memory.pmx.vertices.empty())
        Check(memory.pmx.vertices.back().position[0] ==
              stream.pmx.vertices.back().position[0], "PMX vertex");
    if (!memory.pmx.indices.empty())
        Check(memory.pmx.indices.back() == stream.pmx.indices.back(), "PMX index");
    if (!memory.pmx.materials.empty())
        Check(memory.pmx.materials.back().fields.memo ==
              stream.pmx.materials.back().fields.memo, "PMX material memo");
    if (!memory.pmx.rigids.empty())
        Check(memory.pmx.rigids.back().fields.mass ==
              stream.pmx.rigids.back().fields.mass, "PMX rigid");
    if (!memory.pmx.joints.empty())
        Check(memory.pmx.joints.back().fields.rigidB ==
              stream.pmx.joints.back().fields.rigidB, "PMX joint");
    _close(file);
}
