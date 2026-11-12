"""Reversible changes.

An `Effect` is one change to the machine. Its `capture` records what is there now, and
that record plus `target()` is everything `restore` needs. Restoring takes no theme
code on purpose: the journal may have been written by an older release, and a theme can
be renamed or removed, so undo must still work with only the data on disk.

Consequence for maintainers: a `kind` shipped in any release must keep restoring in
every later one. `tests/test_effects.py` holds a golden journal for exactly this.
"""

import base64
import json
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, cast

from skinamp.fsutil import atomic_write
from skinamp.system.api import TASKBAR_AUTOHIDE, Refresh, RegType, RegValue, System

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None
type JsonObject = dict[str, Json]


class BlockedError(Exception):
    """This cannot happen yet, but can later: Chrome is open, say. Retryable."""


class UnknownEffectError(Exception):
    """A journal entry has a kind this build cannot restore."""


class Effect(ABC):
    kind: ClassVar[str]
    refresh: ClassVar[Refresh | None] = None
    elevated: ClassVar[bool] = False
    """True when `apply` and `restore` only queue work for `Machine.run_elevated`."""

    @abstractmethod
    def target(self) -> JsonObject: ...

    @abstractmethod
    def capture(self, system: System) -> JsonObject: ...

    @abstractmethod
    def apply(self, system: System) -> None: ...

    @abstractmethod
    def describe(self) -> str: ...

    @staticmethod
    @abstractmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None: ...

    def refresh_kind(self) -> Refresh | None:
        return self.refresh

    @staticmethod
    def changed_since_restore(system: System, target: JsonObject, before: JsonObject) -> bool:
        """True if something has since moved this away from what `restore` put back.

        Only effects that can check cheaply say so; the rest are never redone.
        """
        return False

    @staticmethod
    def must_close(target: JsonObject) -> str | None:
        """The process that has to be closed before this can be restored, if any."""
        return None


def encode_value(value: RegValue | None) -> Json:
    if value is None:
        return None
    if isinstance(value.data, bytes):
        return {"type": value.type, "data": base64.b64encode(value.data).decode("ascii")}
    return {"type": value.type, "data": value.data}


def decode_value(encoded: Json) -> RegValue | None:
    if encoded is None:
        return None
    fields = cast(JsonObject, encoded)
    kind = cast(RegType, fields["type"])
    data = cast(str | int, fields["data"])
    if kind == "binary":
        return RegValue(kind, base64.b64decode(cast(str, data)))
    return RegValue(kind, data)


def missing_keys(system: System, key: str) -> list[str]:
    """The keys along `key` that do not exist, deepest first."""
    missing = []
    current = key
    while current and not system.reg_key_exists(current):
        missing.append(current)
        current = current.rpartition("\\")[0]
    return missing


@dataclass(frozen=True)
class SetRegistry(Effect):
    key: str
    name: str
    value: RegValue
    refresh_on: Refresh | None = None

    kind: ClassVar[str] = "registry"

    def refresh_kind(self) -> Refresh | None:
        return self.refresh_on

    def target(self) -> JsonObject:
        return {"key": self.key, "name": self.name}

    def capture(self, system: System) -> JsonObject:
        return {
            "value": encode_value(system.reg_read(self.key, self.name)),
            "created_keys": cast(Json, missing_keys(system, self.key)),
        }

    def apply(self, system: System) -> None:
        system.reg_write(self.key, self.name, self.value)

    def describe(self) -> str:
        return f"HKCU\\{self.key} [{self.name or '(Default)'}]"

    @staticmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None:
        key = cast(str, target["key"])
        name = cast(str, target["name"])
        previous = decode_value(before["value"])
        if previous is not None:
            system.reg_write(key, name, previous)
            return
        system.reg_delete(key, name)
        for created in cast(list[str], before["created_keys"]):
            system.reg_prune_key(created)

    @staticmethod
    def changed_since_restore(system: System, target: JsonObject, before: JsonObject) -> bool:
        return _registry_changed(system, target, before)


