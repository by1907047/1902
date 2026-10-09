# 第二轮评阅：更正、PR 整合核对与最小修正建议

日期：2026-10-09。范围：仓库内独立审阅，未安装或运行驱动，未安排硬件测试，未合并或推送到 `main`。核对对象：

| 对象 | commit | 说明 |
| --- | --- | --- |
| PR #1 `claude/sleepy-pascal-to1mu8` | `2327f44` | 目标 `main`，open |
| PR #3 `claude/out-pipe-recovery-experiment` | `5cf305d` | draft，目标是 PR #1 的分支，包含 PR #1 全部提交 |
| `origin/main` | `a784c70` | 已合并 PR #4 的独立 NTB 加固（`38a6eff`） |

本文更正 [上一轮评阅](2026-10-09-expert-review-response.zh-CN.md) 中的过强断言，并按用户决定（停止进一步实机与线材验证，总结经验、完善源码后合并）给出合并顺序、最小代码修正与风险。

---

## 1. 对上一轮评阅的更正

| 上一轮表述 | 更正 |
| --- | --- |
| "没有人记录过 OUT 端点的 bMaxBurst" | 错误。先前报告已记录 OUT bMaxBurst = 15（16 包），主机原生端口上限 5 Gbps，Mac 设备描述符声明 10 Gbps。正确的说法是：`ParseConfiguration` 不解析 SS Endpoint Companion，驱动日志里没有这个值，但报告里有。用 16 包的 burst 对照已记录的失败包序号 21、22、25、7，burst 内相对位置为 5、6、9、7，没有落在边界上，**现有四个样本不支持"失败与 burst 边界相关"**。 |
| "吞吐差约 70% 说明链路在满载下高频进出 U1/U2" | 过强。四轮对照只能说明 LPM 策略与接收流水线速率相关；策略切换同时影响 hub/控制器的其他行为、DPC 与 CPU 调度，吞吐差不是链路状态切换频率的测量。要说"高频"，只有端口链路状态事件计数才算证据，目前没有。 |
| "复位后 1 s / 73 ms 复发更像设备端点状态未复位，而非线材随机误码" | 过强。边缘线材或接触不良产生的误码在时间上可以成簇（受温度、机械应力、干扰影响），短间隔复发不能排除物理层。 |
| "NCM 格式错误不会让设备对 DP 不做 ACK，格式类假设可以明确降级" | 过强。设备侧功能驱动对畸形 NTB 的处理行为未知，内容触发的设备侧软件故障理论上可以导致端点停摆或不响应。正确的说法是：XACT 是事务层症状，最常见的原因在链路与设备响应层，格式错误通常在 NCM 层显现；NTB 加固与 XACT 之间**两个方向都没有证据**。 |
| 把 32136 字节的 OUT NTB 称为"上传阶段" | 术语错误。本项目约定"上传"为 Mac→Windows，即 USB IN；32136 字节的 OUT NTB 属于 Windows→Mac 方向。本文及后续只使用 USB 方向命名。 |
| 建议"3 s 内无 OUT 成功即报告 Disconnected" | 撤回。无流量时该条件会误报；报告断开后上层停止发包，若恢复条件依赖 OUT 成功则形成闭环。第 4 节改为只在驱动**确定性终态**上报告。 |
| 建议把 STALL、ENDPOINT_HALTED、DEV_NOT_RESPONDING、BABBLE 纳入恢复触发 | 撤回。这些状态在本硬件上没有观察记录，扩大触发集合等于合并未验证路径。本轮保持只有 XACT_ERROR 触发，且恢复默认关闭。 |

### 新事实的解读边界

更换新线并同时更换 Mac 端口后，默认模式 0、原 Moderate 2/2 策略下 600 s 双向 1173 对、2346 次 SHA 检查全部通过，约 78.7 GB/方向，环形 ETW 保留事件未见异常。这与"物理路径参与"一致，但：

- 两个变量同时更换，无法归因到线或端口任一方；
- 旧路径上同一代码也有过 600 s 通过的轮次，单轮通过不构成区分；
- 环形 ETW 只保留末段事件，不是完整 10 分钟零错误证明。

结论：首次 XACT 的根因**保持未定位**。用户已决定停止进一步实机验证，本文不再提出硬件实验。

---

## 2. PR #1、PR #3 与 main 独立 NTB 修复的整合核对

### 2.1 事实（本机 dry-run 合并，已 abort，未提交）

