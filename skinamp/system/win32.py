"""The real `System`: the only module that touches Windows.

Each `Refresh` re-reads what is now in the registry and hands it to the running session.
Restore needs that too, so an apply and a revert run the same refresh code and there is
no separate "undo" path to get wrong.
"""

import ctypes
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Collection
from ctypes import wintypes
from pathlib import Path
from typing import Protocol, cast

if sys.platform != "win32":
    raise ImportError("skinamp.system.win32 needs Windows")

import winreg

import psutil
import pythoncom
import pywintypes
import win32con
import win32event
import win32gui
import win32process
import win32ui
from PIL import Image
from win32com.shell import shell, shellcon

from skinamp import elevated
from skinamp.art.pixels import alpha_from_renders
from skinamp.effects import JsonObject, decode_value
from skinamp.paths import AppPaths
from skinamp.system import explorer, taskbar
from skinamp.system.api import (
    TASKBAR_AUTOHIDE,
    ElevationDeclinedError,
    Machine,
    Refresh,
    RegType,
    RegValue,
)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SystemParametersInfoW.argtypes = (
    wintypes.UINT,
    wintypes.UINT,
    wintypes.LPVOID,
    wintypes.UINT,
)
user32.SendMessageTimeoutW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPCWSTR,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
)
user32.SendMessageTimeoutW.restype = wintypes.LPARAM
user32.SetSysColors.argtypes = (
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(wintypes.DWORD),
)
user32.SetProcessDpiAwarenessContext.argtypes = (wintypes.HANDLE,)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.SHAppBarMessage.restype = ctypes.c_size_t

REG_TYPES: dict[RegType, int] = {
    "sz": winreg.REG_SZ,
    "expand_sz": winreg.REG_EXPAND_SZ,
    "dword": winreg.REG_DWORD,
    "binary": winreg.REG_BINARY,
}
REG_NAMES = {number: name for name, number in REG_TYPES.items()}

SPIF_SENDCHANGE = 0x02
SPIF_PERSIST_AND_BROADCAST = 0x01 | SPIF_SENDCHANGE
SPI_SETDESKWALLPAPER = 0x0014
SPI_SETICONTITLELOGFONT = 0x0022
SPI_GETNONCLIENTMETRICS = 0x0029
SPI_SETNONCLIENTMETRICS = 0x002A
SPI_SETANIMATION = 0x0049
SM_REMOTESESSION = 0x1000
SPI_SETCURSORS = 0x0057

# name: (SPI_GET*, SPI_SET*, True when the setter takes its value in uiParam)
PARAMS: dict[str, tuple[int, int, bool]] = {
    "drag_full_windows": (0x0026, 0x0025, True),
    "font_smoothing": (0x004A, 0x004B, True),
    "menu_animation": (0x1002, 0x1003, False),
    "combobox_animation": (0x1004, 0x1005, False),
    "listbox_smooth_scrolling": (0x1006, 0x1007, False),
    "selection_fade": (0x1014, 0x1015, False),
    "tooltip_animation": (0x1016, 0x1017, False),
    "cursor_shadow": (0x101A, 0x101B, False),
    "drop_shadow": (0x1024, 0x1025, False),
    "client_area_animation": (0x1042, 0x1043, False),
}

# `Control Panel\Colors` value name: index for SetSysColors.
SYS_COLORS = {
    "Scrollbar": 0,
    "Background": 1,
    "ActiveTitle": 2,
    "InactiveTitle": 3,
    "Menu": 4,
    "Window": 5,
    "WindowFrame": 6,
    "MenuText": 7,
    "WindowText": 8,
    "TitleText": 9,
    "ActiveBorder": 10,
    "InactiveBorder": 11,
    "AppWorkspace": 12,
    "Hilight": 13,
    "HilightText": 14,
    "ButtonFace": 15,
    "ButtonShadow": 16,
    "GrayText": 17,
    "ButtonText": 18,
    "InactiveTitleText": 19,
    "ButtonHilight": 20,
    "ButtonDkShadow": 21,
    "ButtonLight": 22,
    "InfoText": 23,
    "InfoWindow": 24,
    "HotTrackingColor": 26,
    "GradientActiveTitle": 27,
    "GradientInactiveTitle": 28,
    "MenuHilight": 29,
    "MenuBar": 30,
}

