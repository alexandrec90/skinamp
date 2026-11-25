import copy
import json
from pathlib import Path

import pytest

from skinamp.effects import (
    SetJsonPref,
    SetMachineRegistry,
    SetMachineShortcutIcon,
    SetParam,
    SetRegistry,
)
from skinamp.elevated import SHELL_ICONS_KEY
from skinamp.engine import (
    ApplyFailedError,
    ApplyResult,
    Engine,
    PlanItem,
    RevertIncompleteError,
    RevertResult,
    Skipped,
    Status,
)
from skinamp.journal import Entry, JournalBusyError, JournalStore
from skinamp.paths import AppPaths
from skinamp.system.api import Refresh, RegValue
from skinamp.themes.model import Component, Theme

KEY = r"Control Panel\Colors"


def registry_component(component_id="one", *names):
    def effects(_context):
        return [
            SetRegistry(KEY, name, RegValue("sz", "new"), Refresh.COLORS)
            for name in names or ("A", "B")
        ]

    return Component(component_id, component_id, "", effects)


def make_theme(*components):
    return Theme("t", "T", "", components or (registry_component(),))


@pytest.fixture
def engine(system, paths):
    return Engine(system, paths)


def snapshot(system):
    return copy.deepcopy((system.registry, system.keys, system.params, system.shortcuts))


def test_starts_on_the_default_state(engine):
    assert engine.status() == Status(None, "default", [], 0)


def test_plan_changes_nothing(engine, system, paths):
    before = snapshot(system)
    items = engine.plan(make_theme())
    assert items == [
        PlanItem("one", f"HKCU\\{KEY} [A]"),
        PlanItem("one", f"HKCU\\{KEY} [B]"),
    ]
    assert snapshot(system) == before
    assert not paths.journal.exists()


def test_plan_does_not_prepare(engine):
    def explode(_context):
        raise AssertionError("plan must not prepare")

    component = Component("one", "", "", lambda _context: [], explode)
    assert engine.plan(make_theme(component)) == []


def test_apply_then_revert_returns_the_machine_to_exactly_where_it_was(engine, system, paths):
    system.reg_write(KEY, "A", RegValue("sz", "mine"))
    before = snapshot(system)
    result = engine.apply(make_theme())
    assert result.changes == 2
    assert system.reg_read(KEY, "A") == RegValue("sz", "new")
    assert engine.status().state == "applied"
    undone = engine.revert()
    assert undone.complete and undone.restored == 2
    assert snapshot(system) == before
    assert not paths.journal.exists()
    assert engine.status().state == "default"


def test_a_second_copy_cannot_change_the_theme_while_another_is(engine, system, paths):
    engine.apply(make_theme())
    before = snapshot(system)
    with JournalStore(paths.journal).hold():
        with pytest.raises(JournalBusyError):
            engine.apply(make_theme(registry_component("two", "C")))
        with pytest.raises(JournalBusyError):
            engine.revert()
    assert snapshot(system) == before
    assert engine.revert().complete


def test_undo_puts_back_what_windows_changes_while_refreshing(engine, system):
    """Live, Windows turned Spotlight off between the wallpaper and the Explorer restart."""

    def effects(_context):
        return [
            SetRegistry(KEY, "Spotlight", RegValue("dword", 0), Refresh.WALLPAPER),
            SetRegistry(KEY, "Other", RegValue("sz", "new"), Refresh.SHELL),
        ]

    system.reg_write(KEY, "Spotlight", RegValue("dword", 1))
    engine.apply(make_theme(Component("one", "", "", effects)))
    seen_by_shell = []
    plain_refresh = system.refresh

    def windows_meddles(what):
        plain_refresh(what)
        if what is Refresh.WALLPAPER:
            system.reg_write(KEY, "Spotlight", RegValue("dword", 0))
        if what is Refresh.SHELL:
            seen_by_shell.append(system.reg_read(KEY, "Spotlight"))

    system.refresh = windows_meddles
    assert engine.revert().complete
    assert seen_by_shell == [RegValue("dword", 1)], "the restart must see the restored value"
    assert system.reg_read(KEY, "Spotlight") == RegValue("dword", 1)


def test_refreshes_run_once_each_in_both_directions(engine, system):
    engine.apply(make_theme())
    assert system.refreshed == [Refresh.COLORS]
    engine.revert()
    assert system.refreshed == [Refresh.COLORS, Refresh.COLORS]


