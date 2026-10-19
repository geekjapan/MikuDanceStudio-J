# 实时 CPU 多材质提交

2026-10-06。应用主画面仍使用 DX9；本阶段只验收选定模型的独立材质子集，
不导入阴影、地面、饰品或其他模型的前序历史。

## 职责与数据

`ModelMaterialPacket` 持有材质编号、原始索引范围、完整管线和 CPU 纹理。
Windows 在原材质绘制边界生成输入；相机、灯光来自 SceneSession 的已应用状态，
材质和纹理由 CPU 资源提供，几何来自现有求解后的 CPU 输出。IK／物理时序保持现状。

`ModelSubmissionBuilder` 是无平台依赖的模型生产者。它保留包顺序、不重新排序；
重复／倒序材质、交叠范围、不支持的纹理、冲突内容或无效绘制均阻断提交。
构建使用私有副本，完整验证后才提交纹理版本登记和输出。

纹理以逻辑身份和采样色彩空间登记稳定 ID。多个材质、多个阶段引用同一身份时，
只发布一个不可变资源；内容变化增加版本。资源退出提交再重新启用也增加版本，
避免把已被 GPU 缓存回收的旧版本重新当成新资源。同一提交不能给一个身份赋予两份不同内容。
几何与索引只发布一次，所有材质共享它们。

共用 `SceneRenderer` 负责 GPU 上传、缓存、命令准备、设备身份／epoch 检查、
fence 回收及设备替换后的恢复。DX11／DX12 消费同一份 `ModelReplayStream`。
这是借鉴 Unity 的设备、资源与提交职责分离；没有复制 Unity 代码或增加生产者对原生句柄的依赖。
诊断预览设备仅用于离屏验收，模型卸载、场景更换、应用退出负责释放对应资源。

## Windows 集成与门禁

`BeginCpuModelMaterials` 在固定功能模型材质循环之前开始收集，
`SubmitLiveCpuModelInputs` 在每次原生绘制边界生成并可选审计输入，
`EndCpuModelMaterials` 在整个循环结束后提交。任何选中批次失败或缺失，整个子集被阻断。
未选中的材质不被宣称为已迁移。

每个选中绘制之后重放同一子集前缀，比较 DX11／DX12 和 DX9 状态参考管线的图像。
所有前缀从清屏开始，因此包含选中批次之间的颜色、深度、模板、混合历史。
它不是原应用整帧历史，也没有新增真实 DX9 整帧图像等价声明。
前缀保留完整资源集，避免诊断边界导致后续材质的资源被提前退休。

`cpu_material_order.<PID>.csv` 记录进程、提交序号、帧、模型槽位、绘制序号、
材质、网格范围、三阶段纹理 ID／版本及剔除／混合／深度写状态。
完整管线逐字段审计在 `cpu_inputs.<PID>.csv`，图像边界及上传计数在 `cpu_preview.<PID>.csv`。
按进程分文件，避免 Save As 回读时两个应用进程并行追加同一个文件造成记录丢失。

诊断开关 `MDS_RHI_CPU_MATERIALS=12,13,14` 默认关闭；脚本要求索引递增且至少两个材质。
直接模式必须有同一应用、GUI 驱动、PMM SHA-256、材质子集、控制选项和契约版本 3 的成功审计。
脚本同时检查所有模型提交的实际顺序、每个图像前缀、完整审计数量及生命周期证据。
旧构建的准入不能继承到新构建。

```powershell
python tools/run_cpu_geometry_diagnostic.py `
  --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe `
  --application build-x64/build/Release/MikuDanceStudio.exe `
  --fixture C:/Users/jstzw/Downloads/MikuMikuDanceE_v932/UserFile/sample.pmm `
  --output exports/cpu-multimaterial-new-audit-x64 `
  --preview --materials 12,13,14 --play --inputs audit --lifecycle