| 操作 | 冲突文件 | 驱动源码与测试 |
| --- | --- | --- |
| `origin/main` ← PR #1 (`2327f44`) | `CONTRIBUTING.md`、`docs/PROVENANCE.md`、`docs/source-current.json`(add/add)、`tools/run_portable_tests.py` | `common/ntb.cpp` 自动合并，无冲突 |
| `origin/main` ← PR #3 (`5cf305d`) | 上述四个，再加 `tools/check_snapshot.py`、`tools/update_source_current.py`(add/add) | **自动合并后的 `NCM-Driver-for-Windows/` 与 `tests/` 与 `5cf305d` 逐字节相同** |

关键结论：main 上独立提取的 NTB 加固（`38a6eff`）与实验分支的 `9d3f3cb` + `38709d3` 在 `ntb.cpp` 和两个 NTB 探针上收敛到**完全相同**的内容。源码层面不存在需要人工裁决的差异。所有冲突都在工具脚本与说明文档，且内容如下：

- `tools/run_portable_tests.py`：main 侧只是把两个 NTB 探针加入列表，实验分支的列表是其超集。取实验分支版本。
- `tools/check_snapshot.py`、`tools/update_source_current.py`：仅 docstring 与 `status` 字符串措辞不同。取实验分支版本。
- `docs/source-current.json`：**不能手工合并**，必须在合并提交上用 `python3 tools/update_source_current.py` 重新生成，否则 `check_snapshot.py` 在 CI 失败。
- `CONTRIBUTING.md`（2 行）、`docs/PROVENANCE.md`（17 行）：措辞合并，保留 main 的"基线不可变"表述与实验分支的"两层校验"表格。

另一个有用的事实：`5cf305d` 相对装机 commit `38709d3` 只改了两个工具脚本的文案，驱动源码与测试逐字节相同。因此合并后 main 的驱动源码等于已装机、已跑过本文第 1 节所列实机测试的源码。这说明的是**源码身份**，不是任何新二进制的资格。

### 2.2 建议的合并顺序

1. **先合并 PR #1 到 main。** 解决四个文件冲突（按 2.1 规则），在合并提交上重新生成 `docs/source-current.json`，等 CI 的 portable 套件通过。PR #1 包含始终生效的改动（链路速率报告、NTB 参数校验、IN NTB 协商、RX 积压上限、重复 PrepareHardware 的内存修正），这些不属于"默认关闭"范围，合并说明里要写明。
2. **PR #1 合并后，GitHub 会把 PR #3 的目标分支自动改为 main**（其 base 分支被删除时）。若未自动改，手工 retarget。此时 PR #3 的增量只剩实验恢复代码、`out_pipe_policy.h`、探针与文档，冲突只剩 `check_snapshot.py`、`update_source_current.py` 与再次需要重新生成的 manifest。
3. **合并 PR #3 前，先在该分支上完成第 4 节的最小修正和文档更新**（`OUT-PIPE-RECOVERY.md`、`KNOWN_ISSUES.md` 中"PR remains draft/unmerged"等表述），再合并。否则 main 上会留下与状态不符的文档。
4. 合并后在 `CHANGELOG.md` Unreleased 段写清：恢复模式默认关闭、无新发布二进制、`38709d3` 的实机结果只对该 SYS 的 SHA256 有效。

也可以一次把 PR #3 直接合并到 main（它包含 PR #1）。冲突内容相同，少一轮解决，但 PR #1 的评审记录会以"superseded"关闭。两种都安全；推荐分两步，便于把"始终生效的改动"与"默认关闭的实验代码"分开追溯。

### 2.3 合并边界：合并源码，不发布新合格二进制

- `Sideline1902DataPathDebug` 不在 INF 的 AddReg 中（已核对），安装后注册表值缺失即模式 0。模式 0 不创建锁、工作项、计时器，不调用 rundown。
- 模式 0 与旧源码的差异（TX 超时分类、NTB 加固、RX 循环防护、常量判断）在 `OUT-PIPE-RECOVERY.md` "What still differs" 一节已列出，合并时保留该节。
- 合并提交本身不会被 WDK 构建，也没有新的 SYS。`docs/source-current.json` 的 `status` 字段应继续写"unreleased source delta"，不要写入任何通过/合格字样。
- 已装机 SYS 的 SHA256 `20AFD6D8…54C1` 只对应 `38709d3` 的构建；合并后若有人重新构建，那是新二进制，需要单独记录身份。

---

## 3. 本轮审查重点：停止/重置/重启失败时仍显示 Connected

### 3.1 现状（源码事实，`host/device.cpp`）

