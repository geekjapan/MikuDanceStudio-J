# 2026 年 9—10 月对齐记录（归档）

本页保存历史修复依据；当前状态见 [移植与验证状态](../PORTING_STATUS.md)。2026-10-20、2026-10-21 的原正文已损坏为问号，以下仅根据对应提交与当前测试保留可核实摘要，不恢复未知原句。三份更早的 x86 台账另列于 [文档索引](../README.md#历史归档)。

## 2026-10-20 Bullet 诊断字段访问

提交 `29582c3` 将弹簧和求解器诊断中依赖架构偏移的刚体引用、编号和速度访问改为具名成员或接口。`tests/check_bullet_diagnostics.py` 对比关闭日志、仅弹簧日志、仅求解器日志和同时开启日志四种情况，检查 32 帧仿真输出一致，以及实际刚体编号和速度被正确记录。

这些结果验证相应诊断路径，不代表所有 Bullet 原始内存转储已脱离 ABI 布局，也不是长期物理轨迹或 GUI 的原程序 A/B 证明。

## 2026-10-21 关键帧类型恢复

提交 `52d969d` 将冗余关键帧标记移入 `mdl::MarkRedundantModelKeys`，由既有删除后端消费标记。测试 `tests/model_key_reduction_test.cpp` 检查关键帧池、链表和负载数据，避免将“标记可删帧”误改为直接删除或重排记录。

提交 `d7425a5` 将时间轴选择统计提取到 `src/window/timeline_selection.cpp`，使用具名关键帧类型与容量，保留选择记录的生产和消费约定。相关边界输入、排序和状态检查见 `tests/timeline_selection_test.cpp`。这些独立测试不替代真实窗口事件序列和原程序对照。

## 2026-09-25 对齐记录

本记录只覆盖列出的路径。参考二进制 SHA-256 见 [x64 重建基准](../X64_RECONSTRUCTION.md)；IDA 会话的装载基址不是持久标识。构建通过不等于原程序 A/B 或全库等价。

| 路径 | 原版证据与触发条件 | 当前处理 | 尚需验证 |
|---|---|---|---|
| PMX VB 创建失败 | MMD x64 RVA `0xAA215`（首 VB）及 `0xAA297`（edge VB）进入不同 JP 标题分支 | `pmx_load.cpp` 复用 Shift-JIS 原文字串，首 VB 用“ファイル読込”、edge 用“ファイル読込2”；英文标题均为 `open file` | 注入测试已覆盖首 VB 和 edge VB 英文；日文及原程序对照待验证 |
| PMX IB Lock 失败 | RVA `0xAB569..0xAB58B` 的错误框与 `0xAB592..0xAB5FA` 的关闭返回；窄/宽索引路径均汇入 | 两种索引宽度失败时显示 `pIndBuf->Lock` 并关闭返回 | 注入测试已覆盖 16/32-bit 英文；日文及原程序对照待验证 |
| 骨位置缓动 | RVA `0xD20BB` 为 `mulss`，`0xD20BF` 为 `addss`，`0xD20C3` 为 `movss`；其他轴同形 | 单精度先乘再加 | seek/advance 输入矩阵与原版逐位 A/B，检查编译器浮点选项 |
| VMD 保存打开失败 | RVA `0x6C661` 将 `_wsopen_s` 返回值传给格式化调用 | 打印返回值而非稍后读取 `errno` | 以拒绝访问/共享冲突路径触发两种语言 |
| 反向粘贴撤销槽 | 正常粘贴和模型释放均用 `operator new/delete`，反向粘贴原端口混用 `malloc/free` | 反向粘贴与同槽所有使用者统一分配器 | 连续粘贴、反向粘贴、撤销、关闭模型的堆检查 |
| MME 绘制窗口 | 原 MMHack `Present` 槽 17 更新 GetDrawnWindow；MME 下一次 `OnBeginScene` 消费 | 两处宿主 `Present` 调用改由内置桥记录实际目标，不再在 `BeginScene` 预置 | 浮动视口及录制窗口切换的逐帧 A/B |

`quat_to_mat3x4.cpp` 无任何调用者，却把与物理库函数冲突的 VA 解释为独立四元数函数，并引入只供该死代码使用的全局常量；已从构建和源码移除。`d3d_init.cpp` 的恒真 D3DX 分支源于当前静态导入方式，不能在没有替代加载机制时仅为了消除硬编码而删除。

## 未证明严格一致的路径

- `TextureValue` 的原版 `sub_180064020` 在 RVA `0x64095` 限定格式 20..116，97 项查表在 `0x67490`，但大部分落到同一默认分支（RVA `0x673F5`）；不是转换所有 97 种格式。端口已撤销原版不转换的 L8/A8L8，依据 RVA `0x65E70`/`0x668C3` 补两种 A2/10-bit 格式，并按 `divss` 改正 8-bit 通道舍入与 X8 的零 alpha。其余有独立目标的格式仍需提取通道与舍入语义并用真实设备 A/B。
- PMM 固定宽字段的栈尾字节被清零，不能声称与原版逐字节保存一致；不应故意读未初始化内存来复刻。
- 品牌标题和 About 使用 `MikuDanceStudio`/当前 `VERSION`，是产品身份的有意偏差，不是原版 UI 字节复刻。重置路径与新品牌保持一致。
- PMX 损坏文件的越界索引防护及 PMD 对话框取消时的句柄关闭保持安全偏差，不回退到原版未定义行为或泄漏。
- VSQ tempo 表原版按轨道数分配、按变速事件数填写，可能越界；端口现按 `tempoCount` 分配。仍需构造单轨多次变速输入、验证文件消费和失败路径，不能以保真为由接受内存破坏。
- `charset_conv.cpp` 的代码页优先路径和 locale 回退尚未与 x64 原版 WideToSjis 逐分支验证；不能将 x86 另一个方向的转换函数直接用作改写依据。
- WAV 缺少 `data` 标记或长度字段截断时扫描现在返回失败，不再在 EOF 死循环；波形列宽为零时也提前关闭解析流。PMM v2 拒绝值为 255 的模型/附件槽位，附件加载中止后释放模型映射工作区。均为损坏输入安全偏差；仍需带窗口的端到端失败路径及堆检查。

尚无覆盖全库、社区效果包、设备丢失、长期 Bullet 轨迹和 GUI 图像输出的原版 A/B 矩阵。

v10.01 的 x86/x64 CI 构建及测试通过，双架构 ZIP 和 SHA-256 已发布。v10.02 发布前本地 x64/x86 Release 完整构建和 CTest 分别为 41/41、39/39 通过。PMX 注入测试验证端口弹窗，不代替原程序 GUI A/B；新增 10-bit 通道测试是纯解码测试，不代替设备纹理 readback。原程序与端口的逐帧采集尚未在同一设备、D3DX 运行库、窗口尺寸、输入序列及固定场景下配对，不能给出像素或状态等价结论。

## 2026-09-26 MME 后台窗口 Reset 调查

用户反馈：窗口模式下切到资源管理器，单击任意项目后出现 `Failed to reset MikuMikuEffect`，没有拖入 `.x` 文件。该字符串仅从 MME `OnResetDevice` 的失败分支弹出；文件单击并未加载附件。切出/点击的精确消息序列仍未经用户环境重放。

原版 x64 MMD `SceneConstruct`（IDA `0x7FF7CB4227B0`）创建物理 gizmo 的顶点/索引缓冲区时，设备调用的 pool 实参为数值 `1`，即 `D3DPOOL_MANAGED`；首个顶点缓冲区在 `0x7FF7CB422857` 写入该实参、`0x7FF7CB42286E` 调用。端口 `scene_create.cpp` 错将注释中的 `/*1*/` 写作 `D3DPOOL_DEFAULT`（数值 `0`），十个常驻缓冲区直到场景销毁才释放，设备 Reset 时仍被持有。原版 MMHack `0x180003D30` 先调用 MME `OnLostDevice`，执行真正的设备 Reset，再不检查 Reset HRESULT 调用 MME `OnResetDevice`；原版 MMEffect `0x180058A20` 在恢复资源失败时显示这条弹窗。端口复现了这个调用顺序，但缓冲区 pool 不一致使真正的 Reset 可以先失败。

新增真实 D3D9 `physics_gizmo_reset_test`：修复前 `SceneConstruct` 成功，缓冲区存活时 `Reset` 返回 `0x8876086C` (`D3DERR_INVALIDCALL`)；将两处创建调用改为 `D3DPOOL_MANAGED` 后，同一测试的 Reset 成功。x64/x86 Release 构建及两架构的该测试均通过；x64 `mme_snapshot_cache_gpu`、`mme_assignment_graph_gpu` 亦通过。当前证据确立了端口的设备 Reset 阻断点和原版参数差异；用户机器上是否另有独立失败原因仍需发布后的反馈验证。

后续发布 CI 在 x86 的 `physics_gizmo_reset_gpu` 报访问冲突。重新本地构建 x86 可复现，Reset 已返回 `S_OK`，即使跳过 Reset 仍在 `DisposePhysicsWorld` 删除 `btStaticPlaneShape` 时崩溃（`0xC0000374` 堆损坏或 `0xC0000005`）。该类型含要求 16 字节对齐的 `btVector3`，却未声明 Bullet 对齐分配器；实测对象地址有时只按 8 字节对齐。为 vendored Bullet 的 `btStaticPlaneShape` 加上 `BT_DECLARE_ALIGNED_ALLOCATOR()` 后，重建 Bullet，x86 测试及完整 40 项回归通过；x64 完整 42 项回归通过。测试 D3D 设备改用软件顶点处理，与仓库其余 GPU 测试一致。

## 2026-10-24 关键帧池空闲槽与表情名查找

`searchCursor` 由骨骼、表情、显示三个关键帧池共用。端口的 `RegisterBonePoseAtFrame`（登录按钮）不复位游标即扫描空闲槽：新载入模型时游标为 0，粘贴或 VMD 载入后游标停在显示池位置。轨道头记录 frame 为 0，会被当作空闲槽取走，导致骨骼 0 的 0 帧关键帧丢失，或其他骨骼的轨道头被接入当前骨骼轨道。各注册函数在池满时还会先读 `keys[容量]` 再判断上限。`RegisterMorphKeyFromRecord` 的名称扫描对 `MorphRecord*` 执行 `+= 136`，每步跨 136 条记录，第 2 个及以后的表情无法按名称匹配，并越界读取。

当前处理：空闲槽扫描统一为 `kfa::AllocateFromCursor`，起点不低于第一个非头记录（骨骼数/表情数/1），先判断容量再读取；游标推进方式与原写法相同。表情名扫描改为每步一条记录。以上为安全偏差，有效输入的插入位置与原写法一致。

验证：`tools/keypool_check/run.sh`（真实源码有界穷举 + ASan，见 `verify-keyframe-pool` 技能）修复前 6 项违例，修复后深度 4/5 均通过；去掉起点保护后违例重现。尚需验证：原版 x64 是否存在同样的游标共用问题（未对照）、Windows x86/x64 构建及 CTest、GUI 中“载入模型→登录”和“粘贴→登录”的端到端确认。
