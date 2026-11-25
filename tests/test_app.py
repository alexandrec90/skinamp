import base64
import io
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from skinamp.effects import SetRegistry
from skinamp.engine import Engine
from skinamp.gui import app
from skinamp.gui.app import Api
from skinamp.journal import Entry, Journal, JournalStore
from skinamp.system.api import RegValue
from skinamp.themes import THEMES, retro
from skinamp.themes.model import Component, Theme
from skinamp.updater import UpdateStatus


class StubUpdater:
    def __init__(self):
        self.restarted = False

    def check_and_download(self):
        return UpdateStatus("ready", "2.0")

    def restart_into_update(self):
        self.restarted = True


def simple_theme():
    def effects(_context):
        return [SetRegistry(r"Software\X", "A", RegValue("sz", "new"))]

    return Theme("simple", "Simple", "", (Component("one", "", "", effects),))


@pytest.fixture
def api(system, paths, monkeypatch):
    monkeypatch.setitem(THEMES, "simple", simple_theme())
    return Api(Engine(system, paths), StubUpdater())


def test_data_uri_is_a_png_upscaled_without_smoothing():
    image = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
    uri = app.data_uri(image)
    assert uri.startswith("data:image/png;base64,")
    decoded = Image.open(io.BytesIO(base64.b64decode(uri.split(",")[1])))
    assert decoded.size == (app.PREVIEW_SIZE, app.PREVIEW_SIZE)


def test_describe_theme_lists_components_and_previews():
    description = app.describe_theme(retro.THEME_ID)
    assert description["name"] == "Retro"
    assert len(description["components"]) == len(retro.THEME.components)
    assert description["preview"]["computer"].startswith("data:image/png")


def test_get_state_reports_version_and_default_status(api):
    state = api.get_state()
    assert state["status"]["state"] == "default"
    assert {theme["id"] for theme in state["themes"]} >= {"retro", "simple"}


def test_apply_then_revert(api, system):
    result = api.apply("simple", ["one"])
    assert result["ok"] and result["changes"] == 1
    assert api.get_status()["theme"] == "simple"
    undone = api.revert()
    assert undone["ok"] and undone["restored"] == 1
    assert system.reg_read(r"Software\X", "A") is None


def test_failed_apply_comes_back_as_data(api, system):
    system.fail_writes_to = {"A"}
    result = api.apply("simple", ["one"])
    assert result["ok"] is False
    assert result["rolled_back"] is True
    assert "cannot write A" in result["error"]


def test_unknown_theme_comes_back_as_data(api):
    result = api.apply("nope", [])
    assert result["ok"] is False
    assert "nope" in result["error"]


def test_incomplete_revert_is_not_ok(api, system, paths):
    entry = Entry("json_pref", {"file": __file__, "path": ["a"], "guard": "chrome.exe"}, {})
    JournalStore(paths.journal).save(Journal("simple", ["one"], [entry], state="applied"))
    system.running.add("chrome.exe")
    system.refuse_close.add("chrome.exe")
    result = api.revert()
    assert result["ok"] is False
    assert result["pending"]


def test_unreadable_journal_comes_back_as_data(api, paths):
    paths.journal.parent.mkdir(parents=True)
    paths.journal.write_text("{broken", encoding="utf-8")
    result = api.revert()
    assert result["ok"] is False
    assert "Cannot read" in result["error"]


def test_updates_flow_through_the_bridge(api):
    assert api.get_update()["phase"] == "unmanaged"
    assert api.check_updates() == {"phase": "ready", "version": "2.0", "detail": None}
    assert api.get_update()["version"] == "2.0"
    api.restart_to_update()
    assert api._updater.restarted


def test_web_files_ship_with_the_package():
    for name in ("index.html", "app.js", "style.css"):
        assert (app.WEB_ROOT / name).is_file()


def test_run_opens_the_page_with_the_bridge(monkeypatch, system, paths):
    calls = {}
    fake = SimpleNamespace(
        create_window=lambda *args, **kwargs: calls.update(args=args, kwargs=kwargs),
        start=lambda: calls.update(started=True),
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    app.run(Engine(system, paths), StubUpdater())
    assert calls["args"][1].endswith("index.html")
    assert isinstance(calls["kwargs"]["js_api"], Api)
    assert calls["started"]
