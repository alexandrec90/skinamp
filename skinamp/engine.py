"""Applying a theme as a transaction, and undoing it."""

import contextlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from skinamp import __version__
from skinamp.effects import (
    RESTART_ARGUMENTS,
    BlockedError,
    Effect,
    UnknownEffectError,
    drifted,
    is_elevated,
    process_to_close,
    restore_entry,
)
from skinamp.journal import Entry, Journal, JournalError, JournalStore
from skinamp.paths import AppPaths
from skinamp.system.api import ElevationDeclinedError, Refresh, System
from skinamp.themes.model import BuildContext, Component, Theme

logger = logging.getLogger(__name__)

# What restoring one entry can fail with: the OS refusing, or an entry this build cannot
# read. Anything else is a bug and stops the revert, which is safe: the journal is still
# on disk and restoring is idempotent, so running it again loses nothing.
RESTORE_ERRORS = (OSError, ValueError, KeyError, TypeError, UnknownEffectError)
DECLINED_APPLY = "Windows' admin prompt was declined or not answered"
DECLINED_REVERT = "Say yes to Windows' admin prompt to finish undoing"


class ApplyFailedError(Exception):
    """An apply failed part-way and was rolled back as far as `rollback` says."""

    def __init__(self, message: str, rollback: "RevertResult") -> None:
        super().__init__(message)
        self.rollback = rollback


class RevertIncompleteError(Exception):
    """A new theme cannot start until the previous one is fully undone."""


@dataclass(frozen=True)
class Skipped:
    component: str
    reason: str


@dataclass(frozen=True)
class PlanItem:
    component: str
    change: str


@dataclass
class ApplyResult:
    theme: str
    applied: list[str]
    skipped: list[Skipped] = field(default_factory=list)
    changes: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class RevertResult:
    restored: int = 0
    pending: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.pending


@dataclass(frozen=True)
class Status:
    theme: str | None
    state: str
    components: list[str]
    changes: int
    error: str | None = None


def _refreshes(kinds: set[str]) -> list[Refresh]:
    return [refresh for refresh in Refresh if refresh.value in kinds]


