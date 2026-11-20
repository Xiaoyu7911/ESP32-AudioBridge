"""Generate quiet uncompressed PCM signals using the Python standard library."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import wave

ROOT = Path(__file__).resolve().parents[1]

def create(path: Path, seconds: float = 5.0, bits: int = 24,
           channels: int = 1, rate: int = 48000, level_dbfs: float = -24.0) -> dict:
    if bits not in (16, 24) or channels not in (1, 2) or rate != 48000:
        raise ValueError("supported test profiles: 48kHz, 16/24-bit, mono/stereo")
    if not (0.02 <= seconds <= 600) or not (-80 <= level_dbfs <= -6):
        raise ValueError("duration/level outside conservative test limits")
    path.parent.mkdir(parents=True, exist_ok=True)
    count = round(seconds * rate)
    width = bits // 8
    amplitude = (2**(bits-1)-1) * 10**(level_dbfs/20)
    fade_samples = 240
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels); wav.setsampwidth(width); wav.setframerate(rate)
        pending = bytearray()
        for i in range(count):
            envelope = min(1.0, i/fade_samples, (count-1-i)/fade_samples)
            for c in range(channels):
                frequency = 997.0 if c == 0 else 1499.0
                sample = round(amplitude * envelope * math.sin(2*math.pi*frequency*i/rate))
                pending.extend(sample.to_bytes(width, "little", signed=True))
            if len(pending) >= 65536:
                wav.writeframesraw(pending); pending.clear()
        wav.writeframesraw(pending)
    result = {"path": str(path), "sample_rate": rate, "bits": bits,
              "channels": channels, "frames": count, "level_dbfs": level_dbfs,
              "frequencies_hz": [997] if channels == 1 else [997, 1499],
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "evidence_type": "GENERATED_TEST_SIGNAL_NOT_MEASUREMENT"}
    path.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--bits", type=int, choices=[16,24], default=24)
    parser.add_argument("--channels", type=int, choices=[1,2], default=1)
    parser.add_argument("--level", type=float, default=-24)
    args = parser.parse_args()
    path = ROOT / "artifacts" / f"test_48k_{args.bits}bit_{args.channels}ch.wav"
    print(json.dumps(create(path,args.seconds,args.bits,args.channels,level_dbfs=args.level),indent=2))

if __name__ == "__main__":
    main()
