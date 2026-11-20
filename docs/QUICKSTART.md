# 上手指南

主目录使用 **48 kHz / 24-bit / mono / UART 2M**。下列命令均在发布包根目录、激活项目虚拟环境后运行。

## 1. 安装主机依赖

Windows 示例：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r host/requirements.lock.txt
```

如果本机 PowerShell 不允许运行激活脚本，可直接使用 `.\.venv\Scripts\python.exe` 代替后续 `python`，无需更改系统执行策略。

macOS 示例：

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r host/requirements.lock.txt
```

也可使用 Python 3.12。Intel Mac 和 Windows 的虚拟环境应分别建立，不要互相复制。依赖版本固定于 `host/requirements.lock.txt`。

## 2. 准备音频和 USB 连接

1. 声卡接电脑，机架正常处理音频；先确认耳机里能听到预期效果。
2. 将**处理后的输出**路由到一个可采集端点。Mac 已测方案为 REAPER → BlackHole 2ch；Windows 需选择实际可用的 loopback / 虚拟音频输入。直接选择 Solo 原始输入会绕过机架效果。
3. 电脑接开发板 COM / USB-UART 口。确认板子两口供电设计后，手机接原生 USB 口。详见 [HARDWARE.md](HARDWARE.md)。

Mac 首次采集需要为运行终端授予麦克风权限。CH343P 串口在 macOS 中需有正常工作的驱动；已测环境使用 WCH 官方驱动。上述系统安装、授权和音频路由需在本机完成，依赖安装不会代办。

## 3. 刷入对应固件并绑定设备

首次使用先按 [prebuilt/README.md](../prebuilt/README.md) 写入对应固件。已有正确固件可跳过刷写。

```bash
python -m host.sender ports
python -m host.sender devices
```

在枚举结果中确认目标串口与其 USB 序列号，然后替换以下占位符：

```bash
python tools/bind_sender.py --port PORT --expected-serial USB_SERIAL --output configs/hardware.local.json --confirm-known-board --execute
python -m host.sender --baud 2000000 hello
```

`bind_sender.py` 只接受已审查的 CH343 VID:PID `1A86:55D3`，并核对序列号；保存绑定时不打开串口。使用其他芯片或缺少序列号的驱动需要单独适配。已有同名本地配置时不会覆盖，请先保留旧配置并选择新的 `*.local.json` 文件名，随后通过 `--config` 指定。

`hello` 返回的格式应为 `sample_rate=48000`、`bits=24`、`channels=1`、`baud=2000000`。位深、声道或速率不匹配时应使用相应固件 / 发送参数。

## 4. 先发送 WAV

```bash
python tools/make_test_wav.py --help
python -m host.sender --baud 2000000 --wait-for-usb 120 wav YOUR_MONO_48K_24BIT.wav --channels 1
```

手机先选择外置 USB 输入并开始录音。发送器最多等待 120 秒，检测到 USB 录音流后才发送。WAV 应为 48 kHz PCM；其他位深或立体声转单声道必须通过参数明确选择转换，不会自动猜测。

## 5. 实时发送：Mac

先播放 REAPER 工程或输入人声，确认 BlackHole 对应路由有信号，再开启手机录音：

```bash
python -m host.sender --baud 2000000 --wait-for-usb 120 capture \
  --source-name "BlackHole 2ch" --source-api "Core Audio" \
  --post-fx-confirmed --input-channels 2 --channels 1 --bits 24 \
  --mix average --asrc --capture-block-frames 480 \
  --capture-latency low --seconds 60
```

## 6. 实时发送：Windows

从 `devices` 中选择已经确认的机架效果后输入索引，将下面的 `SOURCE_INDEX` 换为其整数编号。PowerShell 单行示例：

```powershell
python -m host.sender --baud 2000000 --wait-for-usb 120 capture --source SOURCE_INDEX --post-fx-confirmed --input-channels 2 --channels 1 --bits 24 --mix average --asrc --capture-block-frames 480 --capture-latency low --seconds 60
```

输入为单声道时改成 `--input-channels 1` 并移除 `--mix average`。当前 Python 原型使用 PortAudio 所枚举的输入端点，不能把某台电脑上的设备编号直接复制到另一台。

## 7. 停止和观察状态

- 按 `Ctrl+C` 停止；有限时长完成后也会正常停止。需要更长使用时显式调整 `--seconds`。
- `--stats-log artifacts/session.jsonl` 可保存运行统计；先创建本地 `artifacts/` 目录。
- 注意欠载、溢出、坏帧、CRC、序号及采集丢块等统计。设备拔插后重新枚举，避免继续使用过期端口。
- 有效监听继续从电脑声卡耳机输出。手机伴奏回到电脑的功能位于独立开发目录。

ASRC 微调采样以适配两端时钟；不能将其描述为原始采样逐位不变。双声道平均也会改变声像和空间效果。端到端延迟受音频路由、声卡、机架、USB 接收端和录音 App 共同影响，本发布包不提供未测量的延迟数字。
