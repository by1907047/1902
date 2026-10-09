# Apple USB NCM Windows 驱动

[English](README.md)

通过 USB 数据线连接 Mac 和 Windows，使用 Mac 提供的 `05AC:1902` USB 网口传输数据。本项目基于 KMDF / NetAdapterCx 实现 USB 网络控制模型（NCM），不是给 Windows 自带的 `UsbNcm.sys` 加一个 INF。

当前发布包为**测试签名版本**，尚无微软正式签名或 WHQL 认证。已有一套 Mac/工作站的分版本实测记录；使用前请阅读 [安装要求](docs/INSTALLING.md)，并保留独立管理通道。

当前源码的 Windows 显示名称统一为 **Apple USB NCM Network Adapter**，提供方为 Sideline。alpha.2 保留旧名称，命名修正版等待实机验收。本项目独立维护，不是 Apple 或微软官方驱动。名称与标识见 [设备命名](docs/DEVICE_NAMING.md)。

## 支持范围

- 仅 Windows x64；INF 最低 build 26100，已有实机记录使用 build 26200。
- 仅匹配 `USB\VID_05AC&PID_1902` 的复合设备父节点，不匹配 `MI_XX` 子节点，也不匹配其他 Apple PID。
- 已测试一套 USB2 480 Mbps 和一套 USB3 5 Gbps 级连接，不代表兼容所有 Mac、系统、端口或线材。
- 只负责 Windows USB 网络数据路径，不自动设置 Mac 的设备模式、IP、SMB、路由、防火墙或睡眠策略。

## 使用与开发

alpha.2 发布附件包含 SYS / INF / CAT 和**公开测试证书**，不含私钥。它只适合已有合格测试策略的实验机器，不适用于正常 Secure Boot 策略；不提供自动修改安全策略的安装器。旧个人路径测试包仍不公开。新版身份与验收边界见 [实机验证](docs/2026-10-10-alpha2-validation.md)。

本轮设备未声明从挂起状态接收入站数据所需的远程唤醒能力，因此继续禁用设备级空闲挂起，不修改 Windows 电源方案。USB 链路节能仍由 Windows 与硬件管理。设计和云端评审结论见 [电源管理方案](docs/POWER_MANAGEMENT.zh-CN.md)。

依赖 DMF 已放在仓库内。macOS / Linux 上有 Python 3 和 Clang 即可运行：

```sh
python3 tools/run_portable_tests.py
```

这些测试只验证部分源码和带模拟接口的控制流，不等于 Windows 内核、真实 USB 并发或长期稳定性验证。

Windows 构建见 [构建说明](docs/BUILDING.md)。安装前请读 [安装与回滚](docs/INSTALLING.md)、[签名状态](docs/SIGNING.md) 和 [已知问题](docs/KNOWN_ISSUES.md)。源码 INF 的版本字段尚需构建工具生成，不能直接安装。

`v0.1.0-alpha.1` 标签是经过实机测试的冻结候选版源码导出。后续修复见 [更新记录](CHANGELOG.md)，各版本构建与实机结果见 [管道恢复记录](docs/OUT-PIPE-RECOVERY.md)，不能自动沿用旧版实测结果。本轮情况与边界见 [经验总结](docs/2026-10-10-lessons-and-source-integration.zh-CN.md)。`tools/check_snapshot.py` 分别核对基线与标签，以及当前源码清单中的全部改动。

实测速度、失败记录和证据范围见 [测试记录](docs/TESTING.md)，源码来源与哈希见 [版本溯源](docs/PROVENANCE.md)。上传速度不对称、属性显示错误、真正睡眠后的恢复，以及 Secure Boot 正常策略加载都还在待办范围内。

Windows 代码继承上游 MIT 许可，保留微软和 DMF 的版权声明；上游 Linux 代码未纳入仓库。来源见 [第三方说明](THIRD_PARTY_NOTICES.md)。本项目不是 Apple 或 Microsoft 官方驱动。
