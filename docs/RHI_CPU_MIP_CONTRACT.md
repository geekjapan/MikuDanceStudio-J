# 完整 Mip 准备、版本与模型材质验收

2026-10-07，承接 [CPU 地面／阴影前序](RHI_CPU_SCENE_PASSES.md)。
应用默认渲染仍为 DX9。本阶段把完整纹理层纳入平台无关的模型资源提交，
保留原始解码；DX9 数值兼容准备为显式、可拒绝的后端服务。

## 准备策略与数据所有权

`PreparedMipChain` 包含策略、输入顶层内容版本 `sourceRevision`、数值提供者版本
`providerRevision`、包含全部层的 `revision`，以及拥有 RGBA 字节的 `levels`。
三种策略互不等价：

| 策略 | 定义 | 来源／限制 |
| --- | --- | --- |
| `SingleLevel` | 只有原始顶层 | 可移植，不生成隐藏层 |
| `BoxLinear` | 每层整数面积分区、四通道独立、半值向上舍入、无隐式 gamma | Windows／Linux／macOS 相同算法；不承诺匹配 DX9 驱动 |
| `Dx9AutoLinear` | 独立 DX9 暂存纹理的线性自动 Mip | 必须由后端能力支持，数值提供者含适配器／驱动／设备类型及配方版本 |

`SealPreparedMipChain`／`ValidatePreparedMipChain` 校验每层尺寸、RGBA 长度、顶层字节、
输入版本和配方／全层内容版本。非单层策略要求按 `max(1, size/2)` 一直完整到 1×1；
截断、额外层、错误尺寸、修改后的低层或提供者版本均拒绝。
源与准备结果由 `MaterialTextureAsset.content`、`prepared`、`mipChain` 分开保留。
若先缩放，chain 的输入版本指向准备后的顶层，原始解码版本另行记录和参与提交版本变化。

`TexturePreparer::SupportsMipPolicy`／`PrepareMips` 默认不支持，不能静默回退为其他策略。
DX9 服务只接收 CPU RGBA：创建自己的托管暂存纹理、上传原始字节、生成自动层，
使用共享逐 LOD 读取工具返回完整不可变字节，并恢复目标、视口、状态和场景范围。
它从不取应用材质纹理作为生产输入；GPU 句柄不进入可移植契约。
独立暂存纹理在准备完成后释放，DX11／DX12 的最终纹理由 SceneRenderer 持有。
这是一项 GPU／驱动数值兼容能力，不能称为纯 CPU 的 DX9 等价 Mip 算法。

当前 DX9 Mip 服务接受上限 4096 的二次幂尺寸。Windows 场景边界明确选择下一二次幂尺寸，
必要时用已有 D3DX `Prepare` 服务准备顶层，再生成 Mip；不读取原生纹理尺寸来选择策略。
真实材质 6 的 `eyeM2.bmp` 为 106×106，准备为 128×128，完整 8 层。
`metal.sph`／`mikuhair.sph` 为 256×256，完整 9 层。
缺少后端服务或超出验证范围时保持阻断，原始解码仍可用于其他平台／策略。

## 版本、缓存及设备恢复

`ModelSubmissionBuilder` 发布所有显式层，`generateMips=false`：DX11／DX12 不再自行重生成兼容数据。
逻辑纹理 ID 和颜色空间保持共享，源解码版本、准备配方版本、层数、尺寸或任一层字节变化
都会使资源版本递增；同一提交中冲突的数据、损坏的链或失败构建不提交注册表更新。
去除纹理后重新引用仍遵循现有版本退休规则。

`SceneRenderer` 原有完整纹理比较继续拒绝“同版本、不同低层”；保留全部 CPU 层用于
资源重建／设备替换，并拒绝旧 prepared frame。颜色空间由材质采样输入独立声明。
旧 `MaterialTextureCache` 只有顶层上传接口，遇到显式链直接拒绝，避免悄悄丢失 Mip；
完整模型链走 `CreateModelTexture`，不扩大旧接口职责。
设备替换上传的是已验收的不可变层，不要求再使用 DX9 暂存准备器。

