# 高光兼容策略与共用常量准备

`ModelOptions::diagnosticSpecularFma` 默认关闭，且只允许用于 `Dx9Measured`。DX11、DX12 共用同一 HLSL 实现；CPU 场景生产者、材质契约及默认 DX9 渲染路径无需改变。它实现此前独立用例验证过的候选运算，不能据此推断所有显卡均具有相同的固定功能行为。

## 职责与数据流

- `MaterialShaderInputs` 保留独立的 world、view、projection 矩阵。
- `detail::BuildModelConstants` 使用明确的 float32 乘法、顺序加法准备 world×view，并由它准备组合裁剪矩阵与法线矩阵。两个后端共用此函数。
- `ModelCompatibilityConstants` 对应 HLSL b1：前 64 字节为组合裁剪矩阵，后 64 字节为 world×view。语义场景数据与后端兼容传输布局分开；b0 布局保持不变。
- 开关打开时，高光视线的相机坐标使用预备矩阵及逐步融合的四项点积；局部视线的乘倒长度与灯光相加采用一次融合舍入。固定视线、漫反射、幂函数和光栅插值继续使用原公式。关闭时使用原高光路径。
- 原生设备查询会报告所选策略；非 measured 请求明确返回 `diagnostic_specular_requires_dx9_measured`。设备替换重新使用同一 `ModelOptions`，不改变策略。

## 验收入口

`rhi_specular_scope_hardware` 的候选改为使用正式共享着色器及 CPU 准备的 b1，不再在测试着色器内重新组合矩阵。保留 160 组输入、每组三次，检查 float32 顶点高光、全视口重现、退化和固定视线不变；x64/x86 可用 `tools/analyze_specular_scope.py` 比较。

