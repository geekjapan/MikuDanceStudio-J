#pragma once
// Minimal Win32 surface for compiling src/media/wave_audio.cpp on a
// non-Windows host. File I/O goes to POSIX; GDI calls are no-ops;
// MessageBoxA records the last message for the harness.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>

#define __cdecl
typedef void* HWND;
typedef void* HDC;
typedef void* HANDLE;
typedef void* HPEN;
typedef void* HBRUSH;
typedef void* HGDIOBJ;
typedef std::uint32_t DWORD;
typedef std::int32_t LONG;
typedef std::int32_t HRESULT;
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define FAILED(hr) ((hr) < 0)
#define INVALID_HANDLE_VALUE (reinterpret_cast<HANDLE>(static_cast<std::intptr_t>(-1)))
#define GENERIC_READ 0x80000000u
#define OPEN_EXISTING 3
#define FILE_ATTRIBUTE_NORMAL 0x80
#define FILE_BEGIN 0
#define PS_SOLID 0

struct RECT {
    LONG left, top, right, bottom;
};

inline LONG InterlockedCompareExchange(volatile LONG* p, LONG, LONG) { return *p; }
inline LONG InterlockedExchange(volatile LONG* p, LONG v) {
    LONG old = *p;
    *p = v;
    return old;
}

// Paths are narrowed: the harness only opens ASCII names.
inline void NarrowPath(const wchar_t* w, char* out, size_t n) {
    size_t i = 0;
    for (; w[i] && i + 1 < n; ++i)
        out[i] = static_cast<char>(w[i]);
    out[i] = 0;
}
inline int _wfopen_s(FILE** out, const wchar_t* path, const wchar_t*) {
    char p[1024];
    NarrowPath(path, p, sizeof p);
    *out = std::fopen(p, "rb");
    return *out ? 0 : 2;
}
inline HANDLE CreateFileW(const wchar_t* path, DWORD, DWORD, void*, DWORD, DWORD, void*) {
    char p[1024];
    NarrowPath(path, p, sizeof p);
    int fd = ::open(p, O_RDONLY);
    return fd < 0 ? INVALID_HANDLE_VALUE : reinterpret_cast<HANDLE>(static_cast<std::intptr_t>(fd));
}
extern LONG g_lastSeek;
inline DWORD SetFilePointer(HANDLE h, LONG off, LONG*, DWORD) {
    g_lastSeek = off;
    return static_cast<DWORD>(::lseek(static_cast<int>(reinterpret_cast<std::intptr_t>(h)), off, SEEK_SET));
}
inline BOOL ReadFile(HANDLE h, void* buf, DWORD n, DWORD* got, void*) {
    ssize_t r = ::read(static_cast<int>(reinterpret_cast<std::intptr_t>(h)), buf, n);
    *got = r < 0 ? 0 : static_cast<DWORD>(r);
    return r >= 0;
}
inline int wcscpy_s(wchar_t* dst, size_t n, const wchar_t* src) {
    size_t i = 0;
    for (; src[i] && i + 1 < n; ++i)
        dst[i] = src[i];
    dst[i] = 0;
    return 0;
}
inline int swprintf_s(wchar_t* dst, size_t n, const wchar_t* fmt) { return wcscpy_s(dst, n, fmt); }

extern const char* g_lastMessage;
inline int MessageBoxA(HWND, const char* text, const char*, unsigned) {
    g_lastMessage = text;
    return 0;
}
inline HPEN CreatePen(int, int, unsigned) { return nullptr; }
inline HBRUSH CreateSolidBrush(unsigned) { return nullptr; }
inline HGDIOBJ SelectObject(HDC, HGDIOBJ) { return nullptr; }
inline BOOL DeleteObject(HGDIOBJ) { return 1; }
inline BOOL Rectangle(HDC, int, int, int, int) { return 1; }
inline BOOL MoveToEx(HDC, int, int, void*) { return 1; }
inline BOOL LineTo(HDC, int, int) { return 1; }
inline BOOL InvalidateRect(HWND, const RECT*, BOOL) { return 1; }
inline void Sleep(DWORD) {}
inline BOOL KillTimer(HWND, std::uintptr_t) { return 1; }
inline std::uintptr_t SetTimer(HWND, std::uintptr_t, unsigned, void*) { return 1; }
