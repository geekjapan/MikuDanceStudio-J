# 绘制 23 的插值、像素中心与采样探针

这份记录只描述诊断探针，不改变生产着色器、图像验收阈值或适配器开关。探针从已保存的 DX9 前序重放数据构造一个三角形，重复每个阶段三次，并把焦点像素和视口内统计写入 CSV。

## x86 真实场景异常

输入是 `exports/cpu-live-summary-audit-x86/prefix.118344.2`，保存的失败点是 `(583,255)`，绘制 23 的三角形 5202。原始完整场景的失败记录为：

```text
DX9    (16,89,134,255)
候选    (16,89,133,255)
```

`exports/model23-stages-x86-anomaly3/analysis.json` 通过了独立分析器。阶段结果在三次重复中稳定：

| 阶段 | 结果 |
| --- | --- |
| 漫反射 varying | 完全一致 |
| 高光 varying | 首个可观测差异，焦点处为 float32 级差异 |
| Toon 坐标 0 | U 的位模式相差 2 个 float32 ULP；V 一致 |
| Toon 坐标 1 | 完全一致 |
| Toon 第一级采样 | 候选值与 DX9 不同，焦点差值约 `0.0003814697` |
| 第二级纹理采样 | 完全一致 |
| 最终颜色 | 延续上述差异；不能归因于第二级纹理 |

探针同时逐个三角形缩减，只有三角形 5202 保留该像素差异；关闭混合、Alpha test、深度、灯光或高光会改变诊断输入，因此这些开关只能说明差异位于该批次的组合路径，不能作为生产修复。

## 像素中心控制

`pixel_center.csv` 对 DX11 诊断视口分别使用 `(x+0.5,y+0.5)` 和整数 `(x,y)` 原点，DX9 侧保持保存的视口。半像素偏移时焦点仍有覆盖；整数原点时焦点 Alpha 为零。这个控制证明半像素位置是覆盖契约的一部分，不能为了拟合颜色而删除；它没有定位上述颜色通道的根因。

CSV 同时记录 `knownDifferentPixels`（仅视口范围）和 `focusDifferent`。`differentPixels` 是整张目标缓冲的诊断统计，包含视口外清屏差异，不用于图像验收。

## 采样控制

`sampling_precision.csv` 比较保存的采样状态、Point、Linear+Mip Point 和 Linear+Mip Linear。Point 会改变焦点采样值，说明滤波状态确实参与结果；保存状态与候选 DX11 采样仍不同，而第二级纹理采样保持一致。因此当前证据不足以把问题归因于 Mip 生成或第二级纹理资源，生产路径继续保留原生插值和采样行为。

## x64 对照

输入是 `exports/model23-owned-capture-x64/prefix.19376`，焦点 `(867,486)`，三角形 1383。`exports/model23-stages-x64-rerun2/stages.csv` 三次稳定：漫反射、高光、两级采样和加高光前颜色完全一致；最终绿色通道为：

```text
DX9  0.37451168894767761
DX11 0.37451171875
```

这里的 DX11 最终阶段使用通用的分离乘法、加法表达式，是历史舍入控制，并非当前 measured 后端的完整表达式。融合诊断表达式可以重现 DX9 的 float 值；它不是驱动指令捕获。当前 measured 策略的后续验收见 [最终纹理组合兼容规则](RHI_FINAL_MODULATE_COMPATIBILITY.md)。x86 与 x64 的这些结果来自不同保存输入，不能互相外推。

## 重跑入口

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-stages exports/cpu-live-summary-audit-x86/prefix.118344.2 `
  exports/model23-stages-x86-anomaly3 583 255 5202

python tools/analyze_saved_batch_precision.py `
  --stages exports/model23-stages-x86-anomaly3 `
  --failure exports/cpu-live-summary-audit-x86/cpu_history_failure.118344.full_scene.23.dx11.pixels.csv `
  --output exports/model23-stages-x86-anomaly3/analysis.json
```

探针输出带有 `productionActivation=0 imageAcceptance=0`，因此它只能用于定位和回归诊断；在真实场景历史达到零像素对照前，不开放 DX11/DX12 替换路径。

后续 [固定 UV 与固定高光的因果对照](RHI_BATCH23_CAUSALITY.md) 使用当前 measured 最终颜色公式，并交叉传入相同的 UV／导数／采样值／高光，区分“首先看到差异”和“导致字节差异的原因”。
