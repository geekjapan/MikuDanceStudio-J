#pragma once
// A probe hook on mme::DrawIndexedPrimitive (mme_bridge.cpp), the draw every
// model body and edge submits. Only --mds-ground-probe (src/tools/trace_mode.cpp)
// sets it; the hook reads device state and does not change the draw.
#include <d3d9.h>

namespace mikudancestudio::mme {
using DrawObserver = void (*)(IDirect3DDevice9* device, unsigned int start_index,
                              unsigned int primitive_count);

// nullptr removes the observer.
void SetDrawObserver(DrawObserver observer);
} // namespace mikudancestudio::mme
