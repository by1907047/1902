# USB 网卡空闲休眠与唤醒方案

当前版本保持网卡设备常醒，USB 链路的 U1/U2 节能仍由 Windows 和硬件处理。不修改 Windows 电源方案，也不以限制传输速率代替电源管理。

## 当前设备的能力门槛

2026 年 10 月 10 日本地复核的 Mac NCM 配置为 `bmAttributes=0xC0`，Remote Wakeup 位未设置。Windows 报告支持 D0 和 D3，但只报告从 D0 唤醒。这不能作为从设备挂起状态接收入站数据并自动恢复的资格。

因此，本设备继续禁用 S0 idle。不能强制声明它具有未证实的网络唤醒能力，也不能通过 Windows 驱动修改 Mac 提供的 USB 描述符。常醒不等于禁用 USB3 链路 U1/U2，不等于阻止整机睡眠。

## 以后支持休眠的实现顺序

1. 每次 PrepareHardware 重新读取 USB 远程唤醒能力和当前设备、配置、速度身份。能力不支持或查询失败时保持常醒。
2. 即使 USB 描述符支持远程唤醒，也需确认 Mac NCM 实际能在新入站数据到达时发出唤醒信号。描述符位为真不等于端到端能力已通过。
3. 按 NetAdapterCx 的真实硬件能力配置网络唤醒源。不能只把 `Enabled` 改成 true，或虚报 ARP/NS 卸载、魔术包、包过滤唤醒能力。
4. 实现并记录队列停止、USB 读取器和请求取消、回调排空、D0 恢复、管道恢复及恢复预算的生命周期；不以周期性 PnP 重启代替唤醒。
5. 经独立实验版验证后再允许该硬件配置启用空闲休眠，默认配置不依赖系统电源方案修改。

## 云端评审补充（2026-10-10）

云端对 `4a5b1bb` 的只读评审支持上述能力门槛和保持空闲关闭的决定。以下是后续实现的设计检查点，尚未实机验证：

- USB3 还需核验接口 `GET_STATUS` 的功能唤醒能力，以及主机对 `FUNCTION_SUSPEND` 的正确配置。配置描述符单个位为真仍不足以放行。
- NetAdapterCx 的网络队列不是普通 WDF 电源管理队列。应在真实包过滤唤醒能力成立后，由 NDIS/NetAdapterCx 管理电源引用，不能只开 WDF 计时器。`*SelectiveSuspend` 和 `*SSIdleTimeout` 属于设备属性；不替用户切换 Windows 电源方案。
- 当前 `EnterWorkingState` 会重新选择数据接口、重建管道。需单独评估 D2 选择性挂起恢复时保留接口配置，避免唤醒首包被 alt-setting 重置丢弃；不能把该建议直接当成已验证补丁。
- 每次 D0 会话会重置实验恢复预算。需先明确选择性挂起是否应该重新补充额度，避免周期性空闲变成无界故障重试。
- 重复周期必须核对接收缓冲区归还、请求排空和计时器生命周期。验证包括入站唤醒、出站唤醒和超时边缘持续流量。

本轮仅完成能力核验和方案评审；没有启用休眠，不宣称完成 D0→Dx→D0 测试。

## 快速验收

只在能力合格的独立实验版本设置本设备的短空闲超时。工作站保持运行，不让整机睡眠；保留独立管理网线。

真实休眠的证据必须包括本设备 D0→Dx，以及恢复后的 Dx→D0。单纯等待、ping 成功或 PnP 重启不算休眠验收。分别验证 Windows 主动发送和 Mac 主动访问，记录恢复延迟、数据校验、队列状态和失败结果。

SMB 只挂载并不等于持续流量。还需分别覆盖持续传输、挂载后空闲、再次读取及再次写入；验证其使用 USB 而不是独立管理网线的 SMB 多通道。测试文件写入 Windows C 盘，不使用 D 盘。不得为了制造空闲而破坏用户已有 SMB 会话。

当前设备未通过上述能力门槛，本轮不强制挂起，也不声称已实现选择性挂起、网络唤醒、睡眠唤醒或 WoL。

## 参考

- [Microsoft KMDF USB selective suspend](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/selective-suspend-in-a-kmdf-function-driver)
- [Microsoft NetAdapterCx power management](https://learn.microsoft.com/en-us/windows-hardware/drivers/netcx/configuring-power-management)
- [Microsoft USB3 function suspend/wake](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/how-to--implement-remote-and-function-wake-support)
- [Microsoft USB3 link power management](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/usb-3-0-lpm-mechanism-)
