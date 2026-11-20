# 编译与恢复

已编译、带哈希的主版本镜像位于 [prebuilt](../prebuilt/README.md)。普通使用者无需安装 ESP-IDF。

## 固定依赖

| 项目 | 版本 |
| :--- | :--- |
| 芯片 | ESP32-S3 |
| ESP-IDF | 5.5.6；commit `880a203ae603d08a94d06aa01e0d6761958e5e9e` |
| espressif/usb_device_uac | 1.3.2 |
| espressif/tinyusb | 0.19.0~3 |
| espressif/cmake_utilities | 1.2.0 |

组件内容哈希见 `firmware/bridge/dependencies.lock`。主目录固件源码对应历史构建输入，逐文件哈希记录在 `SOURCE_PROVENANCE.json`；依赖锁保留原构建使用的换行格式。固定组件内容不在此源码包内重复分发，由 ESP-IDF 组件管理器按锁文件获取。

## 构建 24-bit 单声道

先按 ESP-IDF 自身说明准备上述版本的开发环境，并在已激活 ESP-IDF 的终端中进入 `firmware/bridge/`：

```bash
idf.py -B build24_2m -D SDKCONFIG=build24_2m/sdkconfig -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.24.defaults;sdkconfig.2m.defaults" build
```

基础配置已选择 ESP32-S3。构建后检查 `build24_2m/sdkconfig` 确认 48 kHz、24-bit、mic channels=1、speaker channels=0、UART=2000000。使用干净、独立的构建目录，避免旧 sdkconfig 影响配置。

16-bit 回退使用基础 16-bit 配置和 2M 配置：

```bash
idf.py -B build16_2m -D SDKCONFIG=build16_2m/sdkconfig -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.2m.defaults" build
```

本次发布整理没有重编译或重新刷板。重新编译的二进制可能受路径、工具链、时间信息等影响，不能仅凭源码相同沿用历史镜像 SHA256 或硬件验收结果。

## 恢复

按 [prebuilt/README.md](../prebuilt/README.md) 检查相应配置的三个镜像和哈希，再对一个明确枚举、确认的设备执行写入。24-bit 和 16-bit 是独立固件；仅改变主机发送位深不能替代刷入对应镜像。

开发中的立体声与双向版本使用独立源码目录和构建选项，请先阅读对应开发目录说明。它们不能与主目录单声道镜像混用。
