# 回读场景第 23 次绘制：纹理与高光组合舍入

2026-10-06，NVIDIA TITAN Xp，单采样。承接
[CPU 材质与前序历史](RHI_CPU_SCENE_HISTORY.md)中的 x64 回读第 5 帧阻断。
本次已定位一个像素的计算差异，增加独立复现和诊断候选；没有改变生产后端、容差或准入条件。

## 不可变输入与复现

之前的 CSV 和 DX9 日志有状态和差异图像，缺少完整顶点／索引和纹理 Mip 字节。
增加 `--history-export` 后，原生重放验证的每个进程保存独立 `prefix.<PID>` 档案，
包括所有资源字节、描述、矩阵、状态、原生逐绘制图像及索引格式日志。
首次加载和 Save As 回读的数据不覆盖。资源仍在被忽略的 `exports` 中，不纳入仓库分发。

使用回读档案 `exports/model23-owned-capture-x64/prefix.19376`：

| 字段 | 实测 |
| --- | --- |
| 目标 | 1920×1080，RGBA8／D24S8，单采样 |
| 已初始化视口 | `(565,25,1032,774)`，深度 0…1 |
| 原生第 23 次绘制 | XYZ／法线／UV，stride 32，indexed triangle list |
| 索引范围 | firstIndex 7275，23001 个索引，7667 个三角形 |
| 两级纹理 | 32×32、256×256；第二级含完整捕获的自动 Mip |
| 目标像素 | `(867,486)` |
| DX9 RGBA | `(17,95,150,255)` |
| DX11／DX12 原历史图像 | `(17,96,150,255)` |

独立探针通过共用 `SceneRenderer` 和正式 `Dx9Measured` DX11 后端重放。
前 23 条绘制的原生图像与应用档案逐字节一致；独立绘制第 23 个批次仍只有同一像素差异。
带历史和独立绘制各重复三次，完整图像稳定。二分 7667 个三角形，将差异缩减至
批次内 **零起算第 1383 个三角形**，原顶点索引 `8065、8067、7923`。
压缩到三顶点／索引 `(0,1,2)` 后两路径各自的完整图像不变。

x86 探针读取这份相同的 x64 档案，也复现同一差异。
两架构的 142 个隔离证据文件（68 组完整对照）SHA-256 全部一致。
因此先前 x86 真实场景通过不表示它对同一输入具有不同的计算规则；两个架构捕获的场景输入不同。

## 定向控制

每组改变一个状态，两 API 消费相同改变。以下为缩减后三角形的整幅已知视口比较：

| 控制 | 差异像素 | 目标像素是否仍有差异 |
| --- | ---: | --- |
| 原始输入 | 1 | 是 |
| 关闭混合／Alpha test／深度和模板，分别测试 | 各 1 | 是 |
| 关闭法线归一化 | 1 | 是 |
| 关闭高光 | 0 | 否 |
| 关闭灯光 | 0 | 否 |
| 仅 Toon／关闭纹理 | 0 | 否 |
| 仅第二级纹理／白 Toon | 1 | 是 |
| 白第二级纹理／两级皆白 | 0 | 否 |
| Point／Linear + Mip Point／Linear + Mip Linear | 各 1 | 是 |

将自动 Mip 改为已捕获的显式层，不改变原始两路径图像。
这些控制说明差异要求第二级纹理与高光同时参与，不能单凭“关闭高光通过”判断高光公式错误。
为区分这些运算，继续测量浮点阶段输出。

## 浮点观测与确定的舍入差异

DX9 保留固定功能顶点处理，分别读取未修改的固定功能浮点输出，以及安装诊断 PS 后的中间量。
DX11 使用正式 measured VS 的源码、编译规则和常量生成器，观察同一像素的阶段值。
诊断 PS 的完整字节图像在两侧分别等于各自原始图像；固定功能浮点最终值与 DX9 诊断 PS 在目标像素一致。
不把诊断 PS 当作原生顶点寄存器捕获。

目标像素的绿色通道，以下输出都重复三次稳定：

| 阶段 | DX9 | DX11 |
| --- | ---: | ---: |
| 插值后的漫反射颜色 | 0.57812494039535522 | 同值 |
| 插值后的高光 | 0.016300942748785019 | 同值 |
| Toon 采样 | 1 | 1 |
| 第二级纹理采样 | 0.61960786581039429 | 同值 |
| 加高光前的颜色 | 0.35821077227592468 | 同值 |
| 最终颜色 | **0.37451168894767761** | **0.37451171875** |

