import ctypes
import os
from pathlib import Path

NO_PACKAGE = 15700
INSUFFICIENT_BUFFER = 122


def kernel32(kernel=None):
    return kernel if kernel is not None else ctypes.WinDLL("kernel32", use_last_error=True)


def package_identity(kernel=None):
    fn = kernel32(kernel).GetCurrentPackageFullName
    fn.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p]
    fn.restype = ctypes.c_long
    size = ctypes.c_uint32()
    code = fn(ctypes.byref(size), None)
    if code == NO_PACKAGE:
        return False
    if code == INSUFFICIENT_BUFFER:
        return True
    raise OSError(code, "Cannot determine Windows package identity")


def package_family_name(kernel=None):
    fn = kernel32(kernel).GetCurrentPackageFamilyName
    fn.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p]
    fn.restype = ctypes.c_long
    size = ctypes.c_uint32()
    code = fn(ctypes.byref(size), None)
    if code == NO_PACKAGE:
        return None
    if code != INSUFFICIENT_BUFFER:
        raise OSError(code, "Cannot read the Windows package family name")
    buffer = ctypes.create_unicode_buffer(size.value)
    code = fn(ctypes.byref(size), buffer)
    if code:
        raise OSError(code, "Cannot read the Windows package family name")
    return buffer.value


def package_home(family):
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Packages" / family / "LocalState"


def register_app_id(app_id, name, icon):
    import winreg

    path = "Software\\Classes\\AppUserModelId\\" + app_id
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        for value_name, value in (("DisplayName", name), ("IconUri", icon)):
            try:
                if winreg.QueryValueEx(key, value_name)[0] == value:
                    continue
            except FileNotFoundError:
                pass
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)


def ensure_apartment():
    from winrt.runtime import init_apartment, ApartmentType

    try:
        init_apartment(ApartmentType.SINGLE_THREADED)
        return True
    except Exception:
        return False


def startup_activation():
    try:
        if not package_identity():
            return False
        ensure_apartment()
        from winrt.windows.applicationmodel import AppInstance
        from winrt.windows.applicationmodel.activation import ActivationKind

        args = AppInstance.get_activated_event_args()
        return args is not None and args.kind == ActivationKind.STARTUP_TASK
    except Exception:
        return False
