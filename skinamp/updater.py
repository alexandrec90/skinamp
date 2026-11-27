"""Automatic updates through Velopack, from this repository's GitHub Releases.

The app checks on launch and downloads a found update in the background. The user can
then restart into it at once, or let it install silently when the app exits. An update
problem must never get in the way of theming, or above all of undoing a theme, so every
failure here becomes a status and nothing raises.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import velopack

logger = logging.getLogger(__name__)

REPOSITORY = "https://github.com/alexandrec90/skinamp"

Phase = Literal["unmanaged", "current", "ready", "failed"]


@dataclass(frozen=True)
class UpdateStatus:
    phase: Phase
    version: str | None = None
    detail: str | None = None


def velopack_manager() -> velopack.UpdateManager:
    return velopack.UpdateManager(velopack.GithubSource(REPOSITORY))


class Updater:
    def __init__(self, factory: Callable[[], velopack.UpdateManager] = velopack_manager) -> None:
        self._factory = factory
        self._manager: velopack.UpdateManager | None = None
        self._pending: velopack.UpdateInfo | None = None

    def check_and_download(self) -> UpdateStatus:
        try:
            self._manager = self._factory()
        except RuntimeError as exc:
            # Running from source or an unpacked build: there is nothing to update.
            logger.info("updates unavailable: %s", exc)
            return UpdateStatus("unmanaged")
        try:
            update = self._manager.check_for_updates()
            if update is None:
                return UpdateStatus("current")
            self._manager.download_updates(update)
        except (RuntimeError, OSError) as exc:
            logger.exception("update failed")
            return UpdateStatus("failed", detail=str(exc))
        self._pending = update
        return UpdateStatus("ready", update.TargetFullRelease.Version)

    def restart_into_update(self) -> None:
        """Install the downloaded update now and relaunch. Velopack exits this process.

        The install is queued here, not at download time: Velopack starts one waiting
        installer per call, and a silent one queued earlier would race this one and could
        finish without relaunching.
        """
        if self._manager is not None and self._pending is not None:
            self._manager.apply_updates_and_restart(self._pending)

    def install_on_exit(self) -> None:
        """Queue the downloaded update to install, silently, once this process exits."""
        if self._manager is None or self._pending is None:
            return
        try:
            self._manager.wait_exit_then_apply_updates(self._pending, silent=True, restart=False)
        except (RuntimeError, OSError):
            logger.exception("could not queue the update for exit")
