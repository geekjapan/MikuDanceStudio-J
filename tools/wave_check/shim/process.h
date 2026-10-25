#pragma once
#include <Windows.h>
extern int g_threadsStarted;
inline std::uintptr_t _beginthread(void (*)(void*), unsigned, void*) {
    return ++g_threadsStarted;
}
inline void _endthread() {}
