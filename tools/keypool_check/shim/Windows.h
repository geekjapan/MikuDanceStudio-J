// Minimal Win32 surface for compiling the keyframe-pool sources on a
// non-Windows host. Every UI call is a no-op; checkboxes read unchecked.
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
inline HWND GetDlgItem(HWND, int) { return nullptr; }
inline BOOL EnableWindow(HWND, BOOL) { return 0; }
inline LRESULT SendMessageA(HWND, unsigned, WPARAM, LPARAM) { return 0; }
inline unsigned IsDlgButtonChecked(HWND, int) { return BST_UNCHECKED; }
inline int GetWindowTextLengthA(HWND) { return 0; }
inline BOOL SetWindowTextA(HWND, const char*) { return 0; }
inline BOOL CheckRadioButton(HWND, int, int, int) { return 0; }
inline int MessageBoxA(HWND, const char*, const char*, unsigned) { return 0; }
inline int _finite(double x) { return std::isfinite(x); }
#define sprintf_s std::snprintf
#define strcpy_s(dst, n, src) std::snprintf((dst), (n), "%s", (src))
