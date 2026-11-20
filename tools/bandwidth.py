"""Print conservative UART 8N1 bitrate including protocol overhead."""
from __future__ import annotations
import json

def estimate(rate: int, bits: int, channels: int, block_frames: int, baud: int) -> dict:
    if rate <= 0 or bits not in (16, 24) or channels not in (1, 2) or block_frames <= 0 or baud <= 0:
        raise ValueError("invalid audio/serial parameters")
    payload = block_frames * channels * (bits // 8)
    raw = 32 + payload + 4
    wire = raw + raw // 254 + 2  # conservative COBS + delimiter
    uart_bps = wire * (rate / block_frames) * 10
    return {"rate": rate, "bits": bits, "channels": channels,
            "block_frames": block_frames, "baud": baud,
            "audio_bytes_per_second": rate * channels * (bits // 8),
            "max_wire_bytes_per_block": wire, "required_uart_bits_per_second": uart_bps,
            "utilization": uart_bps / baud,
            "physical_transmission_ms_per_block": wire * 10 / baud * 1000,
            "note": "The wire duration is NOT end-to-end latency; telemetry is additional."}

if __name__ == "__main__":
    values = [estimate(48000, b, c, 48, baud)
              for b, c, baud in ((16, 1, 3000000), (24, 1, 3000000),
                                  (24, 2, 3000000), (24, 2, 4000000))]
    print(json.dumps(values, indent=2))
