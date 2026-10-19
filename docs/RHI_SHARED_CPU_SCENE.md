# 独立预览的共享 CPU 场景

2026-10-19 后续：最终骨骼相机／饰品绑定和可选 CPU 场景通道见
[绑定与场景通道](RHI_CPU_BINDINGS_PASSES.md)。以下保留共享世界阶段的验收范围。

2026-10-16。独立 DX11／DX12 模型材质预览接入 `RuntimeCpuScene`，由同一世界求解所有模型。
窗口仍默认关闭，主编辑器仍使用 DX9。设备替换只恢复渲染资源，不重建或推进 CPU 世界。

## 职责与生命周期

`SceneSession` 持有 PMM 文档、模型引用、相机／灯光／重力和可移植轨道状态。
`RuntimeCpuScene` 持有它的独立实例，以及模型槽表、一个 Bullet 世界、共享 CPU 几何资源命名空间、
播放游标和剩余时间。`RuntimeCpuModel` 在场景内借用该世界与资源命名空间，单独使用时仍可拥有私有世界。

`RuntimeCpuScene` 不接收设备、窗口或交换链。输出的 CPU 几何继续经过
`CpuSceneFrameAssembler → SceneRenderer → DX11/DX12`；预览控制器负责呈现、缩放和设备替换。
场景销毁先逆序释放模型约束／刚体和 CPU 几何，再释放世界。失败的加载候选不会替换已有场景。

接口包括 `Load`、`LoadModel`、`Seek`、`StartPlayback`、`Pause`、`Advance`、`Tick`、`Edit` 和只读状态快照。
`Advance` 的时间参数为绝对秒数；`Tick` 只运行该帧物理，不自动推进轨道。
跳帧采用旧运行时的 seek 和 settle 规则，不承诺从头重新模拟到该帧的物理结果。

## 轨道与求解

`runtime_cpu_tracks` 校验并发布 PMM 的骨骼、morph、显示／IK、选择器关键帧，保留稀疏索引与链关系。
v2 的 IK 与选择器来源映射到模型记录；骨骼／morph 的数量及名称必须匹配。
重选后结构不同、父模型缺失、链损坏和不支持的物理模式会明确失败，不按错误索引继续运行。

原生 `SeekModelFrame`、`InitModelTrackCursors`、`AdvanceModelKeyframes` 保留物理 arming 和备份语义。
编辑器与独立场景共用 `ApplyCpuPmmPose`：有刚体或选择器的骨骼由原生推进处理，其余符合类型条件的
骨骼才由可移植轨道覆盖。所有模型按显示顺序求姿态、按槽位同步刚体，再由共用调度器推进一个世界。
骨骼回读后调用现有 PMD／PMX 蒙皮；PMX 骨骼 morph 和 SDEF 可走原有 CPU 运算。

无网格 Dummy Bone 继续参与绑定和求解，输出零绘制资源。
PMM 编辑后重新验证、发布轨道并跳到当前帧。写回同时补齐物理模式、v1 骨骼／morph／IK 关键帧，
插值控制字节按文件的 lane/group 顺序排列；v1 不接受写入文件中不存在的逐关键帧物理禁用字段。

## 验证入口

```powershell
ctest --test-dir build-x64/build -C Release --output-on-failure -R '^runtime_cpu_scene$'
ctest --test-dir build-x64/build -C Release --output-on-failure -R '^rhi_independent_'
```

CPU 测试生成自有 PMD／PMX／PMM 素材，验证物理模式 0–3、双模型共享世界、IK、物理禁用切换、
PMX 骨骼 morph／SDEF、跳帧、播放、暂停、轨道编辑、失败候选与重复加载。
与保留的旧调度控制流比较四组骨骼矩阵、姿态、arming／备份／工作副本、游标、IK 状态、
刚体当前／插值变换和线／角速度。它验证相同输入和时间规则，不把不同 UI 时间步进当作等价输入。

真实本地 PMM 可另行运行，素材不进入仓库：

```powershell
runtime_cpu_scene_test.exe --scene sample.pmm C:/path/to/UserFile/Model
```

图形 CTest 在每个后端、架构与驱动组合运行 11 个生成素材及一次应用早期启动入口，
覆盖六帧动画／轨道编辑、Save As／回读、缓存复用、缩放、最小化恢复及设备替换。
设备替换还核查 CPU 状态指纹，避免图像一致却意外重置求解状态。

真实含饰品 PMM 的模型材质子集需要显式 `--model-materials-only`。
该选项仍加载并求解所有模型；它不表示已呈现饰品等完整场景通道。
`--model-slot` 则只加载指定模型，存在未加载选择器父模型时拒绝运行。

## 本轮实测结果

| 验收 | x64 | x86 |
| --- | --- | --- |
| CPU／轨道／写回 CTest | 8/8 | 8/8 |
| 自生成场景与旧调度流程的精确 CPU 检查点 | 152 | 152 |
| DX11／DX12，硬件与 WARP | 4/4；每组 11 个素材及应用启动 | 同左 |
| 真实 `sample.pmm` CPU 对照 | 3 模型、45 刚体、12 检查点一致 | 同左 |
| 真实 `sample(AllStar).pmm` CPU 对照 | 11 模型、275 刚体、12 检查点一致 | 同左 |
| 真实 `sample.pmm` 独立模型材质预览 | DX11／DX12 六帧、编辑、保存回读与设备恢复通过 | 同左 |
| DX9 设备创建探针 | 12/12 | 12/12 |
| 主应用真实 v1/v2 图形回归 | 9 检查点，1145 项整帧／逐绘制检查通过 | 同左 |

主应用图形回归覆盖缺失模型重选、跳帧、播放、编辑、Save As／回读，
以及两个预览窗口的反复开关、缩放、最小化恢复和设备替换。
CPU 字段、资源账本与图像比较均通过。这里使用独立 CPU 输入的应用诊断，
不是把独立宿主的物理时间步进直接等同于 UI 的时间步进。
格式专用构建的 PMM 写回测试也通过。
关闭 `MIKUDANCESTUDIO_DIAG` 的 x64 产品构建通过，DX11／DX12 硬件各运行 11 个生成素材
和一次应用早期启动入口，六帧播放／编辑、保存回读及设备恢复均通过。

最初 x64 时间轴测试失败的记录保留：测试换到双模型场景后沿用了上一场景的已编辑姿态。
修正各模型的测试初始化，并为默认 CTest 生成素材后，8 项 CPU 回归全部通过。
这项失败及修正后的日志在证据索引中分别列出。

## 边界

共享调度／时间状态层可在 Windows、Linux、macOS 构建；本次原生模型适配器仍依赖 Windows
模型记录和 D3DX CPU 数学。它不创建 DX9 设备、VB／IB／纹理，也不读取 DX9 GPU 状态。
不能据此声称整个 IK／物理／蒙皮已移植到 Linux/macOS。

预览当前支持单采样模型材质。QDEF、活动材质 morph、结构不匹配后的名称重映射、
相机绑定及饰品／阴影／背景／MME 等完整呈现仍有独立门禁。
生成素材和设备替换图像验收不能替代真实 DX9 与 DX11／DX12 的逐像素对照；
DX9 无法创建设备时继续记录阻断，不放宽原有精度要求。
本轮通过也不关闭此前记录的偶发后端精度回归，默认主渲染路径保持现状。

本轮实测证据索引：`exports/shared-cpu-scene-acceptance.json`。
