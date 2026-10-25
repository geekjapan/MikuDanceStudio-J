// The CRT file calls of the loaders, on POSIX. _wsopen_s takes the 2-byte
// wide path the harness builds from ASCII.
#pragma once
#include <fcntl.h>
#include <unistd.h>
#define _O_BINARY 0
#define _S_IREAD 0
inline int _read(int fd, void* buffer, unsigned count) {
    return static_cast<int>(::read(fd, buffer, count));
}
inline int _close(int fd) { return ::close(fd); }
inline int _wsopen_s(int* fd, const wchar_t* path, int, int, int) {
    char narrow[1024];
    std::size_t i = 0;
    for (; i + 1 < sizeof narrow && path[i]; ++i)
        narrow[i] = static_cast<char>(path[i]);
    narrow[i] = 0;
    *fd = ::open(narrow, O_RDONLY);
    return *fd < 0 ? 2 : 0;
}
// SavePmdFile is compiled but never called by the check.
inline int _sopen_s(int* fd, const char*, int, int, int) { *fd = -1; return 2; }
inline int _write(int, const void*, unsigned) { return 0; }