def test_refreshes_run_in_declared_order(engine, system):
    def effects(_context):
        return [
            SetRegistry(KEY, "A", RegValue("sz", ""), Refresh.TASKBAR),
            SetRegistry(KEY, "B", RegValue("sz", ""), Refresh.COLORS),
        ]

    engine.apply(make_theme(Component("one", "", "", effects)))
    assert system.refreshed == [Refresh.COLORS, Refresh.TASKBAR]


def test_journal_is_on_disk_before_the_first_mutation(engine, system, paths):
    seen = []
    original = system.reg_write

    def spying_write(key, name, value):
        seen.append(paths.journal.exists())
        original(key, name, value)

    system.reg_write = spying_write
    engine.apply(make_theme())
    assert seen == [True, True]


def test_failure_mid_apply_rolls_everything_back(engine, system):
    system.reg_write(KEY, "A", RegValue("sz", "mine"))
    system.fail_writes_to = {"B"}
    with pytest.raises(ApplyFailedError) as failure:
        engine.apply(make_theme())
    assert failure.value.rollback.complete
    assert system.reg_read(KEY, "A") == RegValue("sz", "mine")
    assert engine.status().state == "default"


def test_failed_prepare_touches_nothing_and_leaves_no_journal(engine, system, paths):
    def explode(_context):
        raise OSError("download failed")

    def effects(_context):
        raise AssertionError("effects must not run after a failed prepare")

    with pytest.raises(ApplyFailedError, match="download failed") as failure:
        engine.apply(make_theme(Component("one", "", "", effects, explode)))
    assert failure.value.rollback == RevertResult()
    assert not paths.journal.exists()
    assert system.registry == {}


def test_failed_capture_touches_nothing(engine, system, paths):
    def effects(_context):
        return [
            SetRegistry(KEY, "A", RegValue("sz", "new")),
            SetJsonPref(paths.root / "missing", ("a",), 1, "x.exe"),
        ]

    with pytest.raises(ApplyFailedError):
        engine.apply(make_theme(Component("one", "", "", effects)))
    assert system.registry == {}
    assert not paths.journal.exists()


def test_crash_mid_apply_can_still_be_undone_by_a_new_process(engine, system, paths, monkeypatch):
    before = snapshot(system)
    theme = make_theme()
    system.fail_writes_to = {"B"}
    with monkeypatch.context() as patched:
        # Simulate a process dying: the rollback never happens.
        patched.setattr(Engine, "_revert", lambda self: RevertResult())
        with pytest.raises(ApplyFailedError):
            engine.apply(theme)
    fresh = Engine(system, paths)
    assert fresh.status().state == "applying"
    assert fresh.revert().complete
    assert snapshot(system) == before


def test_blocked_component_is_skipped_and_reported(engine, system):
    component = Component(
        "chrome",
        "",
        "",
        lambda _context: [SetParam("x", 0)],
        blocker=lambda _context: "Close Chrome",
    )
    result = engine.apply(make_theme(registry_component(), component))
    assert result == ApplyResult("t", ["one"], [Skipped("chrome", "Close Chrome")], 2, [])
    assert "x" not in system.params


def test_everything_blocked_opens_no_journal(engine, paths):
    component = Component("c", "", "", lambda _context: [], blocker=lambda _context: "no")
    result = engine.apply(make_theme(component))
    assert result.changes == 0
    assert not paths.journal.exists()


def test_selection_limits_what_applies(engine, system):
    theme = make_theme(registry_component("one", "A"), registry_component("two", "B"))
    engine.apply(theme, ["two"])
    assert system.reg_read(KEY, "A") is None
    assert system.reg_read(KEY, "B") == RegValue("sz", "new")
    assert engine.status().components == ["two"]


def test_unknown_component_is_refused_before_anything_changes(engine, system):
    with pytest.raises(ValueError, match="nope"):
        engine.apply(make_theme(), ["nope"])
    assert system.registry == {}


def test_reapply_keeps_the_original_baseline(engine, system):
    system.reg_write(KEY, "A", RegValue("sz", "mine"))
    theme = make_theme()
    engine.apply(theme)
    engine.apply(theme)
    engine.revert()
    assert system.reg_read(KEY, "A") == RegValue("sz", "mine")


def chrome_theme(prefs):
    def effects(_context):
        return [SetJsonPref(prefs, ("a",), 2, "chrome.exe")]

    return make_theme(registry_component("one", "A"), Component("chrome", "", "", effects))


