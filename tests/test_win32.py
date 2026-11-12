"""The real Windows backend.

Windows-only, and run by the gate's Windows job. Nothing here changes how the machine
looks: registry tests write under a private scratch key, everything else only reads.
"""

import json
import shutil
import threading
import time
from types import SimpleNamespace

import pytest

from skinamp import elevated
from skinamp.paths import AppPaths
from skinamp.system.api import (
    TASKBAR_AUTOHIDE,
    ElevationDeclinedError,
    Machine,
    Refresh,
    RegValue,
    System,
)
from tests.test_api import public_methods

win32 = pytest.importorskip("skinamp.system.win32", exc_type=ImportError)
explorer = pytest.importorskip("skinamp.system.explorer", exc_type=ImportError)

SCRATCH = r"Software\SkinampTests"
WALLPAPER_PARENTS = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer",
    r"Software\Microsoft\Windows\CurrentVersion",
    r"Software\Microsoft\Windows",
    r"Software\Microsoft",
    "Software",
)


@pytest.fixture
def native(tmp_path):
    system = win32.Win32System(AppPaths(tmp_path), key_prefix=SCRATCH)
    yield system
    root = win32.winreg.HKEY_CURRENT_USER
    for key in (rf"{SCRATCH}\K\Deep", rf"{SCRATCH}\K", SCRATCH):
        try:
            win32.winreg.DeleteKey(root, key)
        except FileNotFoundError:
            continue


@pytest.mark.parametrize(
    "value",
    [
        RegValue("sz", "text"),
        RegValue("expand_sz", r"%WINDIR%\x"),
        RegValue("dword", 0xFF800000),
        RegValue("binary", b"\x00\x01"),
    ],
)
def test_registry_values_round_trip(native, value):
    native.reg_write("K", "Name", value)
    assert native.reg_read("K", "Name") == value


def test_default_value_uses_the_empty_name(native):
    native.reg_write("K", "", RegValue("sz", "x"))
    assert native.reg_read("K", "") == RegValue("sz", "x")


def test_reading_and_deleting_what_is_absent_is_quiet(native):
    assert native.reg_read("Nope", "Name") is None
    native.reg_delete("Nope", "Name")
    native.reg_prune_key("Nope")


def test_key_exists_and_prune(native):
    native.reg_write(r"K\Deep", "Name", RegValue("sz", "x"))
    assert native.reg_key_exists(r"K\Deep")
    native.reg_prune_key(r"K\Deep")
    assert native.reg_key_exists(r"K\Deep"), "a key with values must survive"
    native.reg_delete(r"K\Deep", "Name")
    native.reg_prune_key("K")
    assert native.reg_key_exists("K"), "a key with subkeys must survive"
    native.reg_prune_key(r"K\Deep")
    assert not native.reg_key_exists(r"K\Deep")


@pytest.mark.parametrize("name", sorted(win32.PARAMS))
def test_every_system_parameter_can_be_read(native, name):
    assert native.get_param(name) in (0, 1, 2)


def test_reloading_cursors_succeeds(native):
    """Reloads what is already configured. SPIF_UPDATEINIFILE makes Windows refuse this."""
    native.refresh(Refresh.CURSORS)


def test_process_running(native):
    assert native.process_running("python.exe") or native.process_running("pytest.exe")
    assert not native.process_running("definitely-not-running.exe")


def test_dpi_is_plausible(native):
    assert native.dpi() >= 96


def test_struct_sizes_match_the_windows_abi():
    assert win32.ctypes.sizeof(win32.LOGFONTW) == 92
    assert win32.ctypes.sizeof(win32.NONCLIENTMETRICSW) == 504
    assert win32.ctypes.sizeof(win32.ANIMATIONINFO) == 8
    assert win32.ctypes.sizeof(win32.APPBARDATA) == 48


def test_win32_system_implements_the_whole_boundary():
    assert public_methods(System) <= public_methods(win32.Win32System)
    assert public_methods(Machine) <= public_methods(win32.Win32Machine)


