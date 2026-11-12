import json
import shutil

import pytest

from skinamp.effects import (
    EFFECT_TYPES,
    BlockedError,
    Effect,
    KeepTaskbarMode,
    PreserveFile,
    PreserveRegistry,
    SetJsonPref,
    SetMachineRegistry,
    SetMachineShortcutIcon,
    SetParam,
    SetRegistry,
    SetShortcutIcon,
    UnknownEffectError,
    decode_value,
    drifted,
    encode_value,
    is_elevated,
    missing_keys,
    process_to_close,
    restore_entry,
)
from skinamp.system.api import TASKBAR_AUTOHIDE, Refresh, RegValue

KEY = r"Software\Skinamp\Sub"


def roundtrip(effect, system):
    """Apply and undo through plain JSON, as a journal written by another run would."""
    before = json.loads(json.dumps(effect.capture(system)))
    target = json.loads(json.dumps(effect.target()))
    effect.apply(system)
    restore_entry(system, effect.kind, target, before)


@pytest.mark.parametrize(
    "value",
    [
        RegValue("sz", "hello"),
        RegValue("expand_sz", r"%WINDIR%\x"),
        RegValue("dword", 7),
        RegValue("binary", b"\x00\xff"),
    ],
)
def test_registry_value_survives_json(value):
    assert decode_value(json.loads(json.dumps(encode_value(value)))) == value


def test_absent_value_encodes_as_none():
    assert encode_value(None) is None
    assert decode_value(None) is None


def test_missing_keys_lists_deepest_first(system):
    assert missing_keys(system, r"Software\A\B") == [r"Software\A\B", r"Software\A"]


def test_registry_restores_previous_value_and_type(system):
    system.reg_write(KEY, "Name", RegValue("expand_sz", "old"))
    roundtrip(SetRegistry(KEY, "Name", RegValue("sz", "new")), system)
    assert system.reg_read(KEY, "Name") == RegValue("expand_sz", "old")


def test_registry_removes_value_and_keys_it_created(system):
    roundtrip(SetRegistry(r"Software\New\Deep", "Name", RegValue("sz", "new")), system)
    assert system.reg_read(r"Software\New\Deep", "Name") is None
    assert not system.reg_key_exists(r"Software\New\Deep")
    assert not system.reg_key_exists(r"Software\New")
    assert system.reg_key_exists("Software")


def test_registry_keeps_a_created_key_something_else_now_uses(system):
    effect = SetRegistry(r"Software\New", "Name", RegValue("sz", "new"))
    before = effect.capture(system)
    effect.apply(system)
    system.reg_write(r"Software\New", "Other", RegValue("sz", "theirs"))
    effect.restore(system, effect.target(), before)
    assert system.reg_read(r"Software\New", "Other") == RegValue("sz", "theirs")


def test_registry_reports_its_refresh():
    assert (
        SetRegistry(KEY, "N", RegValue("sz", ""), Refresh.COLORS).refresh_kind() is Refresh.COLORS
    )


def test_param_restores_previous_value(system):
    system.params["drop_shadow"] = 1
    effect = SetParam("drop_shadow", 0)
    before = effect.capture(system)
    effect.apply(system)
    assert system.params["drop_shadow"] == 0
    restore_entry(system, effect.kind, effect.target(), before)
    assert system.params["drop_shadow"] == 1


def test_shortcut_icon_restores(system, tmp_path):
    link = tmp_path / "App.lnk"
    link.touch()
    system.shortcuts[link] = "app.exe,0"
    roundtrip(SetShortcutIcon(link, "ours.ico,0"), system)
    assert system.shortcuts[link] == "app.exe,0"


def test_shortcut_icon_leaves_one_an_app_rewrote_since(system, tmp_path):
    link = tmp_path / "App.lnk"
    link.touch()
    system.shortcuts[link] = "app.exe,0"
    effect = SetShortcutIcon(link, "ours.ico,0")
    before = effect.capture(system)
    effect.apply(system)
    system.shortcuts[link] = "app-v2.exe,0"
    effect.restore(system, effect.target(), before)
    assert system.shortcuts[link] == "app-v2.exe,0"


