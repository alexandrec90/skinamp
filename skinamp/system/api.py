"""The boundary between theme logic and the operating system.

Everything above this file is plain Python that runs and is tested on any OS. Only
`win32.py` touches Windows, and it implements `System`.

`System.reg_*` calls are always under HKEY_CURRENT_USER. Anything that needs admin rights
goes through `System.machine`, so it cannot be added by accident, and its writes queue rather
than run: `run_elevated` carries out the whole queue behind one UAC prompt. Skinamp never runs
elevated, because an elevated process can be a different user, with a different HKCU, and
`Run` entries and per-user settings must land on the person at the keyboard.

Every operating-system failure is raised as `OSError`, whichever library it came from.
The engine relies on that to tell "this step failed, carry on undoing the rest" from a bug.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from PIL import Image

RegType = Literal["sz", "expand_sz", "dword", "binary"]
TASKBAR_AUTOHIDE = "taskbar_autohide"
"""A `get_param` name: Windows' own taskbar, 1 when it hides itself."""


class ElevationDeclinedError(OSError):
    """The user said no at the UAC prompt, so nothing queued has happened."""


class Refresh(StrEnum):
    """What must be told about a change. Declaration order is execution order."""

    COLORS = "colors"
    WALLPAPER = "wallpaper"
    CURSORS = "cursors"
    METRICS = "metrics"
    ICONS = "icons"
    SETTINGS = "settings"
    SHELL = "shell"
    TASKBAR = "taskbar"


@dataclass(frozen=True)
class RegValue:
    type: RegType
    data: str | int | bytes


class Machine(Protocol):
    """What is shared by every account on the PC. Reading is free; writing needs admin."""

    def reg_read(self, key: str, name: str) -> RegValue | None:
        """Read HKEY_LOCAL_MACHINE."""
        ...

    def key_exists(self, key: str) -> bool: ...

    def reg_write(self, key: str, name: str, value: RegValue) -> None:
        """Queue a write to HKEY_LOCAL_MACHINE."""
        ...

    def reg_delete(self, key: str, name: str) -> None:
        """Queue a delete from HKEY_LOCAL_MACHINE."""
        ...

    def reg_prune_key(self, key: str) -> None:
        """Queue deleting `key` if it holds no values and no subkeys."""
        ...

    def list_shortcuts(self) -> list[Path]:
        """Every shortcut shared by all accounts."""
        ...

    def set_shortcut_icon(self, path: Path, location: str) -> None:
        """Queue changing the icon of an all-users shortcut."""
        ...

    def run_elevated(self) -> None:
        """Carry out everything queued, behind one UAC prompt. Nothing queued, no prompt.

        Raises `ElevationDeclinedError` if the user says no. The queue is empty afterwards
        either way, so a retry queues its work again.
        """
        ...


class System(Protocol):
    machine: Machine

    def reg_read(self, key: str, name: str) -> RegValue | None: ...

    def reg_write(self, key: str, name: str, value: RegValue) -> None: ...

    def reg_delete(self, key: str, name: str) -> None: ...

    def reg_key_exists(self, key: str) -> bool: ...

    def reg_prune_key(self, key: str) -> None:
        """Delete `key` if it holds no values and no subkeys."""
        ...

    def get_param(self, name: str) -> int: ...

    def set_param(self, name: str, value: int) -> None: ...

    def list_shortcuts(self) -> list[Path]:
        """Every shortcut the current user can rewrite without elevation."""
        ...

    def get_shortcut_icon(self, path: Path) -> str: ...

    def set_shortcut_icon(self, path: Path, location: str) -> None: ...

    def extract_icon(self, path: Path) -> Image.Image: ...

    def process_running(self, image_name: str) -> bool: ...

    def close_app(self, image_name: str) -> Path | None:
        """Close a running app the way logging off would, so it saves its session.

        Returns its executable, or None if it was not running. Raises `OSError` if it is
        still open afterwards: it is never killed while it may hold unsaved work.
        """
        ...

    def start_app(self, exe: Path, arguments: tuple[str, ...]) -> None: ...

    def dpi(self) -> int: ...

    def refresh(self, what: Refresh) -> None: ...
