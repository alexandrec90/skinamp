"""Chrome's colours, set in each profile's `Preferences` file.

The routes that sound more direct are closed. `--load-extension` is gone from branded
Chrome; "Load unpacked" is a manual step Skinamp could never undo; a policy puts Chrome
under "managed by your organization". Editing `Preferences` needs none of that, and
`browser.theme` is not one of the MAC-protected prefs. The price is that Chrome rewrites
the file on exit, so it has to be closed first; the engine closes and reopens it.

`is_grayscale2` is Chrome's own "Grey" option. A grey `user_color2` looks like the obvious
route, but Chrome tints whatever seed colour it gets: silver comes out pale teal.

A theme extension outranks all of this, so its id is cleared too, and restored on revert.
"""

import os
from pathlib import Path

from skinamp.effects import Effect, SetJsonPref

PROCESS = "chrome.exe"
SKIPPED_PROFILES = {"System Profile", "Guest Profile"}


def user_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"


def profiles(user_data: Path) -> list[Path]:
    return [
        path
        for path in sorted(user_data.glob("*/Preferences"))
        if path.parent.name not in SKIPPED_PROFILES
    ]


def effects(user_data: Path) -> list[Effect]:
    settings: list[tuple[tuple[str, ...], str | bool]] = [
        (("extensions", "theme", "id"), ""),
        (("browser", "theme", "is_grayscale2"), True),
    ]
    return [
        SetJsonPref(preferences, path, value, PROCESS)
        for preferences in profiles(user_data)
        for path, value in settings
    ]
