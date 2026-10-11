from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np

from .logsys import log

IS_WINDOWS = sys.platform == "win32"


def enable_dpi_awareness() -> str:
    if not IS_WINDOWS:
        return "n/a"
    try:
        user32 = ctypes.windll.user32
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        if user32.AreDpiAwarenessContextsEqual(user32.GetThreadDpiAwarenessContext(), ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return "system"
    except (AttributeError, OSError):
        return "desconocido"


@dataclass
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int
    primary: bool
    device: str
    dpi: int = 96
    refresh_hz: int = 0

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height

    def describe(self) -> str:
        p = " (principal)" if self.primary else ""
        return (
            f"#{self.index}{p} {self.width}x{self.height} en ({self.left},{self.top}) "
            f"escala {round(self.dpi / 96 * 100)}% {self.refresh_hz or '?'} Hz {self.device}"
        )


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", ctypes.c_wchar * 32),
    ]


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPosition_x", wintypes.LONG),
        ("dmPosition_y", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", wintypes.SHORT),
        ("dmDuplex", wintypes.SHORT),
        ("dmYResolution", wintypes.SHORT),
        ("dmTTOption", wintypes.SHORT),
        ("dmCollate", wintypes.SHORT),
        ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


ENUM_CURRENT_SETTINGS = -1


def current_mode(device: str | None) -> DEVMODEW | None:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    if ctypes.windll.user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
        return dm
    return None


def list_monitors() -> list[Monitor]:
    if not IS_WINDOWS:
        return _list_monitors_mss()
    mons: list[Monitor] = []
    user32 = ctypes.windll.user32
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    def _cb(hmon, _hdc, _rect, _lp):
        mi = _MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            dpi = 96
            try:
                dx, dy = wintypes.UINT(), wintypes.UINT()
                if ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                    dpi = int(dx.value)
            except (AttributeError, OSError):
                pass
            dm = current_mode(mi.szDevice)
            mons.append(
                Monitor(
                    len(mons) + 1,
                    r.left,
                    r.top,
                    r.right - r.left,
                    r.bottom - r.top,
                    bool(mi.dwFlags & 1),
                    mi.szDevice,
                    dpi,
                    int(dm.dmDisplayFrequency) if dm else 0,
                )
            )
        return True

    try:
        user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_cb), 0)
    except OSError as e:
        log.warning("EnumDisplayMonitors falló (%s); se usa mss.", e)
        return _list_monitors_mss()
    return mons or _list_monitors_mss()


def _list_monitors_mss() -> list[Monitor]:
    from mss import mss

    with mss() as s:
        out = []
        for i, m in enumerate(s.monitors[1:], start=1):
            out.append(
                Monitor(
                    i,
                    m["left"],
                    m["top"],
                    m["width"],
                    m["height"],
                    m["left"] == 0 and m["top"] == 0,
                    f"mss{i}",
                )
            )
        return out


def primary_monitor(mons: list[Monitor]) -> Monitor:
    for m in mons:
        if m.primary:
            return m
    for m in mons:
        if m.left == 0 and m.top == 0:
            return m
    return mons[0]


def find_game_window(include_minimized=False) -> tuple[int, tuple[int, int, int, int]] | None:
    if not IS_WINDOWS:
        return None
    user32 = ctypes.windll.user32
    found: list[int] = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    cls = ctypes.create_unicode_buffer(64)
    title = ctypes.create_unicode_buffer(128)

    def _cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != "UnrealWindow":
            return True
        user32.GetWindowTextW(hwnd, title, 128)
        if title.value.strip().upper().startswith("VALORANT"):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    if not found:
        return None
    hwnd = found[0]
    if user32.IsIconic(hwnd):
        return (hwnd, (0, 0, 0, 0)) if include_minimized else None
    rc = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w < 320 or h < 240:
        return None
    return hwnd, (pt.x, pt.y, w, h)


@dataclass
class CaptureTarget:
    left: int
    top: int
    width: int
    height: int
    source: str
    monitor: Monitor | None

    @property
    def key(self) -> str:
        dev = self.monitor.device if self.monitor else "?"
        return f"{self.source.split()[0]}:{self.width}x{self.height}:{dev}"

    def describe(self) -> str:
        return f"{self.source}: {self.width}x{self.height} en ({self.left},{self.top})"


