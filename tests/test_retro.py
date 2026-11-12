"""The real Retro theme, end to end, against the fake system.

Only the taskbar's downloads are stubbed: everything else, including writing the real
cursors and icons, runs for real into a temp folder.
"""

import copy
import json
import shutil
from pathlib import Path

import pytest

from skinamp.effects import SetParam
from skinamp.elevated import SHELL_ICONS_KEY
from skinamp.engine import Engine
from skinamp.system.api import TASKBAR_AUTOHIDE, Refresh, RegValue
from skinamp.targets import appearance, retrobar
from skinamp.themes import THEMES, get_theme, retro
from skinamp.themes.model import BuildContext

COMPONENTS = {
    "colors",
    "desktop",
    "cursors",
    "fonts",
    "motion",
    "icons",
    "system_icons",
    "taskbar",
    "chrome",
}


@pytest.fixture
def desktop(system, monkeypatch, tmp_path):
    """A plausible user: their own settings, two shortcuts, one Chrome profile."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(retrobar, "prepare", lambda _paths: None)
    monkeypatch.setattr(retrobar, "unsupported_reason", lambda: None)
    profile = tmp_path / "appdata" / "Google" / "Chrome" / "User Data" / "Default"
    profile.mkdir(parents=True)
    (profile / "Preferences").write_text(
        json.dumps({"extensions": {"theme": {"id": "their-theme"}}, "browser": {}}),
        encoding="utf-8",
    )
    for effect in appearance.no_animation_effects():
        if isinstance(effect, SetParam):
            system.params[effect.name] = 1
    system.params["font_smoothing"] = 1
    system.params[TASKBAR_AUTOHIDE] = 0
    system.reg_write(r"Control Panel\Desktop", "Wallpaper", RegValue("sz", r"C:\mine.jpg"))
    system.reg_write(
        r"Control Panel\Cursors", "Arrow", RegValue("expand_sz", r"%SystemRoot%\a.cur")
    )
    for name in ("Notes.lnk", "Game.lnk"):
        link = tmp_path / name
        link.touch()
        system.shortcuts[link] = f"{name}.exe,0"
    shared = tmp_path / "Shared.lnk"
    shared.touch()
    system.machine.shortcuts[shared] = "shared.exe,0"
    return system


def state_of(system):
    return copy.deepcopy(
        (
            system.registry,
            system.keys,
            system.params,
            system.shortcuts,
            system.machine.registry,
            system.machine.keys,
            system.machine.shortcuts,
        )
    )


def test_theme_is_registered():
    assert get_theme("retro") is retro.THEME
    assert set(THEMES) == {"retro"}


def test_unknown_theme_is_refused():
    with pytest.raises(ValueError, match="nope"):
        get_theme("nope")


def test_retro_offers_every_component():
    assert {component.id for component in retro.THEME.components} == COMPONENTS


def test_every_component_explains_itself():
    assert all(c.title and c.description for c in retro.THEME.components)


def test_desktop_images_cover_what_the_icon_effects_reference():
    assert set(retro.desktop_images()) >= {"computer", "bin_full"}
    assert set(retro.folder_images()) == {"folder", "folder_open"}


def test_only_what_needs_admin_says_so():
    assert [c.id for c in retro.THEME.components if c.needs_admin] == ["system_icons"]


def test_preview_is_images():
    assert all(image.size == (32, 32) for image in retro.preview().values())


def test_plan_writes_no_files(desktop, paths):
    Engine(desktop, paths).plan(retro.THEME)
    assert not paths.root.exists()


def test_full_apply_and_revert_is_a_perfect_round_trip(desktop, paths, tmp_path):
    prefs = tmp_path / "appdata" / "Google" / "Chrome" / "User Data" / "Default" / "Preferences"
    original_prefs = prefs.read_text(encoding="utf-8")
    before = state_of(desktop)
    engine = Engine(desktop, paths)

    result = engine.apply(retro.THEME)

    assert set(result.applied) == COMPONENTS
    assert result.skipped == []
    assert desktop.reg_read(r"Control Panel\Desktop", "Wallpaper").data == ""
    assert "Arrow.cur" in str(desktop.reg_read(r"Control Panel\Cursors", "Arrow").data)
    every_icon = [*desktop.shortcuts.values(), *desktop.machine.shortcuts.values()]
    assert all(icon.endswith(".ico,0") for icon in every_icon)
    for icon in every_icon:
        assert Path(icon.rsplit(",", 1)[0]).exists()
    folder_icon = desktop.machine.reg_read(SHELL_ICONS_KEY, "3").data
    assert Path(folder_icon.rsplit(",", 1)[0]).is_relative_to(paths.machine_assets)
    saved = json.loads(prefs.read_text(encoding="utf-8"))
    assert saved["extensions"]["theme"]["id"] == ""
    assert saved["browser"]["theme"]["is_grayscale2"] is True

    undone = engine.revert()

    assert undone.complete
    assert state_of(desktop) == before
    assert json.loads(prefs.read_text(encoding="utf-8")) == json.loads(original_prefs)
    assert not paths.assets.exists()
    assert not paths.machine_assets.exists()


def test_undo_restores_the_animation_bits_a_remote_session_hides(desktop, paths):
    # Live finding: over RDP Windows reports animations as off, so the parameters capture 0,
    # and restoring that 0 clears bits the registry value still held.
    mask = RegValue("binary", bytes.fromhex("9e1e078012000000"))
    desktop.reg_write(appearance.DESKTOP_KEY, appearance.PREFERENCES_MASK, mask)
    for effect in appearance.no_animation_effects():
        if isinstance(effect, SetParam):
            desktop.params[effect.name] = 0
    original_set = desktop.set_param

    def set_and_clobber_the_mask(name, value):
        original_set(name, value)
        cleared = RegValue("binary", bytes.fromhex("9016078010000000"))
        desktop.reg_write(appearance.DESKTOP_KEY, appearance.PREFERENCES_MASK, cleared)

    desktop.set_param = set_and_clobber_the_mask
    engine = Engine(desktop, paths)
    engine.apply(retro.THEME, ["motion"])
    assert engine.revert().complete
    assert desktop.reg_read(appearance.DESKTOP_KEY, appearance.PREFERENCES_MASK) == mask


def test_spotlight_user_gets_their_vanished_picture_and_rotation_back(desktop, paths, tmp_path):
    picture = tmp_path / "IrisService" / "photo.jpg"
    picture.parent.mkdir()
    picture.write_bytes(b"spotlight photo")
    desktop.reg_write(appearance.DESKTOP_KEY, "Wallpaper", RegValue("sz", str(picture)))
    desktop.reg_write(appearance.SPOTLIGHT_KEY, appearance.SPOTLIGHT_VALUE, RegValue("dword", 1))
    engine = Engine(desktop, paths)

    engine.apply(retro.THEME, ["desktop"])
    assert desktop.reg_read(appearance.SPOTLIGHT_KEY, appearance.SPOTLIGHT_VALUE).data == 0
    shutil.rmtree(picture.parent)  # Spotlight rotated while the theme was on.

    assert engine.revert().complete
    assert picture.read_bytes() == b"spotlight photo"
    assert desktop.reg_read(appearance.SPOTLIGHT_KEY, appearance.SPOTLIGHT_VALUE).data == 1
    assert desktop.reg_read(appearance.DESKTOP_KEY, "Wallpaper").data == str(picture)
    assert Refresh.WALLPAPER in desktop.refreshed


def test_undo_keeps_the_taskbar_mode_past_the_replacement_exiting(desktop, paths):
    # Undo runs in reverse, so the mode must be listed before the entry that runs RetroBar.
    effects = retrobar.effects()
    kinds = [effect.kind for effect in effects]
    assert kinds.index("taskbar_mode") < kinds.index("registry")
    engine = Engine(desktop, paths)
    engine.apply(retro.THEME, ["taskbar"])
    desktop.params[TASKBAR_AUTOHIDE] = 1  # RetroBar turned it on and did not turn it off.
    assert engine.revert().complete
    assert desktop.params[TASKBAR_AUTOHIDE] == 0


def test_a_running_chrome_is_closed_and_reopened(desktop, paths):
    desktop.running.add("chrome.exe")
    result = Engine(desktop, paths).apply(retro.THEME)
    assert "chrome" in result.applied
    assert desktop.closed == ["chrome.exe"]
    assert [arguments for _exe, arguments in desktop.started] == [("--restore-last-session",)]


def test_a_chrome_that_will_not_close_is_skipped_and_the_rest_applies(desktop, paths):
    desktop.running.add("chrome.exe")
    desktop.refuse_close.add("chrome.exe")
    result = Engine(desktop, paths).apply(retro.THEME)
    assert "chrome" not in result.applied
    assert [item.component for item in result.skipped] == ["chrome"]


def test_declining_the_admin_prompt_keeps_the_rest_of_the_theme(desktop, paths):
    desktop.machine.decline_elevation = True
    result = Engine(desktop, paths).apply(retro.THEME)
    assert "system_icons" not in result.applied
    assert [item.component for item in result.skipped] == ["system_icons"]
    assert desktop.machine.registry == {}
    assert "colors" in result.applied


def test_undo_restores_the_recent_wallpaper_list_windows_rewrites_at_apply(desktop, paths):
    # Measured live: under a second after Spotlight turns off, Windows pushes the old
    # picture onto this list, before any refresh has run. So it must be in the journal.
    desktop.reg_write(appearance.WALLPAPERS_KEY, "BackgroundHistoryPath0", RegValue("sz", "a.jpg"))
    desktop.reg_write(appearance.WALLPAPERS_KEY, "BackgroundHistoryPath1", RegValue("sz", "b.jpg"))
    engine = Engine(desktop, paths)
    engine.apply(retro.THEME, ["desktop"])
    desktop.reg_write(
        appearance.WALLPAPERS_KEY, "BackgroundHistoryPath0", RegValue("sz", "spotlight.jpg")
    )
    desktop.reg_write(appearance.WALLPAPERS_KEY, "BackgroundHistoryPath1", RegValue("sz", "a.jpg"))
    assert engine.revert().complete
    assert desktop.reg_read(appearance.WALLPAPERS_KEY, "BackgroundHistoryPath0").data == "a.jpg"
    assert desktop.reg_read(appearance.WALLPAPERS_KEY, "BackgroundHistoryPath1").data == "b.jpg"


def test_chrome_is_skipped_when_it_has_no_profile(system, paths, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    context = BuildContext(system, paths)
    [chrome_component] = retro.THEME.select(["chrome"])
    assert chrome_component.blocker(context) == "Chrome has no profile on this PC"


def test_taskbar_blocker_reports_an_unsupported_machine(system, paths, monkeypatch):
    monkeypatch.setattr(retrobar, "unsupported_reason", lambda: "needs x64")
    [taskbar_component] = retro.THEME.select(["taskbar"])
    assert taskbar_component.blocker(BuildContext(system, paths)) == "needs x64"
