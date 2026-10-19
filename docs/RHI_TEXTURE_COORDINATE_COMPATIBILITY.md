# 法线纹理坐标的受控兼容策略

`ModelOptions::diagnosticTextureFma` 默认关闭，且仅允许与 `ModelCompatibility::Dx9Measured` 一起使用；其余组合在设备创建时以 `diagnostic_texture_requires_dx9_measured` 拒绝。DX11 和 DX12 在共享的 `model_material_vertex.hlsl` 中使用同一规则，后端只负责能力检查、编译和执行。

## 运算与边界

对 `CameraNormal` 坐标，将 `(nx,ny,nz,1)` 与纹理矩阵的 U/V 列分别点乘。按 X、Y、Z、平移项的顺序，每一步使用已有 `Dx9FusedStep`，将乘积加 float32 累加器后再舍入到 float32。当前通过 shader double 实现，依赖已有的 `Dx9Measured` double 能力要求。没有基于像素位置、材质号或归档数值的分支。

规则只改变法线纹理坐标生成。法线变换、归一化、灯光、高光、纹理滤波、CPU 场景输入、网格 UV 和默认着色路径保持各自职责。Alpha 的 `diagnosticAlpha12` 是另一个独立开关。这里的测量结论限于所测适配器和输入，不能作为所有 DX9 驱动的普遍算术保证。

应用诊断入口为 `MDS_RHI_DIAGNOSTIC_TEXTURE_FMA=1`，驱动工具参数为 `--texture-fma`。进程内冻结的 `ModelOptions` 传给子集、完整场景和替换设备。设备创建、生命周期、逐绘制日志均记录实际配置，Python 验收检查配置与请求一致。默认应用继续由 DX9 呈现。

## 独立验证

`rhi_texture_fma_scope_hardware` 无需 PMM 或外部模型：程序生成三角形、法线、三层小纹理和四份纹理矩阵。48 组控制覆盖两个法线集合、归一化开关、正负系数、平移项和三个纹理阶段。末份矩阵和第二组法线作为独立验证输入，不用测量数据调整系数。

每组重复三次，实际读取 float32 目标中的 UV，以及固定功能／共享 measured 像素公式的 RGBA8 目标；同时核查原路径一致的像素没有退化。诊断 PS 保留完整的 VS 输出顺序，避免精简输入声明改变原生寄存器链接。最终 x64/x86 各 144 次观测：原路径 90 次存在浮点差异，候选浮点／RGBA8 失败为 0，退化为 0。

```powershell
ctest --test-dir build-x64/build -C Release -R '^rhi_texture_fma_scope_hardware$' --output-on-failure
ctest --test-dir build-x86/build -C Release -R '^rhi_texture_fma_scope_hardware$' --output-on-failure
```

CSV 与摘要分别位于两个构建目录的 `texture-fma-evidence/`。

## 保存的完整历史

`--texture-history-diagnostic` 重放现有场景归档，在候选组启用 Alpha12 与纹理坐标规则；对照组保持两者关闭。先验证 DX9 原生重放，再用同一资源版本、状态和顺序逐边界运行 DX11/DX12。不能以原生不可用替代原生验收。

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --texture-history-diagnostic exports/cpu-live-summary-audit-x86/prefix.118344.2 `
  exports/texture-fma-history-x86
```

x64 使用相同归档与对应二进制。两种架构均通过：57 次绘制、157 份资源、44 次纹理上传；各 304 条观测含原生／基线／候选边界、重复提交和目标缩放。原生失败 0，候选失败 0，DX12 调试层错误 0。关闭两个开关的基线有 76 个不一致边界，不能据此把所有改善单独归因于纹理规则；独立测试及先前固定 Alpha 的 UV 因果对照才用于判定该规则。

证据：`exports/texture-fma-history-x64/`、`exports/texture-fma-history-x86/`。硬件适配器为 NVIDIA TITAN Xp，单采样。

## 实时验收