METRIC_KEY = r"Control Panel\Desktop\WindowMetrics"
COLORS_KEY = r"Control Panel\Colors"
DESKTOP_KEY = r"Control Panel\Desktop"
WALLPAPERS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers"
WALLPAPER_HISTORY = tuple(f"BackgroundHistoryPath{index}" for index in range(5))
SPOTLIGHT_PARENT = r"Software\Microsoft\Windows\CurrentVersion\DesktopSpotlight"
SPOTLIGHT_KEY = rf"{SPOTLIGHT_PARENT}\Settings"
SPOTLIGHT_VALUE = "EnabledState"
# Windows reacts to a new wallpaper on its own time, so what it rewrites is put back for
# this long. Live, Spotlight once lost this race with no wait at all, and none since.
WALLPAPER_SETTLE_CHECKS = 12
WALLPAPER_SETTLE_SECONDS = 0.25
OWN_PROFILE_FLAG = "--user-data-dir"
ABM_GETSTATE = 4
ABM_SETSTATE = 10
ABS_AUTOHIDE = 1
ABS_ALWAYSONTOP = 2
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
ENDSESSION_CLOSEAPP = 0x00000001
SMTO_ABORTIFHUNG = 0x0002
BROADCAST_TIMEOUT_MS = 2000
END_SESSION_TIMEOUT_MS = 3000
CLOSE_TIMEOUT_SECONDS = 20
BACKGROUND_EXIT_SECONDS = 5
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
ERROR_CANCELLED = 1223
ELEVATED_WAIT_MS = 300_000
# Over a dropped remote session the prompt waits on a screen nobody can see.
ADMIN_PROMPT_SECONDS = 120
SHCNE_ASSOCCHANGED = 0x08000000
ICON_RENDER_SIZE = 32
DI_NORMAL = 0x0003
DPI_AWARENESS_PER_MONITOR_V2 = -4
STGM_READ = 0
TWIPS_PER_PIXEL = 15

# None of these derive from OSError, and `System` promises callers exactly that.
NATIVE_ERRORS = (pywintypes.error, pywintypes.com_error, win32ui.error, psutil.Error)


class LOGFONTW(ctypes.Structure):
    _fields_ = (
        ("lfHeight", wintypes.LONG),
        ("lfWidth", wintypes.LONG),
        ("lfEscapement", wintypes.LONG),
        ("lfOrientation", wintypes.LONG),
        ("lfWeight", wintypes.LONG),
        ("lfItalic", wintypes.BYTE),
        ("lfUnderline", wintypes.BYTE),
        ("lfStrikeOut", wintypes.BYTE),
        ("lfCharSet", wintypes.BYTE),
        ("lfOutPrecision", wintypes.BYTE),
        ("lfClipPrecision", wintypes.BYTE),
        ("lfQuality", wintypes.BYTE),
        ("lfPitchAndFamily", wintypes.BYTE),
        ("lfFaceName", wintypes.WCHAR * 32),
    )


class NONCLIENTMETRICSW(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.UINT),
        ("iBorderWidth", ctypes.c_int),
        ("iScrollWidth", ctypes.c_int),
        ("iScrollHeight", ctypes.c_int),
        ("iCaptionWidth", ctypes.c_int),
        ("iCaptionHeight", ctypes.c_int),
        ("lfCaptionFont", LOGFONTW),
        ("iSmCaptionWidth", ctypes.c_int),
        ("iSmCaptionHeight", ctypes.c_int),
        ("lfSmCaptionFont", LOGFONTW),
        ("iMenuWidth", ctypes.c_int),
        ("iMenuHeight", ctypes.c_int),
        ("lfMenuFont", LOGFONTW),
        ("lfStatusFont", LOGFONTW),
        ("lfMessageFont", LOGFONTW),
        ("iPaddedBorderWidth", ctypes.c_int),
    )


