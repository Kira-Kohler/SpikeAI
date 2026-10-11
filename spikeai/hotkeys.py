import ctypes
from ctypes import wintypes
from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication


def parse(text):
    parts = text.lower().replace(" ", "").split("+")
    modifiers = 0x4000
    for part in parts[:-1]:
        if part not in ("ctrl", "alt", "shift", "win"):
            raise ValueError("Use Ctrl, Alt, Shift or Win modifiers")
        modifiers |= {"alt": 1, "ctrl": 2, "shift": 4, "win": 8}[part]
    key = parts[-1]
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError("Use F1–F24 or an ASCII letter/number")
    return modifiers, vk


class GlobalHotkeys(QAbstractNativeEventFilter):
    def __init__(self, enqueue, api=None):
        super().__init__()
        self.enqueue = enqueue
        self.api = api or ctypes.WinDLL("user32", use_last_error=True)
        self.bindings = {}
        self.requested = []
        if api is None:
            self.api.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            self.api.RegisterHotKey.restype = wintypes.BOOL
            self.api.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            self.api.UnregisterHotKey.restype = wintypes.BOOL
        QApplication.instance().installNativeEventFilter(self)

    def clear(self):
        for identifier in list(self.bindings):
            self.api.UnregisterHotKey(None, identifier)
        self.bindings.clear()

    def configure(self, bindings):
        parsed = [(parse(key), action) for key, action in bindings]
        if len({key for key, action in parsed}) != len(parsed):
            raise ValueError("Shortcuts must be different")
        previous = self.requested
        self.clear()
        try:
            for index, ((mod, vk), action) in enumerate(parsed, 0x6100):
                if not self.api.RegisterHotKey(None, index, mod, vk):
                    raise OSError("Shortcut is occupied or unavailable")
                self.bindings[index] = action
            self.requested = list(bindings)
        except Exception:
            self.clear()
            for index, (key, action) in enumerate(previous, 0x6100):
                mod, vk = parse(key)
                if self.api.RegisterHotKey(None, index, mod, vk):
                    self.bindings[index] = action
            raise

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0312 and msg.wParam in self.bindings:
            self.enqueue(self.bindings[msg.wParam])
            return True, 0
        return False, 0

    def close(self):
        self.clear()
        QApplication.instance().removeNativeEventFilter(self)
