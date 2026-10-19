# 绘制 23：固定 UV 与固定高光的因果对照

保存的 x86 v2 场景在 `(583,255)` 的蓝通道为 DX9 **134**、DX11／DX12 **133**。本轮以该归档的三角形 5202 为输入，对 DX9／DX11 做定向交叉输入。结果将该字节差异定位到 **Toon UV 插值值不同，在各向异性采样中产生不同结果**。没有获得可普遍应用的插值修正规则，因此生产着色器和后端启用开关没有改变。

## 保持相同的输入

- 归档：`exports/cpu-live-summary-audit-x86/prefix.118344.2`。x86 与 x64 都读取这一份数据，以区别程序架构与场景输入差别。
- 两后端使用同一组原始纹理和完整 Mip 字节；DX9 自动 Mip 转为保存的显式层后，分别核对两 API 原始图像和 float 输出不变。
- 保存的 Toon 是 32×32、单层，Min／Mag 使用各向异性过滤，最大各向异性为 16；颜色空间保持线性。固定 UV 的控制必须同时固定导数，不能假设同一 UV 足以确定采样值。
- 使用运行时常量，未把数值拼入 HLSL 表达式。DX9 保留固定功能顶点路径和 `ps_2_a` 的 TEXCOORD 链接；零值运行时运算让常量坐标进入合法的采样临时寄存器。
- DX11 最终颜色沿用当前 measured 公式。每个查询先验证诊断 PS 与原始 DX9 固定功能／DX11 measured 路径在 float32 和 RGBA8 上一致。
- 两边清屏为透明零，只记录共同覆盖的邻近像素。RGBA8 直接从 UNORM 目标读取，不用 CPU 把浮点结果换算成字节。

## 焦点处的结果

测得的 U 坐标：

```text
DX9  0.95611560344696045
DX11 0.95611572265625000
```

位模式相差 **2 ULP**（绝对差 `1.1920928955078125e-7`）；两边 V 一致。每个控制重复三次：

| 控制 | DX9 蓝通道 | DX11 蓝通道 | 说明 |
| --- | ---: | ---: | --- |
| 原始输入 | 134 | 133 | 复现保存的失败 |
| 两边固定为 DX9 UV／导数 | 134 | 134 | UV 输入消除字节差异 |
| 两边固定为 DX11 UV／导数 | 133 | 133 | 换用另一 UV 会改变两边的结果 |
| 两边固定为 DX9 Toon 采样值 | 134 | 134 | 相同结论 |
| 两边固定为 DX11 Toon 采样值 | 133 | 133 | 相同结论 |
| 两边固定为 DX9 高光 | 134 | 133 | 高光差异不是这次字节差异的原因 |
| 两边固定为 DX11 高光 | 134 | 133 | 同上 |
| 固定全部颜色输入 | 完全一致 | 完全一致 | 包括 float32 输出 |

在 DX9 UV 下，两边的 Toon 采样均为 `0.9516441822052002`；在 DX11 UV 下，均为 `0.9512627124786377`。交换两边实测导数，结果不变；两边都使用零导数，则采样为 1。说明保存的过滤足迹参与结果，但这次差异由 U 坐标选择触发，并非“相同 UV／导数下两 API 滤波值不同”。这些观察没有确定 GPU 内部的插值系数或各向异性 tap 量化实现。

固定采样后，仍可看到高光导致约一个 ULP 的最终 float32 差异，但两边 RGBA8 相同。首个可观测的高光 varying 差异与导致蓝通道跨阈值的 UV 差异必须分开描述。

## 范围与证据

除了焦点，保存三角形查询 `(582,253)`、`(582,254)`，并记录各查询周围共同覆盖的 5×5 区域。独立三角形由新的位置、法线和恒等矩阵生成，保留相同材质、灯光、纹理；查询 `(24,32)`、`(22,30)`、`(23,30)`。独立几何还额外接收归档焦点的六组固定 UV／导数，以覆盖原来的敏感采样条件。

每架构完成 132 组控制、每组重复三次，共 396 次观测，`controls.csv` 包含 6822 行像素记录，每次都有 float32 和 RGBA8 输出。分析器检查重复稳定性、原始路径一致性、归档采样输入在独立几何上保持结果，并对两架构 CSV／汇总的 SHA-256 做完整比较，全部一致。焦点原始 RGBA 也与保存的应用失败记录一致。

最终证据位于 `exports/model23-causal-final-x86` 和 `exports/model23-causal-final-x64`；分析报告为前者的 `analysis.json`。它输出 `DIAGNOSTIC_EVIDENCE_VALID`、`crossArchitectureExact=true` 和 `imageAcceptance=false`；这不是全场景零像素验收。

两架构构建成功，相关 CTest 各 6/6 通过，覆盖 DX9 转换、Hardware／WARP 重放、最终颜色组合、DX11 着色输入和多材质切换。Python 分析器语法检查和归档回读成功。

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-causal exports/cpu-live-summary-audit-x86/prefix.118344.2 `
  exports/model23-causal-final-x86 583 255 5202

build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-causal exports/cpu-live-summary-audit-x86/prefix.118344.2 `
  exports/model23-causal-final-x64 583 255 5202

python tools/analyze_batch_causality.py `
  --input exports/model23-causal-final-x86 `
  --compare exports/model23-causal-final-x64 `
  --failure exports/cpu-live-summary-audit-x86/cpu_history_failure.118344.full_scene.23.dx11.pixels.csv `
  --output exports/model23-causal-final-x86/analysis.json
```

下一步只针对产生 TEXCOORD0 的顶点输出和插值过程做诊断，区分顶点坐标生成与光栅插值建立。现有证据不支持全局 UV 偏移、降低各向异性过滤或增加图像容差；也不要求改写已通过的颜色组合规则。取得可验证的通用规则后，才能在后端 measured 策略内接入，再重跑 DX11／DX12 完整历史和实时编辑流程。

后续隔离结果见 [Toon UV 生成与光栅插值](RHI_BATCH23_UV_ORIGIN.md)：相同顶点 UV／裁剪坐标的光栅结果一致，差异位于自动生成 Toon 坐标的路径。
