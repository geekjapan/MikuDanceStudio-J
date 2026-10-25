// Memory-backed vertex and index buffers in place of the D3D9 device the
// loaders create them on. The harness reads the skinned buffers back here.
#pragma once
#include <vector>
#include <Windows.h>
enum D3DPOOL { D3DPOOL_DEFAULT = 0, D3DPOOL_MANAGED = 1 };
enum D3DFORMAT { D3DFMT_INDEX16 = 101, D3DFMT_INDEX32 = 102 };
struct D3DBufferShim {
    std::vector<unsigned char> data;
    HRESULT Lock(UINT offset, UINT, void** out, DWORD) {
        *out = data.data() + offset;
        return 0;
    }
    HRESULT Unlock() { return 0; }
};
struct IDirect3DVertexBuffer9 : D3DBufferShim {};
struct IDirect3DIndexBuffer9 : D3DBufferShim {};
struct IDirect3DDevice9 {
    HRESULT CreateVertexBuffer(UINT length, DWORD, DWORD, D3DPOOL, IDirect3DVertexBuffer9** out,
                               HANDLE*) {
        *out = new IDirect3DVertexBuffer9;
        (*out)->data.assign(length, 0);
        return 0;
    }
    HRESULT CreateIndexBuffer(UINT length, DWORD, D3DFORMAT, D3DPOOL, IDirect3DIndexBuffer9** out,
                              HANDLE*) {
        *out = new IDirect3DIndexBuffer9;
        (*out)->data.assign(length, 0);
        return 0;
    }
};