第二级纹理坐标也一致。Toon 的 U 坐标存在一个 ULP 差异，但该像素的 Toon 采样两侧都为全白，
不能解释最终绿色通道差异。这里的首次有效分叉是最后颜色组合，差一个 float32 ULP。

记漫反射为 `a`、第二级纹理采样为 `b`、高光为 `c`，使用实测 float32 输入：

```text
单次舍入：float32(a × b + c)             = 0.37451168894767761  // DX9
分两次舍入：float32(float32(a × b) + c)  = 0.37451171875        // DX11
```

所有乘数来自实测数据，不拟合系数或引入 epsilon。
两个 float32 的乘积可在 float64 中精确表达，此组乘积与 float32 加数之和也可精确表达，
因此 float64 运算后只转一次 float32，可以验证单次舍入假设。
DX11 诊断反汇编确认原表达式是独立 `mul` 与 `add_sat`；候选使用 `dmul`、`dadd` 和一次 `dtof`。
没有取得 DX9 驱动实际指令，结论是其观测结果符合单次乘加舍入，不宣称捕获了原生 MAD 指令。

候选只改变第二级纹理乘法与最终高光相加的舍入：

```hlsl
precise float3 previous = diffuse * toonSample;
precise double3 product = double3(previous) * double3(textureSample);
precise double3 combined = product + double3(specular);
return saturate(float3(combined));
```

三次重复的候选浮点值在目标像素与 DX9 完全一致，候选 RGBA8 的整幅三角形图像也与 DX9 完全一致。
恢复的不只是截图中的目标像素。两架构的 32 个高精度证据文件全部逐字节一致。
最终共核验 174 个跨架构证据文件、68 组隔离对照和 27 次阶段观测。

## 可重跑入口

```powershell
python tools/run_cpu_geometry_diagnostic.py `
  --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe `
  --application build-x64/build/Release/MikuDanceStudio.exe `
  --fixture C:/Users/jstzw/Downloads/MikuMikuDanceE_v932/UserFile/sample.pmm `
  --output exports/model23-new-capture `
  --preview --materials 12,13,14 --play --lifecycle --inputs audit --history --ground --history-export

build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-isolation exports/model23-owned-capture-x64/prefix.19376 exports/model23-new-isolation

build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-batch23-stages exports/model23-owned-capture-x64/prefix.19376 exports/model23-new-stages

python tools/analyze_model_batch23.py `
  --archive exports/model23-owned-capture-x64/prefix.19376 `
  --isolation exports/model23-isolation-x64 --stages exports/model23-verified-stages-x64 `
  --compare-isolation exports/model23-isolation-x86-shared `
  --compare-stages exports/model23-verified-stages-x86-shared
```

每次诊断选择新输出目录。捕获的完整场景 history audit 仍应失败，不能把独立候选成功当作已开放准入。
分析器验证原生应用边界、原顶点字节、重复图像、阶段顺序、每阶段数据、两种算式预测、
候选整幅图像和跨架构 SHA-256，结果写入阶段目录 `analysis.json`。
现有 DX9→可移植转换、DX11 Hardware/WARP 重放回归，两架构各 3/3 通过。

## 下一步边界

本次定位到此三角形／像素的最后乘加舍入，不声称所有驱动与材质都采用同一规则。
生产 `model_material_pixel.hlsl` 和 DX11／DX12 后端未修改，x64 原历史准入继续阻断。
下一步用独立材质、三角形及颜色阈值控制验证“最后有效 Modulate 阶段＋高光”的适用条件，
包括无高光、Add、单级／多级纹理和饱和颜色；通过后将兼容运算限定在 measured 策略内，
再重跑实际第 23 次绘制及完整前序历史，保留通用着色路径。

2026-10-07 后续：上述独立控制和正式 measured 策略接入已完成，见
[最终纹理组合兼容规则](RHI_FINAL_MODULATE_COMPATIBILITY.md)。
两架构的冻结档案与八组真实场景 audit/direct 历史验收通过，
第 23 次绿色通道差异已消除，详见
[本轮场景历史复验](RHI_CPU_SCENE_HISTORY.md#最终乘加修正后的复验2026-10-07)。
上文未启用的状态描述是本次隔离阶段记录，最新状态以上述后续验收为准。