class Engine:
    def __init__(self, system: System, paths: AppPaths) -> None:
        self._system = system
        self._paths = paths
        self._store = JournalStore(paths.journal)

    def status(self) -> Status:
        try:
            journal = self._store.load()
        except JournalError as exc:
            return Status(None, "unreadable", [], 0, str(exc))
        if journal is None:
            return Status(None, "default", [], 0)
        return Status(journal.theme, journal.state, journal.components, len(journal.entries))

    def plan(self, theme: Theme, ids: list[str] | None = None) -> list[PlanItem]:
        """List what `apply` would change, without changing anything."""
        context = BuildContext(self._system, self._paths, planning=True)
        return [
            PlanItem(component.id, effect.describe())
            for component in theme.select(ids)
            for effect in component.effects(context)
        ]

    def apply(self, theme: Theme, ids: list[str] | None = None) -> ApplyResult:
        selected = theme.select(ids)
        with self._store.hold():
            self._revert_previous()
            context = BuildContext(self._system, self._paths)
            ready, skipped = self._partition(selected, context)
            if not ready:
                return ApplyResult(theme.id, [], skipped)
            try:
                for component in ready:
                    component.prepare(context)
            except Exception as exc:
                # Nothing has been mutated yet, so there is nothing to roll back.
                logger.exception("could not prepare %s", theme.id)
                raise ApplyFailedError(str(exc), RevertResult()) from exc
            # Last, so a slow download does not leave the user's browser shut meanwhile.
            ready, closed = self._close_for(ready, skipped)
            try:
                result = self._commit(theme, context, ready, skipped)
            finally:
                reopen_warnings = self._reopen(closed)
        result.warnings.extend(reopen_warnings)
        return result

    def _commit(
        self, theme: Theme, context: BuildContext, ready: list[Component], skipped: list[Skipped]
    ) -> ApplyResult:
        result = ApplyResult(theme.id, [component.id for component in ready], skipped)
        if not ready:
            return result
        try:
            effects = [effect for component in ready for effect in component.effects(context)]
            journal = self._open_journal(theme, ready, effects)
        except Exception as exc:
            logger.exception("could not record %s", theme.id)
            raise ApplyFailedError(str(exc), RevertResult()) from exc
        try:
            for effect in effects:
                effect.apply(self._system)
            self._run_elevated(journal, result, ready)
        except Exception as exc:
            logger.exception("apply failed; rolling back")
            raise ApplyFailedError(str(exc), self._revert()) from exc
        result.changes = len(journal.entries)
        result.warnings = self._run_refreshes({e.refresh for e in journal.entries if e.refresh})
        if journal.entries:
            journal.state = "applied"
            self._store.save(journal)
        else:
            self._store.clear()
        return result

    def _run_elevated(
        self, journal: Journal, result: ApplyResult, components: list[Component]
    ) -> None:
        """Run what needs admin. Declining costs only those parts, and nothing happened to them."""
        try:
            self._system.machine.run_elevated()
        except ElevationDeclinedError:
            declined = {component.id for component in components if component.needs_admin}
            journal.entries = [entry for entry in journal.entries if not is_elevated(entry.kind)]
            journal.components = [c for c in journal.components if c not in declined]
            result.applied = [c for c in result.applied if c not in declined]
            result.skipped.extend(Skipped(c, DECLINED_APPLY) for c in sorted(declined))
            self._store.save(journal)

    def _close_for(
        self, components: list[Component], skipped: list[Skipped]
    ) -> tuple[list[Component], dict[str, Path]]:
        """Close what each component needs closed; one that stays open skips its component."""
        ready = []
        closed: dict[str, Path] = {}
        for component in components:
            try:
                for image in component.closes:
                    exe = self._system.close_app(image)
                    if exe is not None:
                        closed[image] = exe
            except OSError as exc:
                logger.warning("could not close for %s: %s", component.id, exc)
                skipped.append(Skipped(component.id, str(exc)))
            else:
                ready.append(component)
        return ready, closed

    def _close_for_entries(self, entries: list[Entry]) -> dict[str, Path]:
        images = {process_to_close(entry.kind, entry.target) for entry in entries}
        closed: dict[str, Path] = {}
        for image in sorted(image for image in images if image):
            try:
                exe = self._system.close_app(image)
            except OSError:
                # Its entries are refused as blocked, so they stay in the journal for a retry.
                logger.exception("could not close %s", image)
                continue
            if exe is not None:
                closed[image] = exe
        return closed

    def _reopen(self, closed: dict[str, Path]) -> list[str]:
        warnings = []
        for image, exe in closed.items():
            try:
                self._system.start_app(exe, RESTART_ARGUMENTS.get(image, ()))
            except OSError as exc:
                logger.exception("could not reopen %s", image)
                warnings.append(f"Could not reopen {image}, so start it yourself: {exc}")
        return warnings

    def revert(self) -> RevertResult:
        """Undo everything. Safe to call repeatedly, and after a crash."""
        with self._store.hold():
            return self._revert()

    def _revert(self) -> RevertResult:
        journal = self._store.load()
        if journal is None:
            return RevertResult()
        journal.state = "reverting"
        self._store.save(journal)
        closed = self._close_for_entries(journal.entries)
        try:
            result, remaining = self._restore(journal.entries)
        finally:
            reopen_warnings = self._reopen(closed)
        restored = [entry for entry in journal.entries if entry not in remaining]
        result.warnings = [
            *self._run_refreshes({e.refresh for e in journal.entries if e.refresh}, restored),
            *reopen_warnings,
        ]
        if remaining:
            journal.entries = remaining
            self._store.save(journal)
            return result
        self._store.clear()
        self._remove_generated_files()
        return result

    def _revert_previous(self) -> None:
        if not self._store.exists():
            return
        result = self._revert()
        if not result.complete:
            raise RevertIncompleteError("; ".join(sorted(set(result.pending))))

    def _partition(
        self, components: list[Component], context: BuildContext
    ) -> tuple[list[Component], list[Skipped]]:
        ready, skipped = [], []
        for component in components:
            reason = component.blocker(context)
            if reason is None:
                ready.append(component)
            else:
                skipped.append(Skipped(component.id, reason))
        return ready, skipped

    def _open_journal(
        self, theme: Theme, components: list[Component], effects: list[Effect]
    ) -> Journal:
        entries = []
        for effect in effects:
            kind = effect.refresh_kind()
            entries.append(
                Entry(
                    effect.kind,
                    effect.target(),
                    effect.capture(self._system),
                    kind.value if kind else None,
                )
            )
        journal = Journal(
            theme.id, [component.id for component in components], entries, app_version=__version__
        )
        self._store.save(journal)
        return journal

    def _restore(self, entries: list[Entry]) -> tuple[RevertResult, list[Entry]]:
        result = RevertResult()
        remaining: list[Entry] = []
        # One failure must not strand the rest: restore everything that can be restored,
        # keep the journal entries for what could not, and let the user retry those.
        for entry in reversed(entries):
            try:
                restore_entry(self._system, entry.kind, entry.target, entry.before)
                result.restored += 1
            except BlockedError as exc:
                remaining.insert(0, entry)
                result.pending.append(str(exc))
            except RESTORE_ERRORS as exc:
                logger.exception("could not restore %s %s", entry.kind, entry.target)
                remaining.insert(0, entry)
                result.pending.append(f"{entry.kind}: {exc}")
        return self._finish_elevated_restores(entries, result, remaining)

    def _finish_elevated_restores(
        self, entries: list[Entry], result: RevertResult, remaining: list[Entry]
    ) -> tuple[RevertResult, list[Entry]]:
        """Restoring only queued the admin entries, so they count once this has run."""
        try:
            self._system.machine.run_elevated()
        except OSError as exc:
            if not isinstance(exc, ElevationDeclinedError):
                logger.exception("elevated restore failed")
            queued = [e for e in entries if is_elevated(e.kind) and e not in remaining]
            result.restored -= len(queued)
            declined = isinstance(exc, ElevationDeclinedError)
            result.pending.append(DECLINED_REVERT if declined else f"admin changes: {exc}")
            remaining = [e for e in entries if e in remaining or e in queued]
        return result, remaining

    def _run_refreshes(self, kinds: set[str], restored: list[Entry] | None = None) -> list[str]:
        warnings = []
        for refresh in _refreshes(kinds):
            logger.info("refreshing %s", refresh.value)
            try:
                self._system.refresh(refresh)
            except OSError as exc:
                # The setting itself is saved, so it still lands at the next sign-in.
                logger.exception("refresh %s failed", refresh)
                warnings.append(f"{refresh.value} needs a sign-out to take effect: {exc}")
            self._put_back(restored or [])
        return warnings

    def _put_back(self, restored: list[Entry]) -> None:
        """Restore again whatever Windows changed back while refreshing.

        Each refresh then starts from what the journal restored. Live, Windows turned
        Spotlight off between the wallpaper and the Explorer restart, which then kept it off.
        """
        for entry in reversed(restored):
            try:
                if drifted(self._system, entry.kind, entry.target, entry.before):
                    logger.info("Windows changed %s back; restoring it again", entry.target)
                    restore_entry(self._system, entry.kind, entry.target, entry.before)
            except RESTORE_ERRORS:
                logger.exception("could not restore %s again", entry.target)

    def _remove_generated_files(self) -> None:
        for folder in (
            self._paths.assets,
            self._paths.machine_assets,
            self._paths.components,
            self._paths.backups,
        ):
            shutil.rmtree(folder, ignore_errors=True)
        if self._paths.machine_root is not None:
            # Fails if anything else is in there, which is then not ours to remove.
            with contextlib.suppress(OSError):
                self._paths.machine_root.rmdir()
