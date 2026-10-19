# 绘制 23：Toon UV 生成与光栅插值的隔离

承接 [固定 UV／高光因果对照](RHI_BATCH23_CAUSALITY.md)。保存的三角形 5202 在 `(583,255)` 的 Toon U 相差 2 个 float32 ULP。本轮将差异定位到 **自动生成 Toon 顶点坐标的路径**；对这一输入，相同裁剪坐标和 UV 的 DX9／DX11 光栅插值完全一致。还未区分法线变换、归一化与纹理矩阵运算，生产着色器保持不变。

## 测量边界

DX11 使用正式 measured VS、常量生成器和编译规则，通过 stream output 读取三个顶点的裁剪坐标和 TEXCOORD0。DX9 固定功能没有等价的实际绘制输出接口，本轮没有把 `ProcessVertices`、CPU 公式或 PS 像素值称为原生顶点寄存器捕获。

DX9 侧的证据来自交叉输入：把 DX11 的 UV 放入原网格顶点的 UV 字段，关闭该级自动法线坐标生成和纹理变换，保留原来的位置、法线、世界／视图／投影矩阵和视口。这样只绕过 Toon 坐标生成，位置变换仍走 DX9 固定功能。

第二个控制将同一组 DX11 裁剪坐标和 UV 提交给两 API 的透传 VS，分别验证 PS2 与 PS3 链接。第三个控制把三角形的所有法线设为某一个原顶点的法线，再比较自动生成 UV 与写入同一 UV 的网格路径。所有结果比较完整已初始化视口，并另存焦点周围 5×5 的 CSV。

## 保存三角形的结果

输入：`exports/cpu-live-summary-audit-x86/prefix.118344.2`，视口 `(274,25,670,503)`。此三角形覆盖 32 个像素，每项重复三次。

| 控制 | 两 API 的 UV 浮点差异像素 | 相对原始 DX11 图像 |
| --- | ---: | --- |
| 原始自动坐标生成 | 15 | 基线 |
| 写入 DX11 顶点 UV，保留原位置变换 | **0** | 两边都完全等于原始 DX11 |
| 相同裁剪坐标／UV，PS2 链接 | **0** | 两边都完全等于原始 DX11 |
| 相同裁剪坐标／UV，PS3 链接 | **0** | 两边都完全等于原始 DX11 |

焦点处的变化：

```text
原始 DX9   U = 0.95611560344696045
原始 DX11  U = 0.95611572265625000
写入相同 UV 后两边 U = 0.95611572265625000
V 在三者中均为 0.45262208580970764
```

写入相同 UV 后，DX9 的位置变换仍未改变，15 个差异却全部消失。进一步使用相同裁剪坐标重放，也不改变 DX11 的任何视口内像素。这组结果排除了该输入上“即使顶点输入相同，两个光栅器仍产生这 2 ULP 差异”的解释。

逐顶点恒定法线的控制：

| 所用原顶点法线 | DX9 自动生成 vs DX9 写入 UV 的差异像素 | DX11 自动生成 vs DX11 写入 UV |
| --- | ---: | ---: |
| 顶点 0 | 0 | 0 |
| 顶点 1 | 32 | 0 |
| 顶点 2 | 17 | 0 |

写入同一恒定 UV 后，两 API 完全一致；相同裁剪坐标下的恒定 UV 重放也完全一致。因此不能用“恒定平面仍有插值误差”解释这里的原生自动生成差异。

## 独立几何与架构复验

独立三角形使用新位置、法线和恒等世界／视图／投影矩阵，保留相同纹理坐标变换。它覆盖 1416 个像素，原始 UV、网格 UV、共享裁剪坐标以及全部恒定法线控制都在两 API 间一致。这说明本轮归档中的非平凡变换输入会暴露生成精度差异，而不是所有几何都需要相同修正。

x86 与 x64 都消费同一份归档。每架构完成 **26 组控制、每组重复三次，共 78 次观测**，保存完整视口浮点图像、SO 顶点数据和 CSV。分析器逐字节验证全部重复，比较两架构所有图像／CSV 的 SHA-256。结果保存在：

- `exports/model23-uv-origin-x86b/analysis.json`
- `exports/model23-uv-origin-x64/analysis.json`

两架构构建成功；DX9 转换及 Hardware／WARP 重放 CTest 各 3/3 通过，无跳过项。分析器语法检查和两向架构比较均通过。

报告标记 `dx11PreRasterSO=true`、`dx9NativePreRasterCapture=false`、`imageAcceptance=false`。这只是差异来源的诊断证据，未重新开放全场景图像准入。

## 重跑

每次使用新的输出目录：

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-uv-origin exports/cpu-live-summary-audit-x86/prefix.118344.2 `
  exports/model23-uv-origin-x86b 583 255 5202

build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-uv-origin exports/cpu-live-summary-audit-x86/prefix.118344.2 `
  exports/model23-uv-origin-x64 583 255 5202

python tools/analyze_batch_uv_origin.py `
  --input exports/model23-uv-origin-x86b --compare exports/model23-uv-origin-x64 `
  --output exports/model23-uv-origin-x86b/analysis.json
```

下一步对自动生成路径拆成法线矩阵、归一化、Toon 纹理矩阵三段，用相同中间输入分别比较。尤其要检查 `Coordinate()` 中纹理矩阵点积的乘加舍入；当前结果尚不足以直接认定某一种点积规则，也不支持给全部 UV 加固定偏移。

后续三段隔离结果见 [Toon 矩阵点积的 Z 项乘加舍入](RHI_TOON_MATRIX_ROUNDING.md)：法线和归一化阶段观测一致，纹理矩阵的融合舍入候选恢复独立三角形的 UV 与 RGBA8。
