# 无 DX9 设备的启动与模型导入

2026-10-14。此项交付建立可选的模型材质预览入口，移除这条入口的
DX9 设备初始化和导入资源依赖。旧编辑器主窗口仍走原路径。

## 职责与数据流

`WinMain --rhi-preview` 在 `EffectRuntime`、`InitDefaults` 和
`InitMainWindowAndD3D` 之前分流；独立工具 `mds_rhi_preview` 使用同一个宿主。

```text
PMM / PMD / PMX 文件
  → SceneSession / ModelDocument
  → RuntimeCpuModel（CPU 导入、原有蒙皮运算、文件纹理解码）
  → CpuSceneFrameAssembler（有序材质片段、稳定资源 ID / 版本）
  → SceneRenderer（上传、复用、提交与释放）
  → 后端工厂 + ScenePreviewController
  → DX11 或 DX12 设备与交换链
```

这沿用 Unity 调研得到的职责边界；未复制 Unity 源码或接口。
CPU 模型没有原生 VB/IB/纹理，窗口配置没有读取 DX9 呈现参数，正常提交不捕获
DX9 状态。图像回读仅在有界验收模式启用。

* `ModelResourceMode::LegacyDx9` 是原调用者的默认值，原 UI、IK、物理时序不变。
* `CpuOnly` 跳过 GPU 创建、纹理缓存和 `PostLoadInit` UI 更新，不改变进程 CWD。
* `SceneConstruct(scene, nullptr)` 创建相同配置的 Bullet CPU 世界，跳过 GPU gizmo。
* `RuntimeCpuModel` 接受宿主已经求解的最终蒙皮矩阵和 morph 权重，复用原有
  PMD/PMX 蒙皮与顶点/UV morph 运算。失败导入保留原模型；结构不完整的文件
  在进入旧导入适配器前被拒绝。
* 材质片段直接携带材质编号、资源引用及纹理身份，宿主无需解析诊断标签。
  共享纹理保持同一身份，几何变化只推进对应版本。
  CPU 材质通过不可变资源引用共享解码和 Mip 数据；片段逐条交给帧组装器，
  组装器按身份只保留一份待提交字节，避免大 PMX 在 x86 中按材质复制数据耗尽地址空间。
* 纹理使用 CPU 文件/内嵌资源、共同解码和 `BoxLinear` Mip 准备，无 DX9 纹理准备器。
  这个策略的图像不承诺与旧 D3DX Mip 准备逐像素相等。

目前 CPU 记录和原有数学适配器仍是 Windows 实现，并使用 D3DX 的 CPU 数学函数。
**不需要 DX9 设备，不等于已经消除 Windows/D3DX DLL 依赖。**
可移植 `ModelDocument`、场景组装器与 RHI 接口仍是后续非 Windows 宿主的入口。

## 使用

构建启用 `MIKUDANCESTUDIO_RHI_PREVIEW` 及所选后端，或已有 DIAG 构建。

```powershell
mds_rhi_preview.exe dx11 model.pmx
mds_rhi_preview.exe dx12 model.pmd --warp
MikuDanceStudio.exe --rhi-preview dx11 scene.pmm
mds_rhi_preview.exe dx12 scene.pmm --reselect 1 model.pmd --model-slot 1
```

空格切换播放，左右键跳帧，F5 替换设备。`--model-slot` 是显式子集查看。
窗口标题与输出标为模型材质预览，不代表完整场景。
`--frames 6 --lifecycle` 用于自动验收；`--save-as new.pmm` 验证配置字段编辑、
保存与回读，拒绝覆盖已有文件。写出前在内存中完成回读校验。

输出中的 `native_model_buffers=0` 来自导入后的句柄检查；
`legacy_startup=bypassed` 表示入口的代码分支，不是一个虚构的 GPU 设备计数器。

## 验收

`tests/cpu_import_fixture.py` 生成项目原创三角形、BMP、PMD、PMX 及 v1/v2 PMM；
没有外部素材，也没有因素材缺席而跳过的成功项。`rhi_independent_*` CTest
分别运行 DX11/DX12、硬件/WARP，覆盖：

1. 原始 PMD、仅 Sphere 的 PMD、PMX，以及 PMD v1/v2、PMX v2 场景。
2. 场景跳帧、播放和配置字段编辑；确认动画产生新的 CPU 几何版本。
3. 连续绘制保持纹理上传次数；缩放、真实窗口最小化/恢复。
4. 设备替换拒绝旧提交，用保留 CPU 数据恢复，替换前后同帧 RGBA 完全一致。
5. Save As、回读和释放；额外启动主程序的早期分流入口。