def test_blocked_revert_finishes_what_it_can_and_can_be_retried(engine, system, paths, tmp_path):
    prefs = tmp_path / "Preferences"
    prefs.write_text(json.dumps({"a": 1}), encoding="utf-8")
    engine.apply(chrome_theme(prefs))
    system.running.add("chrome.exe")
    system.refuse_close.add("chrome.exe")

    partial = engine.revert()
    assert not partial.complete and partial.restored == 1
    assert partial.pending == ["Close chrome.exe first"]
    assert system.reg_read(KEY, "A") is None
    status = engine.status()
    assert (status.state, status.changes) == ("reverting", 1)

    system.running.clear()
    assert engine.revert().complete
    assert json.loads(prefs.read_text(encoding="utf-8")) == {"a": 1}
    assert not paths.journal.exists()


def test_new_theme_refuses_while_the_old_one_is_half_undone(engine, system, tmp_path):
    prefs = tmp_path / "Preferences"
    prefs.write_text(json.dumps({"a": 1}), encoding="utf-8")
    engine.apply(chrome_theme(prefs))
    system.running.add("chrome.exe")
    system.refuse_close.add("chrome.exe")
    with pytest.raises(RevertIncompleteError, match=r"Close chrome\.exe"):
        engine.apply(make_theme())


def test_unexpected_restore_error_keeps_that_entry_for_retry(engine, system):
    engine.apply(make_theme())
    system.fail_writes_to = set()
    original = system.reg_delete

    def failing_delete(key, name):
        if name == "A":
            raise OSError("registry locked")
        original(key, name)

    system.reg_delete = failing_delete
    result = engine.revert()
    assert result.restored == 1
    assert result.pending == ["registry: registry locked"]
    system.reg_delete = original
    assert engine.revert().complete


def test_undo_carries_on_past_a_journal_entry_it_cannot_read(engine, system, paths):
    engine.apply(make_theme())
    store = JournalStore(paths.journal)
    journal = store.load()
    journal.entries.insert(1, Entry("future_kind", {}, {}))
    store.save(journal)
    result = engine.revert()
    assert result.restored == 2
    assert "future_kind" in result.pending[0]
    assert system.reg_read(KEY, "A") is None
    assert system.reg_read(KEY, "B") is None


def test_failed_refresh_is_a_warning_not_a_failure(engine, system):
    system.fail_refresh = {Refresh.COLORS}
    result = engine.apply(make_theme())
    assert result.changes == 2
    assert "sign-out" in result.warnings[0]
    assert engine.status().state == "applied"


def test_journal_keeps_entries_in_apply_order_after_a_partial_revert(system, paths, tmp_path):
    engine = Engine(system, paths)
    first, second = tmp_path / "first", tmp_path / "second"
    for path in (first, second):
        path.write_text(json.dumps({"a": 1}), encoding="utf-8")

    def effects(_context):
        return [
            SetJsonPref(first, ("a",), 2, "chrome.exe"),
            SetJsonPref(second, ("a",), 2, "chrome.exe"),
        ]

    engine.apply(make_theme(Component("c", "", "", effects)))
    system.running.add("chrome.exe")
    system.refuse_close.add("chrome.exe")
    engine.revert()
    remaining = JournalStore(paths.journal).load().entries
    assert [entry.target["file"] for entry in remaining] == [str(first), str(second)]


def test_complete_revert_removes_generated_files(engine, paths):
    engine.apply(make_theme())
    paths.assets.mkdir(parents=True)
    paths.components.mkdir(parents=True)
    paths.backups.mkdir(parents=True)
    engine.revert()
    assert not paths.assets.exists()
    assert not paths.components.exists()
    assert not paths.backups.exists()


def test_partial_revert_keeps_the_backups_a_retry_needs(engine, system, paths, tmp_path):
    prefs = tmp_path / "Preferences"
    prefs.write_text(json.dumps({"a": 1}), encoding="utf-8")
    engine.apply(chrome_theme(prefs))
    paths.backups.mkdir(parents=True)
    system.running.add("chrome.exe")
    system.refuse_close.add("chrome.exe")
    engine.revert()
    assert paths.backups.exists()


def test_revert_with_nothing_applied_is_a_no_op(engine):
    assert engine.revert() == RevertResult()


def closing_component(prefs):
    def effects(_context):
        return [SetJsonPref(prefs, ("a",), 2, "chrome.exe")]

    return Component("chrome", "", "", effects, closes=("chrome.exe",))


