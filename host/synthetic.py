"""Bounded quiet bench source with an explicit artificial source clock offset."""
import math
import numpy as np


class SyntheticTone:
    def __init__(self, seconds: float, ppm: float = 0):
        if not math.isfinite(seconds) or not 0 < seconds <= 3600 or not math.isfinite(ppm) or abs(ppm) > 1000:
            raise ValueError('Bench duration must be 0..3600s and artificial source offset within +/-1000ppm')
        self.rate = 48000 * (1 + ppm * 1e-6)
        self.total_frames = math.ceil(seconds * self.rate)
        self.frames = 0

    def read(self, count: int = 240):
        count = min(count, self.total_frames - self.frames)
        if count <= 0:
            return None
        positions = self.frames + np.arange(count, dtype=np.float64)
        values = (10 ** (-24 / 20) * np.sin(positions * (2 * np.pi * 997 / self.rate))).astype(np.float32)
        self.frames += count
        return values.reshape(-1, 1)

    def deadline(self, started_at: float) -> float:
        return started_at + self.frames / self.rate
