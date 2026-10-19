# 饰品 Alpha 采样与比较前量化

2026-10-07，使用第 65 次绘制的真实 x64 捕获数据，单采样，硬件 DX9／DX11。
本轮只新增诊断工具和报告，没有修改生产着色器、深度状态或渲染选择。

## 当前实测结论

后续恢复设备后的完整扫描见本页“设备恢复后的完整扫描”节。
首轮和失败尝试的证据保留在原目录；后续结果不覆盖它们。

四个异常坐标与两个验证点的 UV、UV 导数、纹理采样 Alpha 和材质乘法结果，
在原生 DX9 固定功能顶点之后的诊断像素着色器与 DX11 生产顶点之后的诊断像素着色器中逐位一致。
三次独立提交得到相同结果。**这组数据没有发现 Alpha 采样或材质乘法的跨 API 精度差异。**

独立观察保留固定功能像素路径、不安装诊断 PS 的 DX9 float32 输出，其 Alpha
也与诊断 PS 的乘法结果逐位相同。因此诊断 PS 没有改变本组 Alpha 乘法的观测值；
这不代表它完整替代了固定功能像素路径。

材质 Alpha 为 `0.5`。下表取第 0 次提交，后两次完全一致：

| 坐标 | 纹理采样 Alpha | 材质乘法后 Alpha | 乘 255 的 float32 值 | 当前显式量化字节 |
|---|---:|---:|---:|---:|
| (1040,725) | 0.004043641034514 | 0.002021820517257 | 0.515564203262329 | 1 |
| (1097,740) | 0.004226749297231 | 0.002113374648616 | 0.538910508155823 | 1 |
| (1136,757) | 0.004135195165873 | 0.002067597582936 | 0.527237355709076 | 1 |
| (1163,776) | 0.004043641034514 | 0.002021820284426 | 0.515564143657684 | 1 |
| (1041,725)，验证点 | 0.002212558174506 | 0.001106278970838 | 0.282101124525070 | 0 |
| (1097,741)，验证点 | 0.023254750296474 | 0.011627374216914 | 2.964980363845825 | 3 |

注意材质源 Alpha 为 0.5，片元插值后的漫反射 Alpha 在前三个点为 0.5，
后三个点为 `0.49999997019767761`；两套 API 在此也逐位相同。
表中的乘法使用实际片元 Alpha，不以源常量替代插值结果。

当前显式 PS 的转换为 `floor(saturate(alpha)*255+0.5)`，四个异常点得到 1，
所以它们通过 `GreaterEqual, ref=1`，而原生 DX9 在此前完整控制中将它们丢弃。
直接把原始 Alpha 与 `1/255` 比较，或向下取整为字节再比较，都会丢弃这四个点。
但本组数据**不能在这两个候选之间作出选择**；不能据此直接替换生产算法。

原始比较规则已由捕获值 `D3DRS_ALPHAFUNC=7` 核实为 `D3DCMP_GREATEREQUAL`。
上一份深度报告初稿误写 Greater，本轮已修正；旧测试执行的状态一直取自捕获数据。

## 诊断路径与完整性

新增 `tests/accessory_alpha_sampling_fixture.hpp`，入口：

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --accessory-alpha-sampling `
  exports/cpu-accessory-control-audit-x64/prefix.98444 `
  exports/accessory-alpha-sampling-example-x64

