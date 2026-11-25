"""Running the replacement taskbar.

Whether it should run is read from one registry value, the login entry under `Run`. That
value is an ordinary journalled effect, so `sync` needs no state of its own: after an
apply it finds the value and starts the taskbar, after a revert it finds none and stops
it. The same `sync` therefore serves both directions and a retry after a partial revert.
"""

import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import psutil

from skinamp.paths import AppPaths
from skinamp.system.api import System

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Skinamp Taskbar"
RETROBAR_VERSION = "1.22.122"
DOTNET_VERSION = "10.0.14"
SETTINGS_MARKER = "retrobar-settings-are-ours"
STOP_TIMEOUT_SECONDS = 5
DETACHED_PROCESS = 0x00000008


def retrobar_exe(paths: AppPaths) -> Path:
    return paths.components / f"retrobar-{RETROBAR_VERSION}" / "RetroBar.exe"


def dotnet_root(paths: AppPaths) -> Path:
    return paths.components / f"dotnet-{DOTNET_VERSION}"


def retrobar_settings_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RetroBar"


def self_command() -> list[str]:
    """How to run Skinamp again, for frozen and source runs alike."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "skinamp"]


def launch_command() -> str:
    """The command that restarts the taskbar at login."""
    return subprocess.list2cmdline([*self_command(), "taskbar-start"])


def running(paths: AppPaths) -> list[psutil.Process]:
    """Our RetroBar only: one the user runs on their own is not ours to stop."""
    ours = []
    for process in psutil.process_iter(["exe"]):
        exe = process.info["exe"]
        if exe and Path(exe).is_relative_to(paths.components):
            ours.append(process)
    return ours


def start(paths: AppPaths) -> None:
    exe = retrobar_exe(paths)
    if running(paths) or not exe.exists():
        return
    environment = {**os.environ, "DOTNET_ROOT": str(dotnet_root(paths))}
    subprocess.Popen([str(exe)], env=environment, creationflags=DETACHED_PROCESS)


def stop(
    paths: AppPaths,
    ask_to_close: Callable[[set[int]], bool],
    show_native: Callable[[], None],
) -> None:
    processes = running(paths)
    if processes:
        ask_to_close({process.pid for process in processes})
    _, alive = psutil.wait_procs(processes, timeout=STOP_TIMEOUT_SECONDS)
    for process in alive:
        logger.warning("RetroBar ignored a close request; ending it (%s)", process.pid)
        process.kill()
    if alive:
        # A hard kill skips RetroBar's own cleanup, which is what un-hides Explorer's.
        psutil.wait_procs(alive, timeout=STOP_TIMEOUT_SECONDS)
    show_native()
    marker = paths.components / SETTINGS_MARKER
    if marker.exists():
        shutil.rmtree(retrobar_settings_dir(), ignore_errors=True)


def sync(
    system: System,
    paths: AppPaths,
    ask_to_close: Callable[[set[int]], bool],
    show_native: Callable[[], None],
) -> None:
    if system.reg_read(RUN_KEY, RUN_VALUE) is None:
        stop(paths, ask_to_close, show_native)
    else:
        start(paths)
