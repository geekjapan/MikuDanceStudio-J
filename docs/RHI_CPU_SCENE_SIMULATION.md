# 共用 CPU 场景调度与时间状态

2026-10-14。将编辑器的追帧、重力／风、主步进和三次 settle 从窗口函数中提取。
这一步提供无 GPU 的共用调度。2026-10-16 的[共享 CPU 场景](RHI_SHARED_CPU_SCENE.md)已将其接入独立模型预览；下文保留本阶段提取与验收记录。

## 职责

`cpu_scene_simulation.hpp` 不包含 Win32、D3DX、模型布局或 RHI 类型。
`CpuSimulationState` 按场景保存播放游标、追帧后的剩余时间、物理模式、重置／移动标记，
以及重力方向、大小、风参数和风计时器。原来的进程全局 `g_CatchupDtBudget` 已删除。

`CpuSimulationContext` 借用调用方拥有的模型槽位及**一个共享 Bullet 世界**。
所有模型同步完成后才步进世界，禁止逐模型各自推进时间。销毁模型、世界和资源仍由
宿主负责；该视图不会延长它们的寿命。每次调用必须提供有效的世界及操作表。

`CpuSimulationOps` 把调度与现有 CPU 算术分开：模型姿态、刚体同步／重置／读回、
向量归一化和随机数都由适配器提供。Windows 的 `LegacyCpuSimulationOps` 调用原有
IK、morph、刚体函数和 D3DX 归一化，不创建 DX9 设备。随机输入契约为 `[0,32767]`；
Windows 适配器保留 `std::rand()`，其他宿主须提供同范围的生成器。

| 接口 | 责任 |
| --- | --- |
| `RunCpuSimulationCatchup` | 固定子步进、选中槽位跳过、时间余额扣减、最终游标钳位及时间轴回调 |
| `RunCpuSimulationFrame` | 重力／风、选择上升沿重置、物理前姿态、主步进、额外步进、settle、读回、物理后姿态 |
| `CpuSimulationHooks` | 在原诊断采样边界观察状态；时间轴回调由宿主提供 |
| 编辑器桥接 | 将 ABI 状态导入／导出；时间轴更新全局轨道后重新导入，避免覆盖新重力值 |
| 窗口宿主 | 墙钟／录制目标、结束／循环、音频、窗口消息与选择滞留门禁的写回 |

`FrameDriver` 中的 Kinect 泵及选择滞留标记写回位置保持原样。`SceneRenderer` 和
DX11／DX12 后端继续只消费求解后的输入，不负责动画或 Bullet 调度。
这延续了 Unity 调研采用的职责边界：CPU 场景生产输入，共用渲染器管理资源与提交，
设备后端执行绘制。求解层不反向读取 GPU 状态来补全场景。

## 必须保持的时序

* 时间余额在每趟追帧前初始化；录制使用 `1/fps`，其余使用本帧 elapsed time。
  每次实际子步进扣除 float `1/60`，主步进只消费余额。负余额原样传给 Bullet。
* 追帧先将游标加 `1/60`，再判断是否进入循环；每次关键帧前进 → 物理前姿态 →
  正向运动学同步 → 世界固定步进 → 扣余额 → 加游标。最后设到目标并执行一次完整时间轴回调。
* mode 1/2 可运行世界；mode 3 需要移动、重置或播放活动。mode 0 仍执行前后姿态通道。
  移动且 mode 3 时主步与额外步都是 `1/60`。
* settle 是三次“动态刚体重置 → 固定世界步进”，其后清重置标记。
  刚体读回和移动标记清除留在世界门禁内，不能移到第二次姿态通道后。
* 风计时器严格 `>0.5` 才取四次随机数；开启风时不再执行普通重力。
  Windows x86 保留原 x87 中间精度和 float 存储边界，x64 保留原单精度表达式。
  零重力方向的 Y 修正写回场景；饰品编辑门禁位于重力／重置请求之后。

## 验证

`cpu_scene_simulation` 不初始化窗口或 GPU，使用真实 Bullet 检查 512 组门禁与模式组合，
对照提取前冻结的控制流程，逐位比较当前／插值刚体变换、线速度和角速度。
还覆盖不均匀追帧、暂停、回退、重置、负余额、风阈值、随机数调用次数和场景状态隔离。

`cpu_scene_simulation_native` 使用实际 PMD／PMX CPU 模型记录、原生 CCD IK、骨骼 morph、
最高槽位及跨模型父绑定，与独立保留的旧遍历／调度对照最终四类骨骼矩阵、物理备份及刚体速度。
它同样不创建 GPU 设备。对照中的 PMD／PMX 指运行时记录，不能替代真实模型文件的端到端验收。

独立测试入口无需 Conan：

```sh
cmake -S cmake/cpu-simulation-tests -B build-cpu-simulation -DCMAKE_BUILD_TYPE=Release
cmake --build build-cpu-simulation --config Release --parallel 4
ctest --test-dir build-cpu-simulation -C Release --output-on-failure
```

它从仓库已有源码构建 Bullet；兼容辅助函数的 `noinline` 声明改用编译器属性，
保留 Windows 的原声明和运算，只修复 GCC／Clang 无法解析 `__declspec` 的构建问题。
CI 的 `cpu-simulation` job 覆盖 Windows／Linux／macOS；本地 Windows 及授权 Linux 机器
已实测通过，macOS 尚待 CI 结果。完整图形验收的二进制哈希和报告索引记录于
`exports/cpu-scene-simulation-acceptance.json`，该文件为本地生成证据。

本轮最终验收：Windows x64/x86 各 5 项 CPU 回归通过；独立 DX11／DX12 的硬件／WARP
生命周期各 4 项通过。关闭诊断的 x64 产品构建也通过两个硬件后端的六素材测试。
最终二进制的真实 PMM v1/v2 图形检查，x86 首轮和 x64 重试各 9 个检查点通过，
覆盖跳帧、播放、编辑、保存回读、缩放、最小化恢复及设备替换。

必须同时保留 x64 最终二进制第一次复跑的失败：第 22 批次、帧 5 的
`(991,508)`、`(993,509)` 蓝通道分别为原生 121／97、两个后端 120／96。
坐标和值与上一轮记录相同；CPU 输入契约没有失败，问题归入后端精度回归，根因仍未确定。
重试通过不证明重复运行稳定，也没有据此开启新的默认绘制路径。

## 独立预览的时间修复与剩余门禁

独立材质预览原先把 delta seconds 传给 `SceneSession::Advance`，而该接口需要**绝对播放时间**。
宿主现持有累加游标；跳帧重置该游标，暂停不累加，重新启动轨道后推进到同一绝对位置。
六帧生成场景测试检查最终游标确实超过第 4 帧，并继续检查几何版本更新和设备替换图像。

2026-10-16：场景宿主、共享世界和 PMM 轨道桥接已接入，详见
[独立预览的共享 CPU 场景](RHI_SHARED_CPU_SCENE.md)。`RuntimeCpuModel` 在场景内借用统一世界，
无网格模型参与求解但不创建绘制资源。物理和 IK 使用原生 CPU 函数；不支持的绘制特性继续阻断。

原生骨骼求解仍使用 Windows 模型布局和 D3DX CPU 数学。这里的可移植结果是**调度与状态层**，
不是已经完成平台无关的整个 IK／物理／蒙皮实现。
