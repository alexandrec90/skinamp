import sys

import pytest
import velopack

from skinamp import __main__ as entry
from skinamp import __version__, cli


class FakeApp:
    def __init__(self):
        self.callback = None
        self.ran = False
        FAKE_APPS.append(self)

    def on_before_uninstall_fast_callback(self, callback):
        self.callback = callback
        return self

    def run(self):
        self.ran = True


FAKE_APPS: list[FakeApp] = []


def test_version_is_declared():
    assert isinstance(__version__, str) and __version__


def test_install_hooks_run_with_the_uninstall_undo(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(velopack, "App", FakeApp)
    entry.run_install_hooks()
    app = FAKE_APPS[-1]
    assert app.ran
    assert app.callback is entry.undo_before_uninstall


def test_source_runs_skip_the_install_hooks(monkeypatch):
    monkeypatch.setattr(velopack, "App", lambda: pytest.fail("not installed, nothing to run"))
    entry.run_install_hooks()


def test_uninstalling_undoes_the_theme(monkeypatch):
    reverted = []

    class Engine:
        def revert(self):
            reverted.append(True)

    monkeypatch.setattr(cli, "build_engine", lambda _paths: Engine())
    entry.undo_before_uninstall("1.0.0")
    assert reverted == [True]


def test_main_runs_hooks_before_the_command(monkeypatch):
    order = []
    monkeypatch.setattr(entry, "run_install_hooks", lambda: order.append("hooks"))
    monkeypatch.setattr(entry.cli, "main", lambda argv: order.append(argv) or 0)
    monkeypatch.setattr("sys.argv", ["skinamp", "status"])
    assert entry.main() == 0
    assert order == ["hooks", ["status"]]
