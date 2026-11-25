"""Generated files: cursors, desktop icons and pixelated shortcut icons."""

import hashlib
import logging
from collections.abc import Mapping
from pathlib import Path

from PIL import Image

from skinamp.art.ico import encode_cur, encode_ico
from skinamp.art.pixels import icon_frames, pixelate, scale
from skinamp.art.sprites import Cursor, cursors
from skinamp.effects import (
    Effect,
    SetMachineRegistry,
    SetMachineShortcutIcon,
    SetRegistry,
    SetShortcutIcon,
)
from skinamp.elevated import SHELL_ICONS_KEY
from skinamp.system.api import Refresh, RegValue, System

logger = logging.getLogger(__name__)

CURSORS_KEY = r"Control Panel\Cursors"
CLSID_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\CLSID"
CURSOR_SCALES = (1, 2)

DESKTOP_ICON_CLSIDS = {
    "computer": "{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
    "documents": "{59031a47-3f72-44a7-89c5-5595fe6b30ee}",
    "network": "{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}",
}
RECYCLE_BIN_CLSID = "{645FF040-5081-101B-9F08-00AA002F954E}"
# Indexes into the shell's stock icon list.
SHELL_ICON_FOLDER = "3"
SHELL_ICON_FOLDER_OPEN = "4"


def write_cursor(cursor: Cursor, path: Path) -> None:
    frames = []
    for factor in CURSOR_SCALES:
        size = cursor.image.width * factor
        hotspot = (cursor.hotspot[0] * factor, cursor.hotspot[1] * factor)
        frames.append((scale(cursor.image, size), hotspot))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_cur(frames))


def write_cursors(folder: Path) -> None:
    for name, cursor in cursors().items():
        write_cursor(cursor, folder / f"{name}.cur")


def cursor_effects(folder: Path, scheme: str) -> list[Effect]:
    effects: list[Effect] = [
        SetRegistry(
            CURSORS_KEY, name, RegValue("expand_sz", str(folder / f"{name}.cur")), Refresh.CURSORS
        )
        for name in cursors()
    ]
    # "Scheme Source" 0 means no named scheme, so the control panel shows ours as custom.
    effects.append(SetRegistry(CURSORS_KEY, "", RegValue("sz", scheme), Refresh.CURSORS))
    effects.append(SetRegistry(CURSORS_KEY, "Scheme Source", RegValue("dword", 0), Refresh.CURSORS))
    return effects


def write_icons(images: Mapping[str, Image.Image], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, image in images.items():
        (folder / f"{name}.ico").write_bytes(encode_ico(icon_frames(image)))


def _icon_value(folder: Path, name: str) -> RegValue:
    return RegValue("sz", f"{folder / f'{name}.ico'},0")


def desktop_icon_effects(folder: Path) -> list[Effect]:
    effects: list[Effect] = [
        SetRegistry(
            f"{CLSID_ROOT}\\{clsid}\\DefaultIcon", "", _icon_value(folder, name), Refresh.ICONS
        )
        for name, clsid in DESKTOP_ICON_CLSIDS.items()
    ]
    bin_key = f"{CLSID_ROOT}\\{RECYCLE_BIN_CLSID}\\DefaultIcon"
    for value_name, icon in (("", "bin_empty"), ("empty", "bin_empty"), ("full", "bin_full")):
        effects.append(SetRegistry(bin_key, value_name, _icon_value(folder, icon), Refresh.ICONS))
    return effects


def folder_icon_effects(folder: Path) -> list[Effect]:
    """Windows reads `Shell Icons` from HKLM only: the same key under HKCU does nothing.

    Explorer windows pick these up, but the desktop only does when Explorer starts.
    """
    return [
        SetMachineRegistry(SHELL_ICONS_KEY, index, _icon_value(folder, name), Refresh.SHELL)
        for index, name in (
            (SHELL_ICON_FOLDER, "folder"),
            (SHELL_ICON_FOLDER_OPEN, "folder_open"),
        )
    ]


def shortcut_icon_path(folder: Path, shortcut: Path) -> Path:
    digest = hashlib.sha256(str(shortcut).lower().encode("utf-8")).hexdigest()[:16]
    return folder / f"{digest}.ico"


def write_shortcut_icons(system: System, shortcuts: list[Path], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for shortcut in shortcuts:
        try:
            source = system.extract_icon(shortcut)
        except OSError as exc:
            # One unreadable shortcut (a dangling target, say) must not stop the theme.
            logger.warning("Leaving %s alone: %s", shortcut, exc)
            continue
        icon = encode_ico(icon_frames(pixelate(source)))
        shortcut_icon_path(folder, shortcut).write_bytes(icon)


def shortcut_effects(system: System, folder: Path, planning: bool) -> list[Effect]:
    effects: list[Effect] = []
    for shortcut in system.list_shortcuts():
        icon = shortcut_icon_path(folder, shortcut)
        if planning or icon.exists():
            effects.append(SetShortcutIcon(shortcut, f"{icon},0"))
    return effects


def machine_shortcut_effects(system: System, folder: Path, planning: bool) -> list[Effect]:
    effects: list[Effect] = []
    for shortcut in system.machine.list_shortcuts():
        icon = shortcut_icon_path(folder, shortcut)
        if planning or icon.exists():
            effects.append(SetMachineShortcutIcon(shortcut, f"{icon},0"))
    return effects
