# 应用内实时 CPU 场景诊断

2026-10-13：独立 CPU 帧组装与常驻 DX11/DX12 预览已通过 x86/x64 真实 PMM 九阶段验收，包括实际窗口缩放、最小化恢复和设备替换。两种架构各 1145 条逐边界图像/离屏生命周期记录零差异；完整范围与资源复用证据见 [CPU 完整帧与常驻预览](RHI_CPU_FRAME_PREVIEW.md)。预览默认关闭，主窗口保持 DX9。

2026-10-12 最新结果：共用矩阵准备及默认关闭的高光策略已通过 x64/x86 真实 PMM 九阶段实时审计，两种架构各 1145 条图像／生命周期记录通过。修正了 x86 饰品 Ambient 镜像在播放启动时被误作规范灯光 RGB 的发布问题。配置、原因、证据与验收范围见 [高光兼容策略](RHI_SPECULAR_COMPATIBILITY.md)；下方保留各阶段的历史记录。

`MIKUDANCESTUDIO_DIAG` 构建可将独立 Alpha 候选用于应用内的 DX11/DX12 诊断设备。
应用实际呈现仍由 DX9 负责；没有默认开启候选策略或切换整个渲染器。

## 配置和责任

- `MDS_RHI_DIAGNOSTIC_ALPHA12=1`：进程内冻结一份 `ModelOptions`，子集、完整场景和替换设备均使用相同策略。设备日志和生命周期日志记录实际策略。
- `MDS_RHI_DIAGNOSTIC_TEXTURE_FMA=1`（工具参数 `--texture-fma`）：仅对 `Dx9Measured` 诊断设备启用法线纹理坐标的有序乘加，每步舍入到 float32。DX11/DX12 使用同一着色器源码；默认关闭。设备、生命周期及逐绘制日志记录并校验该策略，设备替换保留相同配置。
- `MDS_RHI_CPU_LIVE_HISTORY=1`：完整历史由明确的检查点请求启动。请求在正常场景清屏边界消费，每个进程最多 16 个，结果完整写出后才确认。普通帧不启动历史读回。
- CPU 场景生产者继续提供几何、材质、纹理层和顺序；原生捕获只作字段、资源字节及逐绘制图像的参考。共用 `SceneRenderer` 管理上传、提交及恢复。
- 每个检查点逐绘制比较当帧的实际批次数，再进行三次无新增上传的最终帧提交、目标缩放及设备替换。旧提交必须拒绝，纹理从 CPU 数据恢复，图像要求零差异。
- 播放状态在场景清屏边界固定；播放／停止状态与检查点不符时立即阻断。GUI 等待期间只使窗口失效，不反复投递 `WM_PAINT`，以免 GPU 捕获期间积压消息、延迟播放和保存命令。

历史和 CPU 替换报告按进程及捕获编号保存，避免多个帧覆盖一份证据。完整图像报告额外记录检查点、阶段、播放状态、PMM 版本和 Alpha 策略；资源报告保存 ID、版本、层数和内容摘要。

## 实时输入边界

旧运行时在帧尾为 HUD 开启混合，下一帧地面可能继承该状态。`ModelFrameInputs::groundAlphaBlend` 将它变成显式 CPU 输入，由帧尾及设备创建／Reset 维护。地面生产者据此选择混合状态，透明地面仍写深度；它不查询 DX9 状态来填充自己的输入。

动态 `screen.bmp` 饰品仍可能引用 DX9 画面捕获纹理，这种场景以 `cpu_accessory_screen_source_native_only` 阻断。不能以第一帧未绑定纹理时的通过结果宣称后续帧通过。
`--screen-source empty-background` 是显式限定的临时 GUI 配置：通过现有菜单选择背景屏幕来源；若背景资源实际绑定，原有阻断继续生效。它不代表动态屏幕纹理已经迁移，也不修改原始 PMM 素材。

## 重现

GPU 流程串行执行，证据目录必须新建：

```powershell
python tools/run_cpu_geometry_diagnostic.py `
  --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe `
  --application build-x64/build/Release/MikuDanceStudio.exe `
  --fixture C:/Users/jstzw/Downloads/MikuMikuDanceE_v932/UserFile/sample.pmm `
  --output exports/cpu-live-example-x64 `
  --preview --materials 12,13,14,15,16 --play --lifecycle --inputs audit `
  --history --history-export --ground --projected-shadows `
  --cpu-prefix full-scene --mip-prepare dx9 --alpha12 --live-history `
  --screen-source empty-background
```

流程要求 v1 加载／编辑后、两次跳帧、实际播放、停止保存前，以及 Save As 后 v2 回读／编辑、跳帧、播放和停止的九个检查点。任一检查点未完成、字段或资源不一致、图像差异、设备创建失败及不支持操作都会阻止整组通过。