class ANIMATIONINFO(ctypes.Structure):
    _fields_ = (("cbSize", wintypes.UINT), ("iMinAnimate", ctypes.c_int))


class APPBARDATA(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    )


def _taskbar_state(message: int, state: int = 0) -> int:
    data = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA), lParam=state)
    return int(shell32.SHAppBarMessage(message, ctypes.byref(data)))


METRIC_FONTS = {
    "CaptionFont": "lfCaptionFont",
    "SmCaptionFont": "lfSmCaptionFont",
    "MenuFont": "lfMenuFont",
    "StatusFont": "lfStatusFont",
    "MessageFont": "lfMessageFont",
}
METRIC_SIZES = {
    "BorderWidth": "iBorderWidth",
    "ScrollWidth": "iScrollWidth",
    "ScrollHeight": "iScrollHeight",
    "CaptionWidth": "iCaptionWidth",
    "CaptionHeight": "iCaptionHeight",
    "SmCaptionWidth": "iSmCaptionWidth",
    "SmCaptionHeight": "iSmCaptionHeight",
    "MenuWidth": "iMenuWidth",
    "MenuHeight": "iMenuHeight",
    "PaddedBorderWidth": "iPaddedBorderWidth",
}


class _ShellLink(Protocol):
    def GetIconLocation(self) -> tuple[str, int]: ...

    def SetIconLocation(self, path: str, index: int) -> None: ...


class _PersistFile(Protocol):
    def Load(self, path: str, mode: int) -> None: ...

    def Save(self, path: str, remember: bool) -> None: ...


def os_errors[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Report a native library's failure as OSError, the one type `System` raises."""

    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except NATIVE_ERRORS as exc:
            raise OSError(str(exc) or type(exc).__name__) from exc

    return wrapper


def _spi(action: int, ui_param: int, pv_param: object, flags: int = 0) -> None:
    if not user32.SystemParametersInfoW(action, ui_param, pv_param, flags):
        raise ctypes.WinError(ctypes.get_last_error())


def parse_rgb(text: str) -> int:
    """`"0 128 128"` as the COLORREF SetSysColors takes."""
    red, green, blue = (int(part) for part in text.split())
    return red | green << 8 | blue << 16


def twips_to_pixels(text: str) -> int:
    """Registry metrics are negative twips, or plain pixels when positive."""
    value = int(text)
    return round(-value / TWIPS_PER_PIXEL) if value < 0 else value


def split_icon_location(location: str) -> tuple[str, int]:
    path, _, index = location.rpartition(",")
    return (path, int(index)) if path else ("", 0)


def _open_link(path: Path) -> tuple[_ShellLink, _PersistFile]:
    pythoncom.CoInitialize()
    link = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
    )
    persist = link.QueryInterface(pythoncom.IID_IPersistFile)
    persist.Load(str(path), STGM_READ)
    return link, persist


def windows_of(pids: Collection[int]) -> list[int]:
    """Every top-level window of these processes, hidden ones included."""
    found: list[int] = []

    def visit(window: int, _extra: None) -> None:
        if win32process.GetWindowThreadProcessId(window)[1] in pids:
            found.append(window)

    win32gui.EnumWindows(visit, None)
    return found


def _session_message(window: int, message: int, agreed: int) -> int:
    """Send one log-off message. Hung, or already gone, counts as not objecting."""
    try:
        _, answer = win32gui.SendMessageTimeout(
            window,
            message,
            agreed,
            ENDSESSION_CLOSEAPP,
            SMTO_ABORTIFHUNG,
            END_SESSION_TIMEOUT_MS,
        )
    except pywintypes.error:
        return 1
    return int(answer)


