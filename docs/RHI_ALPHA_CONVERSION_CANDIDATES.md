# Alpha 转换候选筛选与独立验证

本轮完成不依赖 GPU 的候选筛选，以及 x64／x86 独立几何实测。
**按 1/4096 截断 Alpha 后再乘 255、取最近整数的候选，在本组训练、
预留参考值、独立几何和真实六点中均零错误。**
这是一条经过限定范围验证的数值候选，不是 DX9 内部实现的证明；
仍有多个运算表达式不能区分。本轮没有修改生产着色器或开放渲染替换。

## 数据划分与候选范围

输入来自已完成的三个保存目录：

- `exports/accessory-alpha-scan-retry-x64/constant_alpha.csv`
- `exports/accessory-alpha-references-recovered-x64/reference_scan.csv`
- `exports/accessory-alpha-reference-fine-x64/reference_scan.csv`

分析使用**实际片元 float Alpha**，同时预测未启用测试时的 Alpha 字节，
以及 GreaterEqual、Equal、NotEqual 判定；不拿目标字节代替预测公式。
先要求源目录有完成 summary、每组重复三次一致，再只计第 0 次记录，
避免将重复提交当作额外验证样本。
不同扫描来源、比较规则分别计数；这些行不等于统计上相互独立的 Alpha 输入。

训练参考值为 **1、17、127**，共 177 条比较观察；
预留验证参考值为 **2、254**，共 68 条。
这是对既有保存数据的回顾性划分，不宣称以前从未查看验证值。
脚本只按训练错误冻结候选清单，随后计算预留错误，验证结果不改变清单。
后续独立几何与新参考值的观测则在清单冻结后实际取得。

`tools/fit_accessory_alpha_conversion.py` 枚举 11,109 个具名候选，依次检验：

1. 输入表示：double、float32、IEEE half，保留完整指数的有限尾数，或固定小数位。
2. 乘 255：double／float32／half、有限尾数或固定小数位的截断及最近偶数舍入。
3. 最后取整：向下、最近偶数，或先加 0.5，再按上述精度转换并向下取整。

有限尾数候选明确与 IEEE half 区分；固定小数位包含 8、10、12、16 位输入。
所有规则都具备明确的运算顺序；没有拟合额外偏移、色差容忍值或按参考值分支。
每个候选的四项错误计数保存在 `candidate_errors.csv`：
训练字节／判定错误，以及预留字节／判定错误。

## CPU 筛选结果

258 个候选在训练中零错误，**全部都采用输入 `fixed:12:truncate`**。
其中 255 个在预留参考值中仍然零错误，另外三个分别有 3、3、6 个字节及判定错误。

| 候选例子 | 训练字节错误 | 训练判定错误 | 预留字节错误 | 预留判定错误 |
|---|---:|---:|---:|---:|
| float32 乘 255、加 0.5、向下取整（当前显式公式） | 54 | 51 | 15 | 15 |
| 输入先转 IEEE half，后续用当前公式 | 38 | 37 | 17 | 17 |
| double 乘 255 后向下取整 | 60 | 58 | 35 | 33 |
| 输入 12 位固定小数向下截断，double 乘 255，最近偶数取整（8994） | **0** | **0** | **0** | **0** |

最简候选在非负、已饱和的 Alpha 范围内写为：

```text
a12 = floor(clamp(alpha, 0, 1) * 4096) / 4096
byte = clamp(round_to_nearest_even(a12 * 255), 0, 255)
```

保存数据中的乘法 Alpha 本身已与两套 API 逐位相同；
这里的 12 位截断是**转换阶段的假设**，不是将材质乘法改为 12 位。
由于输入步长与乘数的关系，多个后续运算表示在本组输入上给出相同结果，
不能仅凭“零错误候选很多”推定多种不同硬件路径存在。
也不能将候选的每一步都当作内部寄存器的直接观察。

## 选择新的区分输入

脚本保留按训练冻结的 258 个候选，不因预留失败而从独立测试计划中抹掉它们。
在参考值 **3、7、31、63、191、253** 下搜索候选预测不同或与当前公式不同的 Alpha。
将已保存输入与新输入的预测向量一并考虑，区分“在旧数据上相同、在新数据上不同”的候选。
得到四个预测类别的代表（8994、9344、9388、9431），选定 10 个 float32 输入。
计划在 `exports/accessory-alpha-candidate-analysis-v2/probe_inputs.csv` 中保存输入位模式；
没有基于之后的 GPU 结果调整输入。

