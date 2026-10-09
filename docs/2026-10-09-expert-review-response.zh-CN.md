# 对《Apple 1902 USB 网卡驱动技术评审说明》的评阅意见

日期：2026-10-09。评阅对象：实验分支 `claude/out-pipe-recovery-experiment` 的装机 commit `38709d3` 及文档 HEAD `5cf305d`，以及评审说明中引用的测试结论。评阅依据为仓库内源码与文档；`artifacts/` 下的原始 ETL/日志不在仓库中，本文引用的数值均转引自评审说明和 `docs/` 中的记录，未重新解码原始轨迹。

本文沿用评审说明的约定：区分**已观察事实**、**有限证据支持的判断**和**未验证假设**。

---

## 0. 总体判断

评审说明的证据纪律很好：版本身份、方向约定、"通过不等于稳定"的边界都写清楚了。问题卡住的原因不在于谨慎不够，而在于三点：

1. **证据层级单一。** 所有关于首次 OUT transaction error 的证据都来自 Windows 主机软件栈（UCX/URB 字段、驱动计数器）。没有任何一条证据来自设备侧（Mac 的设备控制器日志）、物理层（链路错误计数、换物理路径的对照）或另一套主机软件（Linux 的 `cdc_ncm`）。在这个层级上，"请求构造/生命周期"、"主机控制器与链路电源"、"Mac device-mode 实现"三类假设在观测上几乎无法区分，再多跑几轮也不会收敛。
2. **A/B 的统计口径不可比。** 现有对照全部以"600 s 通过/失败"为单位，而故障率按已记录轮次看大约在每轮几十 GB 到上百 GB 之间出现一次。这种样本量下，任何两倍以内的差异都分不出来。LPM、节流、模式 1/2/3 的对照结论"有通过也有失败"是这一口径的必然结果，不是实验设计失败，但也不是信息。
3. **恢复工作消耗了主要精力，但恢复成功对定位根因没有信息量。** 下文第 1 节会说明：旧版"错误后全部超时"不是独立问题，是 xHCI 端点 halt 的必然结果；pipe-only recovery 只是正确地复位了主机侧端点状态机。它该做，也做对了，但它不能告诉我们第一个错误从哪里来。

因此建议把下一阶段的重心从"再跑几轮当前驱动"切换到**第 3 节的区分性实验**，其中两项（Linux 主机对照、物理路径对照）不改任何驱动代码。

---

## 1. 对首次 XACT 证据的重新解读

### 1.1 事实：XACT_ERROR 在 xHCI 上意味着什么

`USBD_STATUS_XACT_ERROR` (0xC0000011) 对应 xHCI 的 Transaction Error 完成码：主机控制器在发出 Data Packet 后，经过协议规定的重试次数仍未收到有效握手（无 ACK、ACK 带持续的序列号错误、或 CRC 错误）。此后该 bulk 端点进入 **Halted** 状态，传输环停止推进，直到客户端驱动发出 Reset Endpoint + Set TR Dequeue Pointer（Windows 中即 `URB_FUNCTION_SYNC_RESET_PIPE_AND_CLEAR_STALL`）。

由此直接推出三件事：

- **评审说明第 6.A 节的"第 2 步"（后续 OUT 以 5 s 超时结束）不是独立故障，而是端点 halt 后排在环上的请求无法推进的必然表现。** 不需要再为"为什么后续全部超时"寻找原因。
- **IN 一直成功、无 PnP removal、无端口 reset，说明 USB3 链路本身保持在可用状态（U0 可达）。** 失败发生在"主机发 DP → 设备响应"这一个事务层环节，而不是链路掉线。
- **NCM 格式类假设（NTB 头部、保留字段、对齐、NDP 链）可以降到低优先级。** NCM 层的格式错误由设备的功能驱动处理，表现为丢帧、统计计数或接口复位，不会让设备控制器对一个 DP 不做 ACK。文档已把 NTB 加固标为"非根因修复"，这个判断正确，可以说得更肯定一些。

