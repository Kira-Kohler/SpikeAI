import ctypes
import threading
from ctypes import wintypes
from PySide6.QtCore import QObject, Qt, Signal

MUTEX = "Local\\SpikeAI3.Instance"
SHOW = "Local\\SpikeAI3.Show"
ALREADY_EXISTS = 183
ASFW_ANY = 0xFFFFFFFF
INFINITE = 0xFFFFFFFF


class Relay(QObject):
    fired = Signal()


class SingleInstance:
    def __init__(self, mutex=MUTEX, show=SHOW):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.WaitForMultipleObjects.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel.WaitForMultipleObjects.restype = wintypes.DWORD
        self.user.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        self.relay = self.thread = self.stop = None
        ctypes.set_last_error(0)
        self.mutex = self.kernel.CreateMutexW(None, False, mutex)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = ctypes.get_last_error() != ALREADY_EXISTS
        self.event = self.kernel.CreateEventW(None, False, False, show)
        if not self.event:
            error = ctypes.get_last_error()
            self.kernel.CloseHandle(self.mutex)
            raise ctypes.WinError(error)

    def signal(self):
        self.user.AllowSetForegroundWindow(ASFW_ANY)
        return bool(self.kernel.SetEvent(self.event))

    def listen(self, callback):
        self.relay = Relay()
        self.relay.fired.connect(callback, Qt.QueuedConnection)
        self.stop = self.kernel.CreateEventW(None, True, False, None)
        self.thread = threading.Thread(target=self.wait, name="instance", daemon=True)
        self.thread.start()

    def wait(self):
        handles = (wintypes.HANDLE * 2)(self.event, self.stop)
        while self.kernel.WaitForMultipleObjects(2, handles, False, INFINITE) == 0:
            self.relay.fired.emit()

    def close(self):
        if self.thread is not None:
            self.kernel.SetEvent(self.stop)
            self.thread.join(1)
            self.thread = None
        for handle in (self.stop, self.event, self.mutex):
            if handle:
                self.kernel.CloseHandle(handle)
        self.stop = self.event = self.mutex = None
