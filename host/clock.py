"""Explicit, bounded clock adaptation outside every audio callback.

Uses python-soxr 1.1.0's version-pinned experimental variable-rate API.
ASRC changes samples; it is never labelled bit-perfect or enabled silently.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np


class BufferController:
    """Slow PI controller; all levels are source PCM frames, times are seconds."""
    def __init__(self, target_frames: float = 1536, limit_ppm: float = 2000):
        self.target = target_frames
        self.limit = limit_ppm
        self.ppm = self.integral = 0.0
        self.filtered = target_frames
        self.last_time = None
        self.saturated_updates = 0

    def update(self, level_frames: float, now: float) -> float:
        if not math.isfinite(level_frames) or level_frames < 0 or not math.isfinite(now):
            raise ValueError('Invalid clock feedback')
        if self.last_time is None:
            self.last_time = now
            self.filtered = level_frames
            return self.ppm
        dt = now - self.last_time
        if dt <= 0:
            return self.ppm
        if dt > 1.0:
            raise RuntimeError('Clock feedback was absent for more than one second; stop stream')
        self.last_time = now
        self.filtered += (1 - math.exp(-dt / 2.0)) * (level_frames - self.filtered)
        error = self.target - self.filtered
        proposed_integral = self.integral + error * 0.15 * dt
        unconstrained = error * 2.0 + proposed_integral
        if abs(unconstrained) <= self.limit or error * unconstrained < 0:
            self.integral = max(-self.limit, min(self.limit, proposed_integral))
        desired = max(-self.limit, min(self.limit, error * 2.0 + self.integral))
        if abs(desired) == self.limit:
            self.saturated_updates += 1
        # Startup telemetry is often below the target. A slow reversal after
        # filling caused measured overshoot beyond the bounded 64ms ring.
        maximum_step = 500 * dt  # ppm/s, then libsoxr slews over another 100ms
        self.ppm += max(-maximum_step, min(maximum_step, desired - self.ppm))
        return self.ppm


@dataclass
class ASRCStats:
    input_frames: int = 0
    output_frames: int = 0
    invalid_input_samples: int = 0


class AdaptiveCapture:
    def __init__(self, channels: int):
        import soxr
        if soxr.__version__ != '1.1.0':
            raise RuntimeError('Install pinned soxr==1.1.0 before enabling the experimental ASRC API')
        self.channels = channels
        self.controller = BufferController()
        # Constructor ratio is the maximum I/O ratio permitted by soxr's API.
        self.resampler = soxr.ResampleStream(48000 * 1.003, 48000, channels,
                                             dtype='float32', quality='HQ', vr=True)
        self.resampler.set_io_ratio(48000, 48000, slew_len=0)
        self.stats = ASRCStats()
        self.finished = False
        self.last_feedback = None

    def process(self, data: np.ndarray) -> np.ndarray:
        if self.finished:
            raise ValueError('ASRC stream has already been flushed')
        x = np.asarray(data, dtype=np.float32).reshape(-1, self.channels)
        invalid = int(np.count_nonzero(~np.isfinite(x)))
        self.stats.invalid_input_samples += invalid
        if invalid:
            x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        self.stats.input_frames += len(x)
        out = self.resampler.resample_chunk(x)
        self.stats.output_frames += len(out)
        return out

    def observe(self, stats: dict, now: float) -> None:
        if not stats.get('usb_stream_active'):
            raise RuntimeError('USB recording stream is inactive; start the USB recorder before the sender')
        self.last_feedback = now
        if not stats.get('consumed_frames'):
            return  # Initial bounded prefill, not a drift measurement.
        frame_bytes = stats['channels'] * (stats['bits'] // 8)
        level = stats['buffer_bytes'] / frame_bytes
        ppm = self.controller.update(level, now)
        self.resampler.set_io_ratio(48000, 48000 * (1 + ppm * 1e-6), slew_len=4800)

    def check_timeout(self, now: float, started_at: float) -> None:
        if now - (self.last_feedback if self.last_feedback is not None else started_at) > 1.0:
            raise RuntimeError('No current clock feedback for one second; stop stream')

    def finish(self) -> np.ndarray:
        if self.finished:
            raise ValueError('ASRC may be flushed only once')
        self.finished = True
        out = self.resampler.resample_chunk(np.empty((0, self.channels), dtype=np.float32), last=True)
        self.stats.output_frames += len(out)
        return out

    def describe(self) -> dict:
        return {'method': 'soxr 1.1.0 HQ variable-rate (experimental API)', 'bit_perfect': False,
                'ratio_output_per_input': 1 + self.controller.ppm * 1e-6,
                'correction_ppm': self.controller.ppm, 'target_buffer_ms': self.controller.target / 48,
                'slew_limit_ppm_per_second': 500,
                'limit_ppm': self.controller.limit, 'saturated_updates': self.controller.saturated_updates,
                'pending_output_frames': float(self.resampler.delay()), **asdict(self.stats)}