- 链路状态只在 `EnterWorkingState` 置为 TRUE（无通知端点，强制 link up）。全文件没有任何 `EvtUsbNcmAdapterSetLinkState(…, FALSE)` 调用。
- 模式 0：`StartTransmit`/`StartReceive` 对 `StartPipe` 的返回值 `(void)` 丢弃。若 `WdfIoTargetStart` 失败，管道永不运行，Windows 仍显示 Connected。
- 模式 2：`RecoverOutPipeLocked` 在 reset 或 start 失败后把 `m_TxPipeRunning` 置 FALSE、准入关闭，日志写 "OUT closed until queue or device restart"；`RecoverInPipeLocked` 同理让 readers 停住。两者都是驱动**自己判定的终态**，之后所有发送被拒绝或 readers 不再提交，直到队列或设备重启。此时仍显示 Connected。
- 模式 2 的 `StartTransmit`/`StartReceive` 失败路径有日志，但同样不报告链路状态。

### 3.2 最小修正原则

只在驱动已经**确定不会再有数据通过、且只有队列/设备重启才能改变**的状态上报告 Disconnected；恢复 Connected 的条件是队列/设备重启成功，不依赖任何流量。这样：

- 没有"无流量误报"，因为条件不是时间或计数，而是状态机终态；
- 没有闭环，因为恢复条件不是 OUT 成功；
- 不改变恢复触发集合、预算、冷却或默认开关。

### 3.3 建议代码（示意，未编译）

`host/device.h` 增加一个标志与一个辅助函数：

```cpp
// Set once the driver has decided a data pipe stays closed until a queue or
// device restart; cleared when such a restart succeeds.
LONG m_DataPathFaultReported = 0;

_IRQL_requires_max_(DISPATCH_LEVEL)
void ReportDataPathFault(_In_ PCSTR reason);

_IRQL_requires_max_(DISPATCH_LEVEL)
void ClearDataPathFault(void);
```

`host/device.cpp`：

```cpp
void UsbNcmHostDevice::ReportDataPathFault(PCSTR reason)
{
    if (InterlockedCompareExchange(&m_DataPathFaultReported, 1, 0) != 0) return;
    DbgPrint("Sideline1902: data path closed (%s); reporting link down until queue or device restart\n", reason);
    if (m_NcmAdapterCallbacks != nullptr)
    {
        m_NcmAdapterCallbacks->EvtUsbNcmAdapterSetLinkState(m_NetAdapter, FALSE);
    }
}

void UsbNcmHostDevice::ClearDataPathFault(void)
{
    if (InterlockedExchange(&m_DataPathFaultReported, 0) == 0) return;
    if (m_NcmAdapterCallbacks != nullptr)
    {
        m_NcmAdapterCallbacks->EvtUsbNcmAdapterSetLinkState(m_NetAdapter, TRUE);
    }
}
```

调用点，共五处，全部是现有的失败分支，不新增状态判断：

| 位置 | 模式 | 改动 |
| --- | --- | --- |
| `StartTransmit`，`StartPipe` 失败 | 0 和 2 | 模式 0 把 `(void) StartPipe(...)` 改为检查返回值，失败时 `ReportDataPathFault("OUT pipe start failed")`；模式 2 在现有 `DbgPrint` 后加同一调用 |
| `StartReceive`，`StartPipe` 失败 | 0 和 2 | 同上，`"IN pipe start failed"` |
| `RecoverOutPipeLocked`，末尾 `if (!m_TxPipeRunning)` | 2 | 加 `ReportDataPathFault(NT_SUCCESS(resetStatus) ? "OUT start failed" : "OUT reset failed")` |
| `RecoverInPipeLocked`，`if (!m_RxPipeRunning …)` 分支 | 2 | 加 `ReportDataPathFault("IN reset/start failed")`，注意跳过 "pipe not running" 与 "device gone" 两个 return，它们不是新终态 |
| `EnterWorkingState` 置 TRUE 之前；`StartTransmit`/`StartReceive` 的 `StartPipe` 成功分支 | 0 和 2 | `ClearDataPathFault()`。`EnterWorkingState` 本就报告 TRUE，此处只需清标志；队列级重启成功时由 `ClearDataPathFault` 重新报告 TRUE |

IRQL：`EvtUsbNcmAdapterSetLinkState` 的契约是 `_IRQL_requires_max_(DISPATCH_LEVEL)`（`inc/callbacks.h`），`NcmAdapter::SetLinkState` 内部只调用 `NetAdapterSetLinkState`，可在持有 `m_DataPathLock`（PASSIVE 等待锁）时调用。

生命周期：`UsbNcmAdapterDestory` 先调用 `StopReceive`/`StopTransmit`（后者 flush 工作项），再 `NetAdapterStop`，之后 `DestroyAdapter` 才把 `m_NcmAdapterCallbacks` 置空。工作项不可能在回调指针置空后运行；`nullptr` 检查是防御。