```

通过后以新证据目录运行 `--inputs direct --accepted-audit <audit 目录>`。
换成 x86 程序重复；控制用例额外添加 `--switch-toon --translucent`。
控制用例只改测试临时副本：Miku metal 材质 12 改用共享 Toon 2，材质 13 Alpha 改成 0.5，
材质 14 保持不透明，验证不同纹理、半透明剔除 NONE、不透明恢复 CCW。
原始模型、PMM、骨骼权重和几何保持原样。

## 已取得的证据与当前限制

真实 v1 PMM 中的模型槽位 2 实际加载 `Miku_Hatsune_metal.pmd`。
材质 12、13、14 的索引范围依次为 `64515+216`、`64731+336`、`65067+216`，
运行时依赖检查均通过。材质 11 被 `dependent_model_batch` 阻断，不能纳入这次范围。
自然场景三个材质共享 Toon 1；不同 Toon 的场景证据来自明确标记的临时控制副本。

2026-10-06 恢复 GPU 环境后，最新的日志隔离／模型卸载构建完成以下最终复验，
均为单采样，NVIDIA TITAN Xp。两个架构的 DX9 设备探针各创建参数均返回成功：

| 构建与场景 | 模型提交 | 字段审计 | 图像前缀 | 生命周期 |
| --- | --- | --- | --- | --- |
| x64 原场景 audit | 228 | 684 次，零差异 | 684 次，零差异 | 4/4 |
| x64 原场景 direct | 550 | 不读取 DX9 GPU 状态 | 1650 次，零差异 | 4/4 |
| x64 Toon／Alpha 控制 audit | 421 | 1263 次，零差异 | 1263 次，零差异 | 4/4 |
| x64 Toon／Alpha 控制 direct | 501 | 不读取 DX9 GPU 状态 | 1503 次，零差异 | 4/4 |
| x86 原场景 audit | 344 | 1032 次，零差异 | 1032 次，零差异 | 4/4 |
| x86 原场景 direct | 572 | 不读取 DX9 GPU 状态 | 1716 次，零差异 | 4/4 |
| x86 Toon／Alpha 控制 audit | 338 | 1014 次，零差异 | 1014 次，零差异 | 4/4 |
| x86 Toon／Alpha 控制 direct | 510 | 不读取 DX9 GPU 状态 | 1530 次，零差异 | 4/4 |

合计 3464 个完整模型提交、3993 次字段审计、10392 次图像前缀和 32 次生命周期检查，
全部通过。每组都覆盖跳帧、实际播放／停止、编辑、Save As 回读及重新打开。
每个模型提交都具有三个材质顺序记录和三个图像记录；audit 还有三个字段记录。
直接模式使用同一构建、场景和控制参数的本轮 audit 准入。
证据：`exports/cpu-multimaterial-resume-{opaque,switch}-{audit,direct}-{x64,x86}`。
本次应用 SHA-256：x64 `1d3d1a9e120b30b2b4f758b5576f143cea974abf9dc143239d01dbc996e564e7`，
x86 `ca91adeac61798d4ad9bccee8860cccd38986a597e9f9ac0b4f389284c40568a`。
后续增加历史诊断的应用会产生新的 hash，不能继承这些直接模式准入。

最终构建 x64/x86 编译通过，输入、几何、重放、常驻资源、CPU 发布门禁及 AVI 回归各 6/6。
Windows 无界面资源测试 10/10；用户 Linux 主机同一入口 10/10，包含新增多材质测试。
macOS 的同一 CI 入口已包含该测试，本轮没有新增实测结果。

新增原生控制用例在 x64/x86 的 DX11、DX12 Hardware/WARP 各 4/4：
将生产者生成的连续四批次与独立原生命令逐前缀比较，包含纹理切换、Alpha 混合、
同深度 `Less` 拒绝、关闭采样时忽略残留纹理绑定。还验证共享纹理只上传两次。
已有目标重建、1000 次资源版本更新、8 次目标调整、设备替换测试继续通过。

此前 DX9 创建设备的 `0x8876086C`／`0x8876086A` 阻断已经解除。
探针证据：`exports/cpu-multimaterial-resume-probe-{x64,x86}.log`。
旧失败及日志切换中的不完整记录仍保留，不计入本轮通过数量。

其他证据在 `exports/cpu-multimaterial-final-*`、`exports/cpu-multimaterial-controls-{x64,x86}.log`、
`exports/cpu-multimaterial-final-unit-{x64,x86}.log`、`exports/cpu-multimaterial-portable.log`、
`exports/cpu-multimaterial-linux.log`。早期失败保留，不计为通过。

最终复验完成后，开始接入 [同帧 CPU 材质与前序历史](RHI_CPU_SCENE_HISTORY.md)。
该诊断使用完整命令重放恢复颜色、深度和模板，逐绘制对照实际 DX9；不使用解析颜色替代深度历史。
它仍默认关闭，历史对照未通过时不允许启用应用后端替换。
