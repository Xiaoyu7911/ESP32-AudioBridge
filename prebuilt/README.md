# 已验证单声道固件

| 目录 | 音频格式 | UART | 用途 |
| :--- | :--- | :--- | :--- |
| `mono24_2m/` | 48 kHz / 24-bit / mono | 2,000,000 | 主配置 |
| `mono16_2m_recovery/` | 48 kHz / 16-bit / mono | 2,000,000 | 独立回退 |

两种固件沿用已验证的 0.2.2 源码，环形缓存 64 ms，启动预填 40 ms。容量和预填不是端到端延迟。每组包含 bootloader、partition table、application 和 `manifest.json`。本次只核对归档哈希，没有重编译或重新刷写。

## 写入前核对

先关闭发送器和串口监视器，列出设备并确认一个明确端口与 USB 身份：

```bash
python -m host.sender ports
python tools/verify_package.py
```

按具体板卡核对供电和 UART 引脚，保留已知可用镜像。安装历史使用的 esptool 版本（在项目虚拟环境内）：

```bash
python -m pip install esptool==4.12.0
```

下面的 `PORT` 必须换成已确认的目标端口。此命令会真正写入该设备：

```bash
python -m esptool --chip esp32s3 --port PORT --baud 460800 write_flash 0x0 prebuilt/mono24_2m/0x0_bootloader.bin 0x8000 prebuilt/mono24_2m/0x8000_partition-table.bin 0x10000 prebuilt/mono24_2m/0x10000_esp_audio_bridge.bin
```

正常重启后重新枚举、绑定并查询 `hello`；主机音频发送使用 2M，刷写下载使用的 460800 不改变流式 UART 速率。16-bit 回退时将命令中三个镜像目录全部换为 `mono16_2m_recovery`，并显式使用 16-bit 输入 / 发送格式。

若自动进入下载失败，按具体板卡说明使用 BOOT / RESET 后重试同一明确目标。不需要写 eFuse、修改安全启动或擦除整片 Flash。
