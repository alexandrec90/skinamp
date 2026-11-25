from pathlib import Path

from skinamp.paths import AppPaths, default_paths


def test_default_paths_sit_outside_the_install_root(monkeypatch, tmp_path):
    # The updater replaces %LOCALAPPDATA%\Skinamp and the uninstaller deletes it, so the
    # undo journal under there would vanish while a theme was still applied.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = default_paths()
    assert paths.journal.is_relative_to(tmp_path / "SkinampData")
    assert not paths.journal.is_relative_to(tmp_path / "Skinamp")


def test_default_paths_without_local_appdata(monkeypatch):
    # raising=False: the Linux gate has no LOCALAPPDATA to delete.
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert default_paths().root.name == "SkinampData"


def test_layout():
    paths = AppPaths(Path("root"))
    assert paths.journal == Path("root/state/journal.json")
    assert paths.log == Path("root/state/skinamp.log")
    assert paths.backups == Path("root/state/backups")
    assert paths.assets == Path("root/assets")
    assert paths.components == Path("root/components")
    assert paths.machine_assets == Path("root/machine-assets")


def test_shared_icons_live_where_every_account_can_read_them(monkeypatch, tmp_path):
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    assert default_paths().machine_assets == tmp_path / "SkinampData" / "machine-assets"


def test_default_paths_without_program_data(monkeypatch):
    monkeypatch.delenv("PROGRAMDATA", raising=False)
    assert default_paths().machine_root is None
