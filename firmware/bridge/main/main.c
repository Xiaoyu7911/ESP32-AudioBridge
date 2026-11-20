/* SPDX-License-Identifier: MIT
 * UART0 framed PCM -> native USB microphone. No board codec or network.
 * Hardware, phone and long-duration clock adaptation remain acceptance gates.
 */
#include <assert.h>
#include <string.h>
#include <stdint.h>
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "cJSON.h"
#include "usb_device_uac.h"
#include "tusb.h"
#include "protocol.h"

#if CONFIG_UAC_SAMPLE_RATE != 48000 || CONFIG_UAC_MIC_CHANNEL_NUM != 1
#error "This bridge profile is 48kHz mono. Stereo is a separate, unvalidated enhancement."
#endif
#if CONFIG_UAC_BYTES_PER_SAMPLE != 2 && CONFIG_UAC_BYTES_PER_SAMPLE != 3
#error "Only packed PCM16/24 is implemented; no implicit 24-in-32 conversion."
#endif
#if CONFIG_FREERTOS_UNICORE
#error "UART/USB interrupt isolation requires the dual-core ESP32-S3 profile."
#endif
#define SAMPLE_BYTES CONFIG_UAC_BYTES_PER_SAMPLE
#define SAMPLE_BITS CONFIG_UAC_BIT_RESOLUTION
#define UART_BAUD CONFIG_EAB_UART_BAUD
#define RING_BYTES (48000 * SAMPLE_BYTES * 64 / 1000)
/* The component supplies 10ms microphone blocks. A 20ms startup prefill left
 * only 10ms after its first callback, below measured Windows scheduling gaps.
 * Four blocks start near the host's 32ms feedback target without enlarging the
 * fixed 64ms ring. This changes startup buffering, not the sample format. */
#define PREFILL_BYTES (48000 * SAMPLE_BYTES * 40 / 1000)

typedef struct {
    uint64_t audio_frames, usb_callback_frames, consumed_frames, silence_frames;
    uint32_t audio_crc32, crc_errors, malformed_frames, sequence_gaps;
    uint32_t index_gaps, audio_rejected, overflows, underruns, uart_errors;
    uint32_t uart_fifo_overflows, uart_buffer_full, uart_frame_errors, uart_parity_errors;
    uint32_t max_buffer_bytes, watchdog_stops;
} statistics_t;

static portMUX_TYPE mux=portMUX_INITIALIZER_UNLOCKED;
static uint8_t ring[RING_BYTES];
static size_t read_at, write_at, available;
static bool running, configured, primed, integrity_mode, draining;
static bool stop_pending, drain_failed;
static uint32_t stop_reply;
static int32_t last_sample;
static statistics_t stats;
static uint32_t sid, tx_sequence, expected_sequence;
static bool have_session;
static int64_t last_audio_us, last_sink_us;
static QueueHandle_t uart_events;
static uint8_t encoded[EAB_MAX_ENCODED], raw[EAB_MAX_RAW];
static uint8_t tx_raw[EAB_MAX_RAW], tx_encoded[EAB_MAX_ENCODED];
static size_t encoded_len;
static bool discarding;

static void clear_ring_locked(void)
{
    available=read_at=write_at=0;
    primed=false;
}

static void send_json(uint8_t kind, uint32_t reply, cJSON *object)
{
    if (!object) return;
    char json[2048];
    cJSON_AddNumberToObject(object,"reply_to",reply);
    if (cJSON_PrintPreallocated(object,json,sizeof(json),false)) {
        size_t length=eab_encode_control(kind,sid,tx_sequence++,json,tx_raw,tx_encoded);
        if (length) uart_write_bytes(UART_NUM_0,tx_encoded,length);
    }
    cJSON_Delete(object);
}

static void reply_ok(uint32_t reply)
{
    cJSON *o=cJSON_CreateObject();
    if (o) cJSON_AddBoolToObject(o,"ok",true);
    send_json(EAB_ACK,reply,o);
}

static void reply_error(uint32_t reply, const char *message)
{
    cJSON *o=cJSON_CreateObject();
    if (o) { cJSON_AddBoolToObject(o,"ok",false); cJSON_AddStringToObject(o,"message",message); }
    send_json(EAB_ERROR,reply,o);
}