### 1.2 事实：完成长度全部落在 1024 字节边界

已记录的四例 requested/completed：32136/20480、32136/21504、32136/24576、7924/6144。completed 全部是 1024 的整数倍（20、21、24、6 个满包），这是 xHCI 报告残余字节的正常方式：错误发生在第 21、22、25、7 个包上。这组数字目前没有被利用，它能回答一个具体问题：**失败包序号与 OUT 端点 bMaxBurst 的关系。**

- 当前 `ParseConfiguration`（`host/apple1902_validation.h`）只校验接口和端点描述符，**跳过了 SuperSpeed Endpoint Companion 描述符 (type 0x30)**，所以没有人记录过 OUT 端点的 `bMaxBurst`。这是一个零成本的信息缺口，应该在下一个版本把两个数据端点的 bMaxBurst 打到日志里。
- 如果 bMaxBurst+1 = 16，那么 21/22/25 都在第二个 burst 内部；如果失败包序号与 burst 边界存在固定关系，就强烈指向设备侧的 burst/NumP 流控处理；如果没有关系，则物理层随机误码的权重上升。

### 1.3 事实：32136 字节请求全部是上传阶段的满 NTB

32136 ≈ 4 × 8014 字节以太网帧 + NTH32/NDP32/5 个 DPE + 对齐填充，即 MTU 8000 下填满的 OUT NTB。三例 32136 都对应 Windows→Mac 大流量阶段；7924 一例可能是下载阶段的 ACK 聚合或小帧 NTB。建议把每一例首次故障标注到应用方向（上传/下载），目前"交替上传/下载"的描述掩盖了这一维度。如果 XACT 只在 OUT 重载阶段出现，"设备侧 OUT 接收路径在持续满载时的处理"假设的权重就应该上升。

### 1.4 判断：故障前并无空闲间隙，但不能排除 U1/U2

最近成功完成在故障前 115.9 µs，软件层 26 个 OUT pending，说明控制器一直有数据可发。这不是"空闲后首包失败"的典型 U1/U2 退出竞争模式。但 SuperSpeed 下设备一旦 NRDY，链路可在几十微秒内进入 U1，所以 116 µs 的间隔并不能排除链路电源状态参与。

### 1.5 判断：吞吐差异是被低估的硬证据

当前版四轮 300 s 对照里，Mac→Windows 接收流水线中位速率 Moderate≈225 MB/s、Off≈384–409 MB/s，差距约 70%。这与 XACT 是否发生无关，但它说明：**在持续大流量下链路仍在高频进出 U1/U2，即设备侧存在大量 NRDY 空隙。** 每秒可能发生数千到上万次链路电源状态切换。这不证明 LPM 导致 XACT，但它把"与 U1/U2 退出时序相关的设备或控制器缺陷"从"小概率事件"变成"每秒被触发上万次的路径"。第 3 节 E 项给出利用这一点的方法。

### 1.6 判断：复发间隔是一条尚未使用的线索

`HARDWARE-AB-20261008.md` 记录：复位成功后 1.011 s 再次 XACT（期间 7314 次 OUT 成功）；另一轮两次复位后分别 18.660 s 和 **0.073 s** 复发。如果根因是线材/物理层随机误码，复发间隔应随流量近似随机分布；集中在复位后 1 s 以内、甚至 73 ms 内复发，更像是**设备端点状态没有被 CLEAR_FEATURE(ENDPOINT_HALT) 完全复位**，或触发条件（例如某个 burst 模式）在复位后立刻重现。建议把所有已记录的"复位→复发"间隔和"首次故障前累计 OUT 字节数"列成一张表，这是目前最便宜的根因分类信息。

---

## 2. 现有结论中超出证据或表述需要修正的地方

