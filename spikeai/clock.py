import math
import time
from dataclasses import dataclass

NS = 1_000_000_000
DURATION = 38
now_ns = time.perf_counter_ns


@dataclass(frozen=True)
class SpikeTimeline:
    plant_ns: int
    source: str = "visual"

    def remaining_s(self, t_ns=None):
        return DURATION - ((now_ns() if t_ns is None else t_ns) - self.plant_ns) / NS

    def progress(self, t_ns=None):
        return max(0.0, min(1.0, self.remaining_s(t_ns) / DURATION))


def format_remaining(remaining):
    decimals = 3 if remaining <= 3 else 2 if remaining <= 10 else 1
    factor = 10**decimals
    return f"{math.floor(max(0, remaining) * factor) / factor:.{decimals}f}"


def color_for(remaining):
    return "red" if remaining <= 3 else "orange" if remaining <= 10 else "lime"
