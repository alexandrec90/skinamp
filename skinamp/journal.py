"""The undo journal: the single durable record of what Skinamp changed.

Written *before* the first mutation. A power cut halfway through an apply therefore
leaves a journal that restores every entry, and restoring one that was never applied is
a harmless no-op, so no per-entry bookkeeping is needed.

The format is a compatibility promise: an auto-update can land between apply and revert,
so every later release has to read what this one wrote.
"""

import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from skinamp.effects import JsonObject
from skinamp.fsutil import LockHeldError, atomic_write, exclusive_lock

SCHEMA_VERSION = 1
LOCK_FILE = "journal.lock"

State = Literal["applying", "applied", "reverting"]


class JournalError(Exception):
    """The journal exists but cannot be read. It is kept: it may be the only way back."""


class JournalBusyError(JournalError):
    """Another Skinamp is changing the theme, and so the journal, right now."""


@dataclass(frozen=True)
class Entry:
    kind: str
    target: JsonObject
    before: JsonObject
    refresh: str | None = None


@dataclass
class Journal:
    theme: str
    components: list[str]
    entries: list[Entry]
    state: State = "applying"
    app_version: str = ""
    created: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def _parse_entry(raw: JsonObject) -> Entry:
    return Entry(
        kind=cast(str, raw["kind"]),
        target=cast(JsonObject, raw["target"]),
        before=cast(JsonObject, raw["before"]),
        refresh=cast(str | None, raw["refresh"]),
    )


def _parse(raw: JsonObject) -> Journal:
    return Journal(
        theme=cast(str, raw["theme"]),
        components=cast(list[str], raw["components"]),
        entries=[_parse_entry(item) for item in cast(list[JsonObject], raw["entries"])],
        state=cast(State, raw["state"]),
        app_version=cast(str, raw["app_version"]),
        created=cast(str, raw["created"]),
    )


@dataclass(frozen=True)
class JournalStore:
    path: Path

    def exists(self) -> bool:
        return self.path.exists()

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Keep every other process from changing the journal until the block ends.

        Two copies applying or undoing at once would each act on what the other half wrote.
        """
        with ExitStack() as held:
            try:
                held.enter_context(exclusive_lock(self.path.with_name(LOCK_FILE)))
            except LockHeldError as exc:
                raise JournalBusyError(
                    "Another copy of Skinamp is changing your theme. Try again once it has finished."
                ) from exc
            yield

    def load(self) -> Journal | None:
        if not self.path.exists():
            return None
        try:
            raw = cast(JsonObject, json.loads(self.path.read_text(encoding="utf-8")))
            schema = raw["schema"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise JournalError(f"Cannot read {self.path}: {exc}") from exc
        if schema != SCHEMA_VERSION:
            raise JournalError(
                f"{self.path} has schema {schema}, this build reads {SCHEMA_VERSION}"
            )
        try:
            return _parse(raw)
        except (KeyError, TypeError) as exc:
            raise JournalError(f"Cannot read {self.path}: {exc}") from exc

    def save(self, journal: Journal) -> None:
        document = {"schema": SCHEMA_VERSION, **asdict(journal)}
        atomic_write(self.path, json.dumps(document, indent=1).encode("utf-8"))

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