1. **"约 527 万 OUT 请求中没有恰好为 1024 整数倍的提交"不是观测发现，而是代码保证。** `TransmitFrames`（`host/device.cpp`）在 TransferLength 是 MPS 整数倍时追加一个零字节强制短包（与 Linux `cdc_ncm` 行为一致）。它排除的"精确 MPS 提交导致失败"假设本来就不可能发生。应改写为"驱动不会发出 MPS 整数倍长度的 OUT 请求"。
2. **"LPM Off 602 s 通过 / Moderate 32 对失败"不能再作为 LPM 的证据引用。** 当前版 Moderate 已通过 4 × 300 s。文档已标注"不能定根因"，建议进一步从证据表中移除这一对比，只保留吞吐差异（1.5 节）。
3. **"恢复成功"的表述应与"复发"并列。** 评审说明第 1 节"实验性管道恢复已在少数真实故障中恢复传输"是对的，但应在同一句里写明已记录的 1.011 s / 0.073 s 复发，否则读者会把"恢复链成立"读成"恢复后可持续"。
4. **故障率应改用"每 TB OUT 字节的 XACT 次数"表示。** 当前版模式 2 的 600 s 轮：78.8 GB/方向出现 1 次 XACT；10 月 8 日 d7fd6d6 六轮里 4 轮失败，失败前的数据量从不足 1 对到 107 对不等。把这些统一换算成"每 TB OUT 的事件数 ± 置信区间"之后才能比较任何 A/B。按现有数据粗估，事件率量级在每 100 GB 到每 1 TB 一次之间，这意味着**一次有区分力的 A/B 每臂至少需要 1–2 TB OUT 流量**，远超当前 600 s 轮次。
5. **"USB2 约 600 秒通过"是旧版单轮，只能说明 USB2 下 10 分钟没出现，不能用来支持"问题仅限 USB3"。** 需要在同一当前二进制上以同等 OUT 字节量重做（评审说明第 9 节第 3 条已列出，这里强调它对根因分类的意义：如果 USB2 下按字节数折算也不出现，物理层/USB3 协议层假设的权重上升）。

---

## 3. 推荐的区分性实验（按成本和区分力排序）

### P0-A　Linux 主机对照（不改驱动，区分力最高）

同一台 Dell 7920、同一根 USB3 线、同一台 Mac、同一端口，用 Linux live USB 启动，内核自带 `cdc_ncm` 会直接绑定 Apple 的 NCM 接口。用同样的 SHA 校验流量跑到 **≥ 1 TB OUT**。观察 `dmesg` 中 `xhci_hcd ... Transfer error`、`cdc_ncm`/`usbnet` 的 `-EPROTO`/`-EPIPE`，必要时开 `xhci-hcd` tracepoint。

结果解释：

| Linux 结果 | 结论 |
| --- | --- |
| 也出现 bulk OUT transaction error | Windows 驱动基本洗清；根因在 Mac 设备控制器、物理路径或主机控制器硬件；后续对照全部转到物理层和 Mac 侧 |
| 数 TB 无错误 | Windows 侧（本驱动的请求模式，或 USBXHCI 对该设备的处理）成为主嫌疑；可比较两边的 URB 大小、并发深度、U1/U2 配置差异 |

这是目前唯一一项能把"主机软件"与"其余三类"分开的实验，且成本只有一天。

### P0-B　物理路径对照（不改驱动）

固定模式 0、固定 LPM 策略，每臂跑到相同 OUT 字节量，统计每 TB 事件数：

1. 翻转 USB-C 插头方向（任一端旋转 180°，切换 SuperSpeed 通道对）。
2. 换 Mac 另一侧端口。
3. 换另一根 USB3 线，以及反接线的两端。
4. 若有 USB3 hub，经 hub 连接一次（hub 会重新生成链路，能区分主机根端口与设备端的 PHY 问题）。

如果某一个物理变量把事件率改变一个数量级，就不必再在驱动里找了。

