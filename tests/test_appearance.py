import struct

from skinamp.effects import PreserveFile, PreserveRegistry, SetParam, SetRegistry
from skinamp.system.api import Refresh, RegValue
from skinamp.targets import appearance


def test_rgb_text_is_the_control_panel_format():
    assert appearance.rgb_text((0, 128, 255)) == "0 128 255"


def test_abgr_and_argb_order_the_channels():
    assert appearance.abgr((0x11, 0x22, 0x33)) == 0xFF332211
    assert appearance.argb((0x11, 0x22, 0x33)) == 0xFF112233


def test_color_effects():
    [effect] = appearance.color_effects({"Menu": (1, 2, 3)})
    assert effect == SetRegistry(
        appearance.COLORS_KEY, "Menu", RegValue("sz", "1 2 3"), Refresh.COLORS
    )


def test_accent_palette_is_eight_swatches():
    palette = appearance.accent_palette((1, 2, 3))
    assert len(palette) == 32
    assert palette[:4] == bytes((1, 2, 3, 255))


def test_accent_effects_turn_transparency_off():
    effects = {(e.key, e.name): e.value for e in appearance.accent_effects((0, 0, 128), (9, 9, 9))}
    assert effects[(appearance.PERSONALIZE_KEY, "EnableTransparency")].data == 0
    assert effects[(appearance.ACCENT_KEY, "AccentPalette")].type == "binary"


def test_solid_background_clears_the_wallpaper():
    effects = {e.name: e for e in appearance.solid_background_effects((0, 128, 128))}
    assert effects["Wallpaper"].value == RegValue("sz", "")
    assert effects["Wallpaper"].refresh_on is Refresh.WALLPAPER
    assert effects["Background"].value == RegValue("sz", "0 128 128")


def beyond_the_recent_list(system, folder):
    """What wallpaper safety adds to the entries it always has for the recent list."""
    effects = appearance.wallpaper_safety_effects(system, folder)
    return [effect for effect in effects if not isinstance(effect, PreserveRegistry)]


def test_wallpaper_safety_always_keeps_the_recent_list(system, tmp_path):
    kept = appearance.wallpaper_safety_effects(system, tmp_path)
    assert kept == [
        PreserveRegistry(appearance.WALLPAPERS_KEY, name) for name in appearance.WALLPAPER_HISTORY
    ]


def test_wallpaper_safety_keeps_a_copy_of_the_current_picture(system, tmp_path):
    picture = tmp_path / "image.jpg"
    picture.touch()
    system.reg_write(appearance.DESKTOP_KEY, "Wallpaper", RegValue("sz", str(picture)))
    backups = tmp_path / "backups"
    assert beyond_the_recent_list(system, backups) == [
        PreserveFile(picture, backups / "image.jpg", Refresh.WALLPAPER)
    ]


def test_wallpaper_safety_records_spotlight_only_where_it_exists(system, tmp_path):
    assert beyond_the_recent_list(system, tmp_path) == []
    state = RegValue("dword", 1)
    system.reg_write(appearance.SPOTLIGHT_KEY, appearance.SPOTLIGHT_VALUE, state)
    [effect] = beyond_the_recent_list(system, tmp_path)
    assert effect.value == RegValue("dword", appearance.SPOTLIGHT_DISABLED)
    assert effect.refresh_on is Refresh.WALLPAPER


def test_wallpaper_safety_ignores_a_picture_already_gone(system, tmp_path):
    missing = str(tmp_path / "gone.jpg")
    system.reg_write(appearance.DESKTOP_KEY, "Wallpaper", RegValue("sz", missing))
    assert beyond_the_recent_list(system, tmp_path) == []


def test_logfont_is_a_92_byte_logfontw():
    font = appearance.logfont("MS Sans Serif", 8, 96, appearance.WEIGHT_BOLD)
    assert len(font) == 92
    height, _, _, _, weight = struct.unpack_from("<5l", font)
    assert (height, weight) == (-11, 700)
    assert font[28:].decode("utf-16-le").rstrip("\0") == "MS Sans Serif"
    assert font[26] == appearance.NONANTIALIASED_QUALITY


def test_logfont_scales_with_dpi():
    assert struct.unpack_from("<l", appearance.logfont("A", 8, 192))[0] == -21


def test_logfont_truncates_a_long_face_and_stays_terminated():
    font = appearance.logfont("X" * 40, 8, 96)
    assert len(font) == 92
    assert font[-2:] == b"\0\0"


def test_twips_are_negative_and_scaled():
    assert appearance.twips(18, 96) == "-270"
    assert appearance.twips(18, 192) == "-540"


def test_font_effects_turn_smoothing_off():
    effects = appearance.font_effects("MS Sans Serif", 8, 96)
    assert SetParam("font_smoothing", 0) in effects
    fonts = {e.name for e in effects if isinstance(e, SetRegistry)}
    assert fonts == {
        "CaptionFont",
        "SmCaptionFont",
        "MenuFont",
        "StatusFont",
        "MessageFont",
        "IconFont",
    }


def test_metric_effects_write_twips():
    [effect] = appearance.metric_effects({"CaptionHeight": 18}, 96)
    assert effect.value == RegValue("sz", "-270")


def test_no_animation_effects_turn_every_setting_off():
    effects = appearance.no_animation_effects()
    assert all(e.value == 0 for e in effects if isinstance(e, SetParam))
    assert any(isinstance(e, SetRegistry) and e.name == "MinAnimate" for e in effects)


def test_compact_taskbar_left_aligns_and_hides_extras():
    values = {e.name: e.value.data for e in appearance.compact_taskbar_effects()}
    assert values["TaskbarAl"] == 0
    assert values["SearchboxTaskbarMode"] == 0
    assert values["TaskbarSmallIcons"] == 1
