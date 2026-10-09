# Apple 1902 USB 网卡驱动

[English](README.md)

通过一根 USB 数据线，让 Windows 使用 Mac 暴露的 `05AC:1902` USB 网口。本项目包含自行编译的 KMDF / NetAdapterCx 驱动源码，不是给 Windows 自带的 `UsbNcm.sys` 加一个 INF。

目前是 **Alpha 源码版**。M1 MacBook Pro 与一台 Windows 工作站已完成短时双向传输，但 USB3 下载断链、重连恢复和长期稳定性尚未解决。没有微软正式签名，也没有 WHQL 认证。不要把它当作唯一的远程管理通道。

## 支持范围

- 仅 Windows x64；INF 最低 build 26100，已有实机记录使用 build 26200。
- 仅匹配 `USB\VID_05AC&PID_1902` 的复合设备父节点，不匹配 `MI_XX` 子节点，也不匹配其他 Apple PID。
- 已测试一套 USB2 480 Mbps 和一套 USB3 5 Gbps 级连接，不代表兼容所有 Mac、系统、端口或线材。
- 只负责 Windows USB 网络数据路径，不自动设置 Mac 的设备模式、IP、SMB、路由、防火墙或睡眠策略。

## 使用与开发

本次发布不提供可直接安装的 `.sys` / `.cat`。旧测试包内嵌个人编译目录，暂不公开；将来在中性路径重新构建后，需要重新签名并验证，不能直接冒用旧包的测试结果。

依赖 DMF 已放在仓库内。macOS / Linux 上有 Python 3 和 Clang 即可运行：

```sh
python3 tools/run_portable_tests.py
```

这些测试只验证部分源码和带模拟接口的控制流，不等于 Windows 内核、真实 USB 并发或长期稳定性验证。

Windows 构建见 [构建说明](docs/BUILDING.md)。安装前请读 [安装与回滚](docs/INSTALLING.md)、[签名状态](docs/SIGNING.md) 和 [已知问题](docs/KNOWN_ISSUES.md)。源码 INF 的版本字段尚需构建工具生成，不能直接安装。

`v0.1.0-alpha.1` 标签是经过实机测试的冻结候选版源码导出。后续修复见 [更新记录](CHANGELOG.md)，各版本构建与实机结果见 [管道恢复记录](docs/OUT-PIPE-RECOVERY.md)，不能自动沿用旧版实测结果。本轮情况与边界见 [经验总结](docs/2026-10-10-lessons-and-source-integration.zh-CN.md)。`tools/check_snapshot.py` 分别核对基线与标签，以及当前源码清单中的全部改动。

实测速度、失败记录和证据范围见 [测试记录](docs/TESTING.md)，源码来源与哈希见 [版本溯源](docs/PROVENANCE.md)。上传速度不对称、属性显示错误、真正睡眠后的恢复，以及 Secure Boot 正常策略加载都还在待办范围内。

Windows 代码继承上游 MIT 许可，保留微软和 DMF 的版权声明；上游 Linux 代码未纳入仓库。来源见 [第三方说明](THIRD_PARTY_NOTICES.md)。本项目不是 Apple 或 Microsoft 官方驱动。