### P0-C　记录 bMaxBurst，并做 OUT 请求尺寸/深度上限的 A/B（最小驱动改动）

1. 解析 SS Endpoint Companion，把 IN/OUT 的 bMaxBurst 写入日志（见 1.2 节）。
2. A/B：把 TX NTB 上限钳到一个 burst（例如 16 KiB，或 (bMaxBurst+1) × 1024），另一臂保持 dwNtbOutMaxSize。
3. A/B：把 OUT 并发深度钳到 4（当前 128 个请求池，实测 pending 26–50）。

这两个旋钮直接检验"设备 burst/流控处理"假设，且不触碰 NTB 格式、恢复逻辑和电源策略。请把它做成独立注册表位，不要与 NTB 加固或恢复模式混在同一组对照里。

### P0-D　Mac 侧日志与时钟对齐（不改驱动）

1. 先对齐两端时钟：让 Mac 以 Windows 为 NTP 源或两端同一 NTP 服务器，把约 1 分钟的偏差压到毫秒级；这比靠批次号对齐便宜得多，而且是后续所有跨端关联的前提。
2. 故障发生后立即在 Mac 上取：

```sh
log show --last 10m --info --debug \
  --predicate 'eventMessage CONTAINS[c] "XDCI" OR eventMessage CONTAINS[c] "AppleUSBDevice" OR eventMessage CONTAINS[c] "NCM" OR sender CONTAINS[c] "IOUSBHost"'
sudo ioreg -l -w0 -r -c AppleT8103USBXDCI
```

如果 Apple 的设备控制器驱动在同一时刻记录了端点错误、FIFO/流控异常或链路 Recovery，根因就落在设备侧；如果 Mac 侧完全安静而主机报 Transaction Error，则物理层或主机控制器权重上升。

### P1-E　让 LPM 对照具有辨识力

不要比较策略标签，改为：

1. 从 USBHUB3/USBXHCI ETW 中统计端口链路状态变化事件（U1/U2 进入/退出、Recovery）的频率，把它作为每轮的协变量记录。
2. 在设备级单独关闭设备发起的 U1 或 U2：驱动在 D0Entry 后对设备发 `CLEAR_FEATURE(U1_ENABLE)` / `CLEAR_FEATURE(U2_ENABLE)`（主机发起的 U1/U2 由 hub 驱动的端口定时器控制，Off 策略才会同时关掉）。这样可以把"设备发起"与"主机发起"的 LPM 分开。
3. 把 1.5 节的吞吐差作为 NRDY 频率的代理指标一并记录。
4. 必须记录提供该 USB-C 端口的主机控制器身份（VID/DID/固件）。Dell 7920 的 USB-C 可能由芯片组 xHCI、独立 xHCI 或 Thunderbolt 控制器提供，这三者对 SuperSpeed 事务错误和 LPM 的行为差异很大。

### P1-F　确认 USBXHCI 是否已做过 soft retry（待核实）

xHCI 1.1 定义了 Transaction Error 后带 TSP 的 Reset Endpoint "soft retry"。如果 Windows 的 USBXHCI 对 bulk OUT 实现了它，那么上报给驱动的 XACT_ERROR 已经是多次重试失败后的结果，更说明错误是持续性的而非单次抖动。请在 USBXHCI ETW 中查找 Reset Endpoint 命令是否在驱动发出 reset pipe 之前已经出现过。评阅者对 Windows 是否实现此特性没有把握，标为待核实。

---

## 4. 对 pipe-only recovery 设计的审查

总体：PASSIVE 级数据路径锁串行化、`EvtUsbTargetPipeReadersFailed` 返回 FALSE 接管 IN 恢复、Stop(CancelSentIo) → Reset → Start 的顺序、用 rundown protection 在 DISPATCH 级做发送准入，这些与 KMDF/USB 的约束一致，没有发现违反框架规则的地方。以下是需要注意或改进的点。