python tools/analyze_accessory_alpha.py exports/accessory-alpha-sampling-example-x64
```

输出目录必须不存在；GPU 测试串行。构建 x86 后使用同一入口及同一捕获数据。
DX11 诊断使用共用常量构建、生产兼容 VS、相同的纹理 Mip 与采样器描述。
本例只有纹理阶段 0 有效，采样器为各向异性、Wrap、最大各向异性 16。
float32 目标逐项观察 UV、导数、采样、漫反射 Alpha、乘法、字节量化与比较判定。
不使用目标 RGBA8 的 Alpha 反推高精度比较输入。

预定完整流程为：

- 原生固定功能 float 输出 18 行；八组显式 PS 阶段观察 144 行，共 162 行。
- 当前生产 Alpha 判定与两个诊断候选的 byte 控制，共 72 行。
- 程序生成白色 1×1 纹理，改变材质 Alpha，绕开采样与插值；扫描半字节、整字节边界及相邻 float32 值，分别使用 GreaterEqual、Equal、NotEqual 与 ref=1，共 225 行。
- 使用 `Equal`／`NotEqual` 分开“原始浮点比较”与“字节量化比较”，而不只观察 GreaterEqual。

常量控制另存比较前的 DX9／DX11 float Alpha。分析使用实际片元值，
避免把材质输入常量与插值后的片元 Alpha 混为一谈。

首轮 `exports/accessory-alpha-sampling-x64` 已完成 162 行 float 观察、36 行显式 byte 控制。
随后 DX9 `CreateDevice` 返回 `0x8876086C`，常量 Alpha 扫描尚未开始，程序返回失败，无完成 summary。
独立硬件探针及后续重试同样失败，证据为
`exports/accessory-alpha-sampling-probe.log`、`exports/accessory-alpha-sampling-probe-retry.log`。
不能用 RDP Active 或编译成功代替硬件验收。

首轮诊断的 DX11 清屏颜色来自旧共用观察工具的白色默认值，DX9 使用黑色，
因此 `normalized_gate` 的丢弃后颜色不可直接作两 API 图像对照；
该模式的 Alpha 为背景值，也不是乘法结果。
这不影响无丢弃阶段的 UV、采样和乘法数据。
已在测试工具中增加可选清屏颜色，下一轮显式指定同样的黑色背景；旧调用保留默认行为。
首轮未完成证据原样保留，不覆盖或写成通过。

`tools/analyze_accessory_alpha.py` 标记完成状态、检查重复数据，
分别拟合原始浮点比较、最近字节量化、向下字节量化候选；
有第二个架构目录时可逐行对照。
当前分析为 `exports/accessory-alpha-partial-analysis.json`，`complete=false`。

最终诊断程序已在 x64／x86 编译通过，CPU 转换回归两个架构各为 1/1；
证据为 `exports/accessory-alpha-sampling-final-build-{x64,x86}.log` 和
`exports/accessory-alpha-sampling-cpu-{x64,x86}.log`。这些检查不能替代尚未完成的硬件测量。

## 后续验收

恢复 DX9 硬件设备后，在新目录重跑 x64／x86 完整测量，
先核对生产参考值控制，再依据常量 Equal／NotEqual 扫描筛选量化规则。
若存在精确匹配的候选，还要使用其他参考值及独立 Alpha 输入验证，
再回到完整第 65／66 次历史和 DX12 对照。
完整场景仍有四个 Alpha 差异，应用继续使用原 DX9 路径。

## 设备恢复后的完整扫描

2026-10-08，硬件探针 `exports/accessory-alpha-recovered-probe-{x64,x86}.log`
均通过。最终完成目录为：

- x64：`exports/accessory-alpha-scan-retry-x64`
- x86：`exports/accessory-alpha-scan-x86`

两架构各完成 **162 行高精度观察、72 行颜色控制、225 行常量比较**，
三份 CSV 完全相同，全部控制组的三次重复一致。
float 采样、UV 导数、材质 Alpha 插值和乘法的原结论成立。
此次显式指定双方同样的黑色清屏，纠正首轮 `normalized_gate` 背景不同的问题。

常量扫描使用白色 1×1 RGBA8 纹理、真实批次几何和矩阵、白色自发光材质，
并保留实际片元 float Alpha，不以材质常量冒充插值结果。
参考值为 1，比较为 GreaterEqual、Equal、NotEqual。
25 个独立 Alpha 输入包含半字节、整字节边界及相邻 float32 值；每组重复三次。

恢复后第一次 `exports/accessory-alpha-recovered-x64` 在常量转换时失败，
原因是测试生成器指定 `ALPHAARG2=DIFFUSE`，转换器仅支持原始规范路径的 `CURRENT`。
首个阶段的 CURRENT 等价于输入 diffuse；已修正生成器使用 CURRENT，
没有放宽生产转换器。另一次 `exports/accessory-alpha-scan-x64` 为设备创建失败，
均未写完成 summary，不能视为完成的测量。

### 候选规则检验

以下均以**实测比较前的 float Alpha**预测，统计 225 行中不匹配的行数，
包含三次重复；统计依据见 `tools/analyze_accessory_alpha.py`：

| 候选 | DX9 不匹配行数 | DX11 不匹配行数 |
|---|---:|---:|
| 原始 float 与 float32 `1/255` 比较 | 99 | 117 |
| `floor(float32(alpha*255)+0.5)` 后比较字节 | 54 | 0 |
| `floor(float32(alpha*255))` 后比较字节 | 51 | 105 |
| 同输入、不启用 Alpha 测试时，实际 RGBA8 目标 Alpha 字节 | **0** | 54 |

最后一项是独立颜色输出观察与比较判定的关联，**不是内部比较值的直接读回**。
它揭示 DX9 判定与其实测输出字节一致；不能把取目标像素当作生产实现。
直接浮点比较和向下取整两个猜测都被本组数据排除。

具体例子（只列第 0 次，后两次相同）：

| 实际片元 Alpha | DX9 输出字节 | DX11 输出字节 | DX9 GreaterEqual/ref=1 | DX11 GreaterEqual/ref=1 |
|---|---:|---:|---|---|
| 0.001999999862164259 | 0 | 0 | 丢弃 | 放行 |
| 0.0029411762952804565 | 1 | 1 | 放行 | 放行 |
| 0.005921567790210247 | 1 | 1 | 放行 | 放行 |

最后一例的 Equal/ref=1 在 DX9 放行、DX11 丢弃，NotEqual 判定相反。
它说明结果不能简单归为原始 float 的大小比较：
实际转换到目标仍是字节 1，而当前显式着色器已将比较值四舍五入为 2。

在真实六点、ref=1 控制中，诊断的直接 float 比较与 DX9 的片元可见性一致；
但它在独立常量扫描中存在 99 行不匹配，因此**不能因真实四点看起来修复就采用该公式**。

### 分析与剩余验证

```powershell
python tools/analyze_accessory_alpha.py `
  exports/accessory-alpha-scan-retry-x64 --compare exports/accessory-alpha-scan-x86 `
  --output exports/accessory-alpha-scan-analysis.json
