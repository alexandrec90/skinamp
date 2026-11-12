"""The allow-list between a user-writable request file and admin rights."""

from pathlib import Path

import pytest

from skinamp import elevated
from skinamp.system.api import RegValue

ROOT = Path("/public/Desktop")


def test_everything_a_theme_needs_passes():
    elevated.validate(
        [
            elevated.reg_write(elevated.SHELL_ICONS_KEY, "3", RegValue("sz", "a.ico,0")),
            elevated.reg_delete(elevated.SHELL_ICONS_KEY, "3"),
            elevated.reg_prune(elevated.SHELL_ICONS_KEY),
            elevated.shortcut_icon(ROOT / "sub" / "App.lnk", "a.ico,0"),
        ],
        [ROOT],
    )


@pytest.mark.parametrize(
    "op",
    [
        elevated.reg_write(r"SOFTWARE\Microsoft\Windows\Run", "x", RegValue("sz", "evil.exe")),
        elevated.reg_delete(r"SYSTEM\CurrentControlSet", "x"),
        elevated.reg_prune(r"SOFTWARE"),
        elevated.shortcut_icon(Path("/Users/someone/App.lnk"), "a.ico,0"),
        elevated.shortcut_icon(ROOT / "notes.txt", "a.ico,0"),
        elevated.shortcut_icon(ROOT / ".." / ".." / "Windows" / "App.lnk", "a.ico,0"),
        {"op": "run_program", "path": "evil.exe"},
        {},
    ],
)
def test_anything_else_is_refused(op):
    with pytest.raises(ValueError, match="Refusing"):
        elevated.validate([op], [ROOT])


def test_the_helper_claims_the_request_before_reading_it(tmp_path):
    request = tmp_path / elevated.REQUEST_FILE
    request.write_text("[]", encoding="utf-8")
    claimed = elevated.claim(request)
    assert claimed.read_text(encoding="utf-8") == "[]"
    assert not request.exists()
    assert not elevated.abandon(request), "too late to abandon what the helper holds"


def test_an_abandoned_request_can_never_be_claimed(tmp_path):
    request = tmp_path / elevated.REQUEST_FILE
    request.write_text("[]", encoding="utf-8")
    assert elevated.abandon(request)
    with pytest.raises(OSError, match="stopped waiting"):
        elevated.claim(request)


def test_one_bad_operation_refuses_the_whole_request():
    good = elevated.reg_delete(elevated.SHELL_ICONS_KEY, "3")
    with pytest.raises(ValueError, match="Refusing"):
        elevated.validate([good, {"op": "run_program"}], [ROOT])
