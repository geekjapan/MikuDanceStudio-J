# Toon 矩阵点积的 Z 项乘加舍入

承接 [UV 生成／插值隔离](RHI_BATCH23_UV_ORIGIN.md)。对保存的绘制 23、三角形 5202，本轮将差异进一步定位到 **Toon 纹理矩阵点积累加 Z 项时，乘法与加法之间是否提前舍入**。诊断候选只改变该点积的舍入，恢复了独立三角形的全部 UV 浮点结果和 RGBA8 图像。生产着色器、后端选择和全场景准入均未改变。

## 三段分别观测

归档：`exports/cpu-live-summary-audit-x86/prefix.118344.2`；焦点 `(583,255)`。保存的 `D3DRS_NORMALIZENORMALS=0`，原始场景没有执行归一化。开启归一化只作为附加控制。

DX9 保留固定功能顶点路径，用单位／分量置换的纹理矩阵分别输出变换后法线的 XY、Z，再开启归一化做相同观测。DX11 使用相同输入和当前 measured 法线／矩阵常量规则，读取同一光栅区域，同时通过 stream output 记录顶点值。DX9 的这些值是 PS 阶段观测，没有称为原生顶点寄存器捕获。

| 阶段或控制 | 保存三角形两 API 的 float32 差异像素 |
| --- | ---: |
| 法线变换后 XY | 0 |
| 法线变换后 Z | 0 |
| 开启归一化后的 XY | 0 |
| 开启归一化后的 Z | 0 |
| 原始 Toon 矩阵 | 15 |
| 开启归一化，再套用原始 Toon 矩阵 | 20 |
| 原始法线，诊断乘加舍入候选 | **0** |
| 归一化法线，诊断乘加舍入候选 | **0** |

新位置、法线和恒等世界／视图／投影矩阵的独立三角形也通过相同控制：原始未归一化路径已一致；开启归一化后，原矩阵公式存在 425 个 UV 浮点差异，候选恢复为 0。归一化本身的分量观测始终一致。

## 具体运算位置

对每列执行点积 `nx*m0 + ny*m1 + nz*m2 + m3`。当前通用 `Coordinate()` 的 DX11 字节码将乘法和加法分开，候选借用现有测试过的 `Dx9Dot4()`：

```text
分离：acc = float32(acc + float32(nz * m2))
候选：acc = float32(exact(nz * m2 + acc))
```

候选对每个累加步骤只转换一次 float32，用 float64 乘积和加法表达；这与当前 measured 法线／裁剪坐标已有的舍入表达一致。CPU 分析使用保存的法线 SO 值、原纹理矩阵和精确有理数运算，验证每一步；没有拟合系数、偏移或容差。

会影响最终顶点 UV 的两处差异：

| 位置 | 分离乘加 | 诊断融合候选 |
| --- | ---: | ---: |
| 顶点 1，V，Z 项累加后 | -0.06057526171207428 | -0.06057526543736458 |
| 顶点 1，V，加平移后 | 0.43942475318908691 | 0.43942472338676453 |
| 顶点 2，U，Z 项累加后 | 0.44880887866020200 | 0.44880884885787964 |
| 顶点 2，U，加平移后 | 0.94880890846252441 | 0.94880884885787964 |

两处最终 UV 各差 1 ULP；原来的逐像素 U 差异为 2 ULP。顶点 0 的 U 在 Z 项累加时也发生分叉，但加平移后舍入回同一值，因此不能仅按某个中间值不同就判断最终图像必然不同。

分析器的 24 个逐分量预测（两种几何、归一化开／关、三个顶点、UV 两分量）分别匹配通用表达式和融合候选的 GPU SO。DX11 反汇编保留了基线的 `mul/add`、候选的 `dmul/dadd/dtof`。没有捕获 DX9 驱动生成的固定功能指令；结论是原生观察符合这个舍入候选，而不是宣称读取到原生 FMA 指令。

## 最终图像与范围

候选仅用于诊断 VS，最终 PS 使用当前 measured 颜色组合公式。原始三角形是 1 个像素、蓝通道差 1；候选的完整视口 RGBA8 图像与 DX9 完全一致：

```text
原始：DX9 (16,89,134,255)   DX11 (16,89,133,255)
候选：DX9 (16,89,134,255)   DX11 (16,89,134,255)
```

仅开启归一化也会令这个字节差异消失，但其 UV 仍有 20 个浮点差异，而且改变场景状态，所以不作为修复。分离乘加的显式表达式则保留原来的 15 个 UV／1 个 RGBA8 差异，构成反向控制。

x86／x64 都读取同一归档。每架构完成 18 组阶段控制、每组三次，共 54 次阶段观测；另外有 10 组最终 RGBA8 控制、每组三次。完整浮点／RGBA8 图像、CSV、顶点 SO 值及诊断源码／反汇编跨架构逐字节一致。报告位于：

- `exports/model23-toon-final-x86/analysis.json`
- `exports/model23-toon-final-x64/analysis.json`

相关 CTest 回归在 x86、x64 各通过 5/5：`rhi_d3d9_replay_conversion`、`rhi_normal_precision_hardware`、`rhi_normal_transforms_hardware`、`rhi_d3d9_replay_conversion_warp` 和 `rhi_d3d9_replay_conversion_hardware`。这些回归验证现有转换、法线与硬件／WARP 路径；新增的归档诊断通过上述命令单独执行，不把诊断证据通过标记等同于完整场景准入。

## 重跑

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-toon-rounding exports/cpu-live-summary-audit-x86/prefix.118344.2 `
  exports/model23-toon-final-x86 583 255 5202

build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-toon-rounding exports/cpu-live-summary-audit-x86/prefix.118344.2 `
  exports/model23-toon-final-x64 583 255 5202

python tools/analyze_toon_rounding.py `
  --input exports/model23-toon-final-x86 --compare exports/model23-toon-final-x64 `
  --archive exports/cpu-live-summary-audit-x86/prefix.118344.2 `
  --output exports/model23-toon-final-x86/analysis.json
```

以上记录原始定位阶段，范围限于 DX9／DX11 的两个独立三角形。后续的独立输入验证、默认关闭的 DX11／DX12 共用规则及完整历史验收见 [法线纹理坐标兼容策略](RHI_TEXTURE_COORDINATE_COMPATIBILITY.md)。