`rhi_model_inputs_test` 使用存在抵消的矩阵检查共同准备层：顺序 float32 得到 0，而高精度累加得到 1；同时检查原始场景矩阵没有改变。

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe --specular-history-diagnostic <归档目录> <新证据目录>
```

真实归档模式先逐边界重现保存的 DX9 图像，然后比较两后端。两组均保留 Alpha12 和纹理 FMA，只切换高光策略；包括第 23 个材质批次单独绘制、完整前序历史、三次重复、三次目标缩放、设备替换与旧提交拒绝。资源重用和恢复计数也必须通过，DX12 debug 错误数必须为零。

应用诊断入口增加 `MDS_RHI_DIAGNOSTIC_SPECULAR_FMA=1`，运行脚本对应 `--specular-fma`。设备、生命周期和逐绘制 CSV 以及 `run.json` 均记录此项；审计身份包含此项，旧审计不能授权不同策略的 direct 输入模式。未传开关时关闭。

## 验收记录

2026-10-12，NVIDIA TITAN Xp，单采样。

- x64/x86 应用、GUI 驱动及相关测试构建通过。迁移后的独立用例各 160 组、480 次，候选顶点及 float32 图像零差异、零退化、重现门禁通过。固定视线 80 组不变；跨架构七份 CSV／HLSL／反汇编证据逐字节一致。见 `exports/specular-policy-scope-analysis.json`。
- 两种架构相关 CTest 各 8/8 通过，包括共用常量的抵消矩阵控制、命令流、实时证据校验、默认 WARP 生命周期，以及新增的 `rhi_specular_policy_dx11_warp`／`rhi_specular_policy_dx12_warp`。新增测试在正式适配器上启用策略，覆盖重复提交、1000 次几何版本更新、缩放、设备替换及 DX12 移除恢复；恢复前后图像一致。
- 真实归档 `exports/texture-fma-live-audit-x86/prefix.131316.3` 在 x86 的 `exports/specular-policy-history-x86c` 和 x64 的 `exports/specular-policy-history-x64` 各完成 311 次比较。58 个 DX9 清屏／前序边界及独立材质重现通过。两个后端候选均为零差异，包含独立材质、57 次绘制、重复提交、缩放、设备替换；DX12 debug 错误为 0。关闭高光策略时，两后端均重现 `(509,407)` 绿通道 109／108 的原误差，每个架构累计 78 个失败观测，支持本次改变与原问题的因果对应。两架构的图像哈希、差异和资源计数一致，见 `exports/specular-policy-history-analysis.json`。

早期尝试曾因 RDP 断开出现 `0x8876086C`，不计为通过。另已修正新增替换测试：使用独立窗口创建第二条 DX12 flip 交换链，避免旧链仍占用同一 HWND；这属于测试构造问题，没有修改后端交换链契约。

归档通过与九阶段实时流程分别判定；本次两项均在 x64/x86 通过。兼容策略仍默认关闭，实际应用继续由 DX9 呈现。

## 实时输入发布修正

第一次 x86 实时审计 `exports/specular-policy-live-audit-x86` 的前七个阶段通过，v2 播放在 CPU 字段对照处阻断。`light0.specular` 的红／绿两项分别为：

| 分量 | CPU 生成 | 实际 DX9 |
|---|---:|---:|
| 红 | 0.0076678097248077393 | 0.0076678241603076458 |
| 绿 | 0.084635406732559204 | 0.084635414183139801 |

原因是 x86 的旧布局将 `LightColor` 与 `SceneLight().Ambient` 重叠。饰品绘制对 Ambient 减／加 0.3 后，`LightColor` 已产生舍入差；`SceneLight().Specular` 保留原来已应用的颜色。`StartPortableScenePlayback` 之前将这个调整后的 Ambient 镜像发布为会话的规范灯光 RGB，使随后生成的高光输入错误。

修正仅将播放启动时发布的 RGB 改为 CPU 中已应用的 `SceneLight().Specular`。没有读取 GPU 状态，也没有改变旧灯光字段、饰品绘制、场景着色公式或比较阈值。已有 `ApplyTimelineLightState` 的发布仍负责实际灯光关键帧更新。

`pmm_scene_timeline_bridge_test` 新增减／加 0.3 的控制：要求会话保留规范 Specular RGB、旧 Ambient 和标量镜像不被发布操作修改。真实单模型 v2 `test_1.pmm` 在 x64/x86 均通过，日志为 `exports/specular-policy-light-bridge-x64.log`／`specular-policy-light-bridge-x86.log`。

## 最终实时验收

修正后的应用已在 x64/x86 重跑相同的九阶段流程，两组均 `status=PASS`：

| 证据 | x86 | x64 |
|---|---:|---:|
| v1/v2 实时检查点 | 9 | 9 |
| 逐边界图像／生命周期报告行 | 1145 | 1145 |
| 当帧前序绘制数量 | 57／80 | 57／80 |
| CPU 字段审计条目 | 3990 | 3230 |
| 设备策略检查／生命周期检查 | 44／44 | 44／44 |
| 资源版本账本 | 9 | 9 |

两种架构均完成缺失模型重选、v1 编辑与跳帧／播放、Save As、v2 回读与编辑／跳帧／播放／停止。DX11/DX12 对照均零像素差异，字段、顺序、冻结 Mip、资源版本、目标缩放及设备替换全部通过；原始 PMM 哈希保持不变。报告分别为 `exports/specular-policy-live-audit-x86b/run.json` 和 `exports/specular-policy-live-audit-x64/run.json`。CPU 字段条目数量随绘制时序变化，九阶段和逐边界覆盖分别由严格门禁核查。

```powershell
python tools/run_cpu_geometry_diagnostic.py `
  --gui build-x86/build/Release/pmm_v1_relocation_gui_test.exe `
  --application build-x86/build/Release/MikuDanceStudio.exe `
  --fixture C:/Users/jstzw/Downloads/MikuMikuDanceE_v932/UserFile/sample.pmm `
  --output exports/specular-policy-live-example-x86 `
  --preview --materials 12,13,14,15,16 --play --lifecycle --inputs audit `
  --history --history-export --ground --projected-shadows `
  --cpu-prefix full-scene --mip-prepare dx9 --alpha12 --texture-fma --specular-fma `
  --live-history --screen-source empty-background
```

验收范围为单采样、无 MME，使用显式的临时空背景屏幕来源；比较的是初始化的场景视口，不包含后续 HUD 合成。动态屏幕纹理、MSAA、自阴影合成、持续跨帧常驻预览及其他显卡仍需独立验收。本次未开启默认兼容开关或独立呈现窗口。