@pytest.mark.parametrize(
    "error",
    [
        win32.pywintypes.error(5, "api", "denied"),
        win32.pywintypes.com_error(-1, "failed", None, None),
        win32.win32ui.error("failed"),
        win32.psutil.Error("failed"),
    ],
)
def test_native_failures_become_os_errors(error):
    def fail():
        raise error

    with pytest.raises(OSError, match=r".") as caught:
        win32.os_errors(fail)()
    assert caught.value.__cause__ is error


def test_os_errors_leaves_a_bug_alone():
    def bug():
        raise ZeroDivisionError

    with pytest.raises(ZeroDivisionError):
        win32.os_errors(bug)()


def test_show_native_taskbar_shows_each_tray_and_asks_apps_for_their_icons(monkeypatch):
    shown = []
    posted = []
    windows = {"Shell_TrayWnd": 11, "Shell_SecondaryTrayWnd": 0}
    monkeypatch.setattr(win32.win32gui, "FindWindow", lambda name, _title: windows[name])
    monkeypatch.setattr(
        win32.win32gui, "ShowWindow", lambda window, command: shown.append((window, command))
    )
    monkeypatch.setattr(win32.win32gui, "RegisterWindowMessage", lambda _name: 777)
    monkeypatch.setattr(
        win32.win32gui, "PostMessage", lambda window, message, *_rest: posted.append(message)
    )
    win32.show_native_taskbar()
    assert shown == [(11, win32.win32con.SW_SHOW)]
    assert posted == [777]


def session_replies(monkeypatch, replies):
    """Stub the log-off messages. A window missing from `replies` has already gone."""
    sent = []

    def send(window, message, *_rest):
        sent.append((window, message))
        if window not in replies:
            raise win32.pywintypes.error(1400, "SendMessageTimeout", "invalid window")
        return 1, replies[window]

    monkeypatch.setattr(win32.win32gui, "SendMessageTimeout", send)
    monkeypatch.setattr(win32, "windows_of", lambda _pids: [*replies, 99])
    return sent


def test_end_session_asks_every_window_then_tells_them(monkeypatch):
    sent = session_replies(monkeypatch, {1: 1, 2: 1})
    assert win32.end_session({10}) is True
    assert sent == [
        (1, win32.WM_QUERYENDSESSION),
        (2, win32.WM_QUERYENDSESSION),
        (99, win32.WM_QUERYENDSESSION),
        (1, win32.WM_ENDSESSION),
        (2, win32.WM_ENDSESSION),
        (99, win32.WM_ENDSESSION),
    ]


def test_end_session_stops_if_a_window_objects(monkeypatch):
    sent = session_replies(monkeypatch, {1: 0})
    assert win32.end_session({10}) is False
    assert (1, win32.WM_ENDSESSION) not in sent


def test_windows_of_finds_this_processs_windows_only():
    assert all(isinstance(window, int) for window in win32.windows_of({win32.os.getpid()}))
    assert win32.windows_of(set()) == []


class Closing:
    def __init__(self, pid):
        self.pid = pid
        self.terminated = False

    def exe(self):
        return r"C:\apps\chrome.exe"

    def terminate(self):
        self.terminated = True


def closing_app(monkeypatch, processes, *, agreed=True, alive=(), visible=()):
    monkeypatch.setattr(win32, "_processes_named", lambda _name: processes)
    monkeypatch.setattr(win32, "end_session", lambda _pids: agreed)
    monkeypatch.setattr(win32.psutil, "wait_procs", lambda _p, timeout: ([], list(alive)))
    monkeypatch.setattr(win32, "_visible_windows", lambda _pids: list(visible))


def test_close_app_returns_nothing_when_it_is_not_running(native, monkeypatch):
    closing_app(monkeypatch, [])
    assert native.close_app("chrome.exe") is None


def test_close_app_returns_the_executable_to_reopen(native, monkeypatch):
    closing_app(monkeypatch, [Closing(1)])
    assert native.close_app("chrome.exe") == win32.Path(r"C:\apps\chrome.exe")


def test_close_app_reports_an_app_that_objects(native, monkeypatch):
    closing_app(monkeypatch, [Closing(1)], agreed=False)
    with pytest.raises(OSError, match="would not close"):
        native.close_app("chrome.exe")


