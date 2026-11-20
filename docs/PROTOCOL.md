# 串口协议 v1

这是本项目自定义协议，不是CH343/UAC标准。host/protocol.py是可测试参考实现。
host/session.py 与 firmware/bridge/main/ 已实现会话和固定格式桥接；probe 只输出板内测试音，不接收音频。实测范围见 VALIDATION.md；本主目录使用单声道固定配置。

## 线上的一帧
`COBS(32字节头 + payload + CRC32_LE) + 0x00`
COBS把0字节排除于帧内，0作分隔符；CRC32使用IEEE/zlib语义，覆盖头和payload。
所有数值小端；长度受限，CRC通过后才能使用头部/音频数据。

| 字段 | 字节 | 说明 |
|---|---:|---|
| magic | 4 | ASCII EAB1 |
| version | 1 | 1 |
| type | 1 | 下表 |
| flags | 2 | v1必须0 |
| stream_id | 4 | 每次新流随机ID，重连重建 |
| sequence | 4 | 每发送端每stream单调递增，uint32回绕 |
| sample_index | 8 | AUDIO首采样帧位置；控制帧0 |
| frame_count | 2 | 每声道采样帧数，非字节数 |
| channels | 1 | AUDIO为1或2；控制帧0 |
| bits | 1 | AUDIO为16或24；控制帧0 |
| payload_len | 4 | 上限4096字节 |
| payload | N | 音频PCM或UTF-8 JSON控制消息 |
| CRC32 | 4 | header+payload的CRC |

AUDIO载荷长度必须等于frame_count × channels × bits/8。
24bit为3字节小端补码，stereo为L/R交错；不发float32原始内存假装24bit。

## 消息类型
1 HELLO，2 CONFIG，3 START，4 AUDIO，5 STOP，6 STATS，7 ACK，8 ERROR，9 HEARTBEAT。
控制帧payload为JSON，keys必须进行类型/范围校验，不执行任何收到的命令字符串。
HELLO重建会话并返回 protocol=1、firmware、sample_rate、bits、channels、寄存器读回 baud 和 reset_reason。它不在运行中协商位深或切速。
CONFIG只能在停止状态设置；字段为 sample_rate=48000、bits=16或24、channels=1、mode=audio或integrity，必须匹配所刷固定配置。波特率由2M/3M独立构建选择，主机 --baud 必须一致；不会静默降速。
START重置统计/音频缓存，audio模式要求100ms内有原生USB麦克风回调，先启动USB主机录音；integrity模式不要求USB，只核对并丢弃测试PCM，绝不把随机数据播放到USB。
音频环形缓冲64ms，初始预缓冲40ms；STOP可带 drain=true，在接收端队列排空后ACK。普通STOP清空待发数据，音频回调短淡出。最后音频超1秒触发watchdog状态停流。
STATS自动约100ms一次，含CRC错误、序号/索引缺口、累计采样及PCM累计CRC、buffer占用/峰值、underrun/overflow、UART错误及FIFO/软件缓冲/帧/奇偶细分。usb_mounted和usb_stream_active分开，consumed_frames仅为送入上游UAC内部队列的回调采样数，不能证明USB主机或手机实际收到。日志显示约1Hz，原始统计保存JSONL。控制统计不得夹杂printf。

## 流量/时钟
用UART全双工统计观察水位；当前没有硬件流控或基于credit的补发。禁止使用连接到BOOT/EN的RTS/DTR做流控。
不能对每1ms音频包使用stop-and-wait ACK，否则引入调度延迟。
有界流水线：发送队列不得无限堆积；过期帧处理必须记录，不能静默“补发”造成延迟越来越大。
实时捕获可显式 --asrc 用SoXR和缓存反馈适配两端时钟；默认关闭，启用后采样值会改变。物理长时间音频验证仍是独立验收项。

## 损坏与重连
CRC坏帧丢弃并记数，错误数据不送耳机；接收器对长无分隔符/畸形COBS限制内存。
重复帧、seq缺口、sample_index跳跃由会话层判定，protocol.py只做格式与CRC。
欠载用零/平滑淡出，恢复时重新预缓冲；不得硬读未初始化内存。
串口打开可能重启板子：等待HELLO、过滤启动日志，再进入流式状态。

参考工具：`python tools/bandwidth.py` 输出包括封包开销的带宽。
