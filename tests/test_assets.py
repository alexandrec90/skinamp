from pathlib import Path

from PIL import Image

from skinamp.art.sprites import cursors
from skinamp.effects import (
    SetMachineRegistry,
    SetMachineShortcutIcon,
    SetRegistry,
    SetShortcutIcon,
)
from skinamp.elevated import SHELL_ICONS_KEY
from skinamp.system.api import Refresh
from skinamp.targets import assets


def test_write_cursor_scales_the_hotspot(tmp_path):
    path = tmp_path / "sub" / "Hand.cur"
    assets.write_cursor(cursors()["Hand"], path)
    data = path.read_bytes()
    assert data[2:6] == bytes((2, 0, 2, 0))
    assert int.from_bytes(data[10:12], "little") == 6
    assert int.from_bytes(data[26:28], "little") == 12


def test_write_cursors_writes_every_role(tmp_path):
    assets.write_cursors(tmp_path)
    assert {path.stem for path in tmp_path.glob("*.cur")} == set(cursors())


def test_cursor_effects_point_at_the_files(tmp_path):
    effects = assets.cursor_effects(tmp_path, "Scheme")
    by_name = {effect.name: effect for effect in effects}
    assert by_name["Arrow"].value.data == str(tmp_path / "Arrow.cur")
    assert by_name["Arrow"].refresh_on is Refresh.CURSORS
    assert by_name[""].value.data == "Scheme"
    assert by_name["Scheme Source"].value.data == 0


def test_write_icons(tmp_path):
    assets.write_icons({"folder": Image.new("RGBA", (32, 32), (1, 2, 3, 255))}, tmp_path)
    with Image.open(tmp_path / "folder.ico") as loaded:
        assert loaded.format == "ICO"


def test_desktop_icon_effects_cover_both_bin_states(tmp_path):
    effects = assets.desktop_icon_effects(tmp_path)
    values = {(e.key, e.name): e.value.data for e in effects}
    bin_key = f"{assets.CLSID_ROOT}\\{assets.RECYCLE_BIN_CLSID}\\DefaultIcon"
    assert values[(bin_key, "full")] == f"{tmp_path / 'bin_full.ico'},0"
    assert values[(bin_key, "empty")] == f"{tmp_path / 'bin_empty.ico'},0"
    assert all(isinstance(e, SetRegistry) and e.refresh_on is Refresh.ICONS for e in effects)


def test_shortcut_icon_path_is_stable_and_case_blind(tmp_path):
    first = assets.shortcut_icon_path(tmp_path, Path("C:/A/App.lnk"))
    assert first == assets.shortcut_icon_path(tmp_path, Path("C:/a/app.LNK"))
    assert first != assets.shortcut_icon_path(tmp_path, Path("C:/A/Other.lnk"))


def test_write_shortcut_icons_skips_what_it_cannot_read(system, tmp_path):
    good, broken = Path("good.lnk"), Path("broken.lnk")
    system.shortcuts = {good: "", broken: ""}
    assets.write_shortcut_icons(system, [good, broken], tmp_path)
    assert assets.shortcut_icon_path(tmp_path, good).exists()
    assert not assets.shortcut_icon_path(tmp_path, broken).exists()


def test_shortcut_effects_only_for_icons_that_exist(system, tmp_path):
    good, broken = Path("good.lnk"), Path("broken.lnk")
    system.shortcuts = {good: "", broken: ""}
    assets.write_shortcut_icons(system, [good, broken], tmp_path)
    assert assets.shortcut_effects(system, tmp_path, planning=False) == [
        SetShortcutIcon(good, f"{assets.shortcut_icon_path(tmp_path, good)},0")
    ]


def test_folder_icons_are_machine_wide(tmp_path):
    # Windows ignores `Shell Icons` under HKCU: found applying this to a real desktop.
    effects = assets.folder_icon_effects(tmp_path)
    assert all(isinstance(effect, SetMachineRegistry) for effect in effects)
    # Live finding: only Explorer windows pick these up. The desktop needs a new Explorer.
    assert all(effect.refresh_on is Refresh.SHELL for effect in effects)
    assert {(effect.key, effect.name) for effect in effects} == {
        (SHELL_ICONS_KEY, assets.SHELL_ICON_FOLDER),
        (SHELL_ICONS_KEY, assets.SHELL_ICON_FOLDER_OPEN),
    }


def test_machine_shortcut_effects_only_for_icons_that_exist(system, tmp_path):
    good, broken = Path("good.lnk"), Path("broken.lnk")
    system.machine.shortcuts = {good: "", broken: ""}
    assets.write_shortcut_icons(system, [good, broken], tmp_path)
    assert assets.machine_shortcut_effects(system, tmp_path, planning=False) == [
        SetMachineShortcutIcon(good, f"{assets.shortcut_icon_path(tmp_path, good)},0")
    ]


def test_machine_shortcut_effects_list_everything_when_planning(system, tmp_path):
    system.machine.shortcuts = {Path("a.lnk"): "", Path("b.lnk"): ""}
    assert len(assets.machine_shortcut_effects(system, tmp_path, planning=True)) == 2


def test_shortcut_effects_list_everything_when_planning(system, tmp_path):
    system.shortcuts = {Path("a.lnk"): "", Path("b.lnk"): ""}
    assert len(assets.shortcut_effects(system, tmp_path, planning=True)) == 2