def test_close_app_never_kills_an_app_that_still_has_a_window(native, monkeypatch):
    process = Closing(1)
    closing_app(monkeypatch, [process], alive=[process], visible=[5])
    with pytest.raises(OSError, match="still open"):
        native.close_app("chrome.exe")
    assert not process.terminated


def test_close_app_ends_windowless_background_helpers(native, monkeypatch):
    process = Closing(1)
    closing_app(monkeypatch, [process], alive=[process])
    native.close_app("chrome.exe")
    assert process.terminated


def test_start_app_detaches(native, monkeypatch):
    calls = []
    monkeypatch.setattr(
        win32.subprocess, "Popen", lambda args, creationflags: calls.append((args, creationflags))
    )
    native.start_app(win32.Path(r"C:\apps\chrome.exe"), ("--flag",))
    assert calls == [([r"C:\apps\chrome.exe", "--flag"], win32.taskbar.DETACHED_PROCESS)]


def test_machine_reads_work_without_rights(native):
    key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    assert native.machine.key_exists(key)
    assert native.machine.reg_read(key, "ProductName") is not None
    assert native.machine.reg_read(key, "NoSuchValue") is None
    assert not native.machine.key_exists(r"SOFTWARE\SkinampDefinitelyAbsent")
    assert native.machine.reg_read(r"SOFTWARE\SkinampDefinitelyAbsent", "x") is None