使用 [应用内诊断流程](RHI_LIVE_CPU_SCENE_DIAGNOSTICS.md) 的完整命令并增加 `--texture-fma`，输出到新目录。九个检查点必须同时验证真实播放状态、PMM 版本、CPU 字段、资源版本、逐绘制零差异，以及重复提交、缩放和设备替换；还需完成 Save As 和回读。保存的历史通过不能替代这项验收。

2026-10-12 实测：

- `exports/texture-fma-live-audit-x64/run.json`：PASS。v1/v2 九个检查点、1145 条完整场景图像／生命周期记录、3080 项材质输入检查、616 次模型提交、44 项生命周期检查通过；图像零差异，资源账本和 Mip 一致，原始 PMM 哈希未改变。
- `exports/texture-fma-live-audit-x86/run.json`：FAIL。v1 第 5 帧第 23 次绘制，`(509,407)` 原生 `(30,109,162,255)`、DX11/DX12 `(30,108,162,255)`；尚未完成后续播放和 v2 回读验收。CPU 字段、资源、策略和已执行的生命周期检查通过。不能开启正式路径或宣称 x86 全场景零差异。

## 剩余异常的因果隔离

`--model-batch23-isolation-texture` 在保持候选开启时，将新归档缩减到三角形 1362，索引 `8049,8064,7452`。原生归档、三次重复、压缩前后几何以及冻结 Mip 均一致。关闭高光、移除基础纹理或改为点采样时字节差异消失；这些控制改变了着色输入，只能用于诊断。

`--model-batch23-stages-texture` 进一步测得：异常点的漫反射、Toon/Base UV 和采样值均相同；高光绿分量为 DX9 `0.030430374667048454`、DX11 `0.030430367216467857`。正式 measured PS 在 float32 目标的最终绿分量为 `0.425537109375` 与 `0.42553707957267761`（1 ULP）；实际 RGBA8 目标输出 109 与 108。不能把浮点读回在 CPU 上乘 255 的结果当成实际 UNORM 目标读回。

`--model-batch23-spec-causal` 用运行时常量互换采样与高光，保留两侧原始顶点路径。保存三角形和独立几何各七组控制、每组三次，共 42 次控制／672 条像素记录。原生与候选的显式 PS 均通过原输出的字节及 float 门禁。保存三角形的异常点：

| 控制 | DX9 绿通道 | DX11 绿通道 |
|---|---:|---:|
| 原路径 | 109 | 108 |
| 同用 DX9 采样值 | 109 | 108 |
| 同用 DX11 采样值 | 109 | 108 |
| 同用 DX9 高光值 | 109 | 109 |
| 同用 DX11 高光值 | 108 | 108 |

因此新阻断由高光输入的差异触发，不需要更改已验证的 UV 规则或以相反的最终舍入误差抵消它。后续 [高光顶点生成与插值对照](RHI_SPECULAR_VERTEX_ORIGIN.md) 已通过两侧原图重现门禁：相同高光顶点输入的插值完全一致，差异收敛到局部视线参与的顶点高光强度计算。尚未确定具体舍入指令，也未新增推测性的高光修复或颜色量化规则。

证据目录：`exports/texture-fma-live23-isolation-x86/`、`exports/texture-fma-live23-stages-production-x86/`、`exports/texture-fma-live23-spec-causal-x86/`。

回归：x64/x86 各 17/17 CTest 通过，覆盖硬件／WARP 的常驻资源、DX12 调试层、DX11 生命周期与多材质、DX9 转换、法线及新纹理坐标控制、`SceneRenderer` 和实时证据门禁。日志为 `exports/texture-fma-regression-x64.log` / `texture-fma-regression-x86.log`；另通过 Python 编译检查、4 项实时证据负例测试及 `git diff --check`。这些回归通过不改变上述 x86 实时验收 FAIL。

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-spec-causal exports/texture-fma-live-audit-x86/prefix.131316.3 `
  exports/texture-fma-spec-example 509 407 1362
```
