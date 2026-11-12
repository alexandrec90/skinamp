import pytest

from skinamp.themes.model import Component, Theme


def component(component_id):
    return Component(component_id, "", "", lambda _context: [])


THEME = Theme("t", "T", "", (component("a"), component("b")))


def test_select_none_means_everything():
    assert [c.id for c in THEME.select(None)] == ["a", "b"]


def test_select_keeps_theme_order():
    assert [c.id for c in THEME.select(["b", "a"])] == ["a", "b"]


def test_select_empty_means_nothing():
    assert THEME.select([]) == []


def test_select_refuses_unknown_ids():
    with pytest.raises(ValueError, match="zzz"):
        THEME.select(["a", "zzz"])


def test_preview_defaults_to_nothing():
    assert THEME.preview() == {}
