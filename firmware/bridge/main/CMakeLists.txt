idf_component_register(SRCS "main.c" "protocol.c" INCLUDE_DIRS "."
    REQUIRES usb_device_uac espressif__tinyusb esp_driver_uart esp_timer json esp_rom)
