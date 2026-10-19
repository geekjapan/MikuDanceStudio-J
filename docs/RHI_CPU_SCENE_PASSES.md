# CPU 地面与投影阴影前序生产

后续进展见 [完整 Mip 准备与模型材质契约](RHI_CPU_MIP_CONTRACT.md)：
以下保留本阶段模型前序因 Mip 阻断的记录，不能作为后续实现的当前状态。

2026-10-07。承接 [CPU 材质与前序历史](RHI_CPU_SCENE_HISTORY.md)。本阶段将地面线框、
地面深度平面和模型投影阴影改由 CPU 生产，在诊断命令流中逐项替换并验收。
应用实际呈现仍使用 DX9；自阴影、饰品和其他模型前序不能据此宣称完成迁移。

## 职责与输入

`render_scene_passes.hpp`／`scene_passes.cpp` 不依赖 Win32 或 GPU 对象。
`BuildGroundDraw` 产生固定网格、顶点颜色、索引和显式管线状态；透明地面平面仍写深度。
`BuildScenePassInputs` 从 SceneSession 相机／灯光、CPU 编辑器视图参数、材质和最终模型矩阵
生成投影阴影状态。地面投影使用场景坐标灯光方向；着色灯光使用另行旋转后的方向。
投影阴影的顶点／索引来自 CPU 模型快照，辅助纹理来自内嵌 PNG 解码字节。
旧运行时继续负责 IK 和物理的最终求解，生产者不读取 DX9 纹理或设备状态。

Windows 场景遍历只负责提供当前模型、材质、网格范围和提交顺序。
`SceneRenderer` 继续管理发布版本、设备身份、epoch、资源缓存和提交；DX11／DX12 执行相同数据。
这是沿用 Unity 的职责边界，并非复制其私有实现或让可移植层依赖 DX9。

## 原子替换与门禁

`SceneDrawReplacement` 标记绘制边界、家族、模型和材质，并持有单次绘制的完整 CPU 字节。
`ReplaceSceneDraws` 先验证场景、帧、目标、活跃管线／着色字段、几何范围及全部纹理层字节，
通过后才插入独立资源 ID 命名空间，保留版本及原绘制顺序。失败不修改输出，也允许输入输出别名。
原生捕获只作诊断基准，不能将其字段填回 CPU 输入以掩盖差异。
关闭灯光、Alpha 测试或模板测试时，仅忽略不会参与此次绘制的对应状态。

可选开关 `MDS_RHI_CPU_PREFIX`：1 为地面，3 为地面加模型投影阴影，7 额外请求模型材质前序。
MME 和不支持的操作仍阻断；请求家族缺少任一生产批次同样阻断。
未迁移的饰品等前序保留原生捕获来源。每个替换批次记录到 `cpu_prefix.<PID>.csv`，
包括帧号、边界、家族、模型、材质及失败字段。初始流程的 17 个模型阴影材质必须全部覆盖。

## 实测与重现

使用真实 `sample.pmm` 的临时副本开启地面与投影阴影，保留原素材。
图形流程包含模型重选、跳帧、编辑、实际播放、Save As、回读与两后端资源重建。
每组在初始／回读场景替换共 21 次 CPU 绘制，核查 182 个 DX11／DX12 图像边界和 4 次生命周期操作。
历史图像包含其他尚未迁移的原生捕获批次。图像要求零差异，空覆盖不计有效像素证据。

本轮通过的八组结果（每组均为 21 次 CPU 替换、182 次历史图像检查、4 次生命周期检查）：

| 架构／场景／模式 | 非空独立材质图像检查 | 证据目录（`exports/` 下） |
| --- | ---: | --- |
| x64 原场景 audit | 1218 | `cpu-prefix-shadow-final-audit-x64` |
| x64 原场景 direct | 828 | `cpu-prefix-shadow-final-opaque-direct-retry-x64` |
| x64 Toon／半透明 audit | 759 | `cpu-prefix-shadow-final-switch-audit-retry-x64` |
| x64 Toon／半透明 direct | 1605 | `cpu-prefix-shadow-final-switch-direct-retry2-x64` |
| x86 原场景 audit | 1107 | `cpu-prefix-shadow-final-opaque-audit-x86` |
| x86 原场景 direct | 1647 | `cpu-prefix-shadow-final-opaque-direct-x86` |
| x86 Toon／半透明 audit | 1104 | `cpu-prefix-shadow-final-switch-audit-x86` |
| x86 Toon／半透明 direct | 1713 | `cpu-prefix-shadow-final-switch-direct-x86` |