@pytest.fixture
def prefs(tmp_path):
    path = tmp_path / "Preferences"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    return path


def test_apply_closes_a_running_app_and_reopens_it_with_its_session(engine, system, prefs):
    system.running.add("chrome.exe")
    result = engine.apply(make_theme(closing_component(prefs)))
    assert result.skipped == [] and result.changes == 1
    assert json.loads(prefs.read_text(encoding="utf-8")) == {"a": 2}
    assert system.closed == ["chrome.exe"]
    assert system.started == [(Path("apps/chrome.exe"), ("--restore-last-session",))]


def test_apply_leaves_a_closed_app_closed(engine, system, prefs):
    engine.apply(make_theme(closing_component(prefs)))
    assert system.closed == []
    assert system.started == []


def test_prefs_are_captured_after_the_app_saved_them_on_exit(engine, system, prefs):
    original = system.close_app

    def close_and_save(image_name):
        prefs.write_text(json.dumps({"a": "saved on exit"}), encoding="utf-8")
        return original(image_name)

    system.close_app = close_and_save
    system.running.add("chrome.exe")
    engine.apply(make_theme(closing_component(prefs)))
    engine.revert()
    assert json.loads(prefs.read_text(encoding="utf-8")) == {"a": "saved on exit"}


def test_an_app_that_will_not_close_skips_only_its_component(engine, system, prefs):
    system.running.add("chrome.exe")
    system.refuse_close.add("chrome.exe")
    result = engine.apply(make_theme(registry_component("one", "A"), closing_component(prefs)))
    assert result.applied == ["one"]
    assert result.skipped == [Skipped("chrome", "chrome.exe would not close")]
    assert json.loads(prefs.read_text(encoding="utf-8")) == {"a": 1}
    assert system.started == []


def test_nothing_is_closed_when_a_download_fails(engine, system, prefs):
    def explode(_context):
        raise OSError("download failed")

    system.running.add("chrome.exe")
    theme = make_theme(closing_component(prefs), Component("t", "", "", lambda _c: [], explode))
    with pytest.raises(ApplyFailedError):
        engine.apply(theme)
    assert system.closed == []


def test_a_failed_apply_still_reopens_what_it_closed(engine, system, prefs):
    system.running.add("chrome.exe")
    system.fail_writes_to = {"B"}
    with pytest.raises(ApplyFailedError):
        engine.apply(make_theme(closing_component(prefs), registry_component("one", "A", "B")))
    assert len(system.started) == 1


def test_a_failure_to_reopen_is_a_warning(engine, system, prefs):
    system.running.add("chrome.exe")
    system.fail_start = True
    result = engine.apply(make_theme(closing_component(prefs)))
    assert result.changes == 1
    assert "start it yourself" in result.warnings[0]


def test_undo_closes_a_running_app_and_reopens_it(engine, system, prefs):
    engine.apply(make_theme(closing_component(prefs)))
    system.running.add("chrome.exe")
    result = engine.revert()
    assert result.complete
    assert json.loads(prefs.read_text(encoding="utf-8")) == {"a": 1}
    assert system.closed == ["chrome.exe"]
    assert system.started == [(Path("apps/chrome.exe"), ("--restore-last-session",))]


def test_a_failure_to_reopen_after_undo_is_a_warning(engine, system, prefs):
    engine.apply(make_theme(closing_component(prefs)))
    system.running.add("chrome.exe")
    system.fail_start = True
    result = engine.revert()
    assert result.complete
    assert "start it yourself" in result.warnings[0]


def admin_component(component_id="admin"):
    def effects(_context):
        return [
            SetMachineRegistry(SHELL_ICONS_KEY, "3", RegValue("sz", "a.ico,0"), Refresh.ICONS),
            SetMachineRegistry(SHELL_ICONS_KEY, "4", RegValue("sz", "b.ico,0"), Refresh.ICONS),
        ]

    return Component(component_id, "", "", effects, needs_admin=True)


def machine_state(system):
    machine = system.machine
    return copy.deepcopy((machine.registry, machine.keys, machine.shortcuts))


def test_admin_changes_share_one_prompt_each_way(engine, system):
    before = machine_state(system)
    theme = make_theme(registry_component("one", "A"), admin_component())
    result = engine.apply(theme)
    assert result.changes == 3
    assert system.machine.reg_read(SHELL_ICONS_KEY, "3") == RegValue("sz", "a.ico,0")
    assert system.machine.admin_prompts == 1
    assert engine.revert().complete
    assert system.machine.admin_prompts == 2
    assert machine_state(system) == before


