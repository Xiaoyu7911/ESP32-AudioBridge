"""Explicit PCM conversion, bounded callback queue, and strict WAV input."""
from __future__ import annotations
from dataclasses import dataclass
import wave
import numpy as np


def reject_bridge_capture(name: str) -> None:
    # Windows' actual label for our current control interface is "Audio control".
    # Product-name-only checks miss that endpoint and can create a feedback loop.
    if any(alias in name.casefold() for alias in ('esp audio bridge', 'audio control')):
        raise ValueError('Cannot capture the returned bridge microphone into its own sender; choose the explicit post-FX source')


@dataclass
class ConversionStats:
    invalid_samples: int = 0
    clipped_samples: int = 0
    converted_frames: int = 0


class PCMConverter:
    def __init__(self, input_channels: int, output_channels: int, bits: int,
                 mix: str | None = None, dither: bool = True, seed: int | None = None):
        if input_channels not in (1, 2) or output_channels not in (1, 2) or bits not in (16, 24):
            raise ValueError('Supported formats: mono/stereo, signed 16/24-bit')
        if input_channels == 2 and output_channels == 1 and mix not in ('average', 'left', 'right'):
            raise ValueError('Stereo→mono requires explicit --mix average/left/right; stereo space changes')
        if input_channels == 1 and output_channels == 2:
            raise ValueError('Implicit mono duplication is disabled')
        self.input_channels, self.output_channels, self.bits = input_channels, output_channels, bits
        self.mix, self.dither = mix, dither and bits == 16
        self.rng = np.random.default_rng(seed)
        self.stats = ConversionStats()

    def convert(self, data: np.ndarray) -> bytes:
        data = np.asarray(data, dtype=np.float64).reshape(-1, self.input_channels)
        self.stats.invalid_samples += int(np.count_nonzero(~np.isfinite(data)))
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
        if self.input_channels == 2 and self.output_channels == 1:
            data = data.mean(axis=1, keepdims=True) if self.mix == 'average' else data[:, [0 if self.mix == 'left' else 1]]
        scale = 1 << (self.bits - 1)
        self.stats.clipped_samples += int(np.count_nonzero((data < -1.0) | (data > (scale - 1) / scale)))
        data = np.clip(data, -1.0, (scale - 1) / scale) * scale
        if self.dither:
            # TPDF, +/- 1 LSB peak; only in explicit float/integer conversion.
            data += self.rng.random(data.shape) - self.rng.random(data.shape)
        integers = np.clip(np.rint(data), -scale, scale - 1).astype('<i4').reshape(-1)
        self.stats.converted_frames += len(integers) // self.output_channels
        if self.bits == 16:
            return integers.astype('<i2').tobytes()
        packed = np.empty((len(integers), 3), dtype=np.uint8)
        packed[:, 0] = integers & 255
        packed[:, 1] = (integers >> 8) & 255
        packed[:, 2] = (integers >> 16) & 255
        return packed.tobytes()


def unpack_pcm(data: bytes, bits: int, channels: int) -> np.ndarray:
    if len(data) % (channels * (bits // 8)):
        raise ValueError('PCM frame is truncated')
    if bits == 16:
        values = np.frombuffer(data, dtype='<i2').astype(np.float64)
    elif bits == 24:
        b = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        values = ((values ^ 0x800000) - 0x800000).astype(np.float64)
    else:
        raise ValueError('Only signed PCM16 and packed PCM24 are supported')
    return (values / (1 << (bits - 1))).reshape(-1, channels)


class WavSource:
    def __init__(self, path, bits: int | None = None, channels: int = 1, mix: str | None = None):
        self.wav = wave.open(str(path), 'rb')
        try:
            self.source_bits = self.wav.getsampwidth() * 8
            self.source_channels = self.wav.getnchannels()
            if self.wav.getframerate() != 48000 or self.wav.getcomptype() != 'NONE':
                raise ValueError('WAV must be uncompressed 48000 Hz PCM; no silent resampling')
            if self.source_bits not in (16, 24) or self.source_channels not in (1, 2):
                raise ValueError('WAV must be PCM16/24, mono/stereo')
            self.bits = bits or self.source_bits
            self.channels = channels
            self.direct = self.bits == self.source_bits and channels == self.source_channels
            self.converter = PCMConverter(self.source_channels, channels, self.bits, mix)
            self.total_frames = self.wav.getnframes()
        except BaseException:
            self.wav.close()
            raise

    def read(self, count: int) -> bytes:
        data = self.wav.readframes(count)
        if self.direct or not data:
            return data
        return self.converter.convert(unpack_pcm(data, self.source_bits, self.source_channels))

    def close(self):
        self.wav.close()


class CallbackQueue:
    """Single producer/consumer, CPython 3.12 GIL. No wait or large allocation in callback.

    Input callback only copies into preallocated storage. The consumer owns a slot
    until pop() has made its copy. Full queues drop the incoming block and count it;
    the sender aborts on any drop rather than hiding a broken realtime path.
    """
    def __init__(self, frames: int, channels: int, slots: int = 16, sample_bytes: int = 4,
                 armed: bool = True):
        if frames <= 0 or channels not in (1, 2) or slots < 2 or sample_bytes not in (2, 3, 4):
            raise ValueError('Invalid bounded PCM callback queue format')
        self.block_bytes = frames * channels * sample_bytes
        self.storage = [bytearray(self.block_bytes) for _ in range(slots)]
        self.write_index = self.read_index = 0
        self.slots = slots
        self.dropped_blocks = self.status_events = 0
        self.callback_error = False
        self.armed = armed
        self.startup_discarded_frames = 0

    def arm(self):
        """Begin the measured stream after backend startup and board readiness."""
        if self.armed or self.write_index != self.read_index:
            raise RuntimeError('Capture queue may be armed only once while empty')
        self.armed = True

    def callback(self, indata, frames, time_info, status):
        if status:
            self.status_events += 1
        if len(indata) != self.block_bytes:
            self.callback_error = True
            return
        if not self.armed:
            self.startup_discarded_frames += frames
            return
        if self.write_index - self.read_index >= self.slots:
            self.dropped_blocks += 1
            return
        self.storage[self.write_index % self.slots][:] = indata
        self.write_index += 1

    def pop(self) -> bytes | None:
        if self.read_index == self.write_index:
            return None
        data = bytes(self.storage[self.read_index % self.slots])
        self.read_index += 1
        return data