汇总 `exports/cpu-prefix-accepted-summary.json`：**168 次 CPU 绘制字段／字节对照、
1456 次历史边界图像零差异、9981 次非空独立材质图像一致、32 次生命周期检查通过**。
这些计数是诊断检查次数，不表示 1456 个独立场景；历史分别来自初始及回读前序。
x64 应用 SHA-256 为 `d16a94d1b7759b2632a618a54ce5f353d7145255400f88b07487ccc82d163a81`；
x86 为 `c392d7bb5ddf08c1d09bc03eac5386916ebce96fb54393f896e771f2c3db55f4`。

命令示例（先 audit，通过后在新目录 direct，并提供匹配的 audit）：

```powershell
python tools/run_cpu_geometry_diagnostic.py `
  --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe `
  --application build-x64/build/Release/MikuDanceStudio.exe `
  --fixture C:/Users/jstzw/Downloads/MikuMikuDanceE_v932/UserFile/sample.pmm `
  --output exports/cpu-prefix-example-audit-x64 `
  --preview --materials 12,13,14 --play --lifecycle --inputs audit `
  --history --ground --projected-shadows --cpu-prefix ground-shadow
```

增加 `--translucent --switch-toon` 验证材质 13 的半透明和材质 12 的 Toon 切换。
direct 准入包含应用、GUI 和 fixture 的 SHA-256、模型、材质、场景控制及 CPU 契约版本。
`tools/analyze_cpu_scene_passes.py` 检查已通过报告、CPU 来源、单进程顺序、阴影材质覆盖和非空图像证据。

失败记录保留：`cpu-prefix-shadow-final-opaque-direct-x64` 的图像全部一致，
但未采集到实际播放样本，因此整组失败，补跑使用独立 `opaque-direct-retry-x64` 目录。
`cpu-prefix-shadow-final-switch-direct-retry-x64` 的初始进程被现有
`material_pass_override` 门禁拒绝（displayState 或 postLoadFlag2），只完成回读进程的地面，
不能作为阴影／生命周期通过证据。该状态偶发进入的原因尚未定位，未修改门禁或忽略失败。
这些失败均不计入成功汇总。

Windows 与 Linux 无界面资源／场景测试各 **11/11**；新增 `rhi_scene_passes` 覆盖几何、
颜色、透明深度平面、投影状态、错误字段／字节／帧／边界、原子失败和别名替换。
Linux 日志 `exports/cpu-prefix-linux-validation.log`；本轮没有新的 macOS 实测。
现有三平台资源 CI 自动包含新增测试。
x64/x86 的 `rhi_scene_passes`、DX9 转换及 Hardware／WARP 转换回归各 4/4，
日志 `exports/cpu-prefix-backend-regression-{x64,x86}.log`。

## 模型材质前序的明确阻断

`--cpu-prefix ground-shadow-model` 已接入最终 CPU 几何、ModelSubmissionBuilder 和有序前序队列，
但尚未通过完整模型前序门禁。首个材质的 Sphere 纹理在 `scene_texture_bytes_1` 被拒绝：
CPU 当前提供单层，DX9 参考使用完整自动生成 Mip 金字塔。
同一素材 `metal.sph` 的 256×256 顶层解码 RGBA 一致，不能因此将其当作所有层一致。
简单递归平均／舍入也未匹配参考 Mip，禁止借用 GPU 捕获层冒充 CPU 资源生产。

原生转换器另补齐了 CameraNormal 阶段的 Sphere 角色与 Multiply／Add 语义，实际采样和运算保持原样，
并加入转换回归测试。模型门禁随后正确停在资源字节，不再因角色元数据缺失提前失败。
失败证据保留在 `exports/cpu-prefix-all-semantic-audit-x64`，不能计入成功。

下一步为 CPU 模型资源增加显式 Mip 准备策略与后端能力声明，保留源 RGBA、内容版本和准备后的层版本；
先验收完整层字节／尺寸及重建恢复，再重跑首材质和全材质前序。
在此之前不启用完整模型前序替换，也不扩大实际应用渲染范围。