static void send_stats(uint32_t reply)
{
    statistics_t s; size_t used; bool active, test; int64_t sink_time;
    portENTER_CRITICAL(&mux);
    s=stats; used=available; active=running; test=integrity_mode; sink_time=last_sink_us;
    portEXIT_CRITICAL(&mux);
    cJSON *o=cJSON_CreateObject();
    if (!o) return;
#define NUMBER(k,v) cJSON_AddNumberToObject(o,k,(double)(v))
    NUMBER("audio_frames",s.audio_frames); NUMBER("audio_crc32",s.audio_crc32);
    NUMBER("usb_callback_frames",s.usb_callback_frames); NUMBER("consumed_frames",s.consumed_frames);
    NUMBER("silence_frames",s.silence_frames); NUMBER("crc_errors",s.crc_errors);
    NUMBER("malformed_frames",s.malformed_frames); NUMBER("sequence_gaps",s.sequence_gaps);
    NUMBER("index_gaps",s.index_gaps); NUMBER("audio_rejected",s.audio_rejected);
    NUMBER("overflows",s.overflows); NUMBER("underruns",s.underruns);
    NUMBER("uart_errors",s.uart_errors); NUMBER("buffer_bytes",used);
    NUMBER("uart_fifo_overflows",s.uart_fifo_overflows); NUMBER("uart_buffer_full",s.uart_buffer_full);
    NUMBER("uart_frame_errors",s.uart_frame_errors); NUMBER("uart_parity_errors",s.uart_parity_errors);
    NUMBER("buffer_capacity_bytes",RING_BYTES); NUMBER("max_buffer_bytes",s.max_buffer_bytes);
    NUMBER("watchdog_stops",s.watchdog_stops); NUMBER("bits",SAMPLE_BITS);
    NUMBER("sample_rate",48000); NUMBER("channels",1);
#undef NUMBER
    cJSON_AddBoolToObject(o,"running",active);
    cJSON_AddBoolToObject(o,"usb_mounted",tud_mounted());
    cJSON_AddBoolToObject(o,"usb_stream_active",sink_time>0 && esp_timer_get_time()-sink_time<100000);
    cJSON_AddStringToObject(o,"mode",test?"integrity":"audio");
    cJSON_AddStringToObject(o,"clock_adaptation","none");
    send_json(EAB_STATS,reply,o);
}

static int32_t sample_read(const uint8_t *p)
{
    uint32_t value=p[0] | (uint32_t)p[1]<<8;
#if SAMPLE_BYTES == 3
    value |= (uint32_t)p[2]<<16;
    return (int32_t)(value<<8)>>8;
#else
    return (int16_t)value;
#endif
}

static void sample_write(uint8_t *p, int32_t value)
{
    for (unsigned i=0;i<SAMPLE_BYTES;i++) p[i]=(uint8_t)((uint32_t)value>>(8*i));
}

static esp_err_t microphone(uint8_t *buf, size_t len, size_t *bytes_read, void *ctx)
{
    (void)ctx;
    if (!buf || !bytes_read) return ESP_ERR_INVALID_ARG;
    size_t aligned=len-len%SAMPLE_BYTES;
    memset(buf,0,len);
    portENTER_CRITICAL(&mux);
    last_sink_us=esp_timer_get_time();
    stats.usb_callback_frames+=aligned/SAMPLE_BYTES;
    if (running && !integrity_mode && !primed && (available>=PREFILL_BYTES || draining)) primed=true;
    size_t take=running && !integrity_mode && primed ? (available<aligned?available:aligned) : 0;
    take-=take%SAMPLE_BYTES;
    if (take) {
        size_t first=take<RING_BYTES-read_at?take:RING_BYTES-read_at;
        memcpy(buf,ring+read_at,first);
        memcpy(buf+first,ring,take-first);
        read_at=(read_at+take)%RING_BYTES; available-=take;
        stats.consumed_frames+=take/SAMPLE_BYTES;
        last_sample=sample_read(buf+take-SAMPLE_BYTES);
    }
    if (take<aligned) {
        size_t fade=(aligned-take)/SAMPLE_BYTES;
        if (fade>48) fade=48;
        for (size_t i=0;i<fade;i++) sample_write(buf+take+i*SAMPLE_BYTES,last_sample*(int32_t)(47-i)/48);
        last_sample=0;
        stats.silence_frames+=(aligned-take)/SAMPLE_BYTES;
        if (running && primed && !integrity_mode && !draining) { stats.underruns++; primed=false; }
    }
    if (running && draining && !available) { running=false; draining=false; primed=false; }
    portEXIT_CRITICAL(&mux);
    *bytes_read=aligned;
    return ESP_OK;
}

static bool number_is(cJSON *o, const char *key, int value)
{
    cJSON *item=cJSON_GetObjectItemCaseSensitive(o,key);
    return cJSON_IsNumber(item) && item->valuedouble==value;
}

static bool is_running(void)
{
    portENTER_CRITICAL(&mux);
    bool active=running;
    portEXIT_CRITICAL(&mux);
    return active;
}

