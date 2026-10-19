# 饰品与描边的 CPU 输入

## 职责与范围

延续 CPU 场景生产输入、共用 `SceneRenderer` 管理资源与提交、后端执行绘制的边界。
应用仍使用 DX9；本阶段新增输入和诊断，不启用整个模型渲染器替换。

- `AccessoryCpuResource` 持有 PNU 顶点、索引、材质子网格范围和独立解码的纹理。
  Windows 加载 `.x` 时独立调用 D3DX SYSTEMMEM 导入，复制后立即释放导入网格。
  后续 CPU 生产者不锁定应用的 DX9 网格，不读取 GPU 几何、材质、矩阵或纹理状态。
  这仍是 Windows 兼容导入边界，尚不是可移植 `.x` 文件解析器。
- 饰品变换来自 CPU 位置、旋转、缩放及绑定骨骼的最终 CPU 变换，乘以 CPU 场景世界矩阵。
  IK、物理及其时序保持现状。材质来源是加载后保留的 CPU 材质记录。
- `BuildAccessoryPassInputs` 明确灯光阶段、透明度、普通／加法混合、深度、模板、
  法线归一化和基础／Sphere 纹理级联。帧尾灯光保留先前饰品阶段的浮点往返运算。
  纹理从文件独立解码，复用已有 DX9 兼容尺寸与 Mip 准备服务；结果由 RHI 上传和持有。
- 模型描边使用已有最终 CPU 描边顶点及颜色，声明关闭灯光、顺时针剔除、
  `Less` 深度比较、深度写入、Alpha 混合与模板状态。当前限于已接入的 PMD 路径。

明确阻断屏幕纹理饰品、饰品投影阴影、未验证的 PMX 描边、非连续多范围饰品子网格
及导入／纹理准备失败。不得把缺失资源或不支持的绘制悄悄当成成功。

DX9 诊断转换器新增场景类别元数据：槽 0 不再天然代表 Toon，饰品可声明 Base 或 Sphere。
该元数据只用于正确表达旧路径的参考输入；CPU 生产者不从参考状态回填字段。

## 完整绘制顺序诊断

`--cpu-prefix full-scene` 设置族掩码 31，并启用 `MDS_RHI_CPU_FULL_SCENE=1`。
录制从场景清屏开始，穿过地面、前置饰品、模型投影阴影、所有模型材质、
模型描边及帧尾饰品，直到固定功能场景尾部。
这里的“完整”只指上述固定功能场景序列，不包括 HUD、MME 或整个应用呈现。

先验收 DX9 自身逐绘制重放，再审计 CPU 替换的字段、范围、几何字节与全部纹理 Mip；
全部通过才逐边界提交给 DX11、DX12，比较同一视口内的图像。
任一边界失败，停止该序列并保存原因及像素差异。

```powershell
python tools/run_cpu_geometry_diagnostic.py `
  --gui build-x64/build/Release/pmm_v1_relocation_gui_test.exe `
  --application build-x64/build/Release/MikuDanceStudio.exe `
  --fixture C:/Users/jstzw/Downloads/MikuMikuDanceE_v932/UserFile/sample.pmm `
  --output exports/cpu-accessory-example-audit-x64 `
  --preview --materials 12,13,14,15,16 --play --lifecycle --inputs audit `
  --history --ground --projected-shadows --cpu-prefix full-scene --mip-prepare dx9
```

证据分为 `cpu_accessory_import.<pid>.csv`、`cpu_prefix.<pid>.csv`、
`cpu_full_scene.<pid>.csv` 和已有材质／生命周期报告。
报告必须覆盖饰品与描边族，并有从清屏到最后绘制的两个后端连续边界；
只运行到前置模型材质不能通过这个门槛。direct 仍要求相同程序和素材的成功 audit。

## 2026-10-07 验证状态

Windows、Linux 无界面资源与场景契约测试均实际通过 11/11。
Linux 工作目录为 `/data2/wangjun/github/MikuDanceStudio`，证据为
`exports/cpu-accessory-linux-final-tests.log`；Windows 为
`exports/cpu-accessory-resource-final-tests.log`。
新增测试覆盖描边状态、饰品透明度、Sphere／加法混合、灯光阶段及拒绝不支持的输入。

首轮 `exports/cpu-accessory-full-audit-x64` 已完成图形加载、编辑、播放、保存、回读，
保留的独立模型材质 330 次字段／图像检查和 6 次生命周期记录通过；
但饰品输入在第三条绘制前阻断，完整场景报告缺失，整体为 FAIL。
后续补齐即时阻断原因和独立导入报告，修正导入参数与纹理角色语义。
这些修正尚未获得真实饰品／描边图像通过证据。

补跑 `exports/cpu-accessory-full-import-x64` 在应用创建设备时失败，GUI 返回 5；
独立硬件探针 `exports/cpu-accessory-hardware-x64.log` 及 retry 报告均为
DX9 `CreateDevice` 返回 `0x8876086C`，不能把 RDP Active 或 CPU 转换测试视为硬件可用。
**真实 x64/x86 饰品、描边和完整序列图像验收待 GPU 环境恢复后继续，未开放渲染替换。**

## RDP 恢复后的完整场景验收

硬件探针 `exports/cpu-accessory-recovered-probe-{x64,x86}.log` 均通过。
恢复后补齐以下输入边界：

