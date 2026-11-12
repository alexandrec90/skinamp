from types import SimpleNamespace

from skinamp import updater
from skinamp.updater import UpdateStatus, Updater


class FakeManager:
    def __init__(self, update=None, fail_on=None):
        self.update = update
        self.fail_on = fail_on
        self.calls = []

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if self.fail_on == name:
            raise RuntimeError(f"{name} failed")

    def check_for_updates(self):
        self._record("check")
        return self.update

    def download_updates(self, update_info):
        self._record("download", update_info)

    def wait_exit_then_apply_updates(self, update, silent, restart):
        self._record("apply_on_exit", update, silent, restart)

    def apply_updates_and_restart(self, update):
        self._record("restart", update)


UPDATE = SimpleNamespace(TargetFullRelease=SimpleNamespace(Version="1.2.3"))


def test_source_runs_are_unmanaged():
    def refuse():
        raise RuntimeError("not installed")

    assert Updater(refuse).check_and_download() == UpdateStatus("unmanaged")


def test_no_update_available():
    assert Updater(lambda: FakeManager()).check_and_download() == UpdateStatus("current")


def test_update_downloads_and_installs_on_exit():
    manager = FakeManager(UPDATE)
    status = Updater(lambda: manager).check_and_download()
    assert status == UpdateStatus("ready", "1.2.3")
    assert manager.calls == [
        ("check",),
        ("download", UPDATE),
        ("apply_on_exit", UPDATE, True, False),
    ]


def test_failure_is_a_status_not_an_exception():
    status = Updater(lambda: FakeManager(UPDATE, fail_on="download")).check_and_download()
    assert status.phase == "failed"
    assert "download failed" in status.detail


def test_failed_check_is_a_status_too():
    assert Updater(lambda: FakeManager(fail_on="check")).check_and_download().phase == "failed"


def test_restart_applies_the_downloaded_update():
    manager = FakeManager(UPDATE)
    instance = Updater(lambda: manager)
    instance.check_and_download()
    instance.restart_into_update()
    assert manager.calls[-1] == ("restart", UPDATE)


def test_restart_without_an_update_does_nothing():
    manager = FakeManager()
    instance = Updater(lambda: manager)
    instance.check_and_download()
    instance.restart_into_update()
    assert "restart" not in [call[0] for call in manager.calls]


def test_velopack_manager_targets_this_repository(monkeypatch):
    seen = {}

    def fake_source(url):
        seen["url"] = url
        return "source"

    monkeypatch.setattr(updater.velopack, "GithubSource", fake_source)
    monkeypatch.setattr(updater.velopack, "UpdateManager", lambda source: ("manager", source))
    assert updater.velopack_manager() == ("manager", "source")
    assert seen["url"] == updater.REPOSITORY
