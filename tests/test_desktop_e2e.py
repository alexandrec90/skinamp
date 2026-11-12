"""The real desktop end to end: the local tier `scripts/e2e.py` runs.

The Linux gate runs everything above `System` against the fake, and the Windows job tests
`Win32System` one call at a time. Nothing else starts `python -m skinamp` as a user would
and lets it read this desktop through every Retro component, so nothing else can say the
shipped entry point still plans a theme on a real, signed-in Windows session.

**Read-only.** `plan` changes nothing (`CLAUDE.md`), and `LOCALAPPDATA` points into a
temporary folder, so even the log and the journal folder land there and the user's own
`SkinampData` is never touched. `PROGRAMDATA` is left alone: Windows resolves the
all-users Start Menu that `plan` reads through it, and `plan` writes nothing there.
`apply` and `revert` are never run here.

These need this workstation's desktop, which the Linux runner lacks and the Windows
runner has no signed-in user for, so they carry the `local` mark that `addopts`
deselects everywhere but that script.

**Nothing here skips** (`.claude/rules/local-e2e.md`): a machine that is not Windows fails
the test and says so.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from skinamp.themes import get_theme

pytestmark = pytest.mark.local

REPO_ROOT = Path(__file__).resolve().parent.parent
THEME_ID = "retro"
# The components that are registry and file reads on every Windows machine. The others
# depend on what is installed (Chrome) or present (shortcuts), so may plan nothing.
ALWAYS_PLANNED = ("colors", "desktop", "cursors", "fonts", "motion")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def skinamp(*args: str, data: Path) -> subprocess.CompletedProcess[str]:
    """`python -m skinamp <args>` with the user's data folder redirected under `data`."""
    if sys.platform != "win32":
        pytest.fail(f"the desktop tier needs a Windows desktop, not {sys.platform}")
    env = {**os.environ, "LOCALAPPDATA": str(data)}
    return subprocess.run(  # noqa: S603 - this interpreter running this checkout's package
        [sys.executable, "-m", "skinamp", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        creationflags=NO_WINDOW,
    )


def planned_components(stdout: str) -> set[str]:
    """The component column of `skinamp plan`'s output. Pure."""
    return {line.split(maxsplit=1)[0] for line in stdout.splitlines() if line.strip()}


def test_planned_components_reads_the_first_column() -> None:
    assert planned_components("colors     Set X\n\ndesktop    Set Y\ncolors  Z\n") == {
        "colors",
        "desktop",
    }


def test_plan_reads_this_desktop_through_every_component(tmp_path: Path) -> None:
    done = skinamp("plan", THEME_ID, data=tmp_path)
    assert done.returncode == 0, f"skinamp plan exited {done.returncode}:\n{done.stderr}"
    planned = planned_components(done.stdout)
    known = {component.id for component in get_theme(THEME_ID).components}
    assert planned <= known, f"plan named components the theme lacks: {planned - known}"
    missing = set(ALWAYS_PLANNED) - planned
    assert not missing, f"plan changed nothing for {sorted(missing)}:\n{done.stdout}"


def test_status_on_a_fresh_data_folder_says_nothing_is_applied(tmp_path: Path) -> None:
    done = skinamp("status", data=tmp_path)
    assert done.returncode == 0, f"skinamp status exited {done.returncode}:\n{done.stdout}"
    assert "no theme" in done.stdout
