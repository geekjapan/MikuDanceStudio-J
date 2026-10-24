#pragma once

namespace mikudancestudio {
class D3DRenderer;

namespace pmm_io {
// Serialize occupied model slots in PMM 0002 stream order. The caller owns
// the file descriptor and supplies a 256-byte path conversion buffer.
void WritePmmModelBlocks(int fd, const D3DRenderer* renderer, unsigned char** slots, char* text);
} // namespace pmm_io
} // namespace mikudancestudio
