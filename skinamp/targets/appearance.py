"""Colours, wallpaper, fonts, window metrics and shell behaviour: the registry-driven look.

Everything here is data becoming `SetRegistry`/`SetParam` effects, so nothing in this
file can touch the machine by itself.
"""

import struct
from collections.abc import Mapping
from pathlib import Path

from skinamp.effects import Effect, PreserveFile, PreserveRegistry, SetParam, SetRegistry
from skinamp.system.api import Refresh, RegValue, System

COLORS_KEY = r"Control Panel\Colors"
DESKTOP_KEY = r"Control Panel\Desktop"
METRICS_KEY = r"Control Panel\Desktop\WindowMetrics"
DWM_KEY = r"Software\Microsoft\Windows\DWM"
PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
ACCENT_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
WALLPAPERS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers"
ADVANCED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
SEARCH_KEY = r"Software\Microsoft\Windows\CurrentVersion\Search"
SPOTLIGHT_KEY = r"Software\Microsoft\Windows\CurrentVersion\DesktopSpotlight\Settings"
SPOTLIGHT_VALUE = "EnabledState"
SPOTLIGHT_DISABLED = 0
WALLPAPER_HISTORY = tuple(f"BackgroundHistoryPath{index}" for index in range(5))
PREFERENCES_MASK = "UserPreferencesMask"

type Rgb = tuple[int, int, int]

BACKGROUND_TYPE_SOLID = 1
WEIGHT_NORMAL = 400
WEIGHT_BOLD = 700
DEFAULT_CHARSET = 1
NONANTIALIASED_QUALITY = 3
FACE_BYTES = 64
FULLY_OPAQUE = 0xFF
ANIMATION_PARAMS = (
    "client_area_animation",
    "combobox_animation",
    "cursor_shadow",
    "drag_full_windows",
    "drop_shadow",
    "listbox_smooth_scrolling",
    "menu_animation",
    "selection_fade",
    "tooltip_animation",
)


def rgb_text(color: Rgb) -> str:
    return " ".join(str(channel) for channel in color)


def abgr(color: Rgb, alpha: int = FULLY_OPAQUE) -> int:
    """A colour as DWM's accent values store it: 0xAABBGGRR."""
    red, green, blue = color
    return alpha << 24 | blue << 16 | green << 8 | red


def argb(color: Rgb, alpha: int = FULLY_OPAQUE) -> int:
    """A colour as DWM's colorization values store it: 0xAARRGGBB."""
    red, green, blue = color
    return alpha << 24 | red << 16 | green << 8 | blue


def color_effects(colors: Mapping[str, Rgb]) -> list[Effect]:
    return [
        SetRegistry(COLORS_KEY, name, RegValue("sz", rgb_text(color)), Refresh.COLORS)
        for name, color in colors.items()
    ]


def accent_palette(color: Rgb) -> bytes:
    """Eight RGBA swatches. Windows derives its shades from these."""
    return bytes((*color, FULLY_OPAQUE)) * 8


def accent_effects(active: Rgb, inactive: Rgb) -> list[Effect]:
    """Coloured, opaque title bars and light-mode apps."""
    settings = (
        (DWM_KEY, "ColorPrevalence", 1),
        (DWM_KEY, "AccentColor", abgr(active)),
        (DWM_KEY, "AccentColorInactive", abgr(inactive)),
        (DWM_KEY, "ColorizationColor", argb(active)),
        (DWM_KEY, "ColorizationAfterglow", argb(active)),
        (ACCENT_KEY, "AccentColorMenu", abgr(active)),
        (PERSONALIZE_KEY, "EnableTransparency", 0),
        (PERSONALIZE_KEY, "AppsUseLightTheme", 1),
        (PERSONALIZE_KEY, "SystemUsesLightTheme", 1),
    )
    effects: list[Effect] = [
        SetRegistry(key, name, RegValue("dword", value), Refresh.SETTINGS)
        for key, name, value in settings
    ]
    palette = RegValue("binary", accent_palette(active))
    effects.append(SetRegistry(ACCENT_KEY, "AccentPalette", palette, Refresh.SETTINGS))
    return effects


