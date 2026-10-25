#pragma once
#include <mmsystem.h>
struct DSBUFFERDESC {
    DWORD dwSize, dwFlags, dwBufferBytes, dwReserved;
    WAVEFORMATEX* lpwfxFormat;
};
#define DSERR_BUFFERLOST static_cast<HRESULT>(0x88780096)
#define DSBPLAY_LOOPING 1
// WaveFeedThread is linked but never started (the shim _beginthread does not
// run it), so the buffer methods only have to exist.
struct IDirectSoundBuffer {
    virtual ~IDirectSoundBuffer() {}
    HRESULT Lock(DWORD, DWORD, void**, DWORD*, void**, DWORD*, DWORD) { return -1; }
    HRESULT Unlock(void*, DWORD, void*, DWORD) { return 0; }
    HRESULT Restore() { return 0; }
    HRESULT Play(DWORD, DWORD, DWORD) { return 0; }
    HRESULT Stop() { return 0; }
    HRESULT GetCurrentPosition(DWORD*, DWORD*) { return 0; }
    HRESULT SetFrequency(DWORD) { return 0; }
    DWORD Release() { return 0; }
};
struct IDirectSound {
    virtual HRESULT CreateSoundBuffer(const DSBUFFERDESC*, IDirectSoundBuffer**, void*) = 0;
};