def test_shortcut_icon_ignores_a_deleted_shortcut(system, tmp_path):
    target = {"path": str(tmp_path / "gone.lnk"), "icon": "ours.ico,0"}
    restore_entry(system, "shortcut_icon", target, {"icon": ""})
    assert system.shortcuts == {}


def test_preserve_file_puts_back_a_file_that_vanished(system, tmp_path):
    original = tmp_path / "spotlight" / "image.jpg"
    original.parent.mkdir()
    original.write_bytes(b"picture")
    effect = PreserveFile(original, tmp_path / "backups" / "image.jpg")
    before = json.loads(json.dumps(effect.capture(system)))
    effect.apply(system)
    assert original.read_bytes() == b"picture"
    shutil.rmtree(original.parent)
    restore_entry(system, effect.kind, effect.target(), before)
    assert original.read_bytes() == b"picture"


def test_preserve_file_leaves_a_file_that_is_still_there(system, tmp_path):
    original = tmp_path / "image.jpg"
    original.write_bytes(b"picture")
    effect = PreserveFile(original, tmp_path / "backups" / "image.jpg")
    before = effect.capture(system)
    original.write_bytes(b"newer")
    restore_entry(system, effect.kind, effect.target(), before)
    assert original.read_bytes() == b"newer"


def test_preserve_file_reports_a_lost_backup(system, tmp_path):
    target = {"path": str(tmp_path / "gone.jpg"), "backup": str(tmp_path / "also-gone.jpg")}
    with pytest.raises(OSError, match=r"also-gone"):
        restore_entry(system, "preserve_file", target, {})