def end_session(pids: Collection[int]) -> bool:
    """Tell processes Windows is closing them, as logging off does. False if one refuses.

    Closing Chrome's windows one by one would lose all but the last from its session, and
    RetroBar ignores a plain close. Both handle this properly, and every application has
    to, because the alternative is losing work when the user logs off.
    """
    windows = windows_of(pids)
    if any(not _session_message(window, WM_QUERYENDSESSION, 0) for window in windows):
        return False
    for window in windows:
        _session_message(window, WM_ENDSESSION, 1)
    return True


def _visible_windows(pids: Collection[int]) -> list[int]:
    return [window for window in windows_of(pids) if win32gui.IsWindowVisible(window)]


def machine_shortcut_roots() -> list[Path]:
    """The folders of shortcuts shared by every account."""
    pythoncom.CoInitialize()
    return [
        Path(shell.SHGetFolderPath(0, folder, None, 0))
        for folder in (shellcon.CSIDL_COMMON_DESKTOPDIRECTORY, shellcon.CSIDL_COMMON_STARTMENU)
    ]


def _launch_elevated(program: str, arguments: list[str]) -> int:
    """Run a hidden program as admin, wait for it, and return its exit code."""
    try:
        launched = shell.ShellExecuteEx(
            fMask=SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC,
            lpVerb="runas",
            lpFile=program,
            lpParameters=subprocess.list2cmdline(arguments),
            lpDirectory=str(Path.cwd()),
            nShow=win32con.SW_HIDE,
        )
    except pywintypes.error as exc:
        if exc.winerror == ERROR_CANCELLED:
            raise ElevationDeclinedError("The admin prompt was declined") from exc
        raise
    process = launched["hProcess"]
    if win32event.WaitForSingleObject(process, ELEVATED_WAIT_MS) != win32event.WAIT_OBJECT_0:
        raise OSError("The admin step did not finish in time")
    return int(win32process.GetExitCodeProcess(process))


def _await_admin(program: str, arguments: list[str], request: Path) -> int:
    """`_launch_elevated`, giving up on a prompt nobody answers.

    The prompt itself cannot be withdrawn, so giving up means abandoning the request: a
    "Yes" clicked later starts a helper that finds nothing to run.
    """
    outcome: list[int | Exception] = []

    def prompt() -> None:
        pythoncom.CoInitialize()
        try:
            outcome.append(_launch_elevated(program, arguments))
        except (OSError, pywintypes.error) as exc:
            outcome.append(exc)

    # A daemon, so closing Skinamp is not held up by a prompt still on screen.
    worker = threading.Thread(target=prompt, name="admin-prompt", daemon=True)
    worker.start()
    worker.join(ADMIN_PROMPT_SECONDS)
    if worker.is_alive():
        if elevated.abandon(request):
            raise ElevationDeclinedError(
                f"Nobody answered Windows' admin prompt within {ADMIN_PROMPT_SECONDS} seconds"
            )
        # Answered just in time: the helper is running, and its own wait bounds this one.
        worker.join()
    if not outcome:
        raise OSError("The admin step stopped without a result")
    result = outcome[0]
    if isinstance(result, Exception):
        raise result
    return result


