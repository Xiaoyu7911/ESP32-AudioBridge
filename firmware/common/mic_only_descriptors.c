/* SPDX-License-Identifier: MIT
 * Project-owned, microphone-only UAC2 descriptors using TinyUSB's public macros.
 * Keep entity IDs aligned with usb_device_uac 1.3.2's microphone-only branch.
 * No feature/connector controls are advertised: the upstream control handler
 * sizes mute/volume arrays from speaker channels and does not apply mic gain.
 */
#include <string.h>
#include "tusb.h"
#include "uac_descriptors.h"

#if CONFIG_UAC_SPEAKER_CHANNEL_NUM != 0 || CONFIG_UAC_MIC_CHANNEL_NUM != 1
#error "The reviewed descriptors are for a single microphone and no speaker"
#endif

tusb_desc_device_t const desc_device={
    .bLength=sizeof(tusb_desc_device_t), .bDescriptorType=TUSB_DESC_DEVICE, .bcdUSB=0x0200,
    .bDeviceClass=TUSB_CLASS_MISC, .bDeviceSubClass=MISC_SUBCLASS_COMMON, .bDeviceProtocol=MISC_PROTOCOL_IAD,
    .bMaxPacketSize0=CFG_TUD_ENDPOINT0_SIZE, .idVendor=CONFIG_UAC_TUSB_VID, .idProduct=CONFIG_UAC_TUSB_PID,
    .bcdDevice=0x0100, .iManufacturer=1, .iProduct=2, .iSerialNumber=3, .bNumConfigurations=1,
};

uint8_t const desc_configuration[]={
    TUD_CONFIG_DESCRIPTOR(1,ITF_NUM_TOTAL,0,TUD_CONFIG_DESC_LEN+TUD_AUDIO_DEVICE_DESC_LEN,0x00,100),
    TUD_AUDIO_DESC_IAD(ITF_NUM_AUDIO_CONTROL,NUM_INTERFACES,0),
    TUD_AUDIO_DESC_STD_AC(ITF_NUM_AUDIO_CONTROL,0,4),
    TUD_AUDIO_DESC_CS_AC(0x0200,AUDIO_FUNC_MICROPHONE,TUD_AUDIO_DESC_CS_AC_TOTAL_LEN,AUDIO_CTRL_NONE),
    TUD_AUDIO_DESC_CLK_SRC(UAC2_ENTITY_CLOCK,1,1,UAC2_ENTITY_MIC_INPUT_TERMINAL,0),
    TUD_AUDIO_DESC_INPUT_TERM(UAC2_ENTITY_MIC_INPUT_TERMINAL,AUDIO_TERM_TYPE_IN_GENERIC_MIC,
        UAC2_ENTITY_MIC_OUTPUT_TERMINAL,UAC2_ENTITY_CLOCK,1,AUDIO_CHANNEL_CONFIG_FRONT_CENTER,0,AUDIO_CTRL_NONE,0),
    TUD_AUDIO_DESC_OUTPUT_TERM(UAC2_ENTITY_MIC_OUTPUT_TERMINAL,AUDIO_TERM_TYPE_USB_STREAMING,
        UAC2_ENTITY_MIC_INPUT_TERMINAL,UAC2_ENTITY_MIC_FEATURE_TERMINAL,UAC2_ENTITY_CLOCK,AUDIO_CTRL_NONE,0),
    TUD_AUDIO_DESC_FEATURE_UNIT_N_CHANNEL(TUD_AUDIO_DESC_MIC_FEATURE_UNIT_N_CHANNEL_LEN,
        UAC2_ENTITY_MIC_FEATURE_TERMINAL,UAC2_ENTITY_MIC_INPUT_TERMINAL,0,U32_TO_U8S_LE(0),U32_TO_U8S_LE(0)),
    TUD_AUDIO_DESC_STD_AS_INT(ITF_NUM_AUDIO_STREAMING_MIC,0,0,5),
    TUD_AUDIO_DESC_STD_AS_INT(ITF_NUM_AUDIO_STREAMING_MIC,1,1,5),
    TUD_AUDIO_DESC_CS_AS_INT(UAC2_ENTITY_MIC_OUTPUT_TERMINAL,AUDIO_CTRL_NONE,AUDIO_FORMAT_TYPE_I,
        AUDIO_DATA_FORMAT_TYPE_I_PCM,1,AUDIO_CHANNEL_CONFIG_FRONT_CENTER,0),
    TUD_AUDIO_DESC_TYPE_I_FORMAT(CFG_TUD_AUDIO_FUNC_1_FORMAT_1_N_BYTES_PER_SAMPLE_TX,
        CFG_TUD_AUDIO_FUNC_1_FORMAT_1_RESOLUTION_TX),
    TUD_AUDIO_DESC_STD_AS_ISO_EP(0x82,TUSB_XFER_ISOCHRONOUS|TUSB_ISO_EP_ATT_ASYNCHRONOUS|TUSB_ISO_EP_ATT_DATA,
        CFG_TUD_AUDIO_FUNC_1_FORMAT_1_EP_SZ_IN,1),
    TUD_AUDIO_DESC_CS_AS_ISO_EP(AUDIO_CS_AS_ISO_DATA_EP_ATT_NON_MAX_PACKETS_OK,AUDIO_CTRL_NONE,
        AUDIO_CS_AS_ISO_DATA_EP_LOCK_DELAY_UNIT_UNDEFINED,0),
};

char const *string_desc_arr[]={
    (const char[]){0x09,0x04},CONFIG_UAC_TUSB_MANUFACTURER,CONFIG_UAC_TUSB_PRODUCT,
    CONFIG_UAC_TUSB_SERIAL_NUM,"Audio control","Microphone",
};

uint8_t const *tud_descriptor_device_cb(void) { return (uint8_t const *)&desc_device; }
uint8_t const *tud_descriptor_configuration_cb(uint8_t index) { (void)index; return desc_configuration; }

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid)
{
    (void)langid;
    static uint16_t text[32];
    size_t length;
    if (!index) { text[1]=0x0409; length=1; }
    else {
        if (index>=sizeof(string_desc_arr)/sizeof(string_desc_arr[0])) return NULL;
        const char *value=string_desc_arr[index];
        length=strlen(value); if (length>31) length=31;
        for (size_t i=0;i<length;i++) text[i+1]=(uint8_t)value[i];
    }
    text[0]=(uint16_t)((TUSB_DESC_STRING<<8)|(2*length+2));
    return text;
}