def _registry_changed(system: System, target: JsonObject, before: JsonObject) -> bool:
    current = system.reg_read(cast(str, target["key"]), cast(str, target["name"]))
    return current != decode_value(before["value"])


@dataclass(frozen=True)
class SetMachineRegistry(Effect):
    """A value under HKEY_LOCAL_MACHINE, for what Windows reads from nowhere else."""

    key: str
    name: str
    value: RegValue
    refresh_on: Refresh | None = None

    kind: ClassVar[str] = "machine_registry"
    elevated: ClassVar[bool] = True

    def refresh_kind(self) -> Refresh | None:
        return self.refresh_on

    def target(self) -> JsonObject:
        return {"key": self.key, "name": self.name}

    def capture(self, system: System) -> JsonObject:
        missing = []
        current = self.key
        while current and not system.machine.key_exists(current):
            missing.append(current)
            current = current.rpartition("\\")[0]
        return {
            "value": encode_value(system.machine.reg_read(self.key, self.name)),
            "created_keys": cast(Json, missing),
        }

    def apply(self, system: System) -> None:
        system.machine.reg_write(self.key, self.name, self.value)

    def describe(self) -> str:
        return f"HKLM\\{self.key} [{self.name or '(Default)'}]"

    @staticmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None:
        key = cast(str, target["key"])
        name = cast(str, target["name"])
        previous = decode_value(before["value"])
        if previous is not None:
            system.machine.reg_write(key, name, previous)
            return
        system.machine.reg_delete(key, name)
        for created in cast(list[str], before["created_keys"]):
            system.machine.reg_prune_key(created)


@dataclass(frozen=True)
class PreserveRegistry(Effect):
    """Remember a value that other effects change as a side effect.

    Changes nothing on apply. List it before those effects: undo runs in reverse, so this
    restores last and has the final word. `UserPreferencesMask` needs this because its
    bits are written by `SetParam`, and in a remote session Windows reports animation
    settings as off whatever they really are, so the captured parameters can be wrong.
    """

    key: str
    name: str

    kind: ClassVar[str] = "preserve_registry"

    def target(self) -> JsonObject:
        return {"key": self.key, "name": self.name}

    def capture(self, system: System) -> JsonObject:
        return {"value": encode_value(system.reg_read(self.key, self.name))}

    def apply(self, system: System) -> None:
        return None

    def describe(self) -> str:
        return f"keep HKCU\\{self.key} [{self.name}]"

    @staticmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None:
        key = cast(str, target["key"])
        name = cast(str, target["name"])
        previous = decode_value(before["value"])
        if previous is None:
            system.reg_delete(key, name)
        else:
            system.reg_write(key, name, previous)

    @staticmethod
    def changed_since_restore(system: System, target: JsonObject, before: JsonObject) -> bool:
        return _registry_changed(system, target, before)


@dataclass(frozen=True)
class KeepTaskbarMode(Effect):
    """Windows' own taskbar's auto-hide mode, which a replacement taskbar changes.

    Changes nothing on apply: the replacement does that itself. It does not reliably change
    it back on exit, so undo stops the replacement first and then sets the mode, which is
    why this goes before the entry that starts the replacement: undo runs in reverse.
    """

    kind: ClassVar[str] = "taskbar_mode"

    def target(self) -> JsonObject:
        return {}

    def capture(self, system: System) -> JsonObject:
        return {"value": system.get_param(TASKBAR_AUTOHIDE)}

    def apply(self, system: System) -> None:
        return None

    def describe(self) -> str:
        return "keep the taskbar's auto-hide setting"

    @staticmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None:
        system.refresh(Refresh.TASKBAR)
        system.set_param(TASKBAR_AUTOHIDE, cast(int, before["value"]))


