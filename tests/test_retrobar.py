import hashlib
import io
import string
import zipfile

import pytest

from skinamp.effects import KeepTaskbarMode
from skinamp.system import taskbar
from skinamp.system.api import Refresh
from skinamp.targets import retrobar


class FakeResponse(io.BytesIO):
    pass


def serve(monkeypatch, content):
    monkeypatch.setattr(
        retrobar.urllib.request, "urlopen", lambda _url, timeout: FakeResponse(content)
    )


def pinned(content):
    return retrobar.Download(
        "https://example.invalid/x", "sha256", hashlib.sha256(content).hexdigest()
    )


def zip_of(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("download", "length"),
    [(retrobar.RETROBAR, 64), (retrobar.DOTNET[0], 128), (retrobar.DOTNET[1], 128)],
)
def test_pins_are_complete_hashes_over_https(download, length):
    assert download.url.startswith("https://")
    assert len(download.digest) == length
    assert set(download.digest) <= set(string.hexdigits)


def test_fetch_accepts_a_matching_hash(monkeypatch, tmp_path):
    serve(monkeypatch, b"payload")
    target = tmp_path / "sub" / "file.zip"
    retrobar.fetch(pinned(b"payload"), target)
    assert target.read_bytes() == b"payload"


def test_fetch_deletes_a_file_that_fails_its_hash(monkeypatch, tmp_path):
    serve(monkeypatch, b"tampered")
    target = tmp_path / "file.zip"
    with pytest.raises(retrobar.DownloadError, match="pinned"):
        retrobar.fetch(pinned(b"payload"), target)
    assert not target.exists()


def test_fetch_reports_a_network_failure_and_leaves_nothing(monkeypatch, tmp_path):
    def refuse(_url, timeout):
        raise OSError("offline")

    monkeypatch.setattr(retrobar.urllib.request, "urlopen", refuse)
    target = tmp_path / "file.zip"
    with pytest.raises(retrobar.DownloadError, match="offline"):
        retrobar.fetch(pinned(b""), target)
    assert not target.exists()


def fake_fetch(content):
    def fetch(_download, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    return fetch


def test_install_retrobar_extracts_only_the_64_bit_exe(monkeypatch, paths):
    content = zip_of({retrobar.RETROBAR_MEMBER: b"exe", "ARM64/RetroBar.exe": b"arm"})
    monkeypatch.setattr(retrobar, "fetch", fake_fetch(content))
    retrobar.install_retrobar(paths)
    assert taskbar.retrobar_exe(paths).read_bytes() == b"exe"
    assert not (paths.components / "retrobar.zip").exists()


def test_dotnet_pins_the_host_as_well_as_the_desktop_framework():
    # The desktop zip alone has no `host/fxr`, and RetroBar cannot start without it.
    names = [download.url.rsplit("/", 1)[-1] for download in retrobar.DOTNET]
    assert any(name.startswith("dotnet-runtime-") for name in names)
    assert any(name.startswith("windowsdesktop-runtime-") for name in names)


def test_install_dotnet_merges_both_archives(monkeypatch, paths):
    archives = iter(
        [
            zip_of({"host/fxr/hostfxr.dll": b"x"}),
            zip_of({"shared/Microsoft.WindowsDesktop.App/a.dll": b"y"}),
        ]
    )
    monkeypatch.setattr(
        retrobar,
        "fetch",
        lambda _download, destination: fake_fetch(next(archives))(_download, destination),
    )
    retrobar.install_dotnet(paths)
    root = taskbar.dotnet_root(paths)
    assert (root / "host" / "fxr" / "hostfxr.dll").exists()
    assert (root / "shared" / "Microsoft.WindowsDesktop.App" / "a.dll").exists()
    assert not (paths.components / "dotnet.zip").exists()


def test_a_failed_dotnet_download_never_looks_installed(monkeypatch, paths):
    def fail(_download, _destination):
        raise retrobar.DownloadError("offline")

    monkeypatch.setattr(retrobar, "fetch", fail)
    with pytest.raises(retrobar.DownloadError):
        retrobar.install_dotnet(paths)
    assert not taskbar.dotnet_root(paths).exists()


def test_installs_are_skipped_when_already_present(monkeypatch, paths):
    taskbar.retrobar_exe(paths).parent.mkdir(parents=True)
    taskbar.retrobar_exe(paths).touch()
    taskbar.dotnet_root(paths).mkdir(parents=True)
    monkeypatch.setattr(retrobar, "fetch", lambda *_args: pytest.fail("should not download"))
    retrobar.install_retrobar(paths)
    retrobar.install_dotnet(paths)


def test_prepare_marks_a_settings_folder_it_will_create(monkeypatch, paths, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(retrobar, "install_dotnet", lambda _paths: None)
    monkeypatch.setattr(retrobar, "install_retrobar", lambda _paths: None)
    retrobar.prepare(paths)
    assert (paths.components / taskbar.SETTINGS_MARKER).exists()


def test_prepare_leaves_the_users_own_settings_unmarked(monkeypatch, paths, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "RetroBar").mkdir()
    monkeypatch.setattr(retrobar, "install_dotnet", lambda _paths: None)
    monkeypatch.setattr(retrobar, "install_retrobar", lambda _paths: None)
    retrobar.prepare(paths)
    assert not (paths.components / taskbar.SETTINGS_MARKER).exists()


@pytest.mark.parametrize(
    ("machine", "supported"), [("AMD64", True), ("x86_64", True), ("ARM64", False)]
)
def test_unsupported_reason(machine, supported):
    assert (retrobar.unsupported_reason(machine) is None) is supported


def test_effects_register_the_sign_in_entry():
    keep_mode, effect = retrobar.effects()
    assert isinstance(keep_mode, KeepTaskbarMode)
    assert (effect.key, effect.name) == (taskbar.RUN_KEY, taskbar.RUN_VALUE)
    assert effect.refresh_on is Refresh.TASKBAR
    assert "taskbar-start" in effect.value.data
