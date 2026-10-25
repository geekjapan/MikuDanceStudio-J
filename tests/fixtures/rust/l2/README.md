# L2 reference traces

Written on the Windows host `nanoha-lan` (i9-12900K, MSVC 19.44) by the x64
Release app built at `3d53dcd` with `tools/windows/build.ps1`. Each trace
came from

    MikuDanceStudio.exe --mds-trace tests\fixtures\rust\<name>.pmm <out> 600

with the fixture models staged next to the exe (`tools/windows/stage.ps1`).
The format is defined in `src/tools/trace_l2.hpp`. Two runs of each input
gave the same bytes.

| File | Input | sha256 |
|---|---|---|
| `swing600-600.trace` | `../swing600.pmm`, physics mode 2 | `9546bb7fab08847a0952319d36d8d5f52dbe709e6f4801052fd8d13bf6198189` |
| `swing600-nophys-600.trace` | `../swing600-nophys.pmm`, physics mode 0 | `43f154ebcc6aecdb9ccc4f7b96ac7246f3c885fa9fcfff8eeea8370320acc221` |

The physics-off trace gates the pose pipeline (hierarchy, IK, append, morphs)
without Bullet. The physics-on trace adds the rigid bodies.