1. `stage01.x` 引用的 `screen.bmp` 可以声明但未绑定。CPU 路径发布原生捕获／背景纹理可用标记；实际绑定原生屏幕资源时仍以 `cpu_accessory_screen_source_native_only` 阻断。
2. 为 `SEdge.tga`、`Wfloor.tga` 增加有界的 24/32 位真彩 TGA／RLE 解码，保留源 Alpha，使用程序生成素材测试。
3. 网格 UV 纹理不使用相机法线矩阵，字段对照跳过该未使用矩阵；CameraNormal 路径继续严格比较。饰品纹理槽 0 正确区分基础／Sphere 角色。

`exports/cpu-accessory-uv-audit-retry-x86/run.json` 为 **PASS**：
首次 80 次绘制及回读 57 次绘制，两后端含清屏共 278 次图像比较零差异，
137 次 CPU 替换及 Mip 检查、56 次 CPU 饰品导入、
2160 次材质检查和 4 次生命周期记录通过。
这覆盖加载、编辑、播放、Save As、回读及已配置的重建控制。
应用 SHA-256 为 `4b329bde98c2f6b44f4f9b4044d59a0cb5180152729e48c9e974bf1d66b88c8e`。

`exports/cpu-accessory-uv-audit-x64/run.json` 仍为 **FAIL**。
两条序列的 DX9 自身重放、CPU 字段、几何和纹理 Mip 审计通过；
首次序列的 DX11、DX12 均在第 66 次绘制首次出现四个 Alpha 差异，第 65 次后的颜色图像一致。
回读的 57 次绘制图像一致。四个异常坐标为
`(1040,725)`、`(1097,740)`、`(1136,757)`、`(1163,776)`：
DX9 Alpha 为 127，候选为 0，RGB 相同。
`exports/cpu-accessory-uv-audit-repeat-x64` 再次复现。
应用 SHA-256 为 `5552ebea6a67f4681ed0f1bc2a2fbf9d0884cf174d4344bc243a2c6ab9a0d079`。

固定 Toon 的 `exports/cpu-accessory-control-audit-x64` 首次序列也在第 66 次出现相同差异；
回读由 `cpu_accessory_mips` 阻断，不能视为通过。
Windows、Linux 可移植资源／场景测试均为 11/11，证据为
`exports/cpu-accessory-recovered-resource-tests.log` 与
`exports/cpu-accessory-recovered-linux-tests.log`。
这些无界面检查不能替代图像验收，尚未开放完整场景渲染替换。

## 第 65／66 次绘制的深度历史定位

`tests/accessory_alpha_history_fixture.hpp` 的 `--accessory-alpha-history`
入口使用保存的真实数据，等量改变两套 API 的状态，每组重复三次。
`exports/cpu-accessory-alpha-isolation-{x64,x86}/trace.csv` 表明：
单独绘制第 66 批次不复现；关闭其深度测试消除差异；
关闭其模板或 Alpha 测试仍有四个差异。
`exports/cpu-accessory-depth-source-x64/trace.csv` 和
`exports/cpu-accessory-depth-pair-x64/trace.csv` 继续缩减写入来源。
关闭第 65 次的深度写入消除四个 Alpha 差异，却引入一个 RGB 差异，因此不是修复。

进一步的[深度测量报告](RHI_ACCESSORY_DEPTH_MEASUREMENT.md)保存了阈值、顶点、校准及 Alpha 控制：
同一份 x64 捕获数据在两个架构测得完全相同的结果。
独立批次的深度阈值没有跨 API 差异；完整历史在第 65 次后已有四个深度分歧，
其 Alpha `GreaterEqual, ref=1` 在 DX9 丢弃、DX11 放行。
第 66 次的 Alpha 图像差异是随后遮挡行为的结果。
下一步测量 Alpha 采样与比较前量化，不增加深度偏移，也不关闭原始 Alpha 测试。

[Alpha 采样阶段报告](RHI_ACCESSORY_ALPHA_MEASUREMENT.md)已记录首轮 162 行高精度数据：
六点的 UV、导数、采样 Alpha、插值后的材质 Alpha 和乘法结果均逐位一致。
首轮后半段 DX9 创建设备失败，部分观察不视为完整场景验收通过。
后续恢复时已完成 ref=1 的 x64／x86 扫描：各 162 行高精度、72 行颜色及 225 行常量比较，
三次重复稳定、跨架构完全一致。DX9 判定与未启用测试时的实际目标 Alpha 字节符合；
直接 float、最近字节和向下字节三个简单公式均有不匹配。
多参考值阈值扫描仍受设备不稳定阻断，完整转换规则与场景图像验收尚未通过。

后续重连已取得 x64 五个参考值的完整 255 行阈值扫描，三次重复稳定，
DX9 的所有判定与实际目标 Alpha 字节符合。
x86 的前 82 行与 x64 相同，随后设备创建再次失败；完整 x86 验证和 1/256 字节细扫描尚待完成。
详细区间、失败范围及默认关闭的专用设备复用诊断记录在上述 Alpha 报告中。

再次恢复后，x86 五参考值 255 行粗扫描及 x64／x86 各 255 行细扫描均完整完成，
所有输入／观测字段跨架构一致，三次重复稳定。
专用设备复用模式的粗测结果与先前独立设备模式相同，但不代表连续设备创建已稳定。
细扫描显示阈值随数值范围变化，仍需验证可复用的有限精度转换规则；
生产公式和完整场景验收门槛保持现状。
