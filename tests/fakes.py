"""An in-memory `System`, so the theme logic is tested on any OS."""

from collections.abc import Callable
from pathlib import Path

from PIL import Image

from skinamp.system.api import ElevationDeclinedError, Refresh, RegValue

# Every key a real profile would already have, whatever a test sets.
BASE_KEYS = ("Software", "Control Panel", "Control Panel\\Desktop", "Software\\Microsoft")
MACHINE_BASE_KEYS = ("SOFTWARE", r"SOFTWARE\Microsoft", r"SOFTWARE\Microsoft\Windows")


class FakeMachine:
    def __init__(self) -> None:
        self.registry: dict[tuple[str, str], RegValue] = {}
        self.keys: set[str] = set(MACHINE_BASE_KEYS)
        self.shortcuts: dict[Path, str] = {}
        self.queued: list[Callable[[], None]] = []
        self.admin_prompts = 0
        self.decline_elevation = False
        self.fail_elevation = False

    def reg_read(self, key: str, name: str) -> RegValue | None:
        return self.registry.get((key, name))

    def key_exists(self, key: str) -> bool:
        return key in self.keys

    def reg_write(self, key: str, name: str, value: RegValue) -> None:
        def write() -> None:
            current = key
            while current:
                self.keys.add(current)
                current = current.rpartition("\\")[0]
            self.registry[(key, name)] = value

        self.queued.append(write)

    def reg_delete(self, key: str, name: str) -> None:
        def delete() -> None:
            self.registry.pop((key, name), None)

        self.queued.append(delete)

    def reg_prune_key(self, key: str) -> None:
        def prune() -> None:
            if not any(owner == key for owner, _ in self.registry):
                self.keys.discard(key)

        self.queued.append(prune)

    def list_shortcuts(self) -> list[Path]:
        return sorted(self.shortcuts)

    def set_shortcut_icon(self, path: Path, location: str) -> None:
        self.queued.append(lambda: self.shortcuts.__setitem__(path, location))

    def run_elevated(self) -> None:
        queued, self.queued = self.queued, []
        if not queued:
            return
        self.admin_prompts += 1
        if self.decline_elevation:
            raise ElevationDeclinedError("declined")
        if self.fail_elevation:
            raise OSError("the helper crashed")
        for action in queued:
            action()


class FakeSystem:
    def __init__(self) -> None:
        self.registry: dict[tuple[str, str], RegValue] = {}
        self.keys: set[str] = set(BASE_KEYS)
        self.params: dict[str, int] = {}
        self.shortcuts: dict[Path, str] = {}
        self.running: set[str] = set()
        self.refreshed: list[Refresh] = []
        self.fail_writes_to: set[str] = set()
        self.fail_refresh: set[Refresh] = set()
        self.machine = FakeMachine()
        self.refuse_close: set[str] = set()
        self.closed: list[str] = []
        self.started: list[tuple[Path, tuple[str, ...]]] = []
        self.fail_start = False

    def reg_read(self, key: str, name: str) -> RegValue | None:
        return self.registry.get((key, name))

    def reg_write(self, key: str, name: str, value: RegValue) -> None:
        if name in self.fail_writes_to:
            raise OSError(f"cannot write {name}")
        current = key
        while current:
            self.keys.add(current)
            current = current.rpartition("\\")[0]
        self.registry[(key, name)] = value

    def reg_delete(self, key: str, name: str) -> None:
        self.registry.pop((key, name), None)

    def reg_key_exists(self, key: str) -> bool:
        return key in self.keys

    def reg_prune_key(self, key: str) -> None:
        has_values = any(owner == key for owner, _ in self.registry)
        has_children = any(other.startswith(f"{key}\\") for other in self.keys)
        if not has_values and not has_children:
            self.keys.discard(key)

    def get_param(self, name: str) -> int:
        return self.params.get(name, 1)

    def set_param(self, name: str, value: int) -> None:
        self.params[name] = value

    def list_shortcuts(self) -> list[Path]:
        return sorted(self.shortcuts)

    def get_shortcut_icon(self, path: Path) -> str:
        if path in self.machine.shortcuts:
            return self.machine.shortcuts[path]
        return self.shortcuts[path]

    def set_shortcut_icon(self, path: Path, location: str) -> None:
        self.shortcuts[path] = location

    def extract_icon(self, path: Path) -> Image.Image:
        if "broken" in path.name:
            raise OSError("no icon")
        return Image.new("RGBA", (32, 32), (200, 30, 30, 255))

    def process_running(self, image_name: str) -> bool:
        return image_name in self.running

    def close_app(self, image_name: str) -> Path | None:
        if image_name not in self.running:
            return None
        if image_name in self.refuse_close:
            raise OSError(f"{image_name} would not close")
        self.running.discard(image_name)
        self.closed.append(image_name)
        return Path("apps") / image_name

    def start_app(self, exe: Path, arguments: tuple[str, ...]) -> None:
        if self.fail_start:
            raise OSError("cannot start")
        self.started.append((exe, arguments))

    def dpi(self) -> int:
        return 96

    def refresh(self, what: Refresh) -> None:
        if what in self.fail_refresh:
            raise OSError(f"cannot refresh {what}")
        self.refreshed.append(what)