def _run_as_admin(ops: list[JsonObject]) -> None:
    folder = Path(tempfile.mkdtemp(prefix="skinamp-"))
    try:
        request = folder / elevated.REQUEST_FILE
        request.write_text(json.dumps(ops), encoding="utf-8")
        program, *arguments = taskbar.self_command()
        code = _await_admin(program, [*arguments, "elevated-run", str(request)], request)
        if code != 0:
            error = folder / elevated.ERROR_FILE
            detail = error.read_text(encoding="utf-8") if error.exists() else f"exit code {code}"
            raise OSError(f"The admin step failed: {detail}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _execute(op: JsonObject) -> None:
    match op["op"]:
        case elevated.OP_SHORTCUT_ICON:
            path = Path(cast(str, op["path"]))
            link, persist = _open_link(path)
            link.SetIconLocation(*split_icon_location(cast(str, op["location"])))
            persist.Save(str(path), True)
        case elevated.OP_REG_WRITE:
            value = cast(RegValue, decode_value(op["value"]))
            key = cast(str, op["key"])
            flags = winreg.KEY_SET_VALUE
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key, 0, flags) as handle:
                name = cast(str, op["name"])
                winreg.SetValueEx(handle, name, 0, REG_TYPES[value.type], value.data)
        case elevated.OP_REG_DELETE:
            _delete_machine_value(cast(str, op["key"]), cast(str, op["name"]))
        case elevated.OP_REG_PRUNE:
            _prune_machine_key(cast(str, op["key"]))


def _delete_machine_value(key: str, name: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.DeleteValue(handle, name)
    except FileNotFoundError:
        return


def _prune_machine_key(key: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            subkeys, values, _ = winreg.QueryInfoKey(handle)
        if subkeys == 0 and values == 0:
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, key)
    except FileNotFoundError:
        return


def execute_request(request: Path) -> None:
    """The elevated side of `run_elevated`. The file is untrusted until validated."""
    claimed = elevated.claim(request)
    ops = cast(list[JsonObject], json.loads(claimed.read_text(encoding="utf-8")))
    elevated.validate(ops, machine_shortcut_roots())
    for op in ops:
        os_errors(_execute)(op)


class Win32Machine:
    def __init__(self) -> None:
        self._queued: list[JsonObject] = []

    def reg_read(self, key: str, name: str) -> RegValue | None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                data, kind = winreg.QueryValueEx(handle, name)
        except FileNotFoundError:
            return None
        return RegValue(REG_NAMES[kind], data) if kind in REG_NAMES else None

    def key_exists(self, key: str) -> bool:
        try:
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key).Close()
        except FileNotFoundError:
            return False
        return True

    def reg_write(self, key: str, name: str, value: RegValue) -> None:
        self._queued.append(elevated.reg_write(key, name, value))

    def reg_delete(self, key: str, name: str) -> None:
        self._queued.append(elevated.reg_delete(key, name))

    def reg_prune_key(self, key: str) -> None:
        self._queued.append(elevated.reg_prune(key))

    @os_errors
    def list_shortcuts(self) -> list[Path]:
        found = [path for root in machine_shortcut_roots() for path in root.rglob("*.lnk")]
        return sorted(set(found))

    def set_shortcut_icon(self, path: Path, location: str) -> None:
        self._queued.append(elevated.shortcut_icon(path, location))

    @os_errors
    def run_elevated(self) -> None:
        ops, self._queued = self._queued, []
        if ops:
            _run_as_admin(ops)