static void receive_frame(const eab_frame_t *f)
{
    if (f->kind==EAB_HELLO) {
        portENTER_CRITICAL(&mux);
        running=configured=draining=false; clear_ring_locked();
        portEXIT_CRITICAL(&mux);
        sid=f->stream_id; tx_sequence=0; expected_sequence=f->sequence+1; have_session=true;
        stop_pending=false;
        cJSON *o=cJSON_CreateObject();
        if (o) {
            uint32_t actual_baud=0; uart_get_baudrate(UART_NUM_0,&actual_baud);
            cJSON_AddNumberToObject(o,"protocol",1);
            cJSON_AddStringToObject(o,"firmware","0.2.2");
            cJSON_AddNumberToObject(o,"sample_rate",48000);
            cJSON_AddNumberToObject(o,"bits",SAMPLE_BITS); cJSON_AddNumberToObject(o,"channels",1);
            cJSON_AddNumberToObject(o,"baud",actual_baud);
            cJSON_AddNumberToObject(o,"uart_task_core",xPortGetCoreID());
            cJSON_AddNumberToObject(o,"prefill_ms",40);
            cJSON_AddNumberToObject(o,"reset_reason",esp_reset_reason());
        }
        send_json(EAB_HELLO,f->sequence,o); return;
    }
    if (!have_session || f->stream_id!=sid) return;
    bool gap=f->sequence!=expected_sequence;
    expected_sequence=f->sequence+1;
    if (gap) {
        portENTER_CRITICAL(&mux); stats.sequence_gaps++; portEXIT_CRITICAL(&mux);
        if (f->kind==EAB_AUDIO) { reply_error(f->sequence,"sequence discontinuity; stop and restart"); return; }
    }
    if (f->kind==EAB_AUDIO) {
        bool accept;
        portENTER_CRITICAL(&mux);
        accept=running && !draining && f->bits==SAMPLE_BITS && f->channels==1 && f->sample_index==stats.audio_frames;
        if (!accept) { stats.audio_rejected++; if (f->sample_index!=stats.audio_frames) stats.index_gaps++; }
        portEXIT_CRITICAL(&mux);
        if (!accept) { reply_error(f->sequence,"audio state, format or sample index mismatch"); return; }
        uint32_t crc=eab_crc32(stats.audio_crc32,f->payload,f->payload_len);
        portENTER_CRITICAL(&mux);
        stats.audio_crc32=crc; stats.audio_frames+=f->frames;
        if (!integrity_mode) {
            if (f->payload_len>RING_BYTES-available) { stats.overflows++; stats.audio_rejected++; }
            else {
                size_t first=f->payload_len<RING_BYTES-write_at?f->payload_len:RING_BYTES-write_at;
                memcpy(ring+write_at,f->payload,first); memcpy(ring,f->payload+first,f->payload_len-first);
                write_at=(write_at+f->payload_len)%RING_BYTES; available+=f->payload_len;
                if (available>stats.max_buffer_bytes) stats.max_buffer_bytes=available;
            }
        }
        last_audio_us=esp_timer_get_time();
        portEXIT_CRITICAL(&mux);
        return;
    }
    if (f->payload_len && memchr(f->payload,0,f->payload_len)) { reply_error(f->sequence,"NUL in control JSON"); return; }
    cJSON *o=cJSON_ParseWithLength((const char *)f->payload,f->payload_len);
    if (!cJSON_IsObject(o)) { cJSON_Delete(o); reply_error(f->sequence,"control JSON object required"); return; }
    switch (f->kind) {
    case EAB_CONFIG: {
        cJSON *mode=cJSON_GetObjectItemCaseSensitive(o,"mode");
        if (is_running() || !number_is(o,"sample_rate",48000) || !number_is(o,"bits",SAMPLE_BITS) || !number_is(o,"channels",1)
            || !cJSON_IsString(mode) || (strcmp(mode->valuestring,"audio") && strcmp(mode->valuestring,"integrity"))) {
            reply_error(f->sequence,"fixed profile mismatch, bad mode or stream still running"); break;
        }
        portENTER_CRITICAL(&mux);
        configured=true; integrity_mode=!strcmp(mode->valuestring,"integrity");
        portEXIT_CRITICAL(&mux); reply_ok(f->sequence); break;
    }
    case EAB_START:
        if (!configured || is_running()) { reply_error(f->sequence,"CONFIG required while stopped"); break; }
        portENTER_CRITICAL(&mux);
        bool sink_ready=integrity_mode || (last_sink_us>0 && esp_timer_get_time()-last_sink_us<100000);
        portEXIT_CRITICAL(&mux);
        if (!sink_ready) { reply_error(f->sequence,"start USB recorder before audio sender"); break; }
        portENTER_CRITICAL(&mux);
        memset(&stats,0,sizeof(stats)); clear_ring_locked(); running=true; draining=false;
        drain_failed=false; last_audio_us=esp_timer_get_time();
        portEXIT_CRITICAL(&mux); reply_ok(f->sequence); break;
    case EAB_STOP: {
        bool drain=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(o,"drain"));
        portENTER_CRITICAL(&mux);
        if (drain && running && !integrity_mode && available) { draining=true; stop_pending=true; stop_reply=f->sequence; }
        else { running=draining=false; stop_pending=false; clear_ring_locked(); }
        portEXIT_CRITICAL(&mux);
        if (!stop_pending) reply_ok(f->sequence);
        break;
    }
    case EAB_STATS: send_stats(f->sequence); break;
    case EAB_HEARTBEAT: reply_ok(f->sequence); break;
    default: reply_error(f->sequence,"unsupported control direction"); break;
    }
    cJSON_Delete(o);
}