def test_no_admin_changes_means_no_prompt(engine, system):
    engine.apply(make_theme())
    engine.revert()
    assert system.machine.admin_prompts == 0


def test_declining_at_apply_skips_only_the_admin_parts(engine, system):
    system.machine.decline_elevation = True
    result = engine.apply(make_theme(registry_component("one", "A"), admin_component()))
    assert result.applied == ["one"]
    assert result.skipped == [
        Skipped("admin", "Windows' admin prompt was declined or not answered")
    ]
    assert result.changes == 1
    assert system.machine.registry == {}
    status = engine.status()
    assert (status.state, status.changes, status.components) == ("applied", 1, ["one"])


def test_declined_changes_never_prompt_on_undo(engine, system):
    system.machine.decline_elevation = True
    engine.apply(make_theme(registry_component("one", "A"), admin_component()))
    assert engine.revert().complete
    assert system.machine.admin_prompts == 1


def test_declining_when_everything_needs_admin_leaves_no_journal(engine, system, paths):
    system.machine.decline_elevation = True
    result = engine.apply(make_theme(admin_component()))
    assert result.changes == 0
    assert not paths.journal.exists()


def test_a_broken_helper_rolls_the_apply_back(engine, system):
    system.machine.fail_elevation = True
    with pytest.raises(ApplyFailedError, match="helper crashed"):
        engine.apply(make_theme(registry_component("one", "A"), admin_component()))
    assert system.reg_read(KEY, "A") is None


def test_declining_at_undo_keeps_the_admin_entries_for_a_retry(engine, system):
    before = machine_state(system)
    engine.apply(make_theme(registry_component("one", "A"), admin_component()))
    system.machine.decline_elevation = True

    partial = engine.revert()

    assert not partial.complete
    assert partial.restored == 1
    assert partial.pending == ["Say yes to Windows' admin prompt to finish undoing"]
    assert system.reg_read(KEY, "A") is None
    assert engine.status().changes == 2

    system.machine.decline_elevation = False
    assert engine.revert().complete
    assert machine_state(system) == before


def test_a_broken_helper_at_undo_says_so_and_keeps_the_entries(engine, system):
    engine.apply(make_theme(admin_component()))
    system.machine.fail_elevation = True
    partial = engine.revert()
    assert partial.pending == ["admin changes: the helper crashed"]
    assert engine.status().changes == 2


def test_an_all_users_shortcut_round_trips_behind_one_prompt(engine, system, tmp_path):
    link = tmp_path / "Shared.lnk"
    link.touch()
    system.machine.shortcuts[link] = "app.exe,0"

    def effects(_context):
        return [SetMachineShortcutIcon(link, "new.ico,0")]

    engine.apply(make_theme(Component("admin", "", "", effects, needs_admin=True)))
    assert system.machine.shortcuts[link] == "new.ico,0"
    assert engine.revert().complete
    assert system.machine.shortcuts[link] == "app.exe,0"


def test_complete_revert_removes_the_shared_icons(engine, paths):
    engine.apply(make_theme())
    paths.machine_assets.mkdir(parents=True)
    engine.revert()
    assert not paths.machine_assets.exists()


def test_complete_revert_leaves_no_empty_shared_folder(system, tmp_path):
    # Live finding: `%ProgramData%\SkinampData` stayed behind, empty.
    paths = AppPaths(tmp_path / "user", tmp_path / "shared")
    engine = Engine(system, paths)
    engine.apply(make_theme())
    paths.machine_assets.mkdir(parents=True)
    engine.revert()
    assert not (tmp_path / "shared").exists()


def test_a_shared_folder_holding_something_else_is_left_alone(system, tmp_path):
    paths = AppPaths(tmp_path / "user", tmp_path / "shared")
    engine = Engine(system, paths)
    engine.apply(make_theme())
    paths.machine_assets.mkdir(parents=True)
    (tmp_path / "shared" / "not-ours.txt").touch()
    engine.revert()
    assert (tmp_path / "shared" / "not-ours.txt").exists()


def test_unreadable_journal_is_reported_not_deleted(engine, paths):
    paths.journal.parent.mkdir(parents=True)
    paths.journal.write_text("{broken", encoding="utf-8")
    status = engine.status()
    assert status.state == "unreadable" and status.error
    assert paths.journal.exists()
