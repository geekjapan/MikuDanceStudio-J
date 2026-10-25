// The Win32 surface the checked loaders and skinning compile against, on a
// non-Windows host. Message boxes answer IDOK, text conversions and paths are
// no-ops: the check reads none of the strings. wchar_t is 2 bytes
// (-fshort-wchar), so the wide helpers below never call libc.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
typedef void* HWND;
typedef void* HANDLE;
typedef int BOOL;
typedef unsigned int UINT;
typedef std::uint32_t DWORD;
typedef std::int32_t LONG;
typedef std::int32_t HRESULT;
typedef const char* LPCSTR;
typedef const wchar_t* LPCWSTR;
typedef const void* LPCVOID;
typedef int errno_t;
typedef std::size_t rsize_t;
#define WINAPI
#define MAX_PATH 260
#define IDOK 1
#define FAILED(hr) (((HRESULT)(hr)) < 0)
#define SUCCEEDED(hr) (((HRESULT)(hr)) >= 0)
inline int MessageBoxA(HWND, const char*, const char*, unsigned) { return IDOK; }
inline int MessageBoxW(HWND, const wchar_t*, const wchar_t*, unsigned) { return IDOK; }
inline BOOL SetCurrentDirectoryW(const wchar_t*) { return 1; }
#define sprintf_s std::snprintf
#define strcpy_s(dst, n, src) std::snprintf((dst), (n), "%s", (src))
inline errno_t wcscpy_s(wchar_t* dst, rsize_t n, const wchar_t* src) {
    rsize_t i = 0;
    for (; i + 1 < n && src[i]; ++i)
        dst[i] = src[i];
    if (n)
        dst[i] = 0;
    return 0;
}
inline int swprintf_s(wchar_t* dst, rsize_t n, const wchar_t*, ...) {
    if (n)
        dst[0] = 0;
    return 0;
}