```

分析输出 `complete=true`、`other.complete=true`、`architectureExact=true`，
三种数据的 `repeatExact` 均为 true；这些表示诊断完成，**不表示场景图像通过**。

新增 `--accessory-alpha-references` 入口独立扫描参考值
1、2、17、127、254，各 17 个相邻输入、三次重复，共 255 行。
它记录实际 float Alpha、未启用测试时的输出字节和 GreaterEqual 判定，
用于约束不同数值区间的转换边界。
分析器可通过 `--references` 与 `--compare-references` 比较两个架构。

`exports/accessory-alpha-references-x64` 在首次原生 float 提交时创建 DX9 设备失败，
返回 `0x8876086C`，未取得扫描数据；
`exports/accessory-alpha-references-probe-x64.log` 的独立硬件探针也失败。
此次尝试的多参考值扫描未完成；设备随后恢复后的结果见下一节。
此时 x64／x86 已完成并互证的是原定 ref=1 扫描，不能将其范围扩大到所有参考值、驱动或 MSAA。

下一步按多参考值扫描实测映射，再用预留数值与独立几何验证；
通过后才设计兼容转换并回到第 65／66 次完整历史及 DX12 图像验收。
本轮没有修改生产 Alpha 公式或切换应用渲染器。

## 五个参考值的实际阈值扫描

后续重连时，`exports/accessory-alpha-reference-recovered-probe-x64.log` 硬件探针通过。
`exports/accessory-alpha-references-recovered-x64` 完整保存 **255 行**：
参考值 1、2、17、127、254，各 17 个输入、三次重复。
所有重复完全一致，全部 255 行的 DX9 GreaterEqual 判定与同输入、不启用测试时的
实际输出 Alpha 字节关系一致，没有不匹配。

下表给出输入 `alpha*255` 所在的扫描区间。左端为最后一个不通过的输入，
右端为首次通过的输入；扫描分辨率为 1/16 字节，**不是精确的内部转换阈值**。
程序同时记录插值后的实际 float Alpha，分析文件另含这个实测区间。

| 参考值 | DX9 转换边界的输入区间 | DX11 当前公式的输入区间 |
|---|---|---|
| 1 | (0.5, 0.5625] | (0.4375, 0.5] |
| 2 | (1.5, 1.5625] | (1.5, 1.5625] |
| 17 | (16.5, 16.5625] | (16.5, 16.5625] |
| 127 | (126.5, 126.5625] | (126.5, 126.5625] |
| 254 | (253.5, 253.5625] | (253.5, 253.5625] |

除参考值 1 外，粗区间相同，不能据此断言内部边界相同。
参考值 1 的差异区间涵盖真实四个异常点乘 255 后的值。
其他区间也支持继续测量转换规律，但还不能唯一确定舍入公式。

`exports/accessory-alpha-references-recovered-x86` 在扫描途中再次遇到 DX9
`CreateDevice=0x8876086C`，只保存 **82 行**，无完成 summary。
这 82 行与 x64 前 82 行完全相同；它不构成完整的跨架构验收。
结果分别由 `exports/accessory-alpha-reference-analysis.json` 的
`references.complete=true`、`otherReferences.complete=false` 记录。

### 细扫描和设备复用诊断

新增 `--accessory-alpha-reference-fine`：仍用五个参考值、17 个输入、三次重复，
只扫描每个区间的半字节至半字节加 1/16，步长为 **1/256 字节**。
CSV 新增 `bytePosition`，让分析器明确区分粗扫描和细扫描的输入位置。

长期扫描默认仍使用原来的每次观察独立设备模式。
另提供 `--accessory-alpha-references-reuse` 与
`--accessory-alpha-reference-fine-reuse`，仅供诊断使用一个专用 DX9 HAL 设备。
每次仍重新设置原始后台缓冲、重置诊断 PS 绑定、清屏、提交并读回；
共用测试 helper 的默认调用行为没有改变。
summary 显式记录 `nativeMeasurementDeviceReuse`，复用结果不作为连续创建设备稳定性的证据。

设备复用尝试 `exports/accessory-alpha-reference-reuse-{x64,x86}` 仍在首次创建时失败，
说明本次不能通过减少创建次数继续推进。
最后的独立硬件探针 `exports/accessory-alpha-reference-latest-probe-x86.log` 同样失败。
复用模式目前仅编译通过，**尚无运行通过证据**；细扫描也尚未取得数据。

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --accessory-alpha-references `
  exports/cpu-accessory-control-audit-x64/prefix.98444 `
  exports/accessory-alpha-reference-next-x86

build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --accessory-alpha-reference-fine `
  exports/cpu-accessory-control-audit-x64/prefix.98444 `
  exports/accessory-alpha-reference-fine-next-x64

python tools/analyze_accessory_alpha.py `
  exports/accessory-alpha-scan-retry-x64 --compare exports/accessory-alpha-scan-x86 `
  --references exports/accessory-alpha-references-recovered-x64 `
  --compare-references exports/accessory-alpha-references-recovered-x86 `
  --output exports/accessory-alpha-reference-analysis.json
```