def write_prefs(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def read_prefs(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_json_pref_restores_only_its_own_key(system, tmp_path):
    prefs = tmp_path / "Preferences"
    write_prefs(prefs, {"browser": {"theme": {"user_color2": 1}}, "other": 1})
    effect = SetJsonPref(prefs, ("browser", "theme", "user_color2"), 2, "chrome.exe")
    before = effect.capture(system)
    effect.apply(system)
    assert read_prefs(prefs)["browser"]["theme"]["user_color2"] == 2
    data = read_prefs(prefs)
    data["other"] = "changed by chrome"
    write_prefs(prefs, data)
    effect.restore(system, effect.target(), before)
    assert read_prefs(prefs) == {
        "browser": {"theme": {"user_color2": 1}},
        "other": "changed by chrome",
    }


def test_json_pref_removes_a_key_that_was_absent(system, tmp_path):
    prefs = tmp_path / "Preferences"
    write_prefs(prefs, {"browser": {}})
    roundtrip(SetJsonPref(prefs, ("browser", "user_color2"), 2, "chrome.exe"), system)
    assert read_prefs(prefs) == {"browser": {}}


def test_json_pref_removes_parents_it_created(system, tmp_path):
    prefs = tmp_path / "Preferences"
    write_prefs(prefs, {"browser": {}})
    roundtrip(SetJsonPref(prefs, ("browser", "theme", "user_color2"), 2, "chrome.exe"), system)
    assert read_prefs(prefs) == {"browser": {}}


def test_json_pref_keeps_a_created_parent_that_gained_other_keys(system, tmp_path):
    prefs = tmp_path / "Preferences"
    write_prefs(prefs, {"browser": {}})
    effect = SetJsonPref(prefs, ("browser", "theme", "user_color2"), 2, "chrome.exe")
    before = effect.capture(system)
    effect.apply(system)
    data = read_prefs(prefs)
    data["browser"]["theme"]["follows_system_colors"] = False
    write_prefs(prefs, data)
    effect.restore(system, effect.target(), before)
    assert read_prefs(prefs) == {"browser": {"theme": {"follows_system_colors": False}}}


def test_json_pref_restores_a_value_that_was_explicitly_null(system, tmp_path):
    prefs = tmp_path / "Preferences"
    write_prefs(prefs, {"a": None})
    roundtrip(SetJsonPref(prefs, ("a",), 2, "chrome.exe"), system)
    assert read_prefs(prefs) == {"a": None}


def test_json_pref_refuses_while_the_guard_runs(system, tmp_path):
    prefs = tmp_path / "Preferences"
    write_prefs(prefs, {"a": 1})
    effect = SetJsonPref(prefs, ("a",), 2, "chrome.exe")
    before = effect.capture(system)
    system.running.add("chrome.exe")
    with pytest.raises(BlockedError):
        effect.apply(system)
    with pytest.raises(BlockedError):
        effect.restore(system, effect.target(), before)
    assert read_prefs(prefs) == {"a": 1}


def test_json_pref_restore_tolerates_a_deleted_profile(system, tmp_path):
    target = {"file": str(tmp_path / "gone"), "path": ["a"], "guard": "chrome.exe"}
    restore_entry(system, "json_pref", target, {"present": False, "value": None, "keep_depth": 0})


def test_json_pref_describes_its_key(tmp_path):
    effect = SetJsonPref(tmp_path / "Default" / "Preferences", ("a", "b"), 1, "chrome.exe")
    assert effect.describe() == "Default/Preferences [a.b]"


def test_describe_names_the_change(tmp_path):
    assert SetRegistry(KEY, "", RegValue("sz", "")).describe().endswith("[(Default)]")
    assert "drop_shadow" in SetParam("drop_shadow", 0).describe()
    assert "App.lnk" in SetShortcutIcon(tmp_path / "App.lnk", "x").describe()
    assert "a.jpg" in PreserveFile(tmp_path / "a.jpg", tmp_path / "b").describe()


def test_effect_is_abstract_and_every_kind_implements_it():
    with pytest.raises(TypeError):
        Effect()
    assert all(issubclass(effect, Effect) for effect in EFFECT_TYPES.values())


def test_unknown_kind_is_an_error_not_a_silent_skip(system):
    with pytest.raises(UnknownEffectError):
        restore_entry(system, "future_kind", {}, {})


def test_every_shipped_kind_stays_restorable():
    # A journal can outlive the release that wrote it. Removing a kind here strands every
    # user who has that theme applied when the update lands.
    assert set(EFFECT_TYPES) >= {
        "registry",
        "sysparam",
        "shortcut_icon",
        "preserve_file",
        "json_pref",
        "machine_registry",
        "machine_shortcut_icon",
        "preserve_registry",
        "taskbar_mode",
    }


def test_taskbar_mode_is_restored_only_once_the_replacement_has_stopped(system):
    # Live finding: RetroBar left the real taskbar on auto-hide when it exited, so setting
    # the mode any earlier would just be undone by that exit.
    system.params[TASKBAR_AUTOHIDE] = 0
    effect = KeepTaskbarMode()
    before = effect.capture(system)
    effect.apply(system)
    assert system.refreshed == [], "applying changes nothing"
    system.params[TASKBAR_AUTOHIDE] = 1
    original = system.set_param
    order = []
    system.set_param = lambda name, value: (order.extend(system.refreshed), original(name, value))
    restore_entry(system, effect.kind, effect.target(), json.loads(json.dumps(before)))
    assert order == [Refresh.TASKBAR]
    assert system.params[TASKBAR_AUTOHIDE] == 0
    assert "taskbar" in effect.describe()


def test_preserve_registry_changes_nothing_until_it_restores(system):
    system.reg_write("K", "Mask", RegValue("binary", b"\x9e\x1e"))
    effect = PreserveRegistry("K", "Mask")
    before = effect.capture(system)
    effect.apply(system)
    assert system.reg_read("K", "Mask").data == b"\x9e\x1e"
    system.reg_write("K", "Mask", RegValue("binary", b"\x90\x16"))
    restore_entry(system, effect.kind, effect.target(), json.loads(json.dumps(before)))
    assert system.reg_read("K", "Mask").data == b"\x9e\x1e"


def test_preserve_registry_removes_a_value_that_was_not_there(system):
    effect = PreserveRegistry("K", "Mask")
    before = effect.capture(system)
    system.reg_write("K", "Mask", RegValue("binary", b"\x90"))
    restore_entry(system, effect.kind, effect.target(), before)
    assert system.reg_read("K", "Mask") is None


@pytest.mark.parametrize(
    "effect",
    [SetRegistry(KEY, "Name", RegValue("sz", "new")), PreserveRegistry(KEY, "Name")],
)
@pytest.mark.parametrize("original", [RegValue("dword", 1), None])
def test_registry_entries_notice_windows_changing_them_after_undo(system, effect, original):
    if original is not None:
        system.reg_write(KEY, "Name", original)
    before = json.loads(json.dumps(effect.capture(system)))
    target = json.loads(json.dumps(effect.target()))
    effect.apply(system)
    restore_entry(system, effect.kind, target, before)
    assert not drifted(system, effect.kind, target, before)
    system.reg_write(KEY, "Name", RegValue("dword", 0))
    assert drifted(system, effect.kind, target, before)


def test_only_registry_entries_are_checked_for_drift(system):
    effect = SetParam("x", 0)
    before = effect.capture(system)
    effect.apply(system)
    assert not drifted(system, effect.kind, effect.target(), before)
    assert not drifted(system, "from_a_newer_version", {}, {})


def run_queued(system, effect, before):
    restore_entry(system, effect.kind, effect.target(), json.loads(json.dumps(before)))
    system.machine.run_elevated()


def test_machine_registry_restores_the_old_value(system):
    key = r"SOFTWARE\Microsoft\Windows\Icons"
    system.machine.keys.add(key)
    system.machine.registry[(key, "3")] = RegValue("sz", "theirs.ico,0")
    effect = SetMachineRegistry(key, "3", RegValue("sz", "ours.ico,0"))
    before = effect.capture(system)
    effect.apply(system)
    assert system.machine.reg_read(key, "3").data == "theirs.ico,0", "applying only queues"
    system.machine.run_elevated()
    assert system.machine.reg_read(key, "3").data == "ours.ico,0"
    run_queued(system, effect, before)
    assert system.machine.reg_read(key, "3").data == "theirs.ico,0"
    assert effect.describe() == f"HKLM\\{key} [3]"


def test_machine_registry_removes_a_key_it_created(system):
    key = r"SOFTWARE\Microsoft\Windows\New\Icons"
    effect = SetMachineRegistry(key, "3", RegValue("sz", "ours.ico,0"))
    before = effect.capture(system)
    effect.apply(system)
    system.machine.run_elevated()
    assert system.machine.key_exists(key)
    run_queued(system, effect, before)
    assert system.machine.reg_read(key, "3") is None
    assert not system.machine.key_exists(key)
    assert not system.machine.key_exists(r"SOFTWARE\Microsoft\Windows\New")


def test_machine_effects_are_marked_as_needing_admin():
    assert is_elevated("machine_registry")
    assert is_elevated("machine_shortcut_icon")
    assert not is_elevated("registry")
    assert not is_elevated("future_kind")


def test_machine_shortcut_leaves_one_rewritten_since(system, tmp_path):
    link = tmp_path / "Shared.lnk"
    link.touch()
    system.shortcuts[link] = "updated-by-the-app.exe,0"
    restore_entry(
        system,
        "machine_shortcut_icon",
        {"path": str(link), "icon": "ours.ico,0"},
        {"icon": "theirs.exe,0"},
    )
    assert system.machine.queued == []


def test_machine_shortcut_describes_itself(tmp_path):
    assert "all users" in SetMachineShortcutIcon(tmp_path / "A.lnk", "x,0").describe()


def test_only_a_guarded_pref_names_a_process_to_close(tmp_path):
    pref = SetJsonPref(tmp_path / "p", ("a",), 1, "chrome.exe")
    assert process_to_close(pref.kind, pref.target()) == "chrome.exe"
    registry = SetRegistry("K", "N", RegValue("sz", "x"))
    assert process_to_close(registry.kind, registry.target()) is None
    assert process_to_close("future_kind", {}) is None
