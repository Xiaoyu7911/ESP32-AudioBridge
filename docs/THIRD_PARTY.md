# 第三方版本与许可

项目自写源码遵循根目录 MIT LICENSE。上游文件及依赖保留各自许可，未用项目许可覆盖。

| 组件 | 固定版本 | 许可/来源 |
|---|---|---|
| ESP-IDF | 5.5.6，commit 880a203ae603d08a94d06aa01e0d6761958e5e9e | Apache-2.0；https://github.com/espressif/esp-idf |
| usb_device_uac | 1.3.2 | Apache-2.0；https://components.espressif.com/components/espressif/usb_device_uac/versions/1.3.2 |
| TinyUSB | 0.19.0~3 | MIT；https://github.com/hathach/tinyusb |
| cmake_utilities | 1.2.0 | Apache-2.0；Espressif组件库 |
| python-soxr/libsoxr | 1.1.0 / wheel报告0.1.3-14-ga66f3ee | LGPL-2.1-or-later；https://github.com/dofuuz/python-soxr/tree/v1.1.0 |
| NumPy | 2.2.6 | BSD-3-Clause及所含依赖许可；https://numpy.org |
| sounddevice/PortAudio | 0.5.3 / wheel内版本 | MIT/PortAudio许可；https://github.com/spatialaudio/python-sounddevice |
| pyserial | 3.5 | BSD-3-Clause；https://github.com/pyserial/pyserial |
| cffi/pycparser | 2.1.1 / 3.12 | MIT/BSD-3-Clause；PyPI官方项目 |

固件组件完整来源和内容哈希保存在每个工程的 dependencies.lock；已下载源树位于被Git忽略的 managed_components，未修改其原文件。固件映像同时包含上游代码，应随源码/依赖锁及本许可说明一同交付。
主机Python依赖通过pip按锁文件安装，发布源码包不打入整个.venv；如另行分发wheel或动态库，须一并保留其dist-info中的许可及源码来源。
