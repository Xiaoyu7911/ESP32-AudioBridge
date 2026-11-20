"""Optional bounded stage timing on the consumer thread, never an audio callback."""
from collections import deque
import time


class TimingProbe:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.max_seconds = {}
        self.stalls = deque(maxlen=16)

    def call(self, stage, function, *args, **kwargs):
        before = self.clock()
        try:
            return function(*args, **kwargs)
        finally:
            elapsed = self.clock() - before
            self.max_seconds[stage] = max(self.max_seconds.get(stage, 0), elapsed)
            if elapsed >= .02:
                self.stalls.append(dict(stage=stage, seconds=elapsed))

    def describe(self):
        return dict(max_seconds=dict(self.max_seconds), last_stalls=list(self.stalls),
                    scope='Consumer timing only; diagnostic overhead is not a latency measurement')
