import json

import pytest

from skinamp.journal import SCHEMA_VERSION, Entry, Journal, JournalError, JournalStore

# The on-disk format of schema 1, frozen. If this test needs editing, the change broke undo
# for everyone who updates with a theme applied: bump the schema and migrate instead.
GOLDEN_V1 = """{
 "schema": 1,
 "theme": "retro",
 "components": ["cursors"],
 "entries": [
  {
   "kind": "registry",
   "target": {"key": "Control Panel\\\\Cursors", "name": "Arrow"},
   "before": {"value": {"type": "sz", "data": "old"}, "created_keys": []},
   "refresh": "cursors"
  }
 ],
 "state": "applied",
 "app_version": "0.1.0",
 "created": "2026-11-03T00:00:00+00:00"
}"""


def sample():
    entry = Entry("registry", {"key": "K", "name": "N"}, {"value": None}, "cursors")
    return Journal("retro", ["cursors"], [entry], app_version="1.0")


def test_missing_journal_is_none(tmp_path):
    assert JournalStore(tmp_path / "journal.json").load() is None


def test_roundtrip(tmp_path):
    store = JournalStore(tmp_path / "state" / "journal.json")
    journal = sample()
    store.save(journal)
    assert store.exists()
    assert store.load() == journal


def test_clear_removes_it_and_is_repeatable(tmp_path):
    store = JournalStore(tmp_path / "journal.json")
    store.save(sample())
    store.clear()
    store.clear()
    assert not store.exists()


def test_reads_the_frozen_v1_format(tmp_path):
    path = tmp_path / "journal.json"
    path.write_text(GOLDEN_V1, encoding="utf-8")
    journal = JournalStore(path).load()
    assert journal.theme == "retro"
    assert journal.state == "applied"
    assert journal.entries[0].before["value"] == {"type": "sz", "data": "old"}
    assert journal.entries[0].refresh == "cursors"


@pytest.mark.parametrize(
    "content", ["{not json", "[]", '{"schema": 1}', json.dumps({"schema": SCHEMA_VERSION + 1})]
)
def test_damaged_journal_raises_and_stays_on_disk(tmp_path, content):
    path = tmp_path / "journal.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(JournalError):
        JournalStore(path).load()
    assert path.read_text(encoding="utf-8") == content