其中参考值 191 和 253 的四个输入实际区分候选的预测字节；
其他输入主要区分共同截断候选与当前公式。
测试同时使用 Equal、NotEqual，避免只有大小比较时看不见转换字节差异。

## 独立几何的 x64／x86 实测

新增 `tests/alpha_conversion_independent_fixture.hpp`，完全不加载 PMM：

- 几何 0：程序生成的三角形，单位矩阵，64×64 视口。
- 几何 1：程序生成的双三角形四边形，偏移视口 `(17,11,80,96)`，
  W 随 XY 变化的独立投影，使透视插值不同于原饰品。
- 纹理：程序生成的白色 1×1 RGBA8 纹理；白色自发光材质，Alpha 来自输入位模式。
- 目标：128×128、单采样；DX9 原生固定功能与 DX11 原有生产兼容着色路径。

观测未启用 Alpha 测试时的原生 float32 Alpha、实际输出字节，以及启用后的比较判定。
DX11 的 float 观察用诊断 PS；比较判定用未修改的生产兼容后端。
Alpha 的预测依据实际片元值，而不是假定顶点常量不会因插值改变。
两个几何 × 10 输入 × 3 比较 × 3 次重复 = **每个架构 180 行**。
计错误时只取第 0 次，即 60 条比较观察；三次重复另外严格校验。

硬件探针 `exports/alpha-conversion-independent-probe-x64.log` 通过。
`exports/alpha-conversion-independent-{x64,x86}` 均完整完成，
整份 CSV 跨架构相同，每组重复三次一致；专用设备复用模式记录在 summary。
该模式用于减少扫描中的设备创建，不视为连续设备创建稳定性的通过证据。

`tools/validate_alpha_conversion_candidates.py` 首先验证输入位模式、参考值、
两个几何、全部比较与重复严格匹配冻结的测试计划，然后才计算错误。

- 候选 8994：独立字节错误 0、独立比较错误 0。
- 候选 9344：独立字节错误 24、独立比较错误 24，被新数据进一步否定。
- 当前 float32 四舍五入公式：独立字节错误 **30/60**、比较错误 **30/60**。
- 结合训练、预留和独立验证后，仍有 **255 个具名候选**零错误，尚不能唯一确定运算顺序。

另用已保存的真实饰品六点作为独立于训练数据的检查：
候选 8994 预测的字节为 `0,0,0,0,0,3`，与 DX9 实际输出字节及 ref=1 判定相符。
这些是离线预测检查，**没有修改着色器后重新重放完整场景**。
完整第 65／66 次历史及 DX12 验收仍待下一阶段完成。

## 重现

输出目录／文件要求新建，避免把不同版本的试验混在一起。
GPU 程序必须串行。CPU 筛选不依赖 Win32 或 GPU。

```powershell
python tools/fit_accessory_alpha_conversion.py exports exports/alpha-fit-example

build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --alpha-conversion-independent `
  exports/alpha-fit-example/probe_inputs.csv exports/alpha-independent-example-x64

build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --alpha-conversion-independent `
  exports/alpha-fit-example/probe_inputs.csv exports/alpha-independent-example-x86

python tools/validate_alpha_conversion_candidates.py `
  exports/alpha-fit-example/analysis.json `
  exports/alpha-independent-example-x64 exports/alpha-independent-example-x86 `
  exports/alpha-independent-example-analysis.json `
  --real-evidence exports/accessory-alpha-scan-retry-x64
```

实际完整证据：

- `exports/accessory-alpha-candidate-analysis-v2/analysis.json` 与 `candidate_errors.csv`
- `exports/alpha-conversion-independent-x64/independent.csv`
- `exports/alpha-conversion-independent-x86/independent.csv`
- `exports/alpha-conversion-validation-reviewed.json`

结果含源文件 SHA-256，便于核查输入。捕获数据继续放在忽略目录。
数值筛选和 GPU 测量程序返回成功仅表示其范围内完成，`productionActivation=0`、
`imageAcceptance=0`；没有把完整场景验收标为通过。

下一步可在诊断后端实现这一截断候选，并用独立取值、更多 Alpha 比较和完整前序历史检验。
应覆盖 Alpha 的 0／1 边界、RGBA8 输出与 float 输出的适用范围、混合、
两套新后端及硬件／WARP 能力差异，再决定是否纳入限定的 DX9 兼容策略。
不能将当前 TITAN Xp 单采样的数值关联推广成跨驱动通用硬件规则。
