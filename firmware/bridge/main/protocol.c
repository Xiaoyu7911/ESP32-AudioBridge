/* SPDX-License-Identifier: MIT */
#include "protocol.h"
#include <string.h>
#include "esp_rom_crc.h"

static uint16_t rd16(const uint8_t *p) { return p[0] | (uint16_t)p[1] << 8; }
static uint32_t rd32(const uint8_t *p) { return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24; }
static void wr32(uint8_t *p, uint32_t v) { for (int i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i)); }
uint32_t eab_crc32(uint32_t previous, const uint8_t *data, size_t len) { return esp_rom_crc32_le(previous, data, len); }

int eab_decode(const uint8_t *encoded, size_t len, uint8_t *raw, eab_frame_t *f)
{
    if (!len || len > EAB_MAX_ENCODED) return 1;
    size_t in=0, out=0;
    while (in < len) {
        unsigned code=encoded[in++];
        if (!code || in + code - 1 > len || out + code - 1 > EAB_MAX_RAW) return 1;
        for (unsigned i=1;i<code;i++) {
            if (!encoded[in]) return 1;
            raw[out++]=encoded[in++];
        }
        if (code != 255 && in < len) {
            if (out == EAB_MAX_RAW) return 1;
            raw[out++]=0;
        }
    }
    if (out < 36 || out > EAB_MAX_RAW) return 1;
    if (eab_crc32(0, raw, out-4) != rd32(raw+out-4)) return 2;
    if (memcmp(raw,"EAB1",4) || raw[4]!=1 || rd16(raw+6) || raw[5]<1 || raw[5]>9) return 1;
    f->kind=raw[5]; f->stream_id=rd32(raw+8); f->sequence=rd32(raw+12);
    f->sample_index=(uint64_t)rd32(raw+16) | (uint64_t)rd32(raw+20)<<32;
    f->frames=rd16(raw+24); f->channels=raw[26]; f->bits=raw[27];
    f->payload_len=rd32(raw+28); f->payload=raw+32;
    if (f->payload_len != out-36 || f->payload_len > EAB_MAX_PAYLOAD) return 1;
    if (f->kind == EAB_AUDIO) {
        if (!f->frames || (f->channels!=1 && f->channels!=2) || (f->bits!=16 && f->bits!=24)) return 1;
        if (f->payload_len != (uint32_t)f->frames * f->channels * (f->bits/8)) return 1;
    } else if (f->sample_index || f->frames || f->channels || f->bits) return 1;
    return 0;
}

size_t eab_encode_control(uint8_t kind, uint32_t sid, uint32_t sequence,
                          const char *json, uint8_t *raw, uint8_t *encoded)
{
    size_t n=strlen(json);
    if (n > EAB_MAX_PAYLOAD) return 0;
    memset(raw,0,32); memcpy(raw,"EAB1",4); raw[4]=1; raw[5]=kind;
    wr32(raw+8,sid); wr32(raw+12,sequence); wr32(raw+28,n);
    memcpy(raw+32,json,n); wr32(raw+32+n,eab_crc32(0,raw,32+n));
    size_t code_index=0, out=1; unsigned code=1;
    for (size_t i=0;i<36+n;i++) {
        if (!raw[i]) { encoded[code_index]=code; code_index=out++; code=1; }
        else {
            encoded[out++]=raw[i];
            if (++code==255) { encoded[code_index]=code; code_index=out++; code=1; }
        }
    }
    encoded[code_index]=code; encoded[out++]=0;
    return out;
}