def test_machine_writes_queue_until_run_elevated(native, monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(win32, "_run_as_admin", ran.append)
    link = tmp_path / "App.lnk"
    native.machine.reg_write(elevated.SHELL_ICONS_KEY, "3", RegValue("sz", "a.ico,0"))
    native.machine.reg_delete(elevated.SHELL_ICONS_KEY, "4")
    native.machine.reg_prune_key(elevated.SHELL_ICONS_KEY)
    native.machine.set_shortcut_icon(link, "a.ico,0")
    assert ran == []

    native.machine.run_elevated()

    assert [op["op"] for op in ran[0]] == [
        elevated.OP_REG_WRITE,
        elevated.OP_REG_DELETE,
        elevated.OP_REG_PRUNE,
        elevated.OP_SHORTCUT_ICON,
    ]
    native.machine.run_elevated()
    assert len(ran) == 1, "an empty queue must not prompt"


def test_run_elevated_empties_the_queue_even_if_declined(native, monkeypatch):
    def decline(_ops):
        raise ElevationDeclinedError("no")

    monkeypatch.setattr(win32, "_run_as_admin", decline)
    native.machine.reg_delete(elevated.SHELL_ICONS_KEY, "4")
    with pytest.raises(ElevationDeclinedError):
        native.machine.run_elevated()
    native.machine.run_elevated()


def test_declining_the_uac_prompt_is_recognised(monkeypatch):
    def cancelled(**_kwargs):
        raise win32.pywintypes.error(win32.ERROR_CANCELLED, "ShellExecuteEx", "cancelled")

    monkeypatch.setattr(win32.shell, "ShellExecuteEx", cancelled)
    with pytest.raises(ElevationDeclinedError):
        win32._launch_elevated("skinamp.exe", [])


def test_other_launch_failures_are_not_mistaken_for_declining(monkeypatch):
    def broken(**_kwargs):
        raise win32.pywintypes.error(2, "ShellExecuteEx", "not found")

    monkeypatch.setattr(win32.shell, "ShellExecuteEx", broken)
    with pytest.raises(win32.pywintypes.error) as failure:
        win32._launch_elevated("skinamp.exe", [])
    assert not isinstance(failure.value, ElevationDeclinedError)


def test_a_failed_helper_reports_what_it_wrote(monkeypatch):
    def fail_with_message(_program, arguments):
        request = win32.Path(arguments[-1])
        request.with_name(elevated.ERROR_FILE).write_text("key is locked", encoding="utf-8")
        return 1

    monkeypatch.setattr(win32, "_launch_elevated", fail_with_message)
    with pytest.raises(OSError, match="key is locked"):
        win32._run_as_admin([elevated.reg_prune(elevated.SHELL_ICONS_KEY)])


def test_a_helper_that_says_nothing_reports_its_exit_code(monkeypatch):
    monkeypatch.setattr(win32, "_launch_elevated", lambda _program, _arguments: 3)
    with pytest.raises(OSError, match="exit code 3"):
        win32._run_as_admin([elevated.reg_prune(elevated.SHELL_ICONS_KEY)])


@pytest.mark.parametrize("remote", [True, False])
def test_animation_reaches_the_session_only_on_the_console(native, monkeypatch, remote):
    """Over RDP Windows keeps animation off live; pushing the saved value overrides that."""
    calls = []
    monkeypatch.setattr(win32, "_spi", lambda action, *_args: calls.append(action))
    monkeypatch.setattr(win32, "_in_remote_session", lambda: remote)
    win32._refresh_animation(native)
    assert (win32.SPI_SETANIMATION in calls) is (not remote)


def test_in_remote_session_reads_windows():
    assert win32._in_remote_session() in {True, False}


def test_declining_reaches_the_caller_through_the_wait(monkeypatch):
    def decline(_program, _arguments):
        raise ElevationDeclinedError("no")

    monkeypatch.setattr(win32, "_launch_elevated", decline)
    with pytest.raises(ElevationDeclinedError, match="no"):
        win32._run_as_admin([elevated.reg_prune(elevated.SHELL_ICONS_KEY)])


def test_a_bug_in_the_prompt_thread_still_fails_the_admin_step(monkeypatch):
    def bug(_program, _arguments):
        raise RuntimeError("bug")

    monkeypatch.setattr(threading, "excepthook", lambda _args: None)
    monkeypatch.setattr(win32, "_launch_elevated", bug)
    with pytest.raises(OSError, match="without a result"):
        win32._run_as_admin([elevated.reg_prune(elevated.SHELL_ICONS_KEY)])


def test_an_unanswered_prompt_is_given_up_and_a_late_yes_does_nothing(monkeypatch):
    late_yes = threading.Event()
    helper_ran = []
    helper_done = threading.Event()

    def nobody_there(_program, arguments):
        late_yes.wait(5)
        try:
            elevated.claim(win32.Path(arguments[-1]))
            helper_ran.append(True)
        except OSError:
            helper_ran.append(False)
        helper_done.set()
        return 0

    monkeypatch.setattr(win32, "ADMIN_PROMPT_SECONDS", 0.05)
    monkeypatch.setattr(win32, "_launch_elevated", nobody_there)
    with pytest.raises(ElevationDeclinedError, match="answered"):
        win32._run_as_admin([elevated.reg_prune(elevated.SHELL_ICONS_KEY)])
    late_yes.set()
    assert helper_done.wait(5)
    assert helper_ran == [False]


def test_a_prompt_answered_just_in_time_is_waited_for(monkeypatch):
    def answered_at_the_deadline(_program, arguments):
        elevated.claim(win32.Path(arguments[-1]))
        time.sleep(0.3)
        return 0

    monkeypatch.setattr(win32, "ADMIN_PROMPT_SECONDS", 0.05)
    monkeypatch.setattr(win32, "_launch_elevated", answered_at_the_deadline)
    win32._run_as_admin([elevated.reg_prune(elevated.SHELL_ICONS_KEY)])


def test_execute_request_refuses_a_tampered_file_before_doing_anything(tmp_path):
    request = tmp_path / elevated.REQUEST_FILE
    ops = [elevated.reg_delete(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductName")]
    request.write_text(json.dumps(ops), encoding="utf-8")
    with pytest.raises(ValueError, match="Refusing"):
        win32.execute_request(request)


def test_machine_shortcut_roots_are_shared_folders():
    roots = win32.machine_shortcut_roots()
    assert len(roots) == 2
    assert all(root.is_absolute() for root in roots)


def test_list_machine_shortcuts_returns_only_links(native):
    assert all(path.suffix.lower() == ".lnk" for path in native.machine.list_shortcuts())


def test_what_windows_rewrites_late_after_a_wallpaper_change_is_put_back(native, monkeypatch):
    # Live finding: after a wallpaper change Windows pushes it onto Settings' recent list
    # and turns Spotlight off, asynchronously, so undo lost both to a race.
    history = (win32.WALLPAPERS_KEY, win32.WALLPAPER_HISTORY[0])
    spotlight = (win32.SPOTLIGHT_KEY, win32.SPOTLIGHT_VALUE)
    native.reg_write(*history, RegValue("sz", "mine.jpg"))
    native.reg_write(*spotlight, RegValue("dword", 1))

    waits = []

    def windows_catches_up(seconds):
        waits.append(seconds)
        native.reg_write(*history, RegValue("sz", "pushed.jpg"))
        native.reg_write(*spotlight, RegValue("dword", 0))

    monkeypatch.setattr(win32, "_spi", lambda *_args: None)
    monkeypatch.setattr(win32.time, "sleep", windows_catches_up)
    try:
        native.refresh(Refresh.WALLPAPER)
        assert waits, "the rewrite comes later, so a refresh has to wait for it"
        assert native.reg_read(*history).data == "mine.jpg"
        assert native.reg_read(*spotlight).data == 1
    finally:
        for key, name in (history, spotlight):
            native.reg_delete(key, name)
        for key in (
            win32.WALLPAPERS_KEY,
            win32.SPOTLIGHT_KEY,
            win32.SPOTLIGHT_PARENT,
            *WALLPAPER_PARENTS,
        ):
            native.reg_prune_key(key)


class Named:
    def __init__(self, pid, parent, cmdline):
        self.pid = pid
        self.parent = parent
        self.info = {"name": "chrome.exe", "cmdline": cmdline}

    def ppid(self):
        return self.parent


def test_an_automated_browser_is_not_the_users_chrome(monkeypatch):
    # Live finding: a scraper's Playwright Chromes share the image name. Matching by name
    # alone would close them, and block undo for as long as they ran.
    users = Named(1, 0, ["chrome.exe"])
    unreadable = Named(2, 0, None)
    automated = Named(3, 0, ["chrome.exe", r"--user-data-dir=C:\Temp\scraper"])
    its_helper = Named(4, 3, ["chrome.exe", "--type=crashpad-handler"])
    processes = [users, unreadable, automated, its_helper]
    monkeypatch.setattr(win32.psutil, "process_iter", lambda _attrs: processes)
    assert win32._processes_named("chrome.exe") == [users, unreadable]
    assert win32._processes_named("msedge.exe") == []


def test_restarting_explorer_keeps_spotlight_on(native, monkeypatch):
    # Live finding: a new Explorer turned Spotlight off, after undo had restored it.
    spotlight = (win32.SPOTLIGHT_KEY, win32.SPOTLIGHT_VALUE)
    native.reg_write(*spotlight, RegValue("dword", 1))

    def new_explorer_resets_it():
        native.reg_write(*spotlight, RegValue("dword", 0))

    monkeypatch.setattr(explorer, "restart_explorer", new_explorer_resets_it)
    monkeypatch.setattr(win32.time, "sleep", lambda _seconds: None)
    try:
        native.refresh(Refresh.SHELL)
        assert native.reg_read(*spotlight).data == 1
    finally:
        native.reg_delete(*spotlight)
        for key in (win32.SPOTLIGHT_KEY, win32.SPOTLIGHT_PARENT, *WALLPAPER_PARENTS):
            native.reg_prune_key(key)


class FakeRestartManager:
    def __init__(self, steps, shutdown_code=0, restart_code=0):
        self.steps = steps
        self.shutdown_code = shutdown_code
        self.restart_code = restart_code

    def RmStartSession(self, *_args):
        self.steps.append("start")
        return 0

    def RmRegisterResources(self, *_args):
        self.steps.append("register")
        return 0

    def RmShutdown(self, _session, flags, _progress):
        assert flags == explorer.GRACEFUL, "forcing it could lose someone's work"
        self.steps.append("shutdown")
        return self.shutdown_code

    def RmRestart(self, *_args):
        self.steps.append("restart")
        return self.restart_code

    def RmEndSession(self, _session):
        self.steps.append("end")
        return 0


@pytest.fixture
def shell(monkeypatch, tmp_path):
    """A stubbed Explorer. Set `shell.trays` to what each look for the taskbar finds."""
    state = SimpleNamespace(steps=[], trays=[7], started=[], cache=None)
    cache = tmp_path / "Microsoft" / "Windows" / "Explorer" / "iconcache_48.db"
    cache.parent.mkdir(parents=True)
    cache.touch()
    state.cache = cache
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(explorer, "rstrtmgr", FakeRestartManager(state.steps))
    monkeypatch.setattr(explorer, "desktop_icons", lambda: {"A": (1, 2)})
    monkeypatch.setattr(explorer, "sleep", lambda seconds: state.steps.append(f"wait {seconds}"))
    monkeypatch.setattr(
        explorer, "place_desktop_icons", lambda icons: state.steps.append(("place", icons))
    )
    real_clear = explorer.clear_icon_cache

    def clear():
        state.steps.append("clear")
        real_clear()

    monkeypatch.setattr(explorer, "clear_icon_cache", clear)
    monkeypatch.setattr(explorer.win32gui, "FindWindow", lambda _name, _title: state.trays.pop(0))
    monkeypatch.setattr(
        explorer.subprocess, "Popen", lambda args, creationflags: state.started.append(args)
    )
    return state


def test_restarting_explorer_clears_the_cache_only_while_it_is_down(shell):
    explorer.restart_explorer()
    assert shell.steps[:6] == ["start", "register", "shutdown", "clear", "restart", "end"]
    assert not shell.cache.exists()
    assert shell.started == [], "a second explorer.exe would only open a folder window"


def test_icons_go_back_only_once_explorer_has_settled(shell):
    explorer.restart_explorer()
    assert shell.steps[-2:] == [f"wait {explorer.SETTLE_SECONDS}", ("place", {"A": (1, 2)})]


def test_explorer_that_refuses_is_left_running_and_keeps_its_cache(monkeypatch, shell):
    monkeypatch.setattr(explorer, "rstrtmgr", FakeRestartManager(shell.steps, shutdown_code=1223))
    with pytest.raises(OSError, match="canceled"):
        explorer.restart_explorer()
    assert shell.steps == ["start", "register", "shutdown", "end"]
    assert shell.cache.exists()


def test_explorer_is_started_if_restart_manager_leaves_it_down(monkeypatch, shell):
    monkeypatch.setattr(explorer, "rstrtmgr", FakeRestartManager(shell.steps, restart_code=5))
    shell.trays = [*[0] * explorer.RETURN_CHECKS, 0, 7]
    explorer.restart_explorer()
    assert len(shell.started) == 1
    assert shell.started[0][0].lower().endswith("explorer.exe")


def test_an_explorer_that_never_returns_is_reported(shell):
    shell.trays = [0] * (explorer.RETURN_CHECKS + explorer.START_CHECKS)
    with pytest.raises(OSError, match="did not come back"):
        explorer.restart_explorer()


def test_clear_icon_cache_leaves_a_file_another_program_holds(monkeypatch, tmp_path):
    folder = tmp_path / "Microsoft" / "Windows" / "Explorer"
    folder.mkdir(parents=True)
    held = folder / "iconcache_32.db"
    held.touch()
    other = folder / "thumbcache_32.db"
    other.touch()

    def in_use(_path, missing_ok=False):
        raise PermissionError("in use")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(explorer.Path, "unlink", in_use)
    explorer.clear_icon_cache()
    assert held.exists() and other.exists()


def desktop_of(monkeypatch, items):
    sent = []
    monkeypatch.setattr(explorer, "desktop_list", lambda: 9)
    monkeypatch.setattr(explorer, "read_items", lambda _listview: items)
    monkeypatch.setattr(explorer, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        explorer.user32,
        "SendMessageW",
        lambda window, message, index, position: sent.append((window, message, index, position)),
        raising=False,
    )
    return sent


def test_placing_icons_moves_only_what_moved(monkeypatch):
    sent = desktop_of(monkeypatch, {"A": (0, 14, 2), "B": (1, 14, 105), "New": (2, 90, 2)})
    explorer.place_desktop_icons({"A": (14, 2), "B": (90, 208)})
    assert sent == [(9, explorer.LVM_SETITEMPOSITION, 1, 208 << 16 | 90)]


def test_placing_icons_skips_one_that_has_gone(monkeypatch):
    sent = desktop_of(monkeypatch, {"A": (0, 14, 2)})
    explorer.place_desktop_icons({"Gone": (90, 208)})
    assert sent == []


def test_placing_nothing_looks_at_nothing(monkeypatch):
    monkeypatch.setattr(explorer, "desktop_list", pytest.fail)
    explorer.place_desktop_icons({})


def test_no_desktop_means_no_icons(monkeypatch):
    monkeypatch.setattr(explorer, "desktop_list", lambda: 0)
    assert explorer.desktop_icons() == {}


def test_desktop_icons_can_be_read():
    """Reads only. A CI runner may have an empty desktop, so this checks the shape."""
    icons = explorer.desktop_icons()
    assert all(isinstance(name, str) and len(spot) == 2 for name, spot in icons.items())


def test_read_items_reports_every_icon_of_the_real_desktop():
    listview = explorer.desktop_list()
    items = explorer.read_items(listview) if listview else {}
    assert sorted(index for index, _x, _y in items.values()) == list(range(len(items)))


def test_the_taskbar_mode_can_be_read(native):
    assert native.get_param(TASKBAR_AUTOHIDE) in (0, 1)


@pytest.mark.parametrize(("value", "state"), [(0, win32.ABS_ALWAYSONTOP), (1, win32.ABS_AUTOHIDE)])
def test_setting_the_taskbar_mode_sends_its_state(native, monkeypatch, value, state):
    sent = []

    def record(message, data):
        sent.append((message, data._obj.lParam))
        return 1

    monkeypatch.setattr(win32.shell32, "SHAppBarMessage", record)
    native.set_param(TASKBAR_AUTOHIDE, value)
    assert sent == [(win32.ABM_SETSTATE, state)]


def test_parse_rgb_is_a_colorref():
    assert win32.parse_rgb("1 2 3") == 0x030201


def test_twips_to_pixels():
    assert win32.twips_to_pixels("-270") == 18
    assert win32.twips_to_pixels("5") == 5


def test_split_icon_location():
    assert win32.split_icon_location(r"C:\a,b.ico,3") == (r"C:\a,b.ico", 3)
    assert win32.split_icon_location("") == ("", 0)


def make_link(tmp_path):
    win32.pythoncom.CoInitialize()
    link = win32.pythoncom.CoCreateInstance(
        win32.shell.CLSID_ShellLink,
        None,
        win32.pythoncom.CLSCTX_INPROC_SERVER,
        win32.shell.IID_IShellLink,
    )
    link.SetPath(shutil.which("python") or r"C:\Windows\notepad.exe")
    path = tmp_path / "App.lnk"
    link.QueryInterface(win32.pythoncom.IID_IPersistFile).Save(str(path), True)
    return path


def test_shortcut_icon_round_trip(native, tmp_path):
    path = make_link(tmp_path)
    assert native.get_shortcut_icon(path) == ""
    native.set_shortcut_icon(path, r"C:\icons\a.ico,2")
    assert native.get_shortcut_icon(path) == r"C:\icons\a.ico,2"
    native.set_shortcut_icon(path, "")
    assert native.get_shortcut_icon(path) == ""


def test_extract_icon_returns_a_visible_image(native, tmp_path):
    image = native.extract_icon(make_link(tmp_path))
    assert image.mode == "RGBA"
    assert image.size == (win32.ICON_RENDER_SIZE, win32.ICON_RENDER_SIZE)
    assert image.getchannel("A").getbbox() is not None


def test_list_shortcuts_returns_only_links(native):
    assert all(path.suffix.lower() == ".lnk" for path in native.list_shortcuts())
