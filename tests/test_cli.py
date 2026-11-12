import logging

import pytest

from skinamp import cli, elevated
from skinamp.effects import SetRegistry
from skinamp.engine import Engine
from skinamp.journal import JournalStore
from skinamp.system import factory
from skinamp.system.api import RegValue
from skinamp.system.factory import UnsupportedPlatformError, get_system
from skinamp.themes import THEMES
from skinamp.themes.model import Component, Theme


def simple_theme():
    def effects(_context):
        return [SetRegistry(r"Software\X", "A", RegValue("sz", "new"))]

    return Theme("simple", "Simple", "", (Component("one", "", "", effects),))


@pytest.fixture
def run(system, paths, monkeypatch):
    monkeypatch.setitem(THEMES, "simple", simple_theme())
    monkeypatch.setattr(cli, "default_paths", lambda: paths)
    monkeypatch.setattr(cli, "configure_logging", lambda _paths: None)
    monkeypatch.setattr(cli, "build_engine", lambda _paths: Engine(system, paths))
    return cli.main


def test_elevated_run_hands_over_the_request_and_touches_no_user_files(monkeypatch, tmp_path):
    requests = []
    monkeypatch.setattr(cli, "run_request", requests.append)
    monkeypatch.setattr(cli, "configure_logging", lambda _paths: pytest.fail("no log as admin"))
    request = tmp_path / "request.json"
    assert cli.main(["elevated-run", str(request)]) == cli.EXIT_OK
    assert requests == [request]


@pytest.mark.parametrize("error", [OSError("locked"), ValueError("Refusing this")])
def test_elevated_run_leaves_its_failure_for_the_parent(monkeypatch, tmp_path, error):
    def fail(_request):
        raise error

    monkeypatch.setattr(cli, "run_request", fail)
    assert cli.run_elevated_request(tmp_path / "request.json") == cli.EXIT_FAILED
    assert (tmp_path / elevated.ERROR_FILE).read_text(encoding="utf-8") == str(error)


def test_elevated_run_exits_quietly_when_its_folder_is_gone(monkeypatch, tmp_path):
    """A late "Yes" on a prompt Skinamp gave up on: no traceback window for the user."""

    def gone(_request):
        raise FileNotFoundError("request.json")

    monkeypatch.setattr(cli, "run_request", gone)
    request = tmp_path / "removed" / "request.json"
    assert cli.run_elevated_request(request) == cli.EXIT_FAILED


def test_apply_while_another_copy_works_says_so(run, system, paths, capsys):
    with JournalStore(paths.journal).hold():
        assert run(["apply", "simple"]) == cli.EXIT_FAILED
    assert "Another copy of Skinamp" in capsys.readouterr().out
    assert system.registry == {}


def test_run_request_needs_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(factory.sys, "platform", "linux")
    with pytest.raises(UnsupportedPlatformError):
        factory.run_request(tmp_path / "request.json")


def test_plan_prints_and_changes_nothing(run, system, capsys):
    assert run(["plan", "simple"]) == cli.EXIT_OK
    assert "HKCU\\Software\\X" in capsys.readouterr().out
    assert system.registry == {}


def test_apply_status_revert(run, system, capsys):
    assert run(["apply", "simple", "--only", "one"]) == cli.EXIT_OK
    assert run(["status"]) == cli.EXIT_OK
    assert "applied: simple" in capsys.readouterr().out
    assert run(["revert"]) == cli.EXIT_OK
    assert system.reg_read(r"Software\X", "A") is None


def test_failed_apply_exits_non_zero(run, system, capsys):
    system.fail_writes_to = {"A"}
    assert run(["apply", "simple"]) == cli.EXIT_FAILED
    assert "rolled back" in capsys.readouterr().out


def test_unknown_theme_exits_non_zero(run, capsys):
    assert run(["apply", "nope"]) == cli.EXIT_FAILED
    assert "nope" in capsys.readouterr().out


def test_unreadable_journal_exits_non_zero(run, paths, capsys):
    paths.journal.parent.mkdir(parents=True)
    paths.journal.write_text("{broken", encoding="utf-8")
    assert run(["status"]) == cli.EXIT_FAILED
    assert run(["revert"]) == cli.EXIT_FAILED
    assert "Cannot read" in capsys.readouterr().out


def test_no_command_opens_the_window(run, monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "_gui", lambda engine: opened.append(engine) or cli.EXIT_OK)
    assert run([]) == cli.EXIT_OK
    assert len(opened) == 1


def test_taskbar_start_needs_no_engine(run, monkeypatch, paths):
    started = []
    monkeypatch.setattr(cli.taskbar, "start", started.append)
    monkeypatch.setattr(cli, "build_engine", lambda _paths: pytest.fail("no engine needed"))
    assert run(["taskbar-start"]) == cli.EXIT_OK
    assert started == [paths]


def test_build_engine_refuses_other_platforms(monkeypatch, paths):
    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(UnsupportedPlatformError):
        cli.build_engine(paths)
    with pytest.raises(UnsupportedPlatformError):
        get_system(paths)


def test_configure_logging_creates_the_log_folder(paths):
    root = logging.getLogger()
    existing = root.handlers[:]
    root.handlers[:] = []
    try:
        cli.configure_logging(paths)
        logging.getLogger("skinamp").warning("hello")
        for handler in root.handlers:
            handler.close()
    finally:
        root.handlers[:] = existing
    assert "hello" in paths.log.read_text(encoding="utf-8")
