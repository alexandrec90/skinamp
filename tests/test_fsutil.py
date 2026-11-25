from pathlib import Path

import pytest

from skinamp.fsutil import LockHeldError, atomic_write, exclusive_lock


def test_creates_parents_and_writes(tmp_path):
    path = tmp_path / "a" / "b.bin"
    atomic_write(path, b"data")
    assert path.read_bytes() == b"data"


def test_replaces_existing_content(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"old")
    atomic_write(path, b"new")
    assert path.read_bytes() == b"new"


def test_failure_keeps_the_old_file_and_leaves_no_temp(tmp_path, monkeypatch):
    path = tmp_path / "file"
    path.write_bytes(b"old")

    def refuse(_self, _target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert [item.name for item in tmp_path.iterdir()] == ["file"]


def test_exclusive_lock_refuses_a_second_holder_until_released(tmp_path):
    lock = tmp_path / "state" / "x.lock"
    with exclusive_lock(lock):
        with pytest.raises(LockHeldError), exclusive_lock(lock):
            pytest.fail("two holders at once")
    with exclusive_lock(lock):
        pass
