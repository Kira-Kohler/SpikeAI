from .clock import now_ns
from .logsys import log

STAGES = (
    "first_candidate",
    "capture_start",
    "capture_received",
    "processed",
    "dequeued",
    "timer_started",
    "overlay_requested",
    "overlay_painted",
    "voice_requested",
    "voice_playing",
)


class ActivationTrace:
    def __init__(self, keep=64):
        self.keep = keep
        self.records = []
        self.current = None

    def begin(self, **marks):
        self.current = {k: v for k, v in marks.items() if v is not None}
        self.records.append(self.current)
        del self.records[: -self.keep]

    def mark(self, stage, t_ns=None):
        record = self.current
        if record is None or stage in record:
            return
        record[stage] = now_ns() if t_ns is None else t_ns
        if stage == "overlay_painted":
            self.report(record)

    @staticmethod
    def deltas(record):
        base = record.get("first_candidate")
        return {k: round((record[k] - base) / 1e6, 3) for k in STAGES if k in record and base is not None}

    def report(self, record):
        log.debug("Activation latency ms from first candidate: %s", self.deltas(record))

    def summary(self):
        return [self.deltas(r) for r in self.records]