class Win32System:
    def __init__(self, paths: AppPaths, key_prefix: str = "") -> None:
        self._paths = paths
        self._prefix = key_prefix
        self.machine: Machine = Win32Machine()
        # Without this Windows reports 96 DPI whatever the display, and font sizes come out
        # wrong on a scaled screen. False means a toolkit already set it, which is fine.
        user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_PER_MONITOR_V2)

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}\\{key}" if self._prefix else key

    def reg_read(self, key: str, name: str) -> RegValue | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._full_key(key)) as handle:
                data, kind = winreg.QueryValueEx(handle, name)
        except FileNotFoundError:
            return None
        return RegValue(REG_NAMES[kind], data) if kind in REG_NAMES else None

    def reg_write(self, key: str, name: str, value: RegValue) -> None:
        full = self._full_key(key)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, full, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, name, 0, REG_TYPES[value.type], value.data)

    def reg_delete(self, key: str, name: str) -> None:
        access = winreg.KEY_SET_VALUE
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._full_key(key), 0, access) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            return

    def reg_key_exists(self, key: str) -> bool:
        try:
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._full_key(key)).Close()
        except FileNotFoundError:
            return False
        return True

    def reg_prune_key(self, key: str) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._full_key(key)) as handle:
                subkeys, values, _ = winreg.QueryInfoKey(handle)
            if subkeys == 0 and values == 0:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self._full_key(key))
        except FileNotFoundError:
            return

    def get_param(self, name: str) -> int:
        if name == TASKBAR_AUTOHIDE:
            return _taskbar_state(ABM_GETSTATE) & ABS_AUTOHIDE
        getter, _, _ = PARAMS[name]
        value = wintypes.BOOL()
        _spi(getter, 0, ctypes.byref(value))
        return int(value.value)

    def set_param(self, name: str, value: int) -> None:
        if name == TASKBAR_AUTOHIDE:
            _taskbar_state(ABM_SETSTATE, ABS_AUTOHIDE if value else ABS_ALWAYSONTOP)
            return
        _, setter, via_ui_param = PARAMS[name]
        if via_ui_param:
            _spi(setter, value, None, SPIF_PERSIST_AND_BROADCAST)
        else:
            _spi(setter, 0, ctypes.c_void_p(value), SPIF_PERSIST_AND_BROADCAST)

    @os_errors
    def list_shortcuts(self) -> list[Path]:
        pythoncom.CoInitialize()
        desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0))
        appdata = Path(os.environ["APPDATA"])
        start_menu = appdata / "Microsoft" / "Windows" / "Start Menu"
        pinned = appdata / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned"
        found = [*desktop.glob("*.lnk"), *start_menu.rglob("*.lnk"), *pinned.rglob("*.lnk")]
        return sorted(set(found))

    @os_errors
    def get_shortcut_icon(self, path: Path) -> str:
        link, _ = _open_link(path)
        location, index = link.GetIconLocation()
        return f"{location},{index}" if location else ""

    @os_errors
    def set_shortcut_icon(self, path: Path, location: str) -> None:
        link, persist = _open_link(path)
        link.SetIconLocation(*split_icon_location(location))
        persist.Save(str(path), True)

    @os_errors
    def extract_icon(self, path: Path) -> Image.Image:
        pythoncom.CoInitialize()
        flags = shellcon.SHGFI_ICON | shellcon.SHGFI_LARGEICON
        _, (icon, *_rest) = shell.SHGetFileInfo(str(path), 0, flags)
        if not icon:
            raise OSError(f"Windows returned no icon for {path}")
        try:
            on_black = _render_icon(icon, 0x000000)
            on_white = _render_icon(icon, 0xFFFFFF)
        finally:
            win32gui.DestroyIcon(icon)
        return alpha_from_renders(on_black, on_white)

    @os_errors
    def process_running(self, image_name: str) -> bool:
        return bool(_processes_named(image_name))

    @os_errors
    def close_app(self, image_name: str) -> Path | None:
        processes = _processes_named(image_name)
        if not processes:
            return None
        exe = Path(processes[0].exe())
        pids = {process.pid for process in processes}
        if not end_session(pids):
            raise OSError(f"{image_name} would not close. Check it for unsaved work.")
        _, alive = psutil.wait_procs(processes, timeout=CLOSE_TIMEOUT_SECONDS)
        if _visible_windows({process.pid for process in alive}):
            raise OSError(f"{image_name} is still open. Check it for unsaved work.")
        # No window left, so these are background helpers with nothing to lose.
        for process in alive:
            process.terminate()
        psutil.wait_procs(alive, timeout=BACKGROUND_EXIT_SECONDS)
        return exe

    def start_app(self, exe: Path, arguments: tuple[str, ...]) -> None:
        subprocess.Popen([str(exe), *arguments], creationflags=taskbar.DETACHED_PROCESS)

    def dpi(self) -> int:
        return int(user32.GetDpiForSystem())

    @os_errors
    def refresh(self, what: Refresh) -> None:
        match what:
            case Refresh.COLORS:
                _refresh_colors(self)
            case Refresh.WALLPAPER:
                _refresh_wallpaper(self)
            case Refresh.CURSORS:
                # With SPIF_UPDATEINIFILE Windows refuses this: it only reads the registry.
                _spi(SPI_SETCURSORS, 0, None, SPIF_SENDCHANGE)
            case Refresh.METRICS:
                _refresh_metrics(self)
            case Refresh.ICONS:
                _refresh_icons()
            case Refresh.SHELL:
                _restart_shell(self)
            case Refresh.SETTINGS:
                _broadcast("ImmersiveColorSet")
                _broadcast("TraySettings")
            case Refresh.TASKBAR:
                taskbar.sync(self, self._paths, end_session, show_native_taskbar)


