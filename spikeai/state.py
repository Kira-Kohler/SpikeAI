import enum
import math
from dataclasses import dataclass, field
from .clock import NS


class DState(enum.Enum):
    NO_SPIKE = "waiting"
    CANDIDATE = "candidate"
    PLANT_CONFIRMED = "confirmed"
    TIMER_ACTIVE = "visible"
    TEMPORARILY_MISSING = "temporarily_missing"
    WAITING_NEW_ROUND = "waiting_clear"


@dataclass
class Observation:
    t_ns: int
    score: float
    center: tuple | None = None
    size: float = 0
    valid: bool = True
    presence_only: bool = False
    focus_epoch: int | None = None


@dataclass
class Event:
    kind: str
    t_ns: int
    data: dict = field(default_factory=dict)


class DetectionStateMachine:
    def __init__(
        self,
        threshold_high=0.50,
        threshold_low=0.42,
        confirm_frames=2,
        confirm_window_s=0.45,
        max_center_jump=0.25,
        rearm_absent_s=1.5,
        lost_stop_s=5.0,
        observation_gap_s=0.75,
    ):
        self.hi, self.lo = threshold_high, threshold_low
        self.confirm_frames = max(2, confirm_frames)
        self.window = int(confirm_window_s * NS)
        self.max_jump = max_center_jump
        self.rearm_ns = int(rearm_absent_s * NS)
        self.lost_ns = int(lost_stop_s * NS)
        self.gap_ns = int(observation_gap_s * NS)
        self.state = DState.NO_SPIKE
        self.first = self.last_good = self.anchor = None
        self.hits = 0
        self.absent_since = self.previous = None
        self.stop_ns = 0
        self.last_seen = None
        self.focused = True
        self.focus_epoch = None

    def consistent(self, a, b):
        if a is None or b is None:
            return True
        if a.center is not None and b.center is not None:
            if math.dist(a.center, b.center) > self.max_jump * max(a.size, b.size, 1):
                return False
        return not (a.size and b.size and abs(a.size / b.size - 1) > 0.12)

    def clear_candidate(self):
        self.first = self.last_good = None
        self.hits = 0

    def confirmed_hit(self, o):
        if o.score < self.hi or not self.consistent(o, self.anchor):
            return False
        if (
            self.first is None
            or o.t_ns - self.first.t_ns > self.window
            or not self.consistent(o, self.last_good)
        ):
            self.first, self.hits = o, 0
        self.last_good = o
        self.hits += 1
        return self.hits >= self.confirm_frames

    def focus_changed(self, focused, epoch):
        if epoch != self.focus_epoch or focused is not True:
            self.previous = self.absent_since = None
            self.clear_candidate()
            if self.state == DState.CANDIDATE:
                self.state = DState.NO_SPIKE
        self.focused, self.focus_epoch = focused, epoch

    def on_observation(self, o):
        if self.focused is not True or (o.focus_epoch is not None and o.focus_epoch != self.focus_epoch):
            return []
        if o.presence_only and self.state in (DState.NO_SPIKE, DState.CANDIDATE):
            return []
        if self.previous is not None and o.t_ns <= self.previous:
            return []
        gap = self.previous is not None and o.t_ns - self.previous > self.gap_ns
        self.previous = o.t_ns
        if not o.valid or gap:
            self.absent_since = None
            self.clear_candidate()
            if self.state == DState.CANDIDATE:
                self.state = DState.NO_SPIKE
            if not o.valid:
                return [Event("observation_error", o.t_ns)]
        present = o.score >= self.lo and self.consistent(o, self.anchor)
        if present:
            self.last_seen = o.t_ns
        if self.state in (DState.NO_SPIKE, DState.CANDIDATE):
            if self.confirmed_hit(o):
                self.state = DState.PLANT_CONFIRMED
                self.anchor = o
                return [Event("confirmed", o.t_ns, {"t_first_ns": self.first.t_ns, "score": o.score})]
            if self.first is not None:
                self.state = DState.CANDIDATE
                if o.t_ns - self.first.t_ns > self.window:
                    self.clear_candidate()
                    self.state = DState.NO_SPIKE
            return []
        if self.state == DState.TIMER_ACTIVE:
            if present:
                return []
            self.state = DState.TEMPORARILY_MISSING
            self.absent_since = o.t_ns
            self.clear_candidate()
        if self.state == DState.TEMPORARILY_MISSING:
            if self.confirmed_hit(o):
                self.state = DState.TIMER_ACTIVE
                self.absent_since = None
                self.clear_candidate()
                return [Event("visible_again", o.t_ns)]
            if self.absent_since is None:
                self.absent_since = o.t_ns
            if o.t_ns - self.absent_since >= self.lost_ns:
                self.state = DState.WAITING_NEW_ROUND
                self.stop_ns = o.t_ns
                self.absent_since = o.t_ns
                self.clear_candidate()
                return [Event("lost", o.t_ns, {"absent_s": 5.0, "cause": "visibility_loss_unknown"})]
        elif self.state == DState.WAITING_NEW_ROUND:
            if o.score >= self.lo:
                self.absent_since = None
            else:
                if self.absent_since is None:
                    self.absent_since = o.t_ns
                if o.t_ns - self.absent_since >= self.rearm_ns and o.t_ns - self.stop_ns >= self.rearm_ns:
                    self.state = DState.NO_SPIKE
                    self.anchor = None
                    self.clear_candidate()
                    return [Event("rearmed", o.t_ns)]
        return []

    def timer_started(self, t_ns):
        self.state = DState.TIMER_ACTIVE
        self.absent_since = None
        self.clear_candidate()

    def timer_stopped(self, t_ns, reason):
        if self.state == DState.WAITING_NEW_ROUND:
            return
        self.state = DState.WAITING_NEW_ROUND
        self.stop_ns = t_ns
        self.absent_since = None
        self.clear_candidate()
        if reason == "manual_cancel" and self.last_seen is None:
            self.state = DState.NO_SPIKE
            self.anchor = None

    def observation_changed(self):
        self.anchor = None
        self.previous = self.absent_since = None
        self.clear_candidate()
        if self.state == DState.CANDIDATE:
            self.state = DState.NO_SPIKE