`runtime_cpu_model` 覆盖含刚体/关节记录的 PMD/PMX CPU 导入、原有蒙皮、
PMX 顶点 morph、重复更新版本稳定、NaN 拒绝、失败加载和截断文件保持旧数据。
生成的单显示分组 PMX 同时回归修复了旧加载器分组表越界写入。
`rhi_scene_frame` 验证 257 次重复绘制的待提交字节数保持不变，并覆盖
同一纹理有不同局部 ID 时的重映射；`rhi_model_inputs` 验证不可变纹理引用与值输入一致。

本机图形环境：NVIDIA TITAN Xp 与 Microsoft Basic Render Driver；
x64/x86 的结果与最终二进制哈希记录在 `exports/rhi-independent-acceptance.json`。
真实外部初音 PMD 和 Sour Miku PMX 的材质预览另有同目录日志；这些素材不纳入仓库。

最终复验结果（2026-10-14）：

| 构建／环境 | 结果 | 实际覆盖 |
| --- | --- | --- |
| Windows x64 | 12/12 CTest 通过 | CPU 导入、蒙皮、帧组装、共用提交、DX11/DX12 硬件与 WARP 启动及恢复 |
| Windows x86 | 11/11 CTest 通过 | 同上；此构建没有单独配置 `pmd_skinning` 测试 |
| Linux | 13/13 CTest 通过 | 无界面资源、材质输入、帧组装、缓存及生命周期；不包含 Windows CPU 导入适配器 |
| x64 正式配置，`DIAG=OFF` | DX11/DX12 × 硬件/WARP 四组通过 | 每组六个生成素材及一次主程序早期入口启动，共 28 次进程启动 |
| 真实 PMD/PMX | x64/x86 × DX11/DX12 八组通过 | 每组六帧材质绘制、纹理复用、缩放、最小化恢复、设备替换及卸载 |

真实模型的验收是 bind pose 材质预览；设备替换前后同一后端的 RGBA 字节完全一致，
不代表已验证这些模型的完整动画或与 DX9 的新一轮逐像素相等。PMM 跳帧、播放、
配置字段编辑与保存回读由生成的 v1/v2 场景覆盖；本轮没有新增 macOS 实机结果。
正式配置和真实模型日志分别为 `exports/independent-product-accepted.log` 与
`exports/independent-real-models-accepted.log`，逐组日志和二进制 SHA-256 见验收 JSON。

同一轮环境中，旧 DX9 设备探针返回 `0x8876086A` / `0x8876086C`，四项依赖
DX9 的旧导入回归被跳过；这些不计为通过。新的 DX11/DX12 启动、导入和
呈现验收继续运行，证明这条入口不会再被 DX9 设备创建失败阻断。

## 尚未覆盖的功能与实施顺序

后续复验补充：2026-10-14 用户恢复设备后，x64/x86 探针各 12 组通过，
上述四项旧导入回归在两种架构上全部通过。原始失败记录保留，不回写为成功；
新日志为 `exports/dx9-import-retry-20261014-x64.log` 与 `-x86.log`。

此入口支持模型材质、原始模型 bind pose，以及无相关求解依赖的 PMM 骨骼播放。
以下状态明确拒绝，而非生成一个冒充完整场景的近似结果：

* PMM 所需的 IK/物理最终矩阵、相机绑定，以及骨骼 morph 的最终姿态。
  SDEF/QDEF 场景求值尚未开放；CPU 蒙皮保留原 SDEF 工作者，QDEF 明确拒绝。
* 材质 morph、额外 UV 布局、完整 PMX 描边绘制尚未验收。
* 饰品、地面、投影阴影、自阴影、背景、MME、HUD/文字、MSAA 不属于这个
  模型材质宿主的提交范围。原编辑器菜单预览维持原有支持门禁。

下一项首先提取**原有 CPU 求解调度**：由同一套跳帧/播放时序提供最终矩阵，
再接入这个已无 GPU 所有权的模型适配器。不能用独立的近似 IK 或物理替代。
随后验证 PMX 材质 morph、附加 UV、描边；再定义多通道附件读写依赖，
由 DX11 后端处理绑定冲突，DX12 后端处理状态与屏障。
原有姿态／刚体模型遍历阶段已开始提取，见 [CPU 求解调度](RHI_CPU_POSE_SCHEDULE.md)；
独立宿主的完整物理时钟接入仍在其后。
主窗口、剩余 UI 绘制、截图录制、MSAA 和限定范围的 MME 在这些门禁后逐项迁移。