### 3.4 这个修正不做什么

- 不把 Disconnected 用作任何自动重启或 `WdfDeviceSetFailed` 的触发。6.B 类故障已证明锁屏下重枚举会失败，报告状态比重启更稳。
- 不覆盖模式 0 下框架自带 IN 恢复失败的情况：`EvtUsbTargetPipeReadersFailed` 返回 TRUE 后，若框架的 reset 失败，readers 停住且没有回调通知驱动。这是已知缺口，记录到 `KNOWN_ISSUES.md`，不在本轮扩展。
- 不改变 TCP/IP 层以上的任何行为；上层看到 Disconnected 后会快速失败并在 Connected 后重连。

### 3.5 回归测试（portable，不需要硬件）

`tests/out_recovery_probe.py` 已经用模型 KMDF 编译 `device.cpp` 的生产函数，并有 `g_startResults` 注入 `WdfIoTargetStart` 失败、`LogsWith("OUT pipe start failed")` 等断言。最小扩展：

1. 把 `USBNCM_ADAPTER_EVENT_CALLBACKS` 模型加上 `EvtUsbNcmAdapterSetLinkState`，记录 `(BOOLEAN)` 调用序列到 `g_linkStates`。
2. 新增断言：
   - 模式 0，`StartPipe` 失败 → `g_linkStates == {FALSE}`；随后 `StartPipe` 成功 → 追加 `TRUE`；
   - 模式 2，reset 失败 → 恰好一次 FALSE，再次失败不重复报告；
   - 模式 2，start 失败 → 恰好一次 FALSE；
   - 模式 2，成功恢复链 → 没有任何链路状态调用；
   - "pipe not running" 与 "device gone" 跳过路径 → 没有链路状态调用；
   - D0Exit 后 D0Entry（`BeginD0Session` + 队列 start）→ 标志清零，`TRUE` 恰好一次。
3. 保留现有"模式 0 与冻结头 I/O 轨迹相同"的检查：成功路径上没有新增调用，该检查应继续通过；`StartPipe` 失败在冻结轨迹中未被建模，需确认探针不以失败注入运行该比较。

同时把 `tests/host_diagnostics_probe.py` 或 `lifecycle_policy_tests.py` 中与 "start failure is logged" 相关的用例扩成"logged and reported"。

---

## 4. 风险清单

| 风险 | 等级 | 说明与缓解 |
| --- | --- | --- |
| manifest 冲突手工合并导致 CI 失败 | 中 | 必须用 `update_source_current.py` 重新生成；合并说明里写明重新生成不是构建或硬件证据 |
| 合并后文档与状态不符（"draft/unmerged"、"source-only"） | 中 | 合并前在 PR #3 分支更新 `OUT-PIPE-RECOVERY.md`、`KNOWN_ISSUES.md`、`CHANGELOG.md` |
| 把"源码等于已测源码"误读为"main 有合格二进制" | 中 | 第 2.3 节边界；`status` 字段不写合格字样；SHA256 只绑定 `38709d3` 构建 |
| 最小修正本身未经 WDK 构建与实机验证 | 中 | 本轮不构建、不装机；该修正只增加失败分支上的一次回调调用，portable 探针可覆盖逻辑，但 IRQL/注解需 WDK 构建确认 |
| 模式 0 下 `StartPipe` 失败从静默变为报告断开 | 低 | 行为更诚实；该分支在所有已记录实机轮次中未出现 |
| 70 Debug / 68 Release 告警继续存在 | 低 | 不是本轮回归；按既有规则比较计数 |
| 首次 XACT 根因未定位 | 保留 | 用户已决定停止实机验证；文档必须继续把它列为未完成项，不因新线新端口单轮通过而改写 |

---

## 5. 经验总结（供合并说明引用）

1. **先区分症状与根因。** "错误后全部超时"是 xHCI 端点 halt 的后果；恢复逻辑修复了它，但对首次错误来源没有信息量。这一点在前期占用了大量测试时间。
2. **A/B 的计量单位要与事件率匹配。** 以 600 s 轮次做通过/失败比较，在每几十到上百 GB 一次的事件率下区分不了任何两倍以内的差异。
3. **一次只换一个物理变量。** 新线与新端口同时更换，使本来最便宜的一次区分实验失去归因能力。
4. **表述纪律要对双方都生效。** 本文第 1 节的更正说明评阅方同样会把"与……一致"写成"证明"。
5. **默认关闭的实验代码可以合并，但要以"源码身份"而非"二进制资格"来表述**，并在合并时同步修订状态文档。