def _processes_named(image_name: str) -> list[psutil.Process]:
    """The user's own copy of an app.

    An instance started with its own `--user-data-dir` is automation, a scraper's browser
    say. It shares the image name but not the user's settings, so it neither blocks Skinamp
    nor is Skinamp's to close. Its helpers carry no such flag, only such a parent.
    """
    wanted = image_name.lower()
    named = [
        process
        for process in psutil.process_iter(["name", "cmdline"])
        if (process.info["name"] or "").lower() == wanted
    ]
    automated = {
        process.pid
        for process in named
        if any(part.startswith(OWN_PROFILE_FLAG) for part in process.info["cmdline"] or ())
    }
    return [
        process
        for process in named
        if process.pid not in automated and process.ppid() not in automated
    ]


def _refresh_colors(system: Win32System) -> None:
    pairs = []
    for name, index in SYS_COLORS.items():
        value = system.reg_read(COLORS_KEY, name)
        if value is not None:
            pairs.append((index, parse_rgb(str(value.data))))
    indexes = (ctypes.c_int * len(pairs))(*(index for index, _ in pairs))
    colors = (wintypes.DWORD * len(pairs))(*(color for _, color in pairs))
    if not user32.SetSysColors(len(pairs), indexes, colors):
        raise ctypes.WinError(ctypes.get_last_error())


def _refresh_wallpaper(system: Win32System) -> None:
    value = system.reg_read(DESKTOP_KEY, "Wallpaper")
    path = ctypes.create_unicode_buffer(str(value.data) if value else "")
    keep = [(WALLPAPERS_KEY, name) for name in WALLPAPER_HISTORY]
    keep.append((SPOTLIGHT_KEY, SPOTLIGHT_VALUE))
    wanted = {place: system.reg_read(*place) for place in keep}
    _spi(SPI_SETDESKWALLPAPER, 0, path, SPIF_PERSIST_AND_BROADCAST)
    # Windows may push the wallpaper onto Settings' recent list and turn Spotlight off some
    # time after this, which would undo what the journal has just restored.
    _hold_values(system, wanted)


def _hold_values(system: Win32System, wanted: dict[tuple[str, str], RegValue | None]) -> None:
    """Put back what Windows rewrites on its own time, until it has finished."""
    for _ in range(WALLPAPER_SETTLE_CHECKS):
        time.sleep(WALLPAPER_SETTLE_SECONDS)
        for (key, name), value in wanted.items():
            if value is not None and system.reg_read(key, name) != value:
                system.reg_write(key, name, value)


def _restart_shell(system: Win32System) -> None:
    """A new Explorer turns Spotlight off, which would undo what the journal restored."""
    spotlight = (SPOTLIGHT_KEY, SPOTLIGHT_VALUE)
    wanted = {spotlight: system.reg_read(*spotlight)}
    explorer.restart_explorer()
    _hold_values(system, wanted)


