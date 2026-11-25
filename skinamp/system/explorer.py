"""Restarting Explorer, which the desktop needs before it shows new folder icons.

Each step here is a live finding, because the obvious way loses something:

- Explorer's undocumented exit message is replaced by Restart Manager, the documented API
  installers use, which also restarts it.
- Windows' icon cache on disk has to go while Explorer is down. Otherwise the new Explorer
  reloads old icons, and after an undo that means the theme's.
- Explorer does not save icon positions on this exit, and reloads an older layout. So
  they are read beforehand and put back.
- Anything sent to a half-started Explorer can crash it, which took the whole shell down.
  So this waits, and `Refresh.SHELL` runs after every broadcast.
"""

import contextlib
import ctypes
import logging
import os
import struct
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from time import sleep

if sys.platform != "win32":
    raise ImportError("skinamp.system.explorer needs Windows")

import win32gui
import win32process

logger = logging.getLogger(__name__)

TRAY_CLASS = "Shell_TrayWnd"
CHECK_SECONDS = 0.25
RETURN_CHECKS = 40
START_CHECKS = 80
SETTLE_SECONDS = 3
ICON_CHECKS = 40
SESSION_KEY_CHARS = 33
GRACEFUL = 0
DETACHED_PROCESS = 0x00000008

LVM_GETITEMCOUNT = 0x1004
LVM_SETITEMPOSITION = 0x100F
LVM_GETITEMPOSITION = 0x1010
LVM_GETITEMTEXTW = 0x1073
LVIF_TEXT = 0x0001
TEXT_OFFSET = 256
TEXT_BYTES = 1024
REMOTE_BYTES = 4096
LVITEMW_BYTES = 88
PROCESS_VM_ACCESS = 0x0008 | 0x0010 | 0x0020
MEM_COMMIT = 0x1000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

rstrtmgr = ctypes.WinDLL("rstrtmgr")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualAllocEx.argtypes = (
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_size_t,
    wintypes.DWORD,
    wintypes.DWORD,
)
kernel32.VirtualFreeEx.argtypes = (
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_size_t,
    wintypes.DWORD,
)
kernel32.ReadProcessMemory.argtypes = (
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
)
kernel32.WriteProcessMemory.argtypes = (
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
)
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t)


def desktop_list() -> int:
    """The list view holding the desktop's icons, or 0 if Explorer has not made it yet."""
    found: list[int] = []

    def visit(window: int, _extra: None) -> None:
        if win32gui.GetClassName(window) in ("Progman", "WorkerW"):
            view = win32gui.FindWindowEx(window, 0, "SHELLDLL_DefView", None)
            if view:
                found.append(win32gui.FindWindowEx(view, 0, "SysListView32", None))

    win32gui.EnumWindows(visit, None)
    return found[0] if found else 0


