import argparse
import json
import queue
import sys
import time
import logging
from collections import deque
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from . import __version__, tune_opencv
from .clock import SpikeTimeline, now_ns, NS
from .config import Config
from .detector import VisualDetector, search_region
from .logsys import setup, log
from .overlay import Overlay, EdgeAlert
from .screen import enable_dpi_awareness, list_monitors, find_game_window
from .state import DetectionStateMachine, Observation
from .templates import TemplateLibrary
from .timing import ActivationTrace
from .vision_worker import VisionWorker, ReplaySource
from .voice import VoiceEngine, WavePlayer, MARKS


APP_ID = "KiraKohler.SpikeAI3"


class Scheduler:
    def after(self, ms, callback):
        QTimer.singleShot(ms, callback)


class Wake(QObject):
    ready = Signal()


class Application:
    def __init__(self, cfg, args):
        from .ui import Dashboard

        self.cfg, self.args = cfg, args
        if QApplication.instance() is None:
            QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
        self.qt = QApplication.instance() or QApplication(sys.argv[:1])
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.setApplicationName("Spike AI")
        self.qt.setOrganizationName("Kira Kohler")
        try:
            import ctypes

            from .package import package_identity, register_app_id
            from .resources import resource_path

            if not package_identity():
                register_app_id(APP_ID, "Spike AI", resource_path("assets", "logo", "spike-ai-mark.png"))
                fn = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
                fn.argtypes = [ctypes.c_wchar_p]
                fn.restype = ctypes.c_long
                fn(APP_ID)
        except (AttributeError, OSError):
            pass
        self.root = Scheduler()
        self.library = TemplateLibrary.from_folder()
        self.state = DetectionStateMachine()
        self.state.lost_ns = 5 * NS if cfg.data["absence_watch"] else 10**30
        self.timeline = None
        self.preview_timeline = None
        self.editing = False
        self.events = []
        self.queue = queue.Queue(maxsize=32)
        self.actions = queue.SimpleQueue()
        self.trace = ActivationTrace()
        self.voice = VoiceEngine(cfg.data["volume"], cfg.data["muted"])
        self.voice.customize(cfg.data["voice_files"], cfg.data["voice_enabled"])
        self.voice.on_playing = lambda: self.trace.mark("voice_playing")
        self.monitors = list_monitors()
        self.overlay = Overlay(cfg.data, self.on_moved)
        self.overlay.on_painted = lambda: self.trace.mark("overlay_painted")
        self.edge = EdgeAlert(cfg.data)
        self.config_preview = False
        self.config_preview_data = dict(cfg.data)
        self.config_overlay = Overlay(self.config_preview_data, self.on_moved)
        self.config_edge = EdgeAlert(self.config_preview_data)
        self.status_text = "Awaiting Spike plant..."
        self.closed = False
        self.autostarted = bool(getattr(args, "autostart", False))
        self.worker_failed = False
        self.hotkeys_suspended = False
        self.overlay_checks = []
        self.render_times = deque(maxlen=600)
        self.last_dashboard = 0
        self.last_game_scan = 0
        self.game_detected = False
        self.focused = None
        self.finished_at = 0
        source = ReplaySource(args.replay) if args.replay else None
        self.worker = VisionWorker(self.library, self.queue, cfg.data["monitor"], source)
        self.worker.enabled = cfg.data["detection_enabled"]
        self.wake = Wake()
        self.wake.ready.connect(self.drain, Qt.QueuedConnection)
        self.worker.notify = self.wake.ready.emit
        self.dashboard = Dashboard(self)
        self.place_overlay()
        self.overlay.prewarm()
        self.worker.start()
        self.register_hotkeys()
        from .startup import StartupService

        self.startup_service = StartupService(self.dashboard)
        self.startup_service.changed.connect(self.startup_changed)
        self.startup_service.refresh()
        self.qt.screenAdded.connect(lambda _: self.place_overlay())
        self.qt.screenRemoved.connect(lambda _: self.place_overlay())
        self.qt.commitDataRequest.connect(self.session_end)
        self.qt.aboutToQuit.connect(self.close)
        if self.autostarted and cfg.data["start_minimized"]:
            if not self.dashboard.tray.available():
                self.dashboard.showMinimized()
        else:
            self.dashboard.show()
        if args.smoke_seconds:
            if not args.replay:
                self.root.after(300, lambda: self.start_preview(5))
                self.root.after(1000, self.record_overlay)
            else:
                self.root.after(3000, self.record_overlay)
            self.root.after(max(1000, int(args.smoke_seconds * 1000)), self.close)
        self.root.after(10, self.tick)

    def set_status(self, text):
        self.status_text = text

    def register_hotkeys(self):
        if self.args.no_hotkeys:
            return
        from .hotkeys import GlobalHotkeys

        self.hotkeys = GlobalHotkeys(self.enqueue_action)
        try:
            self.hotkeys.configure(self.shortcut_bindings())
        except (ValueError, OSError) as error:
            self.set_status("Shortcut unavailable · " + str(error))

    def shortcut_bindings(self, start=None, cancel=None):
        return [
            (start or self.cfg.data["hotkey"], "start"),
            (cancel or self.cfg.data["cancel_hotkey"], "cancel"),
            ("ctrl+alt+s", "settings"),
            ("ctrl+alt+q", "quit"),
        ]

    def try_hotkeys(self, key, cancel=None):
        cancel = cancel or self.cfg.data["cancel_hotkey"]
        try:
            from .hotkeys import parse

            bindings = self.shortcut_bindings(key, cancel)
            parsed = [parse(k) for k, a in bindings]
            if len(set(parsed)) != len(parsed):
                raise ValueError("That shortcut is already used by another Spike AI action.")
            if hasattr(self, "hotkeys"):
                try:
                    self.hotkeys.configure(bindings)
                finally:
                    if self.hotkeys_suspended:
                        self.hotkeys.clear()
            self.cfg.data.update(hotkey=key, cancel_hotkey=cancel)
            self.cfg.save()
            self.set_status("Shortcuts updated")
            return None
        except (ValueError, OSError) as error:
            return str(error)

    def suspend_hotkeys(self):
        self.hotkeys_suspended = True
        if hasattr(self, "hotkeys"):
            self.hotkeys.clear()

    def resume_hotkeys(self):
        self.hotkeys_suspended = False
        if hasattr(self, "hotkeys"):
            try:
                self.hotkeys.configure(self.shortcut_bindings())
            except (ValueError, OSError) as error:
                self.set_status("Shortcut unavailable · " + str(error))

    def startup_changed(self, state):
        self.startup_service.state = state
        control = self.dashboard.controls["startup"]
        control.blockSignals(True)
        control.setChecked(state.enabled)
        control.setEnabled(state.available)
        control.blockSignals(False)
        self.dashboard.set_startup_status(state.message)
        self.cfg.data["startup"] = state.enabled
        self.cfg.save()

    def enqueue_action(self, action):
        self.actions.put(action)

    def screen(self):
        screens = self.qt.screens()
        setting = str(self.cfg.data["monitor"])
        monitor = None
        if setting == "auto":
            target = self.worker.target if hasattr(self, "worker") else None
            monitor = target.monitor if target else None
        elif setting.isdigit():
            monitor = next((m for m in self.monitors if m.index == int(setting)), None)
        if monitor:
            return min(
                screens,
                key=lambda s: abs(s.geometry().x() - monitor.left) + abs(s.geometry().y() - monitor.top),
            )
        return self.qt.primaryScreen()

    def screen_rect(self):
        rect = self.screen().geometry()
        return rect.x(), rect.y(), rect.width(), rect.height()

    def place_overlay(self):
        position = self.cfg.data["overlay_position"]
        if position:
            self.overlay.place(*position)
        else:
            self.overlay.place_default(self.screen_rect())
        self.overlay.constrain(self.screen().geometry())

    def on_moved(self, x, y):
        self.cfg.data["overlay_position"] = [x, y]
        self.cfg.save()

    def reset_position(self):
        self.cfg.data["overlay_position"] = None
        self.cfg.save()
        self.place_overlay()
        if self.config_preview:
            self.update_config_preview()

    def update_voices(self):
        self.voice.customize(self.cfg.data["voice_files"], self.cfg.data["voice_enabled"])
        self.cfg.save()

    def change_setting(self, key, value):
        if key == "startup":
            self.dashboard.controls["startup"].setEnabled(False)
            self.startup_service.set_enabled(value)
            return
        self.cfg.data[key] = value
        self.cfg.save()
        if key in ("volume", "muted"):
            self.voice.configure(self.cfg.data["volume"], self.cfg.data["muted"])
        if key == "monitor":
            self.worker.monitor = value
            self.reset_position()
        if key == "detection_enabled":
            log.info("Detection %s", "enabled" if value else "paused")
            self.worker.enabled = value
            self.state.observation_changed()
            if not value:
                self.stop_timer("detection_paused")
        if key == "absence_watch":
            self.state.lost_ns = 5 * NS if value else 10**30
            self.state.observation_changed()
        if key == "debug":
            logging.getLogger("spikeai").setLevel(logging.DEBUG if value else logging.INFO)
        if key.startswith("overlay_"):
            self.overlay.apply_config()
            self.place_overlay()
        if key in ("theme", "accent", "effects", "animations", "animation_intensity", "high_contrast"):
            self.dashboard.apply_theme()
        if key == "animations" and not value:
            self.dashboard.stack.setGraphicsEffect(None)
        if key in ("theme", "accent", "effects", "animations", "animation_intensity", "high_contrast"):
            self.overlay.update()
        if self.config_preview:
            self.update_config_preview()
        if key == "edge_enabled" and not value:
            self.edge.hide()
        control = self.dashboard.controls.get(key) if hasattr(self, "dashboard") else None
        if control is not None and hasattr(control, "isChecked") and control.isChecked() != value:
            control.blockSignals(True)
            control.setChecked(value)
            control.blockSignals(False)

    def toggle_detection(self):
        self.change_setting("detection_enabled", not self.cfg.data["detection_enabled"])

    def start_timer(self, plant_ns, source):
        if self.timeline is not None:
            return
        self.stop_preview()
        self.timeline = SpikeTimeline(plant_ns, source)
        if source == "visual":
            self.trace.mark("timer_started")
        self.state.timer_started(now_ns())
        self.present_timer()
        if source == "visual":
            self.trace.mark("voice_requested")
        self.voice.start(plant_ns)
        self.worker.active = True
        if source == "visual" and self.state.anchor:
            self.worker.presence_anchor = (self.state.anchor.center, self.state.anchor.size)
        self.set_status("Spike planted · Monitoring icon visibility.")
        self.events.append({"kind": "start", "source": source, "t_ns": plant_ns})
        log.info("Timer started: %s", source)

    def present_timer(self):
        focused = self.worker.focus.sample().focused if self.worker.focus else None
        if focused is not True:
            return
        self.focused = focused
        self.finished_at = 0
        self.overlay.setWindowOpacity(self.cfg.data["overlay_opacity"])
        self.overlay.render(max(0, self.timeline.remaining_s()))
        self.trace.mark("overlay_requested")
        self.overlay.show()

    def stop_timer(self, reason):
        self.edge.hide()
        self.overlay.hide()
        if self.timeline is None:
            return
        self.timeline = None
        self.voice.cancel()
        self.worker.active = False
        self.worker.presence_anchor = None
        self.state.timer_stopped(now_ns(), reason)
        self.set_status("Watching for the next Spike · " + reason)
        self.events.append({"kind": "stop", "reason": reason, "t_ns": now_ns()})
        if reason == "deadline_finished" and self.cfg.data["animations"]:
            self.finished_at = time.perf_counter() + 0.22
        log.info("Timer stopped: %s", reason)

    def toggle(self):
        if self.timeline:
            self.stop_timer("manual_cancel")
        else:
            self.start_timer(now_ns(), "manual")

    def start_preview(self, seconds=38):
        if self.timeline:
            QMessageBox.information(
                self.dashboard, "Timer active", "Cancel the active timer before starting a preview."
            )
            return
        self.stop_preview()
        self.preview_timeline = SpikeTimeline(now_ns() - int((38 - seconds) * NS), "preview")
        self.voice.start(self.preview_timeline.plant_ns)
        self.set_status("External preview · No real Spike has been detected.")
        self.update_visuals()

    def stop_preview(self):
        if self.preview_timeline is not None:
            self.voice.cancel()
        self.preview_timeline = None
        self.editing = False
        self.overlay.set_editable(False)
        self.overlay.hide()
        self.edge.hide()
        self.finished_at = 0

    def stop_all(self):
        self.stop_preview()
        self.stop_timer("manual_cancel")
        self.voice.cancel()

    def configure_preview(self, active):
        self.config_preview = active
        if active:
            self.config_overlay.set_editable(True)
            self.update_config_preview()
        else:
            self.config_overlay.set_editable(False)
            self.config_overlay.hide()
            self.config_edge.hide()

    def render_config_edge(self):
        if self.cfg.data["edge_enabled"]:
            self.config_edge.render(
                max(0.1, self.cfg.data["edge_threshold"] - 0.5), False, self.screen_rect(), True
            )
        else:
            self.config_edge.hide()

    def update_config_preview(self):
        self.config_preview_data.update(self.cfg.data)
        self.config_preview_data["edge_enabled"] = True
        self.config_overlay.apply_config()
        position = self.cfg.data["overlay_position"]
        if position:
            self.config_overlay.place(*position)
        else:
            self.config_overlay.place_default(self.screen_rect())
        self.config_overlay.constrain(self.screen().geometry())
        self.render_config_edge()
        self.config_overlay.render(38, True)
        self.config_overlay.show()
        self.config_overlay.raise_()

    def edit_overlay(self):
        if self.config_preview:
            self.config_overlay.set_editable(True)
            self.update_config_preview()
            return
        if self.timeline:
            return
        if self.preview_timeline is not None:
            self.voice.cancel()
        self.preview_timeline = None
        self.editing = True
        self.overlay.set_editable(True)
        self.overlay.render(38, True)
        self.overlay.show()

    def finish_edit(self):
        if self.config_preview:
            self.on_moved(self.config_overlay.x(), self.config_overlay.y())
            self.config_overlay.set_editable(False)
        else:
            self.on_moved(self.overlay.x(), self.overlay.y())
            self.stop_preview()

    def update_visuals(self):
        begin = time.perf_counter()
        if self.config_preview and self.dashboard.isVisible() and not self.dashboard.isMinimized():
            self.render_config_edge()
            self.config_overlay.update()
        elif self.config_preview:
            self.config_overlay.hide()
            self.config_edge.hide()
        focused = self.worker.focus.sample().focused if self.worker.focus else None
        self.focused = focused
        if self.preview_timeline and self.preview_timeline.remaining_s() <= 0:
            self.stop_preview()
        preview = self.preview_timeline is not None
        active = self.preview_timeline or self.timeline
        remaining = max(0, active.remaining_s()) if active else None
        if active and (preview or focused is True):
            self.overlay.render(remaining, preview)
            if not preview and not self.overlay.isVisible():
                self.trace.mark("overlay_requested")
            self.overlay.show()
            self.edge.render(remaining, focused, self.screen_rect(), preview)
        elif self.editing:
            self.overlay.show()
            self.edge.hide()
        elif self.finished_at > begin and focused is True:
            self.overlay.render(0)
            self.overlay.show()
            self.overlay.setWindowOpacity(
                self.cfg.data["overlay_opacity"] * (self.finished_at - begin) / 0.22
            )
            self.edge.hide()
        else:
            self.overlay.hide()
            self.edge.hide()
        if self.finished_at <= begin:
            self.overlay.setWindowOpacity(self.cfg.data["overlay_opacity"])
        while not self.actions.empty():
            action = self.actions.get()
            {
                "toggle": self.toggle,
                "start": lambda: self.start_timer(now_ns(), "manual"),
                "cancel": self.stop_all,
                "settings": self.settings,
                "quit": self.close,
            }[action]()
            if self.closed:
                return
        if begin - self.last_game_scan > 2:
            self.game_detected = find_game_window(include_minimized=True) is not None
            self.last_game_scan = begin
        if begin - self.last_dashboard > 0.2:
            self.dashboard.update_state(remaining, focused, self.game_detected)
            self.last_dashboard = begin
        self.render_times.append((time.perf_counter() - begin) * 1000)

    def render_p95(self):
        values = sorted(self.render_times)
        return values[min(len(values) - 1, int(len(values) * 0.95))] if values else 0

    def settings(self):
        self.dashboard.reveal()

    def hide_to_tray(self):
        if self.dashboard.tray.available():
            self.dashboard.hide()
            self.dashboard.tray.notify_hidden()
            log.info("Window hidden to the system tray")
        else:
            self.dashboard.showMinimized()

    def session_end(self, manager=None):
        log.info("Windows session ending")
        try:
            self.cfg.save()
        except OSError:
            pass

    def open_diagnostics(self):
        import os

        os.startfile(str(self.cfg.home))

    def record_overlay(self):
        self.overlay_checks.append(
            {
                "visible": self.overlay.isVisible(),
                "remaining": self.overlay.remaining,
                "geometry": [self.overlay.x(), self.overlay.y(), self.overlay.width(), self.overlay.height()],
                "click_through": bool(
                    self.overlay.windowFlags()
                    & __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WindowTransparentForInput
                ),
                "edge_visible": self.edge.visible,
                "preview": self.preview_timeline is not None,
            }
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.worker.notify = None
        self.stop_all()
        self.worker.stop()
        self.voice.close()
        self.worker.join(timeout=3)
        self.dashboard.logs.shutdown()
        self.startup_service.shutdown()
        self.dashboard.tray.hide()
        if hasattr(self, "hotkeys"):
            self.hotkeys.close()
        self.configure_preview(False)
        self.config_overlay.close()
        self.config_edge.close()
        self.qt.removeEventFilter(self.dashboard.wheel_guard)
        if self.args.report:
            report = {
                "version": __version__,
                "events": self.events,
                "voice_completed": self.voice.played,
                "voice_errors": self.voice.failures,
                "worker": self.worker.metrics,
                "overlay": self.overlay_checks,
                "render_p95_ms": self.render_p95(),
                "activation_latency_ms": self.trace.summary(),
                "target": self.worker.target.describe() if self.worker.target else None,
            }
            Path(self.args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.edge.close()
        self.overlay.close()
        self.dashboard.hide()
        log.info("Spike AI exited")
        self.qt.quit()

    def tick(self):
        if self.closed:
            return
        self.drain()
        if self.closed:
            return
        if self.timeline:
            remaining = self.timeline.remaining_s()
            if remaining <= 0:
                self.stop_timer("deadline_finished")
        if not self.closed:
            if hasattr(self, "dashboard"):
                self.update_visuals()
            self.root.after(16 if self.timeline or getattr(self, "preview_timeline", None) else 50, self.tick)

    def drain(self):
        if self.closed:
            return
        if self.worker.focus:
            focus = self.worker.focus.sample()
            self.state.focus_changed(focus.focused, focus.epoch)
        for _ in range(64):
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "vision":
                if not self.cfg.data["detection_enabled"]:
                    continue
                observation = item[1]
                if self.worker.focus:
                    focus = self.worker.focus.sample()
                    self.state.focus_changed(focus.focused, focus.epoch)
                    if focus.focused is not True or observation.focus_epoch != focus.epoch:
                        continue
                if now_ns() - observation.t_ns > 0.75 * NS:
                    observation = Observation(now_ns(), 0, valid=False)
                for event in self.state.on_observation(observation):
                    if event.kind == "confirmed":
                        info = item[2]
                        self.trace.begin(
                            first_candidate=event.data["t_first_ns"],
                            capture_start=info.get("capture_start"),
                            capture_received=info.get("capture_received"),
                            processed=info.get("processed"),
                            dequeued=now_ns(),
                        )
                        self.start_timer(event.data["t_first_ns"], "visual")
                    elif event.kind == "lost":
                        self.stop_timer(event.data["cause"])
                    elif event.kind == "observation_error":
                        self.set_status("HUD observation unavailable. Timer continues until its deadline.")
                    elif event.kind in ("rearmed", "visible_again"):
                        self.set_status(
                            "Awaiting Spike plant..." if event.kind == "rearmed" else "Spike visible again."
                        )
            elif kind == "geometry":
                self.state.observation_changed()
                self.worker.presence_anchor = None
                self.place_overlay()
            elif kind == "action":
                {"toggle": self.toggle, "settings": self.settings, "quit": self.close}[item[1]]()
            elif kind == "fatal":
                self.worker_failed = True
                self.set_status(item[1])
                self.settings()
            elif kind == "replay_end":
                self.set_status("Replay finished.")
                if self.args.smoke_seconds:
                    self.close()
            if self.closed:
                return


def self_test(image=None):
    import cv2
    import numpy as np

    lib = TemplateLibrary.from_folder()
    engine = VoiceEngine(muted=True)
    report = {
        "version": __version__,
        "templates": len(lib.refs),
        "voices": list(engine.bank),
        "voice_errors": engine.failures,
    }
    if image:
        frame = cv2.imdecode(np.fromfile(image, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Could not read image")
        h, w = frame.shape[:2]
        detector = VisualDetector(lib)
        detector.configure(h)
        x, y, rw, rh = search_region(w, h, detector.prior_fill_h_native)
        result = detector.detect(frame[y : y + rh, x : x + rw])
        report.update(score=result.score, detected=result.score >= 0.5, process_ms=result.process_ms)
    engine.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spike AI 3.0 — Created by Kira Kohler")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--replay", help="Development playback: video or PNG folder")
    parser.add_argument("--no-hotkeys", action="store_true")
    parser.add_argument("--smoke-seconds", type=float)
    parser.add_argument("--report")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--voice-test", action="store_true")
    parser.add_argument("--monitor")
    parser.add_argument("--autostart", action="store_true")
    args = parser.parse_args(argv)
    guard = None
    if not (args.self_test or args.voice_test or args.replay or args.smoke_seconds):
        from .instance import SingleInstance
        from .package import startup_activation

        args.autostart = args.autostart or startup_activation()
        try:
            guard = SingleInstance()
        except OSError:
            guard = None
        if guard is not None and not guard.primary:
            if not args.autostart:
                guard.signal()
            guard.close()
            return 0
    cfg = Config()
    setup(cfg.home, args.debug or cfg.data["debug"])
    tune_opencv()
    dpi = enable_dpi_awareness()
    log.info("Spike AI %s — Created by Kira Kohler. DPI: %s", __version__, dpi)
    log.info("Data folder: %s · automatic start: %s", cfg.home, bool(getattr(args, "autostart", False)))
    if cfg.imported_from:
        log.info("Settings imported once from %s", cfg.imported_from)
    try:
        if args.self_test or args.voice_test:
            report = self_test(args.image)
            if args.voice_test:
                engine = VoiceEngine(volume=cfg.data["volume"], muted=True)
                token = __import__("threading").Event()
                for _, name in MARKS:
                    WavePlayer().play(engine.bank[name], token)
                engine.close()
                report["waveout_completed"] = [name for _, name in MARKS]
            if args.report:
                Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
            if sys.stdout:
                print(json.dumps(report))
            return 0
        if args.monitor:
            cfg.data["monitor"] = args.monitor
        app = Application(cfg, args)
        if guard is not None:
            guard.listen(app.settings)
        try:
            app.qt.exec()
        except KeyboardInterrupt:
            app.close()
        return 0
    except Exception as error:
        log.exception("Spike AI failed to start")
        if not args.self_test and not args.voice_test:
            error_app = QApplication.instance() or QApplication(sys.argv[:1])
            QMessageBox.critical(None, "Spike AI", str(error))
            error_app.quit()
        return 1
    finally:
        if guard is not None:
            guard.close()
