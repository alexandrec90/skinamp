"""Where Skinamp keeps its data.

Data lives in `%LOCALAPPDATA%\\SkinampData`, deliberately NOT `%LOCALAPPDATA%\\Skinamp`.
That second folder is the install root, which the updater replaces and the uninstaller
deletes; the undo journal has to outlive both.
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    machine_root: Path | None = None

    @property
    def journal(self) -> Path:
        return self.root / "state" / "journal.json"

    @property
    def log(self) -> Path:
        return self.root / "state" / "skinamp.log"

    @property
    def backups(self) -> Path:
        """Copies of the user's own files. Removed only once a revert completes."""
        return self.root / "state" / "backups"

    @property
    def assets(self) -> Path:
        """Generated cursors and icons. Removed once a revert completes."""
        return self.root / "assets"

    @property
    def components(self) -> Path:
        """Downloaded third-party components. Removed once a revert completes."""
        return self.root / "components"

    @property
    def machine_assets(self) -> Path:
        """Icons used by settings every account reads, so not in one user's private folder.

        Normal users can create folders in `%ProgramData%`, so writing these needs no admin
        rights. Removed once a revert completes.
        """
        return (self.machine_root or self.root) / "machine-assets"


def default_paths() -> AppPaths:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    shared = os.environ.get("PROGRAMDATA")
    return AppPaths(root / "SkinampData", Path(shared) / "SkinampData" if shared else None)