## 验证范围和重现

无界面测试包含 odd／非方形尺寸、独立期望像素、完整层形状、低层篡改、配方变化、
原始源变化但准备字节未变的版本递增、构建回滚、延迟资源退休及完整层恢复。
Windows 资源模块 11/11，日志 `exports/cpu-mip-portable-accepted-validation.log`；
Linux GCC 11 同一资源模块 11/11，日志 `exports/cpu-mip-linux-final-validation.log`。
DX11／DX12 x64/x86 WARP 生命周期测试改用完整显式层：缓存、连续缩放、设备替换和绘制均通过。
本轮未取得新的 macOS 实测。

`rhi_mip_preparation_d3d9` 独立生成 BMP，把 D3DX 文件加载的自动层与独立 CPU 解码／准备路径逐层比较；
三次重复中包含 active scene 与 Reset，检查源保持、版本稳定及场景恢复。
参考使用与应用相同的“一个可见顶层 + AUTOGEN”加载参数。
首次测试错误地请求 0 个可见层，D3DX 虽返回成功但参考顶层全零；已增加顶层独立校验并修正参数，
该失败不能据此判定 Mip 算法差异。

真实验收使用 `sample.pmm` 的临时副本，模型为槽位 2 的 `Miku_Hatsune_metal.pmd`，共 17 个材质。
0–11 在 CPU 前序中替换，12–16 作为 CPU 连续后缀；其他家族仍保留已明确标记的原生捕获来源。
IK／物理仍由旧运行时求解，取其最终 CPU 几何。MME、PMX、材质覆盖、不支持的状态继续阻断。
不宣称已迁移 PMM 所有模型、描边、饰品、MSAA、自阴影和完整应用呈现。

```powershell
python tools/run_cpu_geometry_diagnostic.py `
  --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe `
  --application build-x64/build/Release/MikuDanceStudio.exe `
  --fixture C:/Users/jstzw/Downloads/MikuMikuDanceE_v932/UserFile/sample.pmm `
  --output exports/cpu-mip-example-audit-x64 `
  --preview --materials 12,13,14,15,16 --play --lifecycle --inputs audit `
  --history --ground --projected-shadows --cpu-prefix ground-shadow-model --mip-prepare dx9
```

direct 需要相同应用／GUI／fixture／场景／材质／Mip 策略且通过的 audit。
额外 `--translucent --switch-toon` 覆盖半透明混合和 Toon 切换。
每个过程必须覆盖模型前序 0–11，后缀顺序必须为 12–16。
`mip_preparation.<PID>.csv` 记录独立来源、源／解码／提供者／准备版本、尺寸和完整层数；
报告门禁检查相同源与提供者的准备版本跨回读一致。
`tools/analyze_cpu_mip_materials.py` 复核全部 17 材质覆盖、阴影顺序、逐绘制报告和跨架构 Mip 版本。

五个后缀批次可能在回读进程额外触发生命周期探针。验收要求至少完整的缩放／替换 × 两后端四条记录，
且所有额外探针都必须 PASS、按 DX11／DX12 成对，不能固定为恰好四条，也不能忽略失败。

## 当前实测结果

下表每个完整组含 45 次 CPU 前序字段／全层字节检查、190 次 DX11／DX12 对 DX9 的
初始／回读历史边界图像检查、10 条独立 Mip 准备记录和 4 次生命周期检查。

| 架构／场景／模式 | 非空独立材质图像检查 | 结果／证据目录（`exports/` 下） |
| --- | ---: | --- |
| x64 原场景 audit | 1130 | PASS `cpu-mip-final-opaque-audit-x64` |
| x64 原场景 direct | 2280 | PASS `cpu-mip-final-opaque-direct-x64` |
| x64 Toon／半透明 audit | 815 | PASS `cpu-mip-final-switch-audit-x64` |
| x64 Toon／半透明 direct | 2400 | PASS `cpu-mip-final-switch-direct-retry-x64` |
| x86 原场景 audit | 1215 | PASS `cpu-mip-final-opaque-audit-x86` |
| x86 原场景 direct | 2145 | PASS `cpu-mip-final-opaque-direct-x86` |
| x86 Toon／半透明 audit | 1090 | PASS `cpu-mip-final-switch-audit-retry-x86` |
| x86 Toon／半透明 direct | 2135 | PASS `cpu-mip-final-switch-direct-restored-x86` |

