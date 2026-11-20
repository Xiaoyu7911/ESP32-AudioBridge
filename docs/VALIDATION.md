# 验证范围与来源

本发布包整理可追溯的通过结果，并保留测试边界。软件测试、电脑台架、Mac 实机和手机使用反馈分别列示。历史诊断日志、录音、机器配置与失败记录不收入公开包，原资料未删除。

| 范围 | 结果 | 依据类型 | 说明 |
| :--- | :--- | :--- | :--- |
| Windows 24-bit 单声道 WAV 闭环 | 通过 | BENCH_MEASUREMENT | 6 秒完整源 PCM 匹配 |
| Windows 24-bit 单声道时钟 / 传输 | 通过 | BENCH_MEASUREMENT | 3600 秒，模拟源钟 −500 ppm，真实 UART + USB，错误计数为 0 |
| Windows 16-bit 回退 | 通过 | BENCH_MEASUREMENT | WAV 闭环、600 秒 ASRC、20 次软件起停 |
| Intel Mac 单声道 UART | 通过 | MANUAL_MAC | 600 秒串口完整性；不等于 USB 音频验收 |
| Intel Mac 单声道 WAV → ESP32 → USB | 通过 | MANUAL_MAC | 6 秒完整 PCM 精确匹配 |
| Intel Mac 单声道实时测试音 → ESP32 → USB | 通过 | MANUAL_MAC | 60 秒，发送 / 消费计数与独立 USB 录音 CRC 一致，使用 ASRC |
| Windows / macOS → 三款手机 | 使用者确认通过 | MANUAL_PHONE / USER_REPORTED_PASS | 48 kHz / 24-bit / mono，最长连续使用约 20 分钟 |

三款手机为 iPhone 14 Pro、iPhone 17、小米 10。手机测试信息由使用者在 2026-11-20 补充确认，未随附新增原始日志；20 分钟不是每个组合的单独记录。系统、App、转接器与该次手机测试的固件 SHA256 未逐项留档，因此不将手机反馈强行绑定到包内某一个镜像。

Windows 长测使用 ASRC；对实际 USB 录音与确定性重放的 **518,382,051 字节转换后 PCM** 作整段比对通过。该结果说明转换后的传输完整性，不代表与原始 ADC 采样逐位相同，也不代表手机 App 无处理。

Mac 短测通过不等同于任意配置均已完成长期稳定性认证。双声道、双向传输、所有手机 / App 兼容性，以及完整端到端延迟仍需在对应配置下独立验证。

## 可追溯信息

- `SOURCE_PROVENANCE.json`：主机 / 固件源码提交、历史构建输入及开发快照来源。
- `prebuilt/*/manifest.json`：每个镜像的写入偏移、字节数、SHA256 与对应配置。
- `validation/verified_results.json`：从保存的通过记录提取的精简结果及来源报告哈希。
- `MANIFEST_SHA256.txt`：本公开目录的逐文件完整性清单。

公开包里的新软件检查结果写入 `validation/package_checks.json`。本次检查不打开串口、不采集音频，也不代替新的硬件测试。
