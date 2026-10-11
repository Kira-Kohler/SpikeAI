import queue
import threading
import time
import cv2
import numpy as np
from .clock import now_ns
from .detector import VisualDetector, PresenceVerifier, search_region
from .screen import CaptureError, CaptureTarget, MssBackend, resolve_target, FocusTracker
from .state import Observation
from .logsys import log


class ReplaySource:
    live = False

    def __init__(self, path):
        from pathlib import Path

        self.frames = sorted(Path(path).glob("*.png")) if Path(path).is_dir() else None
        self.cap = None if self.frames is not None else cv2.VideoCapture(str(path))
        self.fps = 10 if self.frames is not None else (self.cap.get(cv2.CAP_PROP_FPS) or 30)
        self.index = 0
        self.finished = False
        self.first = self.next_frame()
        if self.first is None:
            raise ValueError("No readable replay frames")
        self.h, self.w = self.first.shape[:2]

    def next_frame(self):
        if self.frames is not None:
            frame = (
                cv2.imdecode(np.fromfile(self.frames[self.index], np.uint8), cv2.IMREAD_COLOR)
                if self.index < len(self.frames)
                else None
            )
        else:
            ok, frame = self.cap.read()
            if not ok:
                frame = None
        self.index += 1
        self.finished = frame is None
        return frame

    def target(self):
        return CaptureTarget(0, 0, self.w, self.h, "replay", None)

    def grab(self, rect):
        frame, self.first = self.first, None
        if frame is None:
            frame = self.next_frame()
        if frame is None:
            raise CaptureError("Replay finished")
        x, y, w, h = rect
        return np.ascontiguousarray(frame[y : y + h, x : x + w])

    def close(self):
        if self.cap is not None:
            self.cap.release()


SEARCH_FPS = 60
ACTIVE_FPS = 10
CONFIRM_RETRY_S = 0.002


class VisionWorker(threading.Thread):
    def __init__(self, library, output, monitor="auto", source=None):
        super().__init__(name="vision", daemon=True)
        self.library, self.output, self.monitor, self.source = library, output, monitor, source
        self.stop_event = threading.Event()
        self.focus = FocusTracker() if source is None else None
        self.active = False
        self.enabled = True
        self.presence_anchor = None
        self.target = None
        self.notify = None
        self.metrics = {"frames": 0, "errors": 0, "process_ms_sum": 0, "capture_ms_sum": 0}

    def emit(self, item):
        try:
            self.output.put_nowait(item)
        except queue.Full:
            try:
                self.output.get_nowait()
            except queue.Empty:
                pass
            self.output.put_nowait(item)
        notify = self.notify
        if notify is not None:
            notify()

    def stop(self):
        self.stop_event.set()

    def pause(self, seconds):
        if seconds > 0 and not self.stop_event.is_set():
            time.sleep(seconds)

    def run(self):
        backend = None
        try:
            detector = VisualDetector(self.library)
            presence = PresenceVerifier()
            if self.source is None:
                backend = MssBackend()
            last_geometry = 0
            geometry = None
            focus_epoch = None
            candidate = None
            period = 1 / SEARCH_FPS
            while not self.stop_event.is_set():
                if not self.enabled:
                    candidate = None
                    detector.reset_tracking()
                    self.stop_event.wait(0.1)
                    continue
                started = time.perf_counter()
                focus = self.focus.sample() if self.focus else None
                if focus and focus.epoch != focus_epoch:
                    focus_epoch = focus.epoch
                    candidate = None
                    detector.reset_tracking()
                    last_geometry = 0
                if focus and focus.focused is not True:
                    self.stop_event.wait(0.05)
                    continue
                if started - last_geometry > 2:
                    target = self.source.target() if self.source else resolve_target(self.monitor)
                    new_geometry = (target.left, target.top, target.width, target.height)
                    if new_geometry != geometry:
                        geometry = new_geometry
                        self.target = target
                        detector.configure(target.height)
                        detector.reset_tracking()
                        rect = search_region(target.width, target.height, detector.prior_fill_h_native)
                        self.emit(("geometry", target))
                        candidate = None
                    last_geometry = started
                x, y, w, h = rect
                capture_rect = (target.left + x, target.top + y, w, h)
                t0 = now_ns()
                try:
                    image = (self.source or backend).grab(capture_rect)
                    t1 = now_ns()
                except CaptureError as error:
                    if self.source and self.source.finished:
                        self.emit(("replay_end", None))
                        break
                    self.metrics["errors"] += 1
                    self.emit(("vision", Observation(now_ns(), 0, valid=False), {}))
                    log.warning("Capture failed: %s", error)
                    candidate = None
                    if backend:
                        backend.reset()
                    self.stop_event.wait(0.2)
                    continue
                if self.focus:
                    after = self.focus.sample()
                    if after.focused is not True or after.epoch != focus.epoch:
                        candidate = None
                        continue
                if (
                    candidate is not None
                    and time.perf_counter() - candidate[1] < period
                    and image.shape == candidate[0].shape
                    and np.array_equal(image, candidate[0])
                ):
                    self.pause(CONFIRM_RETRY_S)
                    continue
                candidate = None
                timestamp = (t0 + t1) // 2

                valid = image.size > 0 and int(image.max()) > 2
                if valid:
                    result = detector.detect(image)
                    rescued = False
                    anchor = self.presence_anchor
                    if self.active and anchor and result.score < 0.5:
                        extra_start = time.perf_counter()
                        hit = presence.verify(image, (anchor[0][0] - x, anchor[0][1] - y), anchor[1])
                        if hit:
                            result.score, result.fill_h_native = 0.51, hit[1]
                            rescued = True
                        result.process_ms += (time.perf_counter() - extra_start) * 1000
                    center = (x + result.center[0], y + result.center[1]) if result.center else None
                    if rescued:
                        center = (x + hit[0][0], y + hit[0][1])
                    observation = Observation(
                        timestamp, result.score, center, result.fill_h_native, presence_only=rescued
                    )
                    info = {
                        "process_ms": result.process_ms,
                        "capture_ms": (t1 - t0) / 1e6,
                        "phase": result.phase,
                        "capture_start": t0,
                        "capture_received": t1,
                        "processed": now_ns(),
                    }
                    self.metrics["process_ms_sum"] += result.process_ms
                    self.metrics["capture_ms_sum"] += info["capture_ms"]
                else:
                    observation, info = Observation(timestamp, 0, valid=False), {}
                    self.metrics["errors"] += 1
                observation.focus_epoch = focus.epoch if focus else None
                self.emit(("vision", observation, info))
                self.metrics["frames"] += 1
                period = 1 / (self.source.fps if self.source else ACTIVE_FPS if self.active else SEARCH_FPS)
                if (
                    self.source is None
                    and valid
                    and not self.active
                    and not observation.presence_only
                    and result.score >= detector.accept_threshold
                ):
                    candidate = (image, time.perf_counter())
                    self.pause(CONFIRM_RETRY_S)
                else:
                    self.pause(period - (time.perf_counter() - started))
        except Exception:
            log.exception("Vision worker stopped")
            self.emit(("fatal", "Screen capture stopped. See SpikeAI.log."))
        finally:
            if backend:
                backend.close()
            if self.source:
                self.source.close()
