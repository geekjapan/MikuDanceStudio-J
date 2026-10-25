// The one D3DRenderer field the loaders read.
#pragma once
#include <d3d9.h>
namespace mikudancestudio {
class D3DRenderer {
public:
    IDirect3DDevice9* device;
};
} // namespace mikudancestudio