static void uart_worker(void *ctx)
{
    (void)ctx;
    /* IDF allocates peripheral interrupts on the calling core. Install the
     * UART driver here, on CPU1, away from native USB's CPU0 interrupt.
     * Merely pinning this worker after installation would leave the ISR on CPU0. */
    uart_config_t cfg={.baud_rate=UART_BAUD,.data_bits=UART_DATA_8_BITS,.parity=UART_PARITY_DISABLE,
        .stop_bits=UART_STOP_BITS_1,.flow_ctrl=UART_HW_FLOWCTRL_DISABLE,.source_clk=UART_SCLK_DEFAULT};
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0,&cfg));
    ESP_ERROR_CHECK(uart_set_pin(UART_NUM_0,43,44,UART_PIN_NO_CHANGE,UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0,16384,0,32,&uart_events,0));
    /* Leave 64 FIFO bytes (~213us at 3M 8N1) for ISR scheduling latency. */
    ESP_ERROR_CHECK(uart_set_rx_full_threshold(UART_NUM_0,64));
    uint8_t chunk[1024]; int64_t last_stats=0;
    while (1) {
        uart_event_t event;
        while (xQueueReceive(uart_events,&event,0)) {
            if (event.type==UART_FIFO_OVF || event.type==UART_BUFFER_FULL || event.type==UART_FRAME_ERR || event.type==UART_PARITY_ERR) {
                portENTER_CRITICAL(&mux);
                stats.uart_errors++;
                if (event.type==UART_FIFO_OVF) stats.uart_fifo_overflows++;
                if (event.type==UART_BUFFER_FULL) stats.uart_buffer_full++;
                if (event.type==UART_FRAME_ERR) stats.uart_frame_errors++;
                if (event.type==UART_PARITY_ERR) stats.uart_parity_errors++;
                portEXIT_CRITICAL(&mux);
                if (event.type==UART_FIFO_OVF || event.type==UART_BUFFER_FULL) {
                    uart_flush_input(UART_NUM_0); encoded_len=0; discarding=true;
                }
            }
        }
        int n=uart_read_bytes(UART_NUM_0,chunk,sizeof(chunk),pdMS_TO_TICKS(5));
        for (int i=0;i<n;i++) {
            uint8_t value=chunk[i];
            if (!value) {
                if (!discarding && encoded_len) {
                    eab_frame_t frame;
                    int error=eab_decode(encoded,encoded_len,raw,&frame);
                    if (!error) receive_frame(&frame);
                    else {
                        portENTER_CRITICAL(&mux);
                        if (error==2) stats.crc_errors++; else stats.malformed_frames++;
                        portEXIT_CRITICAL(&mux);
                    }
                }
                encoded_len=0; discarding=false;
            } else if (!discarding) {
                if (encoded_len>=sizeof(encoded)) { encoded_len=0; discarding=true;
                    portENTER_CRITICAL(&mux); stats.malformed_frames++; portEXIT_CRITICAL(&mux); }
                else encoded[encoded_len++]=value;
            }
        }
        int64_t now=esp_timer_get_time();
        portENTER_CRITICAL(&mux);
        if (running && now-last_audio_us>1000000) {
            running=draining=false; clear_ring_locked(); stats.watchdog_stops++; drain_failed=stop_pending;
        }
        bool stopped=!running;
        portEXIT_CRITICAL(&mux);
        if (stop_pending && stopped) {
            stop_pending=false;
            if (drain_failed) reply_error(stop_reply,"sink drain timeout"); else reply_ok(stop_reply);
        }
        if (have_session && now-last_stats>=100000) { send_stats(UINT32_MAX); last_stats=now; }
    }
}

void app_main(void)
{
    assert(eab_crc32(0,(const uint8_t *)"123456789",9)==0xcbf43926u);
    uac_device_config_t uac={.skip_tinyusb_init=false,.input_cb=microphone,.output_cb=NULL,.cb_ctx=NULL};
    ESP_ERROR_CHECK(uac_device_init(&uac));
    assert(xTaskCreatePinnedToCore(uart_worker,"eab_uart",8192,NULL,8,NULL,1)==pdPASS);
}
