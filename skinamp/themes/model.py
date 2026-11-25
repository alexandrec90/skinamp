"""What a theme is: named components, each compiling to a list of effects."""

from collections.abc import Callable
from dataclasses import dataclass, field

from PIL import Image

from skinamp.effects import Effect
from skinamp.paths import AppPaths
from skinamp.system.api import System


@dataclass(frozen=True)
class BuildContext:
    system: System
    paths: AppPaths
    planning: bool = False
    """True for a dry run: `prepare` has not run, so generated files do not exist yet."""


def _nothing_to_prepare(_context: BuildContext) -> None:
    return None


def _never_blocked(_context: BuildContext) -> str | None:
    return None


@dataclass(frozen=True)
class Component:
    """One user-selectable part of a theme.

    `effects` must not touch the machine, because `plan` calls it. Anything that writes
    or downloads belongs in `prepare`, which runs before the journal is opened, so a
    failed download leaves nothing to undo.
    """

    id: str
    title: str
    description: str
    effects: Callable[[BuildContext], list[Effect]]
    prepare: Callable[[BuildContext], None] = _nothing_to_prepare
    blocker: Callable[[BuildContext], str | None] = _never_blocked
    closes: tuple[str, ...] = ()
    """Processes to close while this applies, and reopen after."""
    needs_admin: bool = False
    """Shown to the user up front, because applying this brings up a UAC prompt."""


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    description: str
    components: tuple[Component, ...]
    preview: Callable[[], dict[str, Image.Image]] = field(default=dict)

    def select(self, ids: list[str] | None) -> list[Component]:
        if ids is None:
            return list(self.components)
        known = {component.id for component in self.components}
        unknown = sorted(set(ids) - known)
        if unknown:
            raise ValueError(f"Theme {self.id!r} has no component {', '.join(unknown)}")
        return [component for component in self.components if component.id in ids]
