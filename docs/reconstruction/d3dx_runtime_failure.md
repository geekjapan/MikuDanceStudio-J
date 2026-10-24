# D3D9 / D3DX 运行时失败调查

调查日期：2026-10-24。旧文档的中文正文已损坏为问号；本说明根据保留的错误码、测试源码和本次会话结果重新整理，不恢复无法核实的原句。

已确认部分失败发生在原生 D3D9 设备创建阶段，不能统称为 D3DX 网格 ABI 错误。2026-10-23 的旧日志没有保存 HRESULT，无法将其中所有失败认定为同一个原因。

## 测试内容

[mme_regression.cpp](../../tests/mme_regression.cpp) 的 `TestRuntimeMeshAbi` 加载真实 Microsoft 运行库：x86 使用 `d3dx9_32.dll`，x64 使用 `d3dx9_43.dll`。测试创建 NULLREF 设备，调用真实 effect 接口，并以 129 个面、387 个顶点、选项 `0x220` 和 FVF `0x112` 创建网格，检查顶点大小及属性表。

NULLREF 不需要可见绘制，但仍需要可工作的 D3D9 设备与资源分配。该测试不依赖 Bullet；一次失败不直接证明物理、COM 镜像布局或效果引擎有误。

## 观察结果

| 阶段 | 结果 | 可以得出的结论 |
|---|---|---|
| 10 月 23 日旧测试 | 网格创建断言失败，未记录 HRESULT | 只能确认该次调用未成功，无法据此定位失败原因 |
| 10 月 24 日一次完整 x64 测试 | 45/45 通过 | 当时的运行库、设备和接口组合可以完成测试 |
| 随后出现的设备不可用状态 | 独立 Windows SDK 探针在不调用 D3DX 的情况下也失败 | 至少该阶段存在原生 D3D9 环境问题 |
| 原版复核修正后的完整测试 | x64 48/48、x86 47/47 通过，包含 GPU 和 D3DX 测试 | 当前会话测试正常，不证明历史间歇失败已永久消失 |

设备不可用阶段记录的错误码：

```text
IDirect3D9::GetDeviceCaps(HAL)     = 0x8876086A D3DERR_NOTAVAILABLE
IDirect3D9::GetDeviceCaps(NULLREF) = 0x8876086A D3DERR_NOTAVAILABLE
IDirect3D9::CreateDevice(NULLREF)  = 0x8876086C D3DERR_INVALIDCALL
IDirect3D9::CreateDevice(HAL)      = 0x8876086A D3DERR_NOTAVAILABLE
```

同一环境能列出 NVIDIA TITAN Xp 适配器，D3D12 WARP 也曾成功；这不等于原生 D3D9 的能力查询和设备创建可用。改变窗口大小、呈现参数和 DPI 设置未恢复当时的 D3D9 状态。

## RDP 关系

历史失败时间处于 session 2 的 RDP 断开区间内，因此远程会话切换是相关线索。之后在 WTS 显示 active/unlocked、桌面为 Default 时仍观察到 D3D9 不可用，故尚不能认定 RDP 断开是唯一根因，也不能排除会话恢复或驱动状态的影响。

## 再次失败时的定位方法

运行 `ctest -C Release -R '^mme_d3dx_runtime$' --output-on-failure`，使用实际构建目录。测试的 `CheckRuntimeResult` 会记录失败操作、HRESULT、运行库路径与版本、远程会话状态、HAL/NULLREF 能力查询，以及已有设备的 `TestCooperativeLevel`。

先区分运行库加载、设备创建、effect 和网格创建失败，再比较两架构及旧版结果。设备创建尚未成功时，应先调查原生 D3D9；已创建设备后的接口失败，才进一步核查相应 D3DX 调用。原始探针与会话日志属于本地 `out/d3dx-investigation/` 调查产物，不作为仓库可复现测试入口。
