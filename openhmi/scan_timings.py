"""Bounded acquisition timing statistics, independent of PLC transport."""

from collections import defaultdict, deque
from threading import Lock
import math


class ScanTimings:
    """Bounded, in-memory timing samples for one configured route."""

    def __init__(self):
        self.lock = Lock()
        self.series = defaultdict(lambda: deque(maxlen=256))

    def record(self, metric, seconds):
        with self.lock:
            self.series[metric].append(max(0, seconds) * 1000)

    def snapshot(self):
        with self.lock:
            series = {name: list(samples) for name, samples in self.series.items()}
        result = {}
        for name, samples in series.items():
            ordered = sorted(samples)
            result[name] = {
                'count': len(samples), 'last_ms': round(samples[-1], 3),
                **{f'p{percentile}_ms': round(ordered[math.ceil(len(samples) * percentile / 100) - 1], 3)
                   for percentile in (50, 95, 99)},
            }
        return result
