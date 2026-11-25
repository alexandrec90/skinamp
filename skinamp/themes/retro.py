"""The Retro theme: a mid-90s desktop."""

from pathlib import Path

from PIL import Image

from skinamp.art import sprites
from skinamp.art.pixels import GRAY, NAVY, SILVER, TEAL
from skinamp.effects import Effect
from skinamp.targets import appearance, assets, chrome, retrobar
from skinamp.targets.appearance import Rgb
from skinamp.themes.model import BuildContext, Component, Theme

THEME_ID = "retro"
SCHEME_NAME = "Skinamp Retro"
FONT_FACE = "MS Sans Serif"
FONT_POINTS = 8

COLORS: dict[str, Rgb] = {
    "ActiveBorder": SILVER,
    "ActiveTitle": NAVY,
    "AppWorkspace": GRAY,
    "ButtonDkShadow": (0, 0, 0),
    "ButtonFace": SILVER,
    "ButtonHilight": (255, 255, 255),
    "ButtonLight": (223, 223, 223),
    "ButtonShadow": GRAY,
    "ButtonText": (0, 0, 0),
    "GradientActiveTitle": NAVY,
    "GradientInactiveTitle": GRAY,
    "GrayText": GRAY,
    "Hilight": NAVY,
    "HilightText": (255, 255, 255),
    "InactiveBorder": SILVER,
    "InactiveTitle": GRAY,
    "InactiveTitleText": SILVER,
    "InfoText": (0, 0, 0),
    "InfoWindow": (255, 255, 225),
    "Menu": SILVER,
    "MenuBar": SILVER,
    "MenuHilight": NAVY,
    "MenuText": (0, 0, 0),
    "Scrollbar": SILVER,
    "TitleText": (255, 255, 255),
    "Window": (255, 255, 255),
    "WindowFrame": (0, 0, 0),
    "WindowText": (0, 0, 0),
}

# Pixels at 96 DPI.
METRICS = {
    "BorderWidth": 1,
    "PaddedBorderWidth": 0,
    "CaptionHeight": 18,
    "CaptionWidth": 18,
    "SmCaptionHeight": 15,
    "SmCaptionWidth": 15,
    "MenuHeight": 18,
    "MenuWidth": 18,
    "ScrollHeight": 16,
    "ScrollWidth": 16,
}


def _assets(context: BuildContext) -> Path:
    return context.paths.assets / THEME_ID


def desktop_images() -> dict[str, Image.Image]:
    return {
        "computer": sprites.computer(),
        "documents": sprites.document(),
        "network": sprites.network(),
        "bin_empty": sprites.recycle_bin(),
        "bin_full": sprites.recycle_bin(full=True),
    }


def folder_images() -> dict[str, Image.Image]:
    return {"folder": sprites.folder(), "folder_open": sprites.folder(opened=True)}


def preview() -> dict[str, Image.Image]:
    return {
        "computer": sprites.computer(),
        "folder": sprites.folder(),
        "recycle bin": sprites.recycle_bin(),
        "document": sprites.document(),
        "cursor": sprites.cursors()["Arrow"].image,
        "hourglass": sprites.cursors()["Wait"].image,
    }


def _prepare_cursors(context: BuildContext) -> None:
    assets.write_cursors(_assets(context) / "cursors")


def _cursor_effects(context: BuildContext) -> list[Effect]:
    return assets.cursor_effects(_assets(context) / "cursors", SCHEME_NAME)


def _machine_assets(context: BuildContext) -> Path:
    return context.paths.machine_assets / THEME_ID


def _prepare_icons(context: BuildContext) -> None:
    folder = _assets(context)
    assets.write_icons(desktop_images(), folder / "icons")
    shortcuts = context.system.list_shortcuts()
    assets.write_shortcut_icons(context.system, shortcuts, folder / "shortcuts")


def _icon_effects(context: BuildContext) -> list[Effect]:
    folder = _assets(context)
    return [
        *assets.desktop_icon_effects(folder / "icons"),
        *assets.shortcut_effects(context.system, folder / "shortcuts", context.planning),
    ]


