import json

from skinamp.targets import chrome


def make_profiles(user_data, *names):
    for name in names:
        folder = user_data / name
        folder.mkdir(parents=True)
        (folder / "Preferences").write_text(json.dumps({}), encoding="utf-8")


def test_user_data_dir_is_under_local_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert chrome.user_data_dir() == tmp_path / "Google" / "Chrome" / "User Data"


def test_profiles_skip_internal_ones(tmp_path):
    make_profiles(tmp_path, "Default", "Profile 1", "System Profile", "Guest Profile")
    assert [path.parent.name for path in chrome.profiles(tmp_path)] == ["Default", "Profile 1"]


def test_effects_cover_every_profile_and_clear_the_theme_extension(tmp_path):
    make_profiles(tmp_path, "Default", "Profile 1")
    effects = chrome.effects(tmp_path)
    assert len(effects) == 4
    by_path = {effect.path: effect for effect in effects}
    assert by_path[("extensions", "theme", "id")].value == ""
    assert all(effect.guard == chrome.PROCESS for effect in effects)


def test_grey_uses_chromes_own_grey_option_not_a_seed_colour(tmp_path):
    # Live finding on Chrome 156: a silver `user_color2` renders pale teal, because Chrome
    # tints any seed colour, while this gave true grey (227, 227, 227) in the tab strip.
    make_profiles(tmp_path, "Default")
    assert {effect.path: effect.value for effect in chrome.effects(tmp_path)}[
        ("browser", "theme", "is_grayscale2")
    ] is True


def test_no_chrome_means_no_effects(tmp_path):
    assert chrome.effects(tmp_path / "absent") == []
