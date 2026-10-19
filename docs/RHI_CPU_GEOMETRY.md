# 实时 CPU 几何与 DX11／DX12 诊断批次

这一步把模型变形结果的所有权从 DX9 顶点缓冲中分离出来。应用主画面仍由
DX9 绘制；新入口默认关闭，目前用于实时数据与独立批次的验收。

## 数据与职责

`render::ModelGeometry` 持有主顶点、描边顶点和连续索引的 CPU 数据。
模型加载时从加载器的 CPU 记录初始化，随后使用既有蒙皮运算产生结果。
PMD 的带填充索引在这里转换为连续 UInt16；PMX 按实际索引宽度转换，
转换前检查范围，避免先截断错误索引再验证。

`Publish()` 生成拥有字节数据的 `ModelGeometrySnapshot`。主顶点为
position/normal/UV 的 32 字节记录；描边输出为 position/RGBA8 的 16 字节记录。
旧运行时的 ARGB 颜色在这个边界转换为 RGBA。追加 UV 的 CPU 布局仍保留；
当前 RHI 布局未支持它们，`AppendModelGeometry()` 会明确拒绝。

资源 ID 由场景所有者分配，不使用模型指针作为 GPU 资源身份。主顶点、描边和
索引分别维护单调版本；字节不变时不增加版本。旧快照保留原有内容，模型重载
分配新 ID。卸载删除应用关联。纹理的内容哈希不当作单调版本号使用。

`AppendModelGeometry()` 将拥有 CPU 数据的几何接入共用命令流，随后由
`SceneRenderer` 管理上传、缓存、提交与完成后的回收。DX11／DX12 共享这份输入；
原生 buffer、描述符与 fence 留在后端。这里借鉴 Unity 的资源所有权、设备和
提交边界，不复制它的类继承体系。

## 应用桥接与开关

旧 IK、物理、Morph、边缘宽度和蒙皮运算顺序继续作为行为基线。默认关闭时，
加载器不建立额外几何，也不运行第二次蒙皮。

| 环境变量 | 行为 |
| --- | --- |
| `MDS_RHI_CPU_GEOMETRY=1` | 加载时建立 CPU 几何；每次更新独立计算并与旧缓冲逐字节对照 |
| `MDS_RHI_CPU_GEOMETRY_UPLOAD=1` | 当前模型独立对照通过后，以 CPU 数据填充旧 DX9 缓冲；不一致即关闭资格 |
| `MDS_RHI_CPU_PREVIEW=1` | 诊断构建：选定独立材质批次使用实时 CPU 几何在 DX11／DX12 离屏绘制 |
| `MDS_RHI_CPU_GEOMETRY_DIR` | 写入几何、设备创建和图像对照 CSV |

上传模式的后续字节校验检查上传是否正确，不能把复制后的校验计作独立蒙皮对照。
两种模式在 CSV 中分别标为 `independent_compare` 和 `upload`。
算术对照资格与当前帧可提交状态分开保存。产生新输出后，若原生缓冲锁定等
步骤未完成，该帧不能沿用上一帧的通过状态进入诊断绘制。

诊断批次使用从文件解码并已与原生纹理对照的 CPU Toon 数据，当前仅支持单层
纹理。多层／自动生成 Mip 缺少 CPU 数据时明确阻断。索引和顶点来自加载／蒙皮
CPU 记录，预览不通过读回 DX9 网格来获得它们。

材质、灯光、矩阵和完整混合／深度／模板状态仍在 DX9 绘制边界采集。
独立 Alpha 与模板测试按现有 `ModelPipeline` 契约传递；用户裁剪面、偏移、
雾、双面模板等未实现状态给出具体阻断原因。每个预览批次从独立清屏开始，
**没有继承实际场景的前序颜色／深度／模板历史**。

预览图像要求 DX11 与 DX12 逐像素一致，整段运行必须含有效绘制像素。
极小批次某一帧没有覆盖像素可记录为 `matched_empty`；整段空白不能通过。
设备创建失败与绘制失败分开记录，绘制失败关闭后续提交。

## 验证与复现

可移植 `rhi_model_geometry` 检查快照所有权、独立版本、ARGB 转换、索引范围、
重复发布及不支持布局。`rhi_scene_renderer` 使用实际 CPU 几何生产者测试
1,000 次更新和模拟延迟完成。独立资源套件包含 9 项测试，接入三平台 CI。