**a. Reset pipe 对设备侧的影响没有被单独观察。** `WdfUsbTargetPipeResetSynchronously` 不只是主机侧 Reset Endpoint/Set TR Dequeue，还会向设备发送 `CLEAR_FEATURE(ENDPOINT_HALT)` 控制传输，复位设备端点的序列号并清空其 FIFO。这是恢复能否"真正"成功的关键，也是 1.6 节 73 ms 复发的可疑点。ETW 中应单独确认该控制传输是否成功、设备是否对它回 STALL；如果 Apple 设备对 CLEAR_FEATURE 不复位 OUT 端点的 burst 状态，就能解释短间隔复发。

**b. 恢复期间的用户可见行为对 TCP 过于苛刻。** 准入关闭时 `TransmitFrames` 返回 `STATUS_DEVICE_NOT_READY`，上层帧被丢弃；再叠加 10 s 冷却和 60 s 一个令牌，意味着一次复发可能带来 10–60 s 的黑洞，而 Windows 仍报告 Connected。SMB 会话在这个尺度上会断开。建议：
- 冷却降到 1 s 量级；令牌预算改为"复位后出现真实 OUT 成功即补满"，而非固定 60 s 累积，这样正常复位不消耗预算，只有连续失败才退避。
- 这与 P1"Connected 但停滞"是同一个问题，见第 6 节。

**c. 复位失败或超时后的终态是"永久停滞但 Connected"。** 当前代码在 reset/start 失败后把管道标为不运行，直到队列或设备重启。无人值守时这意味着无限期黑洞。至少应在该路径上报告 Disconnected。不建议用 `WdfDeviceSetFailed` 触发重启，因为 6.B 节已证明 Mac 锁屏时重枚举会失败。

**d. 可恢复状态集合过窄。** `ClassifyTxCompletion` 只把 XACT_ERROR 归为 PipeError；`USBD_STATUS_STALL_PID`、`ENDPOINT_HALTED`、`DEV_NOT_RESPONDING`、`BABBLE_DETECTED` 都归为 OtherFailure 不恢复。但这些状态下 xHCI 端点同样处于 halted，后果与 XACT 完全相同（全部超时）。文档说"等有证据再加"，这个保守是可以理解的，但代价是一旦出现就是无恢复的停滞。建议把"端点已 halt"的所有状态归为同一恢复类，恢复动作不变，并按状态分别计数。

**e. 首次故障的现场没有被冻结。** 完成例程在分类后立即把 bufferRequest 归还池子并可能立刻复用。建议在 PipeError 路径上把该请求的 NTB 头部快照（前 64 字节、TransferLength、wSequence、in-flight 深度、时间戳）写入固定容量环形缓冲，不改时序、不打印。这就是评审说明第 8 节"固定容量驱动内部记录"中最便宜的第一步。

**f. D0Entry 的重新协商。** 非 D3Final 的 D0Entry 会重新 alt0 → SET_NTB_FORMAT → SET_NTB_INPUT_SIZE → alt1。由于 S0 idle 已被禁用（`driver.cpp` 将 IdleTimeout 设为最大且 Enabled=FALSE），这只在系统睡眠/唤醒时发生；但 Mac 侧会把 alt 0 当作链路断开。与 XACT 无关，但属于"睡眠/唤醒"验收项的已知风险。另外，既然驱动已禁用 idle，评审说明第 4 节"选择性挂起开启"对本设备没有实际效果，应注明。

**g. Work item 复用。** OUT 和 IN 共用一个 work item，通过 `m_TxRecoveryQueued`/`m_RxRecoveryPending` 自行保证不丢事件，`WdfWorkItemEnqueue` 在回调运行中再次入队时 KMDF 会在当前回调结束后再运行一次。从源码看是正确的；portable 探针也覆盖了并发停止。无额外意见。

