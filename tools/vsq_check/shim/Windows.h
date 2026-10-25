// Win32 and CRT surface for compiling src/io/vsq_load.cpp on a non-Windows
// host. Handle types are void pointers, as on x64 Windows. The CRT calls the
// file uses are redefined here with their MSVC behavior: sprintf_s fails
// instead of truncating, wide paths are 2 bytes, and the fgets/_read hooks
// let the harness stop loops that never end on the original.
#pragma once
#include <cerrno>
#include <cmath>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <fcntl.h>
#include <unistd.h>

typedef void* HWND;
typedef void* HDC;
typedef void* HMENU;
typedef void* HMODULE;
typedef void* HFONT;
typedef std::intptr_t LPARAM, LRESULT;
typedef std::uintptr_t WPARAM;
typedef int BOOL;
typedef long LONG;
typedef int errno_t;
struct RECT { LONG left, top, right, bottom; };

#define MB_OK 0
#define EM_SETSEL 0x00B1
#define EM_REPLACESEL 0x00C2

// Defined by the harness.
extern "C" {
[[noreturn]] void vsq_shim_fail(const char* what);
int vsq_shim_msgbox(const char* text, const char* caption);
char* vsq_shim_fgets(char* buf, int n, FILE* f);
}

inline HWND GetDlgItem(HWND, int) { return nullptr; }
inline LRESULT SendMessageA(HWND, unsigned, WPARAM, LPARAM) { return 0; }
inline int GetWindowTextLengthA(HWND) { return 0; }
inline BOOL InvalidateRect(HWND, const RECT*, BOOL) { return 0; }
inline int MessageBoxA(HWND, const char* text, const char* caption, unsigned) {
    return vsq_shim_msgbox(text, caption);
}

// MSVC's default invalid-parameter handler ends the process when the result
// does not fit, so overflow is a failure, never a truncation.
inline int sprintf_s(char* dst, std::size_t n, const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    const int r = std::vsnprintf(dst, n, fmt, ap);
    va_end(ap);
    if (r < 0 || static_cast<std::size_t>(r) >= n) vsq_shim_fail("sprintf_s overflow");
    return r;
}

// -fshort-wchar makes wchar_t 2 bytes, which the libc wide functions do not
// understand; the file uses only ASCII paths.
inline const wchar_t* vsq_wcsstr(const wchar_t* h, const wchar_t* n) {
    for (; *h; ++h) {
        const wchar_t *a = h, *b = n;
        while (*a && *b && *a == *b) ++a, ++b;
        if (!*b) return h;
    }
    return *n ? nullptr : h;
}
#define wcsstr vsq_wcsstr

inline void vsq_narrow(const wchar_t* w, char* out, std::size_t cap) {
    std::size_t i = 0;
    for (; w[i] && i + 1 < cap; ++i) out[i] = static_cast<char>(w[i]);
    out[i] = 0;
}
inline errno_t _wsopen_s(int* fd, const wchar_t* path, int, int, int) {
    char p[1024];
    vsq_narrow(path, p, sizeof p);
    *fd = ::open(p, O_RDONLY);
    return *fd < 0 ? errno : 0;
}
inline errno_t _wfopen_s(FILE** f, const wchar_t* path, const wchar_t* mode) {
    char p[1024], m[8];
    vsq_narrow(path, p, sizeof p);
    vsq_narrow(mode, m, sizeof m);
    // "t" is the Windows text mode flag; POSIX text is already LF.
    for (char* c = m; *c; ++c)
        if (*c == 't') std::memmove(c, c + 1, std::strlen(c));
    *f = std::fopen(p, m);
    return *f ? 0 : errno;
}
#define fgets vsq_shim_fgets
