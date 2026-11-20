/* SPDX-License-Identifier: MIT */
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#define EAB_MAX_PAYLOAD 4096u
#define EAB_MAX_RAW (32u + EAB_MAX_PAYLOAD + 4u)
#define EAB_MAX_ENCODED (EAB_MAX_RAW + EAB_MAX_RAW / 254u + 2u)
enum { EAB_HELLO=1, EAB_CONFIG, EAB_START, EAB_AUDIO, EAB_STOP,
       EAB_STATS, EAB_ACK, EAB_ERROR, EAB_HEARTBEAT };
typedef struct {
    uint8_t kind, channels, bits;
    uint32_t stream_id, sequence;
    uint64_t sample_index;
    uint16_t frames;
    uint32_t payload_len;
    const uint8_t *payload;
} eab_frame_t;

/* Decode returns 0=valid, 1=COBS/format error, 2=CRC error. */
int eab_decode(const uint8_t *encoded, size_t len, uint8_t *scratch, eab_frame_t *frame);
size_t eab_encode_control(uint8_t kind, uint32_t sid, uint32_t sequence,
                          const char *json, uint8_t *raw, uint8_t *encoded);
uint32_t eab_crc32(uint32_t previous, const uint8_t *data, size_t len);
