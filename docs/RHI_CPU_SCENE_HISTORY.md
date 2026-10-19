# 同帧 CPU 材质与场景前序历史

2026-10-07 后续：[CPU 地面与投影阴影前序生产](RHI_CPU_SCENE_PASSES.md)
已将这些家族的输入改由 CPU 生成；该阶段完整模型材质前序阻断在 Sphere Mip 资源字节。
后续 [完整 Mip 准备与版本契约](RHI_CPU_MIP_CONTRACT.md) 已完成选定模型全部 17 个材质的
x64/x86 原场景及 Toon／半透明 audit、direct 八组验收，完整层与逐绘制图像通过。
以下保留各阶段的历史验收范围，不能把早期原生捕获前序视为完整 CPU 场景生产。

2026-10-06。先完成 [多材质最终图形复验](RHI_CPU_MULTIMATERIAL.md)，再增加本诊断。
应用仍由 DX9 渲染，默认关闭；此里程碑不启用 DX11／DX12 应用替换。

## 契约与职责

`ComposeModelReplay(prefix, suffix, output)` 接受两份有 CPU 字节所有权的命令流。
prefix 从完整清屏开始；suffix 由既有 `ModelSubmissionBuilder` 生成。
组合保留 prefix 的清屏、目标及已初始化区域，只移除 suffix 的起始清屏。
suffix 的资源 ID 进入独立命名空间，版本、发布顺序、几何范围、材质顺序和管线保持不变。
场景／帧号、颜色／深度／模板、采样及目标尺寸不匹配，或任一事件不支持时，拒绝组合。
最后再次验证整份输出；失败不修改原输出，输入／输出可以别名。

`SceneRenderer` 继续管理资源、版本、提交和 fence；DX11／DX12 执行同一份命令流。
诊断桥接使用独立 renderer 资源空间，避免捕获历史与常驻 CPU 子集的 ID 冲突。
这沿用 Unity 的场景生产、共用资源提交层和后端执行边界，不引入 native handle 到可移植契约。

## 原生证据与门禁

Windows 现有 DX9 记录器从场景清屏记录地面、饰品、投影阴影及前面的模型绘制。
它保存每次绘制的不可变几何、管线、纹理 Mip 和原生边界图像；目标切换、MME 或不支持的操作阻断。
选中材质前先运行 DX9 自身重放：所有边界及最终前序图像都必须零差异。
`CopyPortableHistoryReplay` 现在要求这份原生证明，单纯语法验证不能获得历史流。

首个选中材质之前取得验证后的 CPU 历史；随后立即捕获每个选中材质的实际 DX9 绘制结果。
模型循环结束后，将同一帧的 CPU 几何、纹理和着色输入接到历史后。
只捕获每个模型首次有效提交，不跨帧复用背景，不拼接新姿态与旧历史。
此诊断要求连续材质子集，避免漏掉两材质之间的原生绘制。

DX11／DX12 先比较初始清屏，再逐次重放前序绘制，最后比较每个 CPU 材质绘制后的图像。
只比较记录器明确初始化的视口区域。恢复的是命令形成的颜色、深度、模板历史，
不是仅恢复解析颜色。清屏单独走 RHI frame 操作；model replay 契约仍拒绝无绘制的流。
任一边界出现差异即停止该历史诊断；不扩大容差，不继承旧 hash 的 direct 准入。

`cpu_scene_history.<PID>.csv` 记录帧、阶段、边界、材质、后端、前序绘制数和像素差异。
失败保存逐像素坐标／RGBA CSV，以及裁剪后的 native／candidate RGBA 文件。
DX9 原生重放记录在 `history_replay.<PID>.dx9`，Save As 回读的两个进程分别记录。
脚本要求每个进程具有完整的前序与材质边界序列，不能用最终图像抵消中途差异。

## 运行

```powershell
python tools/run_cpu_geometry_diagnostic.py `
  --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe `
  --application build-x64/build/Release/MikuDanceStudio.exe `
  --fixture C:/Users/jstzw/Downloads/MikuMikuDanceE_v932/UserFile/sample.pmm `
  --output exports/cpu-scene-history-new-audit-x64 `
  --preview --materials 12,13,14 --play --lifecycle --inputs audit --history --ground