@dataclass(frozen=True)
class SetParam(Effect):
    """A `SystemParametersInfo` setting. Windows persists these itself."""

    name: str
    value: int

    kind: ClassVar[str] = "sysparam"

    def target(self) -> JsonObject:
        return {"name": self.name}

    def capture(self, system: System) -> JsonObject:
        return {"value": system.get_param(self.name)}

    def apply(self, system: System) -> None:
        system.set_param(self.name, self.value)

    def describe(self) -> str:
        return f"system setting {self.name}"

    @staticmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None:
        system.set_param(cast(str, target["name"]), cast(int, before["value"]))


@dataclass(frozen=True)
class SetShortcutIcon(Effect):
    path: Path
    icon: str

    kind: ClassVar[str] = "shortcut_icon"
    refresh: ClassVar[Refresh | None] = Refresh.ICONS

    def target(self) -> JsonObject:
        return {"path": str(self.path), "icon": self.icon}

    def capture(self, system: System) -> JsonObject:
        return {"icon": system.get_shortcut_icon(self.path)}

    def apply(self, system: System) -> None:
        system.set_shortcut_icon(self.path, self.icon)

    def describe(self) -> str:
        return f"icon of {self.path.name}"

    @staticmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None:
        path = Path(cast(str, target["path"]))
        # An app update may have deleted or rewritten the shortcut since. Then its icon is
        # no longer ours to restore, and putting the old one back would be a new change.
        if path.exists() and system.get_shortcut_icon(path) == target["icon"]:
            system.set_shortcut_icon(path, cast(str, before["icon"]))


@dataclass(frozen=True)
class SetMachineShortcutIcon(Effect):
    """The icon of a shortcut shared by every account, which only an admin can rewrite."""

    path: Path
    icon: str

    kind: ClassVar[str] = "machine_shortcut_icon"
    refresh: ClassVar[Refresh | None] = Refresh.ICONS
    elevated: ClassVar[bool] = True

    def target(self) -> JsonObject:
        return {"path": str(self.path), "icon": self.icon}

    def capture(self, system: System) -> JsonObject:
        return {"icon": system.get_shortcut_icon(self.path)}

    def apply(self, system: System) -> None:
        system.machine.set_shortcut_icon(self.path, self.icon)

    def describe(self) -> str:
        return f"icon of {self.path.name} (all users)"

    @staticmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None:
        path = Path(cast(str, target["path"]))
        # As with SetShortcutIcon: an app update may have rewritten the shortcut since.
        if path.exists() and system.get_shortcut_icon(path) == target["icon"]:
            system.machine.set_shortcut_icon(path, cast(str, before["icon"]))


@dataclass(frozen=True)
class PreserveFile(Effect):
    """Keep a copy of a file something else may delete while the theme is on.

    Changes nothing on apply. Undo puts the file back only if it has gone, so a file that
    is still there, or that was changed since, is left exactly as it is.
    """

    path: Path
    backup: Path
    refresh_on: Refresh | None = None

    kind: ClassVar[str] = "preserve_file"

    def refresh_kind(self) -> Refresh | None:
        return self.refresh_on

    def target(self) -> JsonObject:
        return {"path": str(self.path), "backup": str(self.backup)}

    def capture(self, system: System) -> JsonObject:
        self.backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path, self.backup)
        return {}

    def apply(self, system: System) -> None:
        return None

    def describe(self) -> str:
        return f"keep a copy of {self.path.name}"

    @staticmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None:
        path = Path(cast(str, target["path"]))
        backup = Path(cast(str, target["backup"]))
        if path.exists():
            return
        if not backup.exists():
            raise FileNotFoundError(f"The saved copy of {path.name} is gone: {backup}")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, path)


def _read_json(path: Path) -> JsonObject:
    return cast(JsonObject, json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, data: JsonObject) -> None:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    atomic_write(path, text.encode("utf-8"))


def _lookup(data: JsonObject, keys: list[str]) -> tuple[bool, Json]:
    current: Json = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return False, None
        current = current[key]
    return True, current


def _assign(data: JsonObject, keys: list[str], value: Json) -> None:
    current = data
    for key in keys[:-1]:
        current = cast(JsonObject, current.setdefault(key, {}))
    current[keys[-1]] = value


