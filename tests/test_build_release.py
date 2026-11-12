import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build-release.py"
spec = importlib.util.spec_from_file_location("build_release", SCRIPT)
assert spec is not None and spec.loader is not None
build_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_release)


@pytest.mark.parametrize("ref", ["v1.2.3", "1.2.3", "refs/tags/v1.2.3"])
def test_version_from_ref(ref):
    assert build_release.version_from_ref(ref) == "1.2.3"


@pytest.mark.parametrize("ref", ["main", "v1.2", "refs/heads/main", "v1.2.3-beta"])
def test_version_from_ref_refuses_non_releases(ref):
    with pytest.raises(ValueError, match="release tag"):
        build_release.version_from_ref(ref)


def test_pyinstaller_builds_a_windowed_folder_with_the_web_ui():
    command = build_release.pyinstaller_command("python")
    assert "--onedir" in command and "--windowed" in command
    assert "--onefile" not in command
    data = command[command.index("--add-data") + 1]
    assert data.endswith(";skinamp/gui/web")


def test_vpk_names_the_version_and_exe():
    command = build_release.vpk_command("1.2.3")
    assert command[:2] == ["vpk", "pack"]
    assert command[command.index("--packVersion") + 1] == "1.2.3"
    assert command[command.index("--mainExe") + 1] == "Skinamp.exe"


def stub_subprocess(monkeypatch, returncode):
    result = SimpleNamespace(returncode=returncode, stdout="out", stderr="err")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: result)


def test_run_writes_the_failure_artifact(monkeypatch, tmp_path):
    log = tmp_path / "logs" / "build-failure.log"
    monkeypatch.setattr(build_release, "FAILURE_LOG", log)
    stub_subprocess(monkeypatch, 1)
    with pytest.raises(SystemExit, match=r"build-failure\.log"):
        build_release.run(["tool", "--flag"])
    text = log.read_text(encoding="utf-8")
    assert "tool --flag" in text and "out" in text and "err" in text


def test_run_success_writes_nothing(monkeypatch, tmp_path):
    log = tmp_path / "build-failure.log"
    monkeypatch.setattr(build_release, "FAILURE_LOG", log)
    stub_subprocess(monkeypatch, 0)
    build_release.run(["tool"])
    assert not log.exists()


def test_main_builds_and_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(build_release, "FAILURE_LOG", tmp_path / "failure.log")
    commands = []
    monkeypatch.setattr(build_release, "run", commands.append)
    monkeypatch.setattr(sys, "argv", ["build", "--pack", "--version", "v1.2.3"])
    assert build_release.main() == 0
    assert [command[0] for command in commands] == [sys.executable, "vpk"]


def test_main_refuses_pack_without_a_version(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["build", "--pack"])
    with pytest.raises(SystemExit):
        build_release.main()