```

`--ground` 只修改临时 PMM 副本；`--translucent --switch-toon` 只修改临时模型副本。
不带 `--history` 时仍执行原多材质验收；两个后端的主应用开关均保持关闭。
历史模式全部通过后才允许对应 `--inputs direct --accepted-audit <本轮 audit 目录>`。

## 验证范围

可移植组合测试覆盖资源 ID 冲突、纹理版本、绘制顺序、已初始化区域、目标／帧拒绝、
输出回滚和输入别名。Windows x64/x86 重放测试通过；Windows／Linux 资源入口各 10/10。
macOS CI 已包含同一测试，本轮没有新的 macOS 实测。

首次真实 PMM x64 四边界验收：50 条原生前序重放通过，前序末尾和三个选中材质后的
DX9／DX11／DX12 图像共 8 次零差异；Save As 回读后的 33 条前序在两个新后端各有 1 像素差异。
因此整组历史验收失败，后端替换未开放。证据：`exports/cpu-scene-history-ground-audit-x64`。
之后增加完整逐绘制追踪，定位首个差异，不能以该首次运行的局部通过替代整体准入。

完整逐绘制追踪结果，单采样、NVIDIA TITAN Xp，包含地面的临时 PMM：

| 架构／场景 | 初始场景 50 条前序与三个 CPU 材质 | 回读场景 33 条前序与三个 CPU 材质 | 生命周期 | 整组准入 |
| --- | --- | --- | --- | --- |
| x64 原场景 audit | 108 次边界，零差异 | 第 23 次前序绘制首次差异，两后端各 1 像素 | 4/4 | 阻断 |
| x64 Toon／Alpha 控制 audit | 108 次边界，零差异 | 同一第 23 次前序绘制、同一像素 | 4/4 | 阻断 |
| x86 原场景 audit | 108 次边界，零差异 | 74 次边界，零差异 | 4/4 | 通过 |
| x86 Toon／Alpha 控制 audit | 108 次边界，零差异 | 74 次边界，零差异 | 4/4 | 通过 |
| x86 原场景 direct | 108 次边界，零差异 | 74 次边界，零差异 | 4/4 | 通过 |
| x86 Toon／Alpha 控制 direct | 108 次边界，零差异 | 74 次边界，零差异 | 4/4 | 通过 |

x64 两场景均在回读第 5 帧、像素 `(867,486)` 首次出现差异：
DX9 RGBA 为 `(17,95,150,255)`，DX11／DX12 均为 `(17,96,150,255)`。
第 23 次绘制是模型材质、`firstIndex=7275`、`indexCount=23001`，有两级纹理输入。
DX9 自身逐边界重放通过；新后端在第 0 至 22 个边界通过。
这定位了触发边界和具体通道，尚不能据此决定是灯光、插值、纹理过滤或组合舍入。
当前共享 shader／兼容转换与 x64 原生输入的这个差异仍待独立批次隔离。

x64 新构建中的独立材质字段和图像检查仍全部通过：原场景 768 次、控制场景 795 次。
历史失败停止该段重放，不使已支持的独立材质路径失效；整组脚本仍返回失败。
x86 audit 原场景 1233 次、控制场景 1254 次字段／独立图像检查均通过。
x86 direct 使用各自本轮相同 hash／控制参数的 audit 准入：原场景 1761 次、控制场景 1923 次
独立图像检查，所选材质不读取 DX9 GPU 几何或状态；前序诊断仍明确读取 DX9 捕获数据。
该架构 audit/direct 四组合计 728 次历史边界检查全部零差异、16 次生命周期检查全部通过。
不为 x64 历史运行 direct：其本轮历史 audit 失败，不能绕过脚本准入。
该架构先遇到模型重选超时／未到主窗口，探针随后全部成功；使用新目录重试取得以上图像证据，
超时运行不计入通过，不能声明图形加载从未出现偶发失败。

证据：x64 `exports/cpu-scene-history-verified-{opaque,switch}-audit-x64`；
x86 `exports/cpu-scene-history-retry-{opaque,switch}-audit-x86`。
x86 direct 为 `exports/cpu-scene-history-verified-{opaque,switch}-direct-x86`。
最终 x64 应用 SHA-256 为 `6d90ddda7ce008701d76ad854db1fac4b68884c292ae81b000b0e9091b5461bd`，
x86 为 `43f5f63876b6f40be2d1b9d0af461dc0755c3f73873eabf3c114b444ee4f1860`。
两个架构的 DX11／DX12 Hardware/WARP 资源恢复 CTest 各 4/4；
日志为 `exports/cpu-scene-history-backends-{x64,x86}.log`。
Windows／Linux 资源测试日志为 `exports/cpu-scene-history-portable.log`、
`exports/cpu-scene-history-linux-validation.log`；Windows 两架构的重放 CTest 也通过。

尚未迁移整帧历史生产者到 CPU 场景层：前序仍来自 DX9 诊断捕获，选中三个材质来自实时 CPU。
MSAA、额外目标／自阴影和 MME 仍属独立范围。本阶段的目的为验证有版本的命令组合和真实历史，
为后续将各绘制家族改为平台无关生产者建立逐边界基准。

下一步只隔离 x64 回读第 23 次批次，比较其双纹理输入、固定功能灯光和过滤／组合精度，
保持当前绿色通道差异的零容差门禁；通过后再扩展前序历史的 CPU 生产者。

2026-10-06 后续已完成 [第 23 次颜色差异隔离](RHI_MODEL_DRAW23_COLOR.md)：
缩减到三角形 1383，漫反射／高光／纹理采样都一致；最终纹理乘法与高光相加的
单次／分步舍入产生一个 ULP。独立诊断候选恢复该三角形整幅零差异，两架构证据完全一致。
正式后端尚未变更，先验证独立输入与状态范围，再开放定向 measured 修正。

## 最终乘加修正后的复验（2026-10-07）

[独立最终纹理组合控制](RHI_FINAL_MODULATE_COMPATIBILITY.md)已验证 90 个条件，
每条件三次整幅 RGBA8／float32 输出；x64/x86 各 270 次全部零差异，记录逐字节一致。
规则限于 DX11／DX12 `Dx9Measured`，默认模式和应用 DX9 渲染保持现状。
两架构使用同一份原来失败的回读冻结档案，各通过 33 次边界、1000 帧重复提交、
目标尺寸切换和后端替换；没有再现第 23 次绘制的那个绿色通道差异。

本轮真实 PMM（含地面的临时副本）结果：

| 架构／场景／输入 | 初始与回读历史边界 | 独立材质图像检查 | 生命周期 | 结果 |
| --- | ---: | ---: | ---: | --- |
| x64 原场景 audit | 182 | 801 | 4 | 通过 |
| x64 原场景 direct | 182 | 4134 | 4 | 通过 |
| x64 Toon／Alpha 控制 audit | 182 | 594 | 4 | 通过 |
| x64 Toon／Alpha 控制 direct | 182 | 1158 | 4 | 通过 |
| x86 原场景 audit（新目录重试） | 182 | 1311 | 4 | 通过 |
| x86 原场景 direct | 182 | 3582 | 4 | 通过 |
| x86 Toon／Alpha 控制 audit | 182 | 849 | 4 | 通过 |
| x86 Toon／Alpha 控制 direct | 182 | 2499 | 4 | 通过 |

八组合计 **1456 次历史边界零差异、14928 次独立材质图像检查一致、32 次生命周期检查通过**。
其中 x64 原场景 direct 的 4011 次独立比较为空覆盖，报告已逐项记录，
不把空图像当作有效像素证据；该组另有 123 次非空覆盖，
八组 `previewCoveredPixels` 都大于零，固定真实历史边界也分别完整验收。
每组使用初始 50 条和回读 33 条前序，加三个实时 CPU 材质，DX11／DX12 全部边界均对照 DX9。
Save As、回读、跳帧、编辑与实际播放均由现有图形测试驱动执行。
direct 仅使用本轮对应场景、同一应用／fixture／GUI hash 且通过的 audit 准入。

证据：x64 `exports/final-modulate-history-{opaque,switch}-{audit,direct}-x64`；
x86 `exports/final-modulate-history-retry-{opaque,switch}-{audit,direct}-x86`。
x86 首次 `exports/final-modulate-history-opaque-audit-x86` 未到主窗口，
卡在模型重选，零图像和生命周期检查，保留为失败，不能计入成功。
硬件原生 DX9 探针通过后新目录重跑成功，未定位该偶发重选失败的完整原因。

本轮 x64 应用 SHA-256：
`82c6a0bc3f878729d8055423ff473d95e949935428f8b147b147b2d942166630`；
x86：`85618925f4885e9a60df2a7acb7949d375abf0e8dbd322f0f1c1f4c1554551f4`。

两架构 Hardware／WARP 回归各 10/10，Windows 无界面资源回归 10/10。
日志 `exports/final-modulate-backend-ctest-{x64,x86}.log`、
`exports/final-modulate-portable-regression.log`；本轮没有新的 Linux/macOS 实测。

已完成选中材质与捕获前序组合的零容差闭环，未切换应用后端。
下一阶段将地面／阴影／模型等前序输入逐类改由 CPU 场景生产，
保留版本、顺序与逐边界图像基准；目前这些前序仍明确依赖 DX9 诊断捕获。
MSAA、额外目标、自阴影和 MME 的完整后端迁移继续是独立验收项。
