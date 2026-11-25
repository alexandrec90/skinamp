import subprocess
import sys

import pytest

from skinamp.system import taskbar
from skinamp.system.api import RegValue


class FakeProcess:
    def __init__(self, exe, pid=1):
        self.info = {"exe": str(exe) if exe else None}
        self.pid = pid
        self.killed = False

    def kill(self):
        self.killed = True


@pytest.fixture
def launched(monkeypatch):
    calls = []
    monkeypatch.setattr(
        taskbar.subprocess, "Popen", lambda args, env, creationflags: calls.append((args, env))
    )
    return calls


@pytest.fixture
def no_processes(monkeypatch):
    monkeypatch.setattr(taskbar.psutil, "process_iter", lambda _attrs: [])


def installed(paths):
    exe = taskbar.retrobar_exe(paths)
    exe.parent.mkdir(parents=True)
    exe.touch()
    return exe


def test_paths_are_versioned(paths):
    assert taskbar.RETROBAR_VERSION in str(taskbar.retrobar_exe(paths))
    assert taskbar.DOTNET_VERSION in str(taskbar.dotnet_root(paths))


def test_retrobar_settings_dir_uses_local_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert taskbar.retrobar_settings_dir() == tmp_path / "RetroBar"


def test_self_command_from_source():
    assert taskbar.self_command() == [sys.executable, "-m", "skinamp"]


def test_self_command_from_the_executable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert taskbar.self_command() == [sys.executable]


def test_launch_command_from_source():
    assert taskbar.launch_command() == subprocess.list2cmdline(
        [sys.executable, "-m", "skinamp", "taskbar-start"]
    )


def test_launch_command_from_the_executable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert taskbar.launch_command().endswith(" taskbar-start")
    assert "-m skinamp" not in taskbar.launch_command()


def test_running_ignores_a_retrobar_the_user_runs_themselves(monkeypatch, paths, tmp_path):
    ours = FakeProcess(taskbar.retrobar_exe(paths))
    theirs = FakeProcess(tmp_path / "elsewhere" / "RetroBar.exe")
    unreadable = FakeProcess(None)
    monkeypatch.setattr(taskbar.psutil, "process_iter", lambda _attrs: [ours, theirs, unreadable])
    assert taskbar.running(paths) == [ours]


def test_start_points_retrobar_at_the_private_runtime(paths, launched, no_processes):
    exe = installed(paths)
    taskbar.start(paths)
    [(args, env)] = launched
    assert args == [str(exe)]
    assert env["DOTNET_ROOT"] == str(taskbar.dotnet_root(paths))


def test_start_does_nothing_when_not_installed(paths, launched, no_processes):
    taskbar.start(paths)
    assert launched == []


def test_start_does_not_run_a_second_copy(monkeypatch, paths, launched):
    exe = installed(paths)
    monkeypatch.setattr(taskbar.psutil, "process_iter", lambda _attrs: [FakeProcess(exe)])
    taskbar.start(paths)
    assert launched == []


def stubbed_stop(monkeypatch, processes, alive):
    monkeypatch.setattr(taskbar.psutil, "process_iter", lambda _attrs: processes)
    monkeypatch.setattr(taskbar.psutil, "wait_procs", lambda _p, timeout: ([], alive))


def no_close_request(_pids):
    pytest.fail("nothing is running, so nothing should be asked to close")


def test_stop_closes_politely_and_shows_the_native_taskbar(monkeypatch, paths):
    process = FakeProcess(taskbar.retrobar_exe(paths), pid=42)
    stubbed_stop(monkeypatch, [process], alive=[])
    asked = []
    shown = []
    taskbar.stop(paths, lambda pids: asked.append(pids) or True, lambda: shown.append(True))
    assert asked == [{42}]
    assert not process.killed
    assert shown == [True]


def test_stop_ends_a_process_that_ignores_the_request(monkeypatch, paths):
    process = FakeProcess(taskbar.retrobar_exe(paths))
    stubbed_stop(monkeypatch, [process], alive=[process])
    shown = []
    taskbar.stop(paths, lambda _pids: False, lambda: shown.append(True))
    assert process.killed
    assert shown == [True]


def test_stop_removes_settings_only_when_we_caused_them(monkeypatch, paths, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings = tmp_path / "RetroBar"
    settings.mkdir()
    stubbed_stop(monkeypatch, [], alive=[])
    paths.components.mkdir(parents=True)

    taskbar.stop(paths, no_close_request, lambda: None)
    assert settings.exists()

    (paths.components / taskbar.SETTINGS_MARKER).touch()
    taskbar.stop(paths, no_close_request, lambda: None)
    assert not settings.exists()


def test_sync_starts_when_the_sign_in_entry_exists(system, paths, launched, no_processes):
    installed(paths)
    system.reg_write(taskbar.RUN_KEY, taskbar.RUN_VALUE, RegValue("sz", "cmd"))
    taskbar.sync(system, paths, no_close_request, pytest.fail)
    assert len(launched) == 1


def test_sync_stops_when_the_sign_in_entry_is_gone(monkeypatch, system, paths):
    stubbed_stop(monkeypatch, [], alive=[])
    shown = []
    taskbar.sync(system, paths, no_close_request, lambda: shown.append(True))
    assert shown == [True]