`--inputs direct --accepted-audit <目录>` 继续要求已通过的审计匹配应用／GUI／原始素材哈希、材质选择和全部诊断配置。CPU 输入契约已更新为 4。独立实时预览的开放仍以完整实时审计通过为前提。

## 实测结果与剩余验收（2026-10-08）

2026-10-12 的默认关闭纹理坐标策略及最新复验见 [法线纹理坐标兼容策略](RHI_TEXTURE_COORDINATE_COMPATIBILITY.md)：x64 九阶段通过；x86 的新阻断已通过互换高光值定位，仍未通过全场景验收。下面保留先前诊断记录。

- x64/x86 最新应用及 GUI 驱动构建通过；两种架构各 8 项 CPU CTest 通过，覆盖场景输入、几何、纹理准备、命令流和 `SceneRenderer`。`python tests/test_cpu_live_evidence.py` 的 4 组验收测试通过，包含状态错标、缺失边界／生命周期、像素错误及缺失／重复阶段的拒绝用例；也已注册为主构建和跨平台资源测试的 `cpu_live_evidence` CTest，独立资源构建的该项测试通过。Linux/macOS CI 尚待实际执行。
- `exports/cpu-live-bounded-audit-x64` 保存了 5 个检查点的 585 行图像／生命周期结果：每帧 57 次绘制，两后端逐边界零差异，重复提交、目标缩放和设备替换通过。它同时暴露了 GUI 消息积压：名为 `playing` 的检查点实际记录 `playing=0`，随后 Save As 对话框超时。**整组失败，不构成播放或 v2 回读通过的证据。**
- 已修正消息积压、同步执行播放／停止命令，并在诊断测试使用更长的播放区间，避免慢速 GPU 读回期间播放自动到达终点；停止后使用实际帧号编辑框及 Enter 提交返回第 0 帧。最新严格验收要求所有边界的播放状态、PMM 版本、两后端顺序及资源账本完整一致，且核查原始 PMM 未修改。
- 修正后的 x64 再运行及最新 x86 GUI 运行都在设备创建处停止；`exports/cpu-live-pump-probe-x64.log` 和 `exports/cpu-live-pump-probe-x86.log` 中所有 DX9 HAL 创建尝试均返回 `0x8876086C`，适配器名称为空。旧探针程序本身退出 0 不代表设备创建成功；已补齐适配器、窗口创建阶段和每次设备创建的 HRESULT 门禁。新探针的 `exports/cpu-live-gated-probe-x64.log` / `cpu-live-gated-probe-x86.log` 均报告 `SUMMARY status=FAIL passed=0 failed=12` 并退出 1。`exports/cpu-live-gated-audit-x86/run.json` 保留此次 GUI 失败结果。

### GPU 恢复后的结果

- `exports/cpu-live-restored-audit-x64/run.json` 已通过：9 个 v1/v2 检查点、488 个批次、1145 个逐绘制边界，DX11/DX12 零差异；真实播放状态、Save As 和 v2 回读、资源账本、Mip、缩放、设备替换、描边和投影阴影均通过，原始素材哈希未变。
- x86 探针同样通过 12/12，但实时审计尚未稳定通过。`cpu-live-restored-audit-x86b` 在 v1 播放的第 39 个模型批次出现一个蓝／绿通道差异；重跑 `cpu-live-restored-audit-x86c` 又在 v2 第二次跳帧的第 23 个批次出现一个蓝通道差异。两次均为 DX11 与 DX12 同时重现、各 1 像素，位置和帧随播放时序变化，不能用容差掩盖，也不能据此开启跨平台预览。
- 已加入失败边界契约归档：`.contract.csv` 会保存该绘制的 world/view/projection、索引范围和顶点／索引／纹理资源 ID 与版本，与像素差异文件成对输出。下一轮 x86 复验先对照这些字段，确认误差来自 CPU 姿态矩阵、资源版本还是后端逐像素求值，再实施定向修正。
- `exports/cpu-live-summary-audit-x86` 的最新复验在 v2 第二次跳帧、模型批次 23 仍得到 `(583,255)` 一个蓝通道差异；契约归档明确标记 `portable_contract_exact_backend_precision`。字段差异中的 `diffuse[0]` 是被 `Active()` 清除的非着色摘要，不属于实际替换契约；矩阵、状态、几何和纹理仍逐项一致。当前应继续做后端精度探针，不能修改场景输入或放宽比较。

目前未完成最新驱动下的真实播放、Save As/v2 回读、描边／阴影以及 x86 实时图像验收；也未开放独立预览窗口。已有检查点使用独立临时 `SceneRenderer`，缓存复用与恢复证据限于检查点内部，不代表持续跨帧 GPU 常驻资源已验收。GPU 恢复后须先用新证据目录完成上述九阶段审计，再为持续实时 CPU 命令流建立常驻资源和独立呈现窗口。动态屏幕纹理、MME、MSAA 和场景后的 HUD／自阴影合成仍属于另外的支持范围。
