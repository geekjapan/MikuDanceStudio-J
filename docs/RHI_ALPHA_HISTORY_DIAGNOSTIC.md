# Alpha 历史诊断重放

`ModelOptions::diagnosticAlpha12` 是一个默认关闭的诊断开关。它只改变 Alpha 测试比较前的候选转换：

```text
a12 = floor(clamp(alpha, 0, 1) * 4096) / 4096
byte = round_to_nearest_even(a12 * 255)
```

它不量化输出颜色，不改变应用的 DX9 路径，也不能脱离 `Dx9Measured` 兼容模式启用。两个后端在其他模式下都会拒绝该请求。该规则来自独立 Alpha 数据筛选和几何测试，仍属于候选实现而非 DX9 内部算法证明。

完整场景诊断入口会从清屏开始逐绘制重放保存的 80 次 PMM 历史，并记录每个边界的像素差异、首个异常位置、资源上传计数、设备身份和 epoch；随后做三次重复提交和三次目标缩放恢复。DX11 与 DX12 都分别运行默认基线和候选策略：

```powershell
build-x64/build/Release/rhi_d3d9_replay_conversion_test.exe `
  --alpha-history-diagnostic `
  exports/cpu-accessory-control-audit-x64/prefix.98444 `
  exports/alpha-history-diagnostic-x64
```

`boundaries.csv` 和 `pixels.csv` 是逐边界证据，`summary.txt` 是机器可读汇总。归档要求 `nativeExact=1`；如果 RDP 下 DX9 HAL 返回 `0x8876086C`，测试会记录 `nativeReplayUnavailable`，继续验证 DX11/DX12，并保留归档的原生对照证据，不将设备环境故障转换成图像通过。

最近一次 x64 与 x86 结果相同：候选策略 DX11/DX12 的 80 个边界、重复绘制和缩放恢复均零差异；默认基线从第 66 次绘制起保持 4 个 Alpha 像素差异。每次运行仍以 `applicationActivation=0` 标记，应用不会自动切换到候选路径。

应用诊断设备现可用默认关闭的同一配置运行实时检查点，并在设备替换后保持策略；配置、实际验收范围及未完成项目见 [应用内实时 CPU 场景诊断](RHI_LIVE_CPU_SCENE_DIAGNOSTICS.md)。保存归档的通过结果不能替代应用加载、播放和回读验证。
