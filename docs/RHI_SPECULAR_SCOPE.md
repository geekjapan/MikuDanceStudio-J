# 高光运算候选的独立适用范围验证

后续已将候选接入默认关闭的共用后端策略，并把矩阵准备移到 CPU 常量层，详见 [高光兼容策略](RHI_SPECULAR_COMPATIBILITY.md)。本页实测结果属于迁移前独立用例；迁移后的复验单独记录。

针对 [高光分段舍入对照](RHI_SPECULAR_STAGE_ROUNDING.md) 的组合候选，新增不依赖 PMM、模型文件或捕获归档的验证入口 `--model-specular-scope`。候选只存在于诊断着色器中：先按既定 float32 顺序组合 world×view，再以 fused 四项点积求相机坐标；局部视线乘倒长度与灯光相加时融合舍入。

## 预设输入

`tests/model_specular_scope_fixture.hpp` 直接生成三角形、法线、材质和灯光。矩阵及法线在任何测量前固定，没有根据原生结果选取或调整系数。

| 组 | world | view | 用途 |
|---|---|---|---|
| 0 | 单位矩阵 | 单位矩阵 | 原本一致输入及局部视线控制 |
| 1 | Y 旋转与平移 | 平移 | 相机组合与乘加边界 |
| 2 | 非均匀缩放与平移 | Y 旋转与平移 | 法线矩阵、独立相机和灯光变换 |
| 3 | 带正负系数的剪切与平移 | X 旋转与平移 | 留出矩阵 |
| 4 | 混合线性变换与平移 | Z 旋转与平移 | 留出矩阵 |

每个矩阵组合覆盖两组不同法线、`NORMALIZENORMALS` 开关、`LOCALVIEWER` 开关，以及高光指数 `0.5、1.7、5、7.3`。第二组法线也作为留出输入。共 160 组，每组三次，480 次图像及顶点观测。

对象坐标通过矩阵的数学逆变换构造，使三角形在 64×64 目标内可见；这一步不使用 GPU 观测值。三个相机位置的 Z 不同，局部视线随顶点变化。正交投影固定可见深度和 W=1，将当前验收集中在高光运算，透视与裁剪仍由已有独立测试覆盖。

## 门禁

原生参考使用 DX9 硬件固定功能顶点处理和 float32 诊断 PS，轮换首顶点并使用平面着色读取各顶点的 RGB。每次检查所有覆盖像素恒定。基线和候选从 DX11 共享 measured VS 的 SO 直接读取 `COLOR1`，要求两条路径的裁剪坐标相同。

不能仅凭平面着色观测值宣称顶点差异：将原生观测值经相同裁剪坐标和 COLOR1 插值，再要求它重现原生 Gouraud 图像。候选 SO 也必须重现候选的实际图像。两侧重现门禁通过后，才统计候选是否与原生一致。

每组检查：

- 九个顶点 RGB 通道与原生 float32 结果逐位相同。
- 全部 4096 个像素的 float32 高光图像逐位相同，包括背景和覆盖边界。
- 原生及候选的原图重现门禁均通过，共享插值的两个后端结果相同。
- 基线原本一致的通道及像素没有退化；局部视线关闭时基线与候选完全相同。
- 每次都有足够覆盖像素和非零、未饱和高光，避免仅凭零值或钳制值通过。
- 三次重复的全部顶点及图像相同；x64/x86 的输入、结果、诊断 HLSL 与反汇编相同。

本测试使用单位材质／灯光高光颜色，直接观察高光。真实材质颜色、Toon／Sphere 采样、RGBA8 量化、完整场景历史和实时编辑仍是后续验收，不与这里的 float32 高光图像混称。

## 复现

```powershell
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-specular-scope exports/specular-scope-example-x86

build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --model-specular-scope exports/specular-scope-example-x64

python tools/analyze_specular_scope.py `
  --input exports/specular-scope-example-x86 `
  --compare exports/specular-scope-example-x64 `
  --output exports/specular-scope-example-analysis.json
```

输出目录可以重复使用，测试只重写自己的固定名称证据文件。`scope.csv` 保存完整图像哈希、逐位差异数量及门禁；`vertices.csv` 保存所有顶点通道及位模式；`inputs.csv` 保存矩阵和生成顶点。没有候选零差异、发生退化或重现门禁失败时，测试及分析器以非零退出码拒绝资格。

新增 CTest 为 `rhi_specular_scope_hardware`，在 Windows DX9/DX11 构建中注册，使用生成输入，无需外部素材。要求可用的原生硬件设备，设备创建失败不会被当作通过或跳过。

```powershell
ctest --test-dir build-x64/build -C Release -R '^rhi_specular_scope_hardware$' --output-on-failure
```

## x64/x86 实测

2026-10-12，NVIDIA TITAN Xp，单采样。x86 直接运行诊断入口；x64 通过新增 CTest 运行同一入口，耗时约 121 秒。两种架构均完成 160 组、各组三次的全部验证。其中 112 组包含留出矩阵或第二组法线。

| 验证 | 基线失败组数 | 候选失败组数 |
|---|---:|---:|
| 顶点高光 float32 | 68 | 0 |
| 全视口高光 float32 图像 | 53 | 0 |
| 原生／候选原图重现门禁 | — | 0 |
| 原本一致通道或像素的退化 | — | 0 |

局部视线关闭的 80 组中，基线与候选的顶点和图像完全相同。所有三次重复一致；两个架构的三份 CSV、两份 HLSL、两份反汇编共七份文件逐字节相同。候选资格为 `candidateQualified=true`。

证据目录为 `exports/specular-scope-generated-x86/` 和 `build-x64/build/specular-scope-evidence/`，跨架构分析为 `exports/specular-scope-analysis.json`；CTest 日志为 `exports/specular-scope-generated-x64.log`。分析器另通过缺少重复记录、缺少顶点记录、顶点明细与零差异汇总矛盾三项负例检查，见 `exports/specular-scope-negative-checks.json`。

相关回归在 x64/x86 各 6/6 通过，覆盖 DX9 转换的无界面、硬件及 WARP 控制，共享裁剪深度、法线精度和纹理 FMA 独立控制。日志为 `exports/specular-scope-regression-x64.log` 和 `exports/specular-scope-regression-x86.log`。另通过 Python 编译、工作区 `git diff --check` 和新增文件空白检查。

候选资格仅适用于所测适配器和输入。`imageAcceptance=false`、`productionActivation=false` 保留完整场景的验收边界；这项测试不会修改默认 DX9 呈现路径或共享生产着色公式。
