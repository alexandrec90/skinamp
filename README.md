# Skinamp

Theme Windows and your apps from one window, and undo all of it with one button.

The first theme is **Retro**: grey bevels, navy title bars, a teal desktop, pixel-art
cursors and chunky icons.

## Using it

Run `Skinamp.exe`, tick what you want changed, and press **Apply theme**.
**Undo everything** puts your desktop back exactly as it was, at any time.

If the window ever will not open, the same undo works from a terminal:

```powershell
& "$env:LOCALAPPDATA\Skinamp\current\Skinamp.exe" revert
```

Uninstalling also undoes the theme.

## What can be themed on Windows

Windows does not expose one theming switch. This is what is possible, and how far Retro
goes today:

| Part | How | Retro | Undo |
| --- | --- | --- | --- |
| Colours of classic controls | `Control Panel\Colors` | yes | automatic |
| Title bars, accent, light mode | DWM and accent settings | yes | automatic |
| Wallpaper | system setting | solid teal | automatic, Spotlight included |
| Mouse cursors | `Control Panel\Cursors` | full original set | automatic |
| System fonts, title bar and scrollbar sizes | window metrics | bitmap font, no ClearType | automatic |
| Animations and shadows | system settings | off | automatic |
| Desktop icons | per-user icon keys | original set | automatic |
| Icons of your own shortcuts | rewrites the `.lnk` | pixelated, 15 colours | automatic |
| Folder icons | `Shell Icons`, machine-wide | original set; admin prompt | automatic, admin prompt |
| Icons of all-users shortcuts | rewrites the `.lnk` | pixelated; admin prompt | automatic, admin prompt |
| Taskbar and Start button | [RetroBar](https://github.com/dremin/RetroBar), a third-party replacement | yes, about 95 MB download | automatic |
| Google Chrome | profile `Preferences` file | Chrome's grey | automatic |

**Chrome** closes the way it does at log-off, and reopens with all its windows. If it will
not close, that part is skipped rather than forced. Browsers that automation started with
their own `--user-data-dir` are left alone.

**Admin rights** are only needed for what every account shares, so the window says which
parts ask. Declining the prompt skips those parts and keeps the rest. Skinamp itself never
runs elevated: one small helper does, and it refuses anything outside the list in
`skinamp/elevated.py`.

**Explorer restarts** when folder icons change, on apply and on undo, because the desktop
only picks them up when Explorer starts. The taskbar blinks for a few seconds, Windows'
icon cache is rebuilt, and desktop icons stay where they were.

What stays out of reach without patching Windows:

- **The actual window chrome.** Windows only loads visual styles (`.msstyles`) that
  Microsoft signed. Third-party styles need a system file patcher that can break on any
  Windows update, so Skinamp does not ship one.
- **Inside modern apps.** Settings, Store and other WinUI apps draw themselves and ignore
  classic colours.
- **Icons of apps with no shortcut.** Store apps have no `.lnk` to rewrite.
- **Chrome's textured themes.** Installing one programmatically needs the Chrome Web
  Store, so that needs a published theme.

## How undo works

Every change is an `Effect`. Before the first thing changes, the original value of
everything about to change goes into a journal in `%LOCALAPPDATA%\SkinampData`. That
folder is deliberately not the install folder, which updates replace and uninstalling
deletes. A crash halfway through an apply still leaves a complete undo record, and a
change that cannot be undone yet (the admin prompt was declined) stays in the journal for a
retry.

## Development

```bash
uv sync --all-extras
uv run python -m skinamp                # the window
uv run python -m skinamp plan retro     # list every change, changing nothing
uv run python -m skinamp apply retro --only cursors,icons
uv run python -m skinamp revert
uv run python scripts/run-tests.py      # the tests for what you changed
uv run python scripts/build-release.py  # dist/Skinamp/Skinamp.exe
```

```text
skinamp/
  engine.py         apply and revert as a transaction
  effects.py        the reversible change types
  journal.py        the on-disk undo record
  elevated.py       the allow-list for the one admin helper
  system/           the boundary with Windows; win32.py and explorer.py touch it
  targets/          what a theme can change
  themes/           the themes themselves
  art/              pixel art and the .ico and .cur encoders
  gui/              the window: pywebview over plain HTML and JavaScript
  updater.py        automatic updates
```

To add a theme, add a module beside `themes/retro.py` and register it in
`themes/__init__.py`. To theme a new application, add a module under `targets/`.

## Releases and updates

Pushing a tag like `v1.2.3` runs `.github/workflows/release.yml`, which builds the
executable, packs it with [Velopack](https://velopack.io) and publishes a GitHub Release.
Installed copies check that release feed when opened, download a found update in the
background, and install it on exit.

The executable is not code-signed yet, so Windows SmartScreen warns on first run.

## Credits

Retro's taskbar is RetroBar by Dremin and contributors (Apache-2.0), downloaded on demand
and not bundled. The artwork is original and drawn in code.

## The vendored harness

`scripts/hooks/` and `.claude/rules/engineering.md` are vendored from
[devkit](https://github.com/alexandrec90/devkit): edit them upstream.
`.github/workflows/pr-gate.yml` runs lint, tests and the drift check on every PR. Keep
its title `PR Gate`, because the Dependabot auto-merge workflow waits on it by name.
