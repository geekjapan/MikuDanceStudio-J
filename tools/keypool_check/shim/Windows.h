// Minimal Win32 surface for compiling the keyframe-pool sources on a
// non-Windows host. Every UI call is a no-op. A control handle is its
// dialog id, and a checkbox reads the state the harness sets in g_checked.
#pragma once
#include <cmath>
#include <cstdint>
#include <cstdio>
typedef void* HWND;
typedef std::intptr_t LPARAM, LRESULT;
typedef std::uintptr_t WPARAM;
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define BST_CHECKED 1
#define BST_UNCHECKED 0
#define BM_GETCHECK 0x00F0
#define BM_SETCHECK 0x00F1
#define EM_SETSEL 0x00B1
#define EM_REPLACESEL 0x00C2
#define CB_GETCURSEL 0x0147
inline unsigned char g_checked[0x400];  // by dialog id
inline unsigned Checked(std::intptr_t id) {
    return id >= 0 && id < 0x400 && g_checked[id] ? BST_CHECKED : BST_UNCHECKED;
}
inline HWND GetDlgItem(HWND, int id) { return reinterpret_cast<HWND>(static_cast<std::intptr_t>(id)); }
inline BOOL EnableWindow(HWND, BOOL) { return 0; }
inline LRESULT SendMessageA(HWND h, unsigned msg, WPARAM, LPARAM) {
    return msg == BM_GETCHECK ? Checked(reinterpret_cast<std::intptr_t>(h)) : 0;
}
inline unsigned IsDlgButtonChecked(HWND, int id) { return Checked(id); }
inline int GetWindowTextLengthA(HWND) { return 0; }
inline BOOL SetWindowTextA(HWND, const char*) { return 0; }
inline BOOL CheckRadioButton(HWND, int, int, int) { return 0; }
inline int MessageBoxA(HWND, const char*, const char*, unsigned) { return 0; }
inline int _finite(double x) { return std::isfinite(x); }
#define sprintf_s std::snprintf
#define strcpy_s(dst, n, src) std::snprintf((dst), (n), "%s", (src))
