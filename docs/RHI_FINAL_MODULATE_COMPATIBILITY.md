# 最终纹理乘加的 measured 兼容规则

2026-10-07，承接 [第 23 次绘制隔离](RHI_MODEL_DRAW23_COLOR.md)。
本项使用独立生成的三角形、常量法线、单位矩阵、材质颜色、方向灯及 1×1 纹理，
不借用 PMM 的几何，也不拟合系数或引入像素容差。

## 职责与规则

CPU 场景继续产生平台无关的材质输入，`SceneRenderer` 管理资源与提交；
共用常量生成器把灯光／高光开关送到共用 HLSL，DX11／DX12 后端选择兼容策略。
不在应用、PMM 读取器或材质生产者中加入厂商精度修补。

独立控制测得，NVIDIA TITAN Xp 的 DX9 固定功能路径符合：

1. 灯光和高光阶段同时开启时，中间 RGB 纹理阶段保留未截断值，最终输出才截断。
   高光贡献为零也适用；关闭灯光或关闭高光阶段时仍逐级截断。
2. 最后一个有效阶段为 Modulate 时，该乘法与最终高光相加使用单次 float32 舍入。
   HLSL 用 double 乘加再转 float 表达这一运算；没有取得 DX9 驱动的原生指令。
3. Alpha 沿用逐级乘法及原 Alpha test；Add、无纹理及关闭高光的条件保留独立控制。

只融合最后一个有效 Modulate，不跨中间级融合。初始候选保持逐级 RGB 截断，
在 Add → Modulate 开启高光的控制中失败：独立三角形有 1446 个像素不同。
扩展控制又排除了“仅高光开关决定截断”的假设：关闭灯光时必须保留逐级截断。
这些失败记录保留在忽略的 `exports` 目录，未作为通过证据。

修正限定在 `ModelCompatibility::Dx9Measured`。`Default` 继续使用原逐级截断与分步乘加。
设备创建已有 double shader 能力检查，缺少该能力时拒绝 measured 模式。
这是已测硬件／驱动的兼容规则，不保证其他 DX9 驱动采用相同内部运算。
应用的实际渲染仍由 DX9 执行，诊断准入仍要求零像素差异。

## 独立测试

`model_final_modulate_fixture.hpp` 覆盖 0～3 级纹理、Modulate、Add、Add → Modulate，
四组非整值／零值／饱和边界材质，关闭高光、开启高光、零高光贡献及关闭灯光。
去除重复组合后共 90 个条件，每个条件重复三次：270 次整幅 RGBA8 和 float32 图像对照。
每次候选输出来自新设备和新提交，只缓存测试本地 shader 字节码。
通用着色器作为负控制保留，报告它与原生固定功能的差异。

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --final-modulate-controls exports/final-modulate-controls-new-x64
build-x86/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --final-modulate-controls exports/final-modulate-controls-new-x86
python tools/analyze_final_modulate_controls.py `
  --controls exports/final-modulate-controls-new-x64 `
  --compare exports/final-modulate-controls-new-x86
```

CTest `rhi_final_modulate_hardware` 执行 27 个条件／81 次对照的缩减集合；
串行运行并占用现有 GUI/GPU 资源锁。完整集合需选择新的输出目录。
分析器检查条件集合、三次重复、整幅字节／浮点差异和跨架构 CSV／摘要一致性。
CSV 的焦点值只供定位，准入使用 C++ 测试计算的整幅图像差异。

## 验证记录

Windows x64/x86 各 270 次独立整幅字节／float32 对照全部零差异，CSV 与摘要逐字节一致。
通用路径的负控制每架构累计 14460 个不同像素；measured 不通过提高容差取得通过。
证据为 `exports/final-modulate-controls-final-{x64,x86}`，分析器写入 `analysis.json`。

两架构使用相同的 x64 回读冻结档案 `exports/model23-owned-capture-x64/prefix.19376`：
DX11／DX12 各 33 条边界全部与原应用图像一致，1000 帧重复提交保持图像一致，
每后端六次目标尺寸切换和一次后端替换通过，旧提交被拒绝、CPU 数据重新上传。
每架构共 80 次精确检查，DX12 debug 错误为零。
资源总量 89，每个后端初次上传 89 个资源，后端替换后累计上传 178 个，无逐帧重传。
证据为 `exports/final-modulate-resident-draw23-{x64,x86}`。

x64/x86 真实应用原场景／Toon+Alpha 控制的 audit、direct 八组已全部通过：
每组 182 次边界，合计 1456 次零差异；生命周期合计 32 次通过。
x86 本轮第一次运行停在缺失模型重选，未进入主窗口，零图像证据，保留为失败记录。
原生 DX9 硬件探针通过后换新目录重试；其完整四组结果另见
[CPU 场景历史记录](RHI_CPU_SCENE_HISTORY.md)的本轮补充。

Hardware／WARP 回归每架构 10/10：独立最终组合控制、DX9 转换、DX11／DX12
resident 场景和 DX11 measured 生命周期通过。CTest 控制集合每架构 81 次整幅对照零差异。
日志：`exports/final-modulate-backend-ctest-{x64,x86}.log`。
Windows 无界面资源入口回归 10/10，日志 `exports/final-modulate-portable-regression.log`。
本轮没有新的 Linux/macOS 或其他 GPU／驱动实测，不将既有 CI 配置当作本轮实测。