恢复 GPU 后先补齐 x86 粗扫描，再细扫并检验预留输入。
目前只确认这份输入与该硬件的实测关联，尚未修改生产转换公式，完整场景验收仍未通过。

## x86 复验及两架构细扫描完成

再次恢复后，`exports/accessory-alpha-reference-probe-recovered2-x86.log` 的
独立 DX9 硬件探针通过。本轮串行执行 GPU 测量，全部扫描完成：

- x86 粗扫描：`exports/accessory-alpha-reference-recovered2-x86`，255 行。
- x64 细扫描：`exports/accessory-alpha-reference-fine-x64`，255 行。
- x86 细扫描：`exports/accessory-alpha-reference-fine-x86`，255 行。

本轮三个扫描均使用专用 DX9 设备复用模式，每次重新清屏、绘制及读回，
summary 标记 `nativeMeasurementDeviceReuse=1`；没有将它当作连续创建设备稳定性测试。
x86 粗扫描的输入、float Alpha、输出字节和比较判定全部与先前使用独立设备的
x64 完整粗扫描一致。因此此模式在本组粗测量中没有改变观测结果。
旧粗扫描没有后来新增的派生字段 `bytePosition`，
分析器比较全部十个原始输入／观测字段，不因 CSV 版本多一个派生字段而误报差异。

