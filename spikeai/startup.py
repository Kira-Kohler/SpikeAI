import sys
import subprocess
import re
from pathlib import Path
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal
from .package import package_identity

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
ENTRY = "SpikeAI3"
LEGACY_ENTRY = "SpikeIA3"
TASK_ID = "SpikeAIStartup"
AUTOSTART = "--autostart"


@dataclass(frozen=True)
class StartupState:
    enabled: bool
    available: bool
    message: str
    packaged: bool = False


def launch_args():
    return (
        [sys.executable]
        if getattr(sys, "frozen", False)
        else [sys.executable, str(Path(__file__).resolve().parents[1] / "SpikeAI.py")]
    )


def base_command():
    return subprocess.list2cmdline(launch_args())


def command():
    return subprocess.list2cmdline(launch_args() + [AUTOSTART])


def unpackaged_state():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, ENTRY)
    except FileNotFoundError:
        return StartupState(False, True, "Off")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            approved, _ = winreg.QueryValueEx(key, ENTRY)
            if approved and approved[0] in (3, 7):
                return StartupState(False, False, "Disabled in Windows startup settings")
    except FileNotFoundError:
        pass
    return StartupState(bool(value), True, "On" if value else "Off")


def set_startup(enabled):
    if package_identity():
        raise OSError("Packaged installs must use Windows StartupTask")
    import winreg

    if not unpackaged_state().available:
        raise OSError("Windows disabled this entry. Re-enable it in Windows startup settings.")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, ENTRY, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, ENTRY)
            except FileNotFoundError:
                pass
    return unpackaged_state()


def rename_legacy_entry():
    import winreg

    legacy_source = base_command().replace("SpikeAI.py", "SpikeIA.py")
    for path in (RUN_KEY, APPROVED_KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
            ) as key:
                value, kind = winreg.QueryValueEx(key, LEGACY_ENTRY)
                if path == RUN_KEY and value == legacy_source:
                    value = command()
                try:
                    winreg.QueryValueEx(key, ENTRY)
                except FileNotFoundError:
                    winreg.SetValueEx(key, ENTRY, 0, kind, value)
                winreg.DeleteValue(key, LEGACY_ENTRY)
        except FileNotFoundError:
            pass


def migrate_legacy_startup():
    state = unpackaged_state()
    if not state.enabled or not state.available:
        return state
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        value, _ = winreg.QueryValueEx(key, ENTRY)
    if value == base_command():
        return set_startup(True)
    if not getattr(sys, "frozen", False):
        return state
    match = re.fullmatch(r'"([^"]+)"|([^"\r\n]+\.exe)', value, re.IGNORECASE)
    if match and Path(match.group(1) or match.group(2)).name.lower() == "spikeia.exe":
        return set_startup(True)
    return state


def task_state(state):
    value = int(state)
    return StartupState(
        value in (2, 4),
        value in (0, 2),
        {
            0: "Off",
            1: "Disabled by you in Windows",
            2: "On",
            3: "Disabled by Windows policy",
            4: "Enabled by Windows policy",
        }.get(value, "Unavailable"),
        True,
    )


class StartupService(QObject):
    changed = Signal(object)
    resolved = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = None
        self.operation = None
        self.pending = None
        self.apartment_initialized = False
        self.state = StartupState(False, False, "Checking Windows…")
        self.resolved.connect(self.on_resolved)
        self.failed.connect(self.on_failed)
        try:
            self.packaged = package_identity()
        except OSError as e:
            self.packaged = None
            self.on_failed(str(e))

    def publish(self, state):
        self.state = state
        self.changed.emit(state)

    def on_failed(self, message):
        self.publish(StartupState(False, False, "Unavailable: " + message, bool(self.packaged)))

    def refresh(self):
        if self.packaged is None:
            return
        try:
            if not self.packaged:
                rename_legacy_entry()
                self.publish(migrate_legacy_startup())
                return
            if self.task:
                self.publish(task_state(self.task.state))
                return
            from winrt.runtime import init_apartment, ApartmentType

            if not self.apartment_initialized:
                init_apartment(ApartmentType.SINGLE_THREADED)
                self.apartment_initialized = True
            from winrt.windows.applicationmodel import StartupTask

            self.operation = StartupTask.get_async(TASK_ID)

            def completed(op, status):
                try:
                    self.resolved.emit(op.get_results())
                except Exception as e:
                    self.failed.emit(str(e))

            self.operation.completed = completed
        except Exception as e:
            self.on_failed(str(e))

    def on_resolved(self, task):
        self.task = task
        self.publish(task_state(task.state))
        if self.pending is not None:
            value, self.pending = self.pending, None
            self.set_enabled(value)

    def set_enabled(self, value):
        try:
            if self.packaged is None:
                raise OSError("Package identity unavailable")
            if not self.packaged:
                set_startup(value)
                self.publish(unpackaged_state())
                return
            if self.task is None:
                self.pending = value
                self.refresh()
                return
            state = task_state(self.task.state)
            if not state.available:
                self.publish(state)
                return
            if not value:
                self.task.disable()
                self.publish(task_state(self.task.state))
                return
            self.operation = self.task.request_enable_async()

            def completed(op, status):
                try:
                    op.get_results()
                    self.resolved.emit(self.task)
                except Exception as e:
                    self.failed.emit(str(e))

            self.operation.completed = completed
        except Exception as e:
            self.on_failed(str(e))

    def shutdown(self):
        if self.operation:
            try:
                self.operation.cancel()
            except (OSError, RuntimeError):
                pass
        if self.apartment_initialized:
            from winrt.runtime import uninit_apartment

            uninit_apartment()
            self.apartment_initialized = False
