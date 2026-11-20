"""Inspect PCM WAV locally; makes no latency or bit-depth provenance claims."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import wave


def inspect(path: Path) -> dict:
    count = 0
    total_sq = 0.0
    peak = 0
    clipped = 0
    low_byte_nonzero = 0
    with wave.open(str(path), "rb") as wav:
        width = wav.getsampwidth()
        if wav.getcomptype() != "NONE" or width not in (2,3,4):
            raise ValueError("only signed 16/24/32-bit integer PCM WAV is supported")
        channels, rate, frames = wav.getnchannels(), wav.getframerate(), wav.getnframes()
        full = 2**(width*8-1)
        while True:
            block = wav.readframes(4096)
            if not block: break
            if len(block) % width: raise ValueError("unaligned audio payload")
            for i in range(0,len(block),width):
                value = int.from_bytes(block[i:i+width],"little",signed=True)
                peak = max(peak,abs(value))
                total_sq += float(value)*float(value)
                clipped += int(value <= -full or value >= full-1)
                low_byte_nonzero += int(block[i] != 0)
                count += 1
    rms = math.sqrt(total_sq/count)/full if count else 0
    return {"sample_rate":rate,"channels":channels,"container_bits":width*8,
            "frames":frames,"duration_seconds":frames/rate,
            "peak_dbfs":20*math.log10(peak/full) if peak else None,
            "rms_dbfs":20*math.log10(rms) if rms else None,
            "full_scale_samples":clipped,
            "nonzero_low_byte_fraction":low_byte_nonzero/count if count else 0,
            "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "note":"WAV header and low-byte activity do NOT prove the upstream effective bit depth. No latency measured."}

if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("path",type=Path)
    print(json.dumps(inspect(parser.parse_args().path),indent=2))
