"""The requests Skinamp's elevated helper will carry out.

The helper runs with admin rights but reads its request from a file the user can write, so
the file is not trusted: `validate` rejects anything but the few operations a theme needs,
on the one key and the shortcut folders Skinamp has a reason to touch. Widening what a theme
can do as admin means widening this list, on purpose, here.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from skinamp.effects import JsonObject, encode_value
from skinamp.system.api import RegValue

SHELL_ICONS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons"
ALLOWED_KEYS = (SHELL_ICONS_KEY,)
OP_REG_WRITE = "reg_write"
OP_REG_DELETE = "reg_delete"
OP_REG_PRUNE = "reg_prune"
OP_SHORTCUT_ICON = "shortcut_icon"
REGISTRY_OPS = (OP_REG_WRITE, OP_REG_DELETE, OP_REG_PRUNE)
REQUEST_FILE = "request.json"
CLAIMED_FILE = "claimed.json"
ABANDONED_FILE = "abandoned.json"
ERROR_FILE = "error.txt"


def claim(request: Path) -> Path:
    """Take the request before reading it, so a parent that gave up cannot be overtaken.

    A rename is atomic, so between this and `abandon` exactly one of the two wins.
    """
    claimed = request.with_name(CLAIMED_FILE)
    try:
        request.rename(claimed)
    except FileNotFoundError as exc:
        raise OSError("Skinamp stopped waiting for this admin prompt, so nothing changed") from exc
    return claimed


def abandon(request: Path) -> bool:
    """Make sure the helper never runs `request`. False if it already took it."""
    try:
        request.rename(request.with_name(ABANDONED_FILE))
    except FileNotFoundError:
        return False
    return True


def reg_write(key: str, name: str, value: RegValue) -> JsonObject:
    return {"op": OP_REG_WRITE, "key": key, "name": name, "value": encode_value(value)}


def reg_delete(key: str, name: str) -> JsonObject:
    return {"op": OP_REG_DELETE, "key": key, "name": name}


def reg_prune(key: str) -> JsonObject:
    return {"op": OP_REG_PRUNE, "key": key}


def shortcut_icon(path: Path, location: str) -> JsonObject:
    return {"op": OP_SHORTCUT_ICON, "path": str(path), "location": location}


def _within(path: Path, roots: Sequence[Path]) -> bool:
    return path.suffix.lower() == ".lnk" and any(path.is_relative_to(root) for root in roots)


def validate(ops: list[JsonObject], shortcut_roots: Sequence[Path]) -> None:
    """Refuse the whole request if any part of it is outside the list above."""
    for op in ops:
        kind = op.get("op")
        if kind in REGISTRY_OPS:
            if op.get("key") not in ALLOWED_KEYS:
                raise ValueError(f"Refusing to change registry key {op.get('key')!r}")
        elif kind == OP_SHORTCUT_ICON:
            path = Path(cast(str, op.get("path", "")))
            if ".." in path.parts or not _within(path, shortcut_roots):
                raise ValueError(f"Refusing to change shortcut {path}")
        else:
            raise ValueError(f"Refusing unknown operation {kind!r}")