def _read_item(process: int, remote: int, listview: int, index: int) -> tuple[str, int, int]:
    """Explorer's memory holds the answers, so the requests have to be made inside it."""
    user32.SendMessageW(listview, LVM_GETITEMPOSITION, index, remote)
    point = ctypes.create_string_buffer(8)
    kernel32.ReadProcessMemory(process, remote, point, 8, None)
    x, y = struct.unpack("<ll", point.raw)
    text_at = remote + TEXT_OFFSET
    # A 64-bit LVITEMW: mask, item, subitem, state, state mask, padding, text, text length.
    item = struct.pack("<IiiIIIQi", LVIF_TEXT, index, 0, 0, 0, 0, text_at, TEXT_BYTES // 2)
    request = ctypes.create_string_buffer(item.ljust(LVITEMW_BYTES, b"\0"))
    kernel32.WriteProcessMemory(process, remote, request, LVITEMW_BYTES, None)
    user32.SendMessageW(listview, LVM_GETITEMTEXTW, index, remote)
    text = ctypes.create_string_buffer(TEXT_BYTES)
    kernel32.ReadProcessMemory(process, text_at, text, TEXT_BYTES, None)
    return text.raw.decode("utf-16-le", "ignore").split("\0")[0], x, y


def read_items(listview: int) -> dict[str, tuple[int, int, int]]:
    """Each icon's name, as its index and position."""
    pid = win32process.GetWindowThreadProcessId(listview)[1]
    process = kernel32.OpenProcess(PROCESS_VM_ACCESS, False, pid)
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    remote = kernel32.VirtualAllocEx(process, None, REMOTE_BYTES, MEM_COMMIT, PAGE_READWRITE)
    try:
        items = {}
        for index in range(user32.SendMessageW(listview, LVM_GETITEMCOUNT, 0, 0)):
            name, x, y = _read_item(process, remote, listview, index)
            items[name] = (index, x, y)
        return items
    finally:
        kernel32.VirtualFreeEx(process, remote, 0, MEM_RELEASE)
        kernel32.CloseHandle(process)


def desktop_icons() -> dict[str, tuple[int, int]]:
    listview = desktop_list()
    if not listview:
        return {}
    return {name: (x, y) for name, (_index, x, y) in read_items(listview).items()}


def place_desktop_icons(positions: dict[str, tuple[int, int]]) -> None:
    """Put icons back. One that has gone is skipped, and a new one stays where it landed."""
    if not positions:
        return
    items: dict[str, tuple[int, int, int]] = {}
    listview = 0
    for _ in range(ICON_CHECKS):
        listview = desktop_list()
        items = read_items(listview) if listview else {}
        if set(positions) <= set(items):
            break
        sleep(CHECK_SECONDS)
    for name, (x, y) in positions.items():
        if name in items and items[name][1:] != (x, y):
            user32.SendMessageW(listview, LVM_SETITEMPOSITION, items[name][0], y << 16 | x & 0xFFFF)


def clear_icon_cache() -> None:
    """Windows rebuilds these. One another program holds open just stays as it is."""
    folder = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Explorer"
    for cache in folder.glob("iconcache_*.db"):
        with contextlib.suppress(OSError):
            cache.unlink()


def _check(code: int) -> None:
    if code:
        raise ctypes.WinError(code)


def _restart_with_a_clean_cache(explorer: Path) -> None:
    """Graceful only: if anything refuses, RmShutdown fails and nothing has been killed."""
    session = wintypes.DWORD()
    key = ctypes.create_unicode_buffer(SESSION_KEY_CHARS)
    _check(rstrtmgr.RmStartSession(ctypes.byref(session), 0, key))
    try:
        files = (wintypes.LPCWSTR * 1)(str(explorer))
        _check(rstrtmgr.RmRegisterResources(session, 1, files, 0, None, 0, None))
        _check(rstrtmgr.RmShutdown(session, GRACEFUL, None))
        clear_icon_cache()
        # A failure here leaves Explorer down, which the caller checks for either way.
        restarted = rstrtmgr.RmRestart(session, 0, None)
        if restarted:
            logger.warning("Restart Manager did not restart Explorer: %s", restarted)
    finally:
        rstrtmgr.RmEndSession(session)


def _wait_for_tray(checks: int) -> bool:
    for _ in range(checks):
        if win32gui.FindWindow(TRAY_CLASS, None):
            return True
        sleep(CHECK_SECONDS)
    return False


def restart_explorer() -> None:
    """Runs in this unelevated process, so that Explorer stays unelevated too."""
    positions = desktop_icons()
    explorer = Path(os.environ["WINDIR"]) / "explorer.exe"
    _restart_with_a_clean_cache(explorer)
    if not _wait_for_tray(RETURN_CHECKS):
        logger.warning("Explorer did not return by itself; starting it")
        subprocess.Popen([str(explorer)], creationflags=DETACHED_PROCESS)
        if not _wait_for_tray(START_CHECKS):
            raise OSError("Explorer did not come back. Start explorer.exe from Task Manager")
    sleep(SETTLE_SECONDS)
    place_desktop_icons(positions)