def resolve_target(setting) -> CaptureTarget:
    mons = list_monitors()
    if not mons:
        raise RuntimeError("No se detectó ningún monitor.")
    if setting in (None, "", "auto"):
        gw = find_game_window()
        if gw is not None:
            _, (x, y, w, h) = gw
            mon = next(
                (
                    m
                    for m in mons
                    if m.left <= x + w // 2 < m.left + m.width and m.top <= y + h // 2 < m.top + m.height
                ),
                primary_monitor(mons),
            )
            return CaptureTarget(x, y, w, h, "ventana VALORANT", mon)
        m = primary_monitor(mons)
        return CaptureTarget(*m.rect, f"monitor #{m.index} (principal)", m)
    if setting == "primary":
        m = primary_monitor(mons)
        return CaptureTarget(*m.rect, f"monitor #{m.index} (principal)", m)
    try:
        idx = int(setting)
        m = next(m for m in mons if m.index == idx)
        return CaptureTarget(*m.rect, f"monitor #{m.index}", m)
    except (ValueError, StopIteration):
        log.warning("Monitor '%s' no existe; se usa el principal.", setting)
        m = primary_monitor(mons)
        return CaptureTarget(*m.rect, f"monitor #{m.index} (principal)", m)


def clamp_to_desktop(
    rect: tuple[int, int, int, int], mons: list[Monitor]
) -> tuple[int, int, int, int] | None:
    x, y, w, h = rect
    for m in mons:
        x0, y0 = max(x, m.left), max(y, m.top)
        x1, y1 = min(x + w, m.left + m.width), min(y + h, m.top + m.height)
        if x1 - x0 >= 8 and y1 - y0 >= 8:
            return x0, y0, x1 - x0, y1 - y0
    return None


class CaptureError(RuntimeError):
    pass


class MssBackend:
    name = "mss"

    def __init__(self):
        from mss import mss

        self._mss_factory = mss
        self._sct = mss()

    def grab(self, rect: tuple[int, int, int, int]) -> np.ndarray:
        x, y, w, h = rect
        try:
            shot = self._sct.grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
        except Exception as e:
            raise CaptureError(str(e)) from e
        arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return np.ascontiguousarray(arr[..., :3])

    def reset(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass
        self._sct = self._mss_factory()

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass


@dataclass(frozen=True)
class FocusSnapshot:
    focused: bool | None
    hwnd: int = 0
    pid: int = 0
    epoch: int = 0


class WindowsFocusAPI:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.GetForegroundWindow.argtypes = []
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def foreground(self):
        return self.user.GetForegroundWindow() or 0

    def pid(self, hwnd):
        pid = wintypes.DWORD()
        if not self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return 0
        return pid.value

    def image(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            return (
                path.value
                if self.kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size))
                else None
            )
        finally:
            self.kernel.CloseHandle(handle)


class FocusTracker:
    def __init__(self, api=None):
        import threading

        self.api = api if api is not None else (WindowsFocusAPI() if IS_WINDOWS else None)
        self.lock = threading.Lock()
        self.snapshot = FocusSnapshot(None)

    def sample(self):
        from pathlib import PureWindowsPath

        with self.lock:
            focused, hwnd, pid = None, 0, 0
            try:
                if self.api:
                    hwnd = self.api.foreground()
                    pid = self.api.pid(hwnd) if hwnd else 0
                    image = self.api.image(pid) if pid else None
                    if image and self.api.foreground() == hwnd and self.api.pid(hwnd) == pid:
                        focused = PureWindowsPath(image).name.casefold() == "valorant-win64-shipping.exe"
            except (OSError, AttributeError):
                focused = None
            old = self.snapshot
            epoch = old.epoch + int((focused, hwnd, pid) != (old.focused, old.hwnd, old.pid))
            self.snapshot = FocusSnapshot(focused, hwnd, pid, epoch)
            return self.snapshot