细扫描每个参考值取 17 个输入，步长为 1/256 字节，每个输入重新提交三次。
两架构的整份细扫描 CSV 完全相同，全部重复一致。
DX9 比较判定与其未启用 Alpha 测试时的实际输出字节依旧全部符合。
这是数值扫描的通过，**完整场景四个 Alpha 差异还没有修复**。

| 参考值 | DX9 边界输入区间（alpha 源值×255） | DX9 实测片元 Alpha 边界区间 |
|---|---|---|
| 1 | (0.55859375, 0.5625] | (0.0021905633620917797, 0.0022058822214603424] |
| 2 | (1.5546875, 1.55859375] | (0.006096812896430492, 0.006112131290137768] |
| 17 | (16.55859375, 16.5625] | (0.06493565440177917, 0.06495098024606705] |
| 127 | (126.50390625, 126.5078125] | (0.4960936903953552, 0.4961090087890625] |
| 254 | (253.50390625, 253.5078125] | (0.9941328763961792, 0.9941482543945312] |

区间左端是不通过、右端是首次通过，不能将右端当作精确内部阈值。
它们表明转换偏离半字节的位置随数值范围变化，统一常数偏移不能解释本组输入。
参考值 1 的 DX11 当前公式在细扫描起始 0.5 字节已经通过，
因此它在此细扫描中没有左侧括界；其粗测区间为 (0.4375,0.5]。
分析器用 `leftBracketAvailable=false` 明示这一限制，不虚构阈值。

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --accessory-alpha-references-reuse `
  exports/cpu-accessory-control-audit-x64/prefix.98444 `
  exports/accessory-alpha-reference-recovered2-x86

build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --accessory-alpha-reference-fine-reuse `
  exports/cpu-accessory-control-audit-x64/prefix.98444 `
  exports/accessory-alpha-reference-fine-x64

python tools/analyze_accessory_alpha.py `
  exports/accessory-alpha-scan-retry-x64 --compare exports/accessory-alpha-scan-x86 `
  --references exports/accessory-alpha-reference-fine-x64 `
  --compare-references exports/accessory-alpha-reference-fine-x86 `
  --output exports/accessory-alpha-reference-fine-analysis.json
```

粗扫描分析在 `exports/accessory-alpha-reference-recovered2-analysis.json`，
细扫描在 `exports/accessory-alpha-reference-fine-analysis.json`。
二者均为 `references.complete=true`、`otherReferences.complete=true`、
`referenceArchitectureExact=true`，两架构 `repeatExact=true`。
真实捕获及原始 CSV 仍在忽略目录，没有添加真实素材到仓库。

下一步用已保存的实际片元 Alpha 和转换字节检验有限精度转换候选，
选取候选预测不同的预留 Alpha 输入及独立几何复验；
只有确定可复用规则并通过真实历史验收，才将其限定接入后端兼容策略。
本轮没有新增色差容忍值、Alpha 偏移或生产着色器修改。

后续[Alpha 转换候选筛选与独立验证](RHI_ALPHA_CONVERSION_CANDIDATES.md)
已完成 11,109 个候选检验、预留参考值验证和两架构独立几何实测。
12 位固定小数截断候选在该范围内零错误，仍未修改生产公式或宣称完整场景通过。