通过的八组合计 **360 次 CPU 输入检查、1520 次历史边界图像零差异、13210 次非空独立材质图像一致、
80 条 Mip 准备与跨架构版本一致、32 次生命周期检查通过**。
汇总 `exports/cpu-mip-accepted-summary.json` 只包含完整通过的组，保留失败目录不计入成功。
x64 应用 SHA-256 `94d09991d391d93548fa0ea22e025d333c8fca01b0097f33db1c5aeb007ef535`；
x86 `7f45ce772e28f4b854d1bf600cb0969d9914a6bc6d9ebbd055197f077ed6e85c`。

后端最终回归 `exports/cpu-mip-backend-accepted-{x64,x86}.log` 每架构为 7 项实际通过、
DX9 独立 Mip 项因创建设备再次不可用而跳过，不能称为 8 项实际通过。
此前 x86 同范围实际 8/8 见 `exports/cpu-mip-backend-final-x86.log`；
x64 独立 Mip 在恢复期间运行通过，包含三次全层对照和 Reset。
两架构 DX11／DX12 Hardware／WARP 的完整层资源与生命周期回归均实际通过。
之后 `exports/cpu-mip-recovery-hardware.log` 记录原生 DX9 创建再度失败 `0x8876086C`。
2026-10-07 RDP 恢复后的补验：`exports/cpu-mip-rdp-restored-probe-x86.log` 中原生硬件绘制及
独立 Mip 两项实际通过，`exports/cpu-mip-rdp-restored-probe-x64.log` 中独立 Mip 实际通过。
保持原应用／GUI／fixture hash，最后的 x86 控制 direct 完整通过模型重选、跳帧、编辑、实际播放、
Save As、回读和重新打开；初始 50 条、回读 33 条前序及五个后缀的两后端图像均零差异。
本阶段选定模型全 17 材质的 Mip 与逐绘制验收已闭环，当前仍不启用应用渲染替换。

## 保留的失败证据

- `exports/cpu-mip-full-prefix-audit-x64`：首轮二次幂 Sphere 已准备，但材质 6 的非二次幂
  顶层尚未准备，正确阻断 `cpu_mip_preparation_failed`；未计入成功。
- 期间 DX9 `CreateDevice` 为 `0x8876086C`，即使 RDP 为 Active 也未将其计为 GPU 可用；
  重连后独立探针恢复，才运行真实场景。
- 中间无界面版本测试把“换源后再换回”误当作版本不变；修正测试顺序，
  回滚校验与源版本变化校验各自独立，不修改实现以压过失败。
- `exports/cpu-mip-final-switch-direct-x64` 的全部图像、Mip 和六条生命周期记录均 PASS，
  旧报告条件因额外回读缩放而整体 FAIL。修正记录数量假设后在新目录补跑，原报告保持原样。
- `exports/cpu-mip-final-switch-audit-x86` 未通过缺失模型重选进入主窗口，GUI 返回 6，
  没有图像／资源证据。独立硬件和 Mip 探针通过后新目录补跑，保留该失败；重选偶发原因未定位。
- `exports/cpu-mip-final-switch-direct-retry-x86` 初始场景图像和生命周期通过，但 Save As 后
  未在 GUI 打开已保存场景，返回 12；只有初始 112 次历史检查，不能当作完整回读验收。

下一项范围是把剩余饰品／描边生产者逐类接入同一契约；DX9 数值兼容策略与
可移植确定性策略继续独立声明，实际应用后端切换仍需要完整帧与 MME 等单独验收。