def _prepare_system_icons(context: BuildContext) -> None:
    folder = _machine_assets(context)
    assets.write_icons(folder_images(), folder / "icons")
    shortcuts = context.system.machine.list_shortcuts()
    assets.write_shortcut_icons(context.system, shortcuts, folder / "shortcuts")


def _system_icon_effects(context: BuildContext) -> list[Effect]:
    folder = _machine_assets(context)
    return [
        *assets.folder_icon_effects(folder / "icons"),
        *assets.machine_shortcut_effects(context.system, folder / "shortcuts", context.planning),
    ]


def _color_effects(_context: BuildContext) -> list[Effect]:
    return [*appearance.color_effects(COLORS), *appearance.accent_effects(NAVY, GRAY)]


def _desktop_effects(context: BuildContext) -> list[Effect]:
    return [
        *appearance.wallpaper_safety_effects(context.system, context.paths.backups),
        *appearance.solid_background_effects(TEAL),
    ]


def _font_effects(context: BuildContext) -> list[Effect]:
    dpi = context.system.dpi()
    return [
        *appearance.font_effects(FONT_FACE, FONT_POINTS, dpi),
        *appearance.metric_effects(METRICS, dpi),
    ]


def _motion_effects(_context: BuildContext) -> list[Effect]:
    return appearance.no_animation_effects()


def _prepare_taskbar(context: BuildContext) -> None:
    retrobar.prepare(context.paths)


def _taskbar_effects(_context: BuildContext) -> list[Effect]:
    return [*appearance.compact_taskbar_effects(), *retrobar.effects()]


def _taskbar_blocker(_context: BuildContext) -> str | None:
    return retrobar.unsupported_reason()


def _chrome_effects(_context: BuildContext) -> list[Effect]:
    return chrome.effects(chrome.user_data_dir())


def _chrome_blocker(_context: BuildContext) -> str | None:
    if not chrome.profiles(chrome.user_data_dir()):
        return "Chrome has no profile on this PC"
    return None


THEME = Theme(
    id=THEME_ID,
    name="Retro",
    description="Grey bevels, navy title bars, a teal desktop and chunky pixels.",
    preview=preview,
    components=(
        Component(
            "colors",
            "Window colours",
            "Navy title bars, grey controls and light mode.",
            _color_effects,
        ),
        Component(
            "desktop", "Desktop", "Replaces the wallpaper with solid teal.", _desktop_effects
        ),
        Component(
            "cursors",
            "Mouse cursors",
            "A full set of pixel-art cursors.",
            _cursor_effects,
            _prepare_cursors,
        ),
        Component(
            "fonts",
            "Fonts and borders",
            "Bitmap system font, no ClearType, compact title bars and scrollbars.",
            _font_effects,
        ),
        Component("motion", "Animations", "Turns off fades and shadows.", _motion_effects),
        Component(
            "icons",
            "Icons",
            "New desktop icons, and pixelates your own shortcuts.",
            _icon_effects,
            _prepare_icons,
        ),
        Component(
            "system_icons",
            "Folders and all-users icons",
            "Folder icons, and shortcuts shared by everyone on this PC. Affects every account. "
            "Explorer restarts here and on undo, so the taskbar blinks.",
            _system_icon_effects,
            _prepare_system_icons,
            needs_admin=True,
        ),
        Component(
            "taskbar",
            "Taskbar",
            "Runs RetroBar, a free third-party taskbar with a Start button. "
            "Downloads about 95 MB, removed again on undo.",
            _taskbar_effects,
            _prepare_taskbar,
            _taskbar_blocker,
        ),
        Component(
            "chrome",
            "Google Chrome",
            "Grey browser colours. Chrome closes and reopens with your tabs, here and on undo.",
            _chrome_effects,
            blocker=_chrome_blocker,
            closes=(chrome.PROCESS,),
        ),
    ),
)