def _refresh_metrics(system: Win32System) -> None:
    metrics = NONCLIENTMETRICSW()
    metrics.cbSize = ctypes.sizeof(NONCLIENTMETRICSW)
    _spi(SPI_GETNONCLIENTMETRICS, metrics.cbSize, ctypes.byref(metrics))
    for value_name, field in METRIC_FONTS.items():
        value = system.reg_read(METRIC_KEY, value_name)
        if value is not None:
            setattr(metrics, field, LOGFONTW.from_buffer_copy(cast(bytes, value.data)))
    for value_name, field in METRIC_SIZES.items():
        value = system.reg_read(METRIC_KEY, value_name)
        if value is not None:
            setattr(metrics, field, twips_to_pixels(str(value.data)))
    _spi(
        SPI_SETNONCLIENTMETRICS,
        metrics.cbSize,
        ctypes.byref(metrics),
        SPIF_PERSIST_AND_BROADCAST,
    )
    _refresh_icon_font(system)
    _refresh_animation(system)


def _refresh_icon_font(system: Win32System) -> None:
    value = system.reg_read(METRIC_KEY, "IconFont")
    if value is None:
        return
    font = LOGFONTW.from_buffer_copy(cast(bytes, value.data))
    size = ctypes.sizeof(LOGFONTW)
    _spi(SPI_SETICONTITLELOGFONT, size, ctypes.byref(font), SPIF_PERSIST_AND_BROADCAST)


def _in_remote_session() -> bool:
    return bool(user32.GetSystemMetrics(SM_REMOTESESSION))


def _refresh_animation(system: Win32System) -> None:
    """The saved setting is enough over RDP: Windows keeps animation off live there, and
    pushing the saved value would override it until the next sign-in."""
    if _in_remote_session():
        return
    value = system.reg_read(METRIC_KEY, "MinAnimate")
    info = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), int(str(value.data)) if value else 1)
    _spi(SPI_SETANIMATION, info.cbSize, ctypes.byref(info), SPIF_PERSIST_AND_BROADCAST)


def _refresh_icons() -> None:
    shell.SHChangeNotify(SHCNE_ASSOCCHANGED, 0, None, None)
    refresher = Path(os.environ["WINDIR"]) / "System32" / "ie4uinit.exe"
    if refresher.exists():
        subprocess.run([str(refresher), "-show"], check=False, capture_output=True)


def _broadcast(area: str) -> None:
    result = ctypes.c_size_t()
    sent = user32.SendMessageTimeoutW(
        HWND_BROADCAST,
        WM_SETTINGCHANGE,
        0,
        area,
        SMTO_ABORTIFHUNG,
        BROADCAST_TIMEOUT_MS,
        ctypes.byref(result),
    )
    if not sent:
        raise ctypes.WinError(ctypes.get_last_error())


def _render_icon(icon: int, background: int) -> Image.Image:
    size = ICON_RENDER_SIZE
    screen = win32gui.GetDC(0)
    device = win32ui.CreateDCFromHandle(screen)
    memory = device.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(device, size, size)
    try:
        memory.SelectObject(bitmap)
        memory.FillSolidRect((0, 0, size, size), background)
        win32gui.DrawIconEx(memory.GetSafeHdc(), 0, 0, icon, size, size, 0, 0, DI_NORMAL)
        bits = bitmap.GetBitmapBits(True)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        memory.DeleteDC()
        device.DeleteDC()
        win32gui.ReleaseDC(0, screen)
    return Image.frombuffer("RGB", (size, size), bits, "raw", "BGRX", 0, 1)


def show_native_taskbar() -> None:
    for class_name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        window = win32gui.FindWindow(class_name, None)
        if window:
            win32gui.ShowWindow(window, win32con.SW_SHOW)
    # What Explorer sends when it starts: apps add their tray icons again. Those icons went
    # to the replacement taskbar, so Explorer's own tray may be missing them.
    created = win32gui.RegisterWindowMessage("TaskbarCreated")
    win32gui.PostMessage(HWND_BROADCAST, created, 0, 0)