def _remove(data: JsonObject, keys: list[str], keep_depth: int) -> None:
    """Delete `keys`, then any parent below `keep_depth` that is left empty."""
    for depth in range(len(keys), keep_depth, -1):
        found, parent = _lookup(data, keys[: depth - 1])
        if not found or not isinstance(parent, dict):
            continue
        child = parent.get(keys[depth - 1])
        if depth == len(keys) or child == {}:
            parent.pop(keys[depth - 1], None)


def _existing_depth(data: JsonObject, keys: list[str]) -> int:
    """How many leading `keys` already exist: below this, a restore prunes what it made."""
    for depth in range(len(keys)):
        if not _lookup(data, keys[: depth + 1])[0]:
            return depth
    return len(keys)


@dataclass(frozen=True)
class SetJsonPref(Effect):
    """One key in an application's JSON settings file.

    Only that key is restored, never the whole file: the application rewrites the rest of
    the file constantly. `guard` names a process that overwrites the file on exit, so
    both directions refuse while it runs, and the engine closes it first.
    """

    file: Path
    path: tuple[str, ...]
    value: Json
    guard: str

    kind: ClassVar[str] = "json_pref"

    def target(self) -> JsonObject:
        return {"file": str(self.file), "path": list(self.path), "guard": self.guard}

    def capture(self, system: System) -> JsonObject:
        data = _read_json(self.file)
        keys = list(self.path)
        present, value = _lookup(data, keys)
        return {"present": present, "value": value, "keep_depth": _existing_depth(data, keys)}

    def apply(self, system: System) -> None:
        _require_closed(system, self.guard)
        data = _read_json(self.file)
        _assign(data, list(self.path), self.value)
        _write_json(self.file, data)

    def describe(self) -> str:
        return f"{self.file.parent.name}/{self.file.name} [{'.'.join(self.path)}]"

    @staticmethod
    def must_close(target: JsonObject) -> str | None:
        return cast(str, target["guard"])

    @staticmethod
    def restore(system: System, target: JsonObject, before: JsonObject) -> None:
        file = Path(cast(str, target["file"]))
        if not file.exists():
            return
        _require_closed(system, cast(str, target["guard"]))
        keys = cast(list[str], target["path"])
        data = _read_json(file)
        if before["present"]:
            _assign(data, keys, before["value"])
        else:
            _remove(data, keys, cast(int, before["keep_depth"]))
        _write_json(file, data)


def _require_closed(system: System, image_name: str) -> None:
    if system.process_running(image_name):
        raise BlockedError(f"Close {image_name} first")


EFFECT_TYPES: dict[str, type[Effect]] = {
    effect.kind: effect
    for effect in (
        SetRegistry,
        SetMachineRegistry,
        PreserveRegistry,
        KeepTaskbarMode,
        SetParam,
        SetShortcutIcon,
        SetMachineShortcutIcon,
        PreserveFile,
        SetJsonPref,
    )
}

# A journal names only the process, and undo runs no theme code, so this cannot live with
# the theme that closed it. Started plainly, Chrome would open an empty window.
RESTART_ARGUMENTS = {"chrome.exe": ("--restore-last-session",)}


def is_elevated(kind: str) -> bool:
    effect = EFFECT_TYPES.get(kind)
    return effect is not None and effect.elevated


def process_to_close(kind: str, target: JsonObject) -> str | None:
    effect = EFFECT_TYPES.get(kind)
    return effect.must_close(target) if effect else None


def drifted(system: System, kind: str, target: JsonObject, before: JsonObject) -> bool:
    """Whether Windows has changed a restored entry back since. Unknown kinds never have."""
    effect = EFFECT_TYPES.get(kind)
    return effect is not None and effect.changed_since_restore(system, target, before)


def restore_entry(system: System, kind: str, target: JsonObject, before: JsonObject) -> None:
    effect = EFFECT_TYPES.get(kind)
    if effect is None:
        raise UnknownEffectError(f"This version cannot undo a change of kind {kind!r}")
    effect.restore(system, target, before)