Windows `model_cpu_geometry` 运行既有 PMD／PMX 蒙皮 worker，覆盖
BDEF1/2/4、SDEF、全部 UV 步长、顶点／UV Morph 的恢复及重复应用、描边、
新模型 ID、错误索引和失败门禁。QDEF 保留旧运行时初始化姿态的行为，
这不表示已经补齐 QDEF 算法。

`rhi_backend_scene_test` 将真实 CPU 几何发布接口接入 Hardware／WARP 的
1,000 次版本更新、尺寸变化和设备替换；新设备重新上传同一快照并恢复图像。
DX12 另有 debug layer 和隔离设备移除测试。

真实场景的 GUI 脚本运行资源重选、编辑、实际前进／后退、可选播放／停止、
Save As、回读和重新打开，并明确统计独立对照、上传校验和预览图像。

```powershell
python tools/run_cpu_geometry_diagnostic.py `
  --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe `
  --application build-x64/build/Release/MikuDanceStudio.exe `
  --fixture C:/path/MikuMikuDanceE_v932/UserFile/sample.pmm `
  --output exports/cpu-geometry-new-run --preview --material 13 --play
```

加 `--upload` 验证 CPU 上传路径；更换 x86 可执行文件验证同一流程。
脚本要求使用新的证据目录。真实模型和图像属于外部素材，留在忽略的 `exports/`。

2026-10-05，本机 NVIDIA TITAN Xp 的实测结果：

| 验收 | 结果 |
| --- | --- |
| 真实 `sample.pmm`，x64 独立对照、实际播放／停止、材质 13 | 164 次独立字节对照、164 次 DX11/DX12 图像对照，全部零差异；7 个播放样本 |
| 同一场景，x86 CPU 上传、实际播放／停止、材质 13 | 2 次独立门禁对照、235 次上传校验、237 次图像对照，全部零差异；20 个播放样本 |
| 同一场景，x86 持续独立对照、材质 13 | 567 次独立对照、567 次图像对照，全部零差异，覆盖 0～10 帧 |
| 真实场景 x64 初始持续独立对照 | 589 次零字节差异，覆盖实际前进／后退的 0～10 帧 |
| Windows 可移植资源套件 | 9/9 |
| x64 / x86 几何、提交与恢复 CTest | 分别 10/10、9/9；Hardware、WARP 与 DX12 debug 均执行，未跳过 |
| 用户提供的 Linux 主机 | 9/9，包含 CPU 几何与版本／延迟回收测试 |
| macOS | 三平台 CI 已包含新增测试；本轮未取得新的 macOS 实测结果 |

两个架构的最终 GUI 流程均包含 7,111 项已有运行时对照、模型重选、编辑、保存、
回读和重新打开。真实图像范围限于单采样独立批次；未按架构之间做像素等价声明。
播放控制使用排队消息，避免跨进程同步停止调用阻断测试；GUI 子进程加入
kill-on-close job，控制程序超时后释放它启动的应用。

私有证据：`exports/cpu-current-ready-play-x64`、
`exports/cpu-current-ready-upload-x86`、`exports/cpu-live-preview-final-x86`、
`exports/cpu-geometry-step-compare-x64`；每个目录有 CSV 与 `run.json`。
恢复／生命周期日志为 `exports/cpu-gpu-contracts-x64.log` 和
`exports/cpu-gpu-contracts-x86.log`。Linux 日志为
`exports/cpu-resource-final-linux.log`。

## 尚未完成的边界

实时预览仅覆盖已选择的独立 PMD 材质。它没有证明 DX9 实际整帧与 DX11／DX12
完整画面一致，也没有接管应用交换链。Windows 蒙皮 producer 仍调用旧运算与
D3DX；跨平台数据契约可编译，不等于整个蒙皮求解器已移植到 Linux／macOS。

从 `SceneSession` 和 CPU 模型／材质记录直接生产矩阵、灯光、纹理绑定的接口已
接入默认关闭的诊断，见 [CPU 着色输入](RHI_CPU_MODEL_INPUTS.md)。真实 PMM 新门禁
已于 2026-10-06 在 x64/x86 通过：材质 13 的字段审计、直接 CPU 输入、
DX11/DX12 图像及目标／设备恢复均完成，证据见上文链接。随后扩展其他绘制家族
及通道历史。完整 PMX、多个模型、饰品、HUD、自阴影、MSAA 与 MME 分别验收，
见 [完整接入计划](RHI_DX11_DX12_ROADMAP.md)。