**h. Driver Verifier。** 文档把 Verifier 列为"owner's choice"。对于这类 stop/start/reset 串行化逻辑，标准 Verifier + KMDF Verifier 是最便宜的"专家评审"，建议至少以模式 2 跑一轮 600 s。它不验证时序，但会抓 IRQL、对象生命周期和框架调用顺序错误。

---

## 5. NTB 与复合设备适配（P1）

- `ParseConfiguration` 很严格（要求接口号 0/1/2/3 的固定顺序、每对 union/ECM/NCM 功能描述符齐全、控制接口无端点），这对 1902 是合适的；缺的是对 SS Endpoint Companion 的解析与记录（见 1.2 节）。
- 强制短包追加字节与 Linux `cdc_ncm` 一致，NCM 规范允许 wBlockLength 小于 USB 传输长度，不应怀疑。
- TX 的 divisor/remainder/alignment 计算符合 NCM 1.0 Errata 1 的 3.3.4/6.2.1；建议把设备返回的 `wNdpOutDivisor`、`wNdpOutPayloadRemainder`、`wNdpOutAlignment`、`dwNtbOutMaxSize`、`wNtbOutMaxDatagrams` 原值记入一次性日志，目前只能从 32136 这个数字反推。
- NDP 保留字段清零和 RX NDP 循环防护都是正确性修正，与首次 XACT 无因果关系，这一点文档判断正确。

---

## 6. "Connected 但数据停滞"（P1）：建议的有界健康状态

NetAdapterCx 的媒体连接状态只有 Connected/Disconnected/Unknown，没有"暂停"。建议规则：

- OUT 管道处于 faulted/closed，或准入拒绝持续发生，且 **≥ 3 s 无任何 OUT 成功完成** → 报告 `MediaConnectStateDisconnected`。
- 第一个 OUT 成功完成 → 恢复 `Connected`。
- IN 成功不计入健康判定。本案例中 IN 一直成功是误导性的"活着"信号。

这不是制造虚假掉线：它把真实的数据面状态告诉 TCP/IP 和 SMB，让上层快速失败并在恢复后快速重连，比 10–60 s 的静默黑洞更诚实。

---

## 7. 签名与发布（P2，简述）

独立 `.sys` 的正式路径是：取得 EV 代码签名证书 → 注册 Windows Hardware Dev Center（Partner Center）→ 对客户端 Windows 10/11 可走 attestation signing（不需要 HLK），服务器版才强制 HLK。NetAdapterCx 网卡若走 HLK，需要通过 NDIS 系列测试，当前的间歇性 XACT 几乎肯定会在长时压力项上失败。所以签名资格实际上以第 3 节的根因工作为前提，顺序不能颠倒。安装时的确认弹窗不等于内核加载信任，这一点评审说明已写对。

---

## 8. 方法论建议

1. **统一指标**：每 TB OUT 字节的 XACT 次数（附置信区间），替代"600 s 通过/失败"。
2. **每轮固定协变量**：主机控制器 VID/DID/固件、线材编号与插头方向、Mac 端口、LPM 策略、U1/U2 事件频率、应用方向、OUT 并发深度峰值、bMaxBurst。
3. **预注册 A/B**：每臂目标字节量在开跑前确定，不以"出现一次失败"为终点。
4. **先做不改代码的对照（P0-A、P0-B、P0-D）**，再做驱动旋钮（P0-C），最后才是恢复策略的调整（第 4 节 b/c/d）。恢复策略的改进值得做，但它改善的是症状，不要让它再占用根因定位的测试时间。

---

## 9. 一句话结论

现有证据已经足以把"NTB 格式/请求构造"类假设降级，把"旧版错误后停滞"归结为 xHCI 端点 halt 的必然后果；真正未被区分的是**Mac 设备控制器的 OUT 流控、物理路径、主机 xHCI** 三者。Linux 主机对照和物理路径对照不改一行驱动代码就能把它们分开，应优先于任何新一轮 Windows 驱动试验。