def wallpaper_safety_effects(system: System, backups: Path) -> list[Effect]:
    """What a plain restore of the wallpaper path would lose.

    Windows Spotlight deletes old images as it rotates, so the current picture may be gone
    by the time the user undoes, and it keeps its own on/off state outside the wallpaper.
    Turning it off also makes Windows push the old picture onto Settings' recent list,
    within a second and before any refresh runs, so that list has to be in the journal.
    """
    effects: list[Effect] = [PreserveRegistry(WALLPAPERS_KEY, name) for name in WALLPAPER_HISTORY]
    current = system.reg_read(DESKTOP_KEY, "Wallpaper")
    if current is not None and current.data:
        path = Path(str(current.data))
        if path.exists():
            effects.append(PreserveFile(path, backups / path.name, Refresh.WALLPAPER))
    if system.reg_read(SPOTLIGHT_KEY, SPOTLIGHT_VALUE) is not None:
        disabled = RegValue("dword", SPOTLIGHT_DISABLED)
        effects.append(SetRegistry(SPOTLIGHT_KEY, SPOTLIGHT_VALUE, disabled, Refresh.WALLPAPER))
    return effects


def solid_background_effects(color: Rgb) -> list[Effect]:
    return [
        SetRegistry(COLORS_KEY, "Background", RegValue("sz", rgb_text(color)), Refresh.COLORS),
        SetRegistry(
            WALLPAPERS_KEY,
            "BackgroundType",
            RegValue("dword", BACKGROUND_TYPE_SOLID),
            Refresh.WALLPAPER,
        ),
        SetRegistry(DESKTOP_KEY, "Wallpaper", RegValue("sz", ""), Refresh.WALLPAPER),
    ]


def logfont(face: str, points: int, dpi: int, weight: int = WEIGHT_NORMAL) -> bytes:
    """A 92-byte LOGFONTW, with antialiasing off so bitmap faces stay crisp."""
    height = -round(points * dpi / 72)
    name = face.encode("utf-16-le")[: FACE_BYTES - 2].ljust(FACE_BYTES, b"\0")
    return (
        struct.pack(
            "<5l8B",
            height,
            0,
            0,
            0,
            weight,
            0,
            0,
            0,
            DEFAULT_CHARSET,
            0,
            0,
            NONANTIALIASED_QUALITY,
            0,
        )
        + name
    )


def twips(pixels: int, dpi: int) -> str:
    """Registry metrics are negative twips, scaled here for the display."""
    return str(-15 * round(pixels * dpi / 96))


def font_effects(face: str, points: int, dpi: int) -> list[Effect]:
    weights = {
        "CaptionFont": WEIGHT_BOLD,
        "SmCaptionFont": WEIGHT_BOLD,
        "MenuFont": WEIGHT_NORMAL,
        "StatusFont": WEIGHT_NORMAL,
        "MessageFont": WEIGHT_NORMAL,
        "IconFont": WEIGHT_NORMAL,
    }
    effects: list[Effect] = [
        SetRegistry(
            METRICS_KEY,
            name,
            RegValue("binary", logfont(face, points, dpi, weight)),
            Refresh.METRICS,
        )
        for name, weight in weights.items()
    ]
    effects.append(SetParam("font_smoothing", 0))
    return effects


def metric_effects(metrics: Mapping[str, int], dpi: int) -> list[Effect]:
    return [
        SetRegistry(METRICS_KEY, name, RegValue("sz", twips(pixels, dpi)), Refresh.METRICS)
        for name, pixels in metrics.items()
    ]


def no_animation_effects() -> list[Effect]:
    effects: list[Effect] = [PreserveRegistry(DESKTOP_KEY, PREFERENCES_MASK)]
    effects.extend(SetParam(name, 0) for name in ANIMATION_PARAMS)
    effects.append(SetRegistry(METRICS_KEY, "MinAnimate", RegValue("sz", "0"), Refresh.METRICS))
    return effects


def compact_taskbar_effects() -> list[Effect]:
    """The built-in taskbar, simplified. Also the fallback if the replacement cannot run."""
    settings = (
        (ADVANCED_KEY, "TaskbarSmallIcons", 1),
        (ADVANCED_KEY, "ShowTaskViewButton", 0),
        (ADVANCED_KEY, "TaskbarAl", 0),
        (SEARCH_KEY, "SearchboxTaskbarMode", 0),
    )
    return [
        SetRegistry(key, name, RegValue("dword", value), Refresh.SETTINGS)
        for key, name, value in settings
    ]
