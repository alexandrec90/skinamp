"""The themes Skinamp ships."""

from skinamp.themes import retro
from skinamp.themes.model import Theme

THEMES: dict[str, Theme] = {retro.THEME.id: retro.THEME}


def get_theme(theme_id: str) -> Theme:
    try:
        return THEMES[theme_id]
    except KeyError:
        raise ValueError(f"Unknown theme {theme_id!r}") from None
