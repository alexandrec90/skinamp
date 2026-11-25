"""Turning modern artwork into chunky low-colour pixel art. Pure image functions."""

from collections.abc import Iterable

from PIL import Image, ImageChops

ICON_SIZES = (16, 24, 32, 48, 64, 96)

BLACK = (0, 0, 0)
MAROON = (128, 0, 0)
GREEN = (0, 128, 0)
OLIVE = (128, 128, 0)
NAVY = (0, 0, 128)
PURPLE = (128, 0, 128)
TEAL = (0, 128, 128)
SILVER = (192, 192, 192)
GRAY = (128, 128, 128)
RED = (255, 0, 0)
LIME = (0, 255, 0)
YELLOW = (255, 255, 0)
BLUE = (0, 0, 255)
FUCHSIA = (255, 0, 255)
AQUA = (0, 255, 255)
WHITE = (255, 255, 255)

DARK_COLORS = (BLACK, MAROON, GREEN, OLIVE, NAVY, PURPLE, TEAL, SILVER)
BRIGHT_COLORS = (GRAY, RED, LIME, YELLOW, BLUE, FUCHSIA, AQUA, WHITE)
VGA_16 = (*DARK_COLORS, *BRIGHT_COLORS)
# Without teal, the colour of the desktop behind every icon: common blues snap to it
# otherwise, and most of the icon disappears.
ICON_COLORS = tuple(color for color in VGA_16 if color != TEAL)


def palette_image(colors: Iterable[tuple[int, int, int]]) -> Image.Image:
    palette = Image.new("P", (1, 1))
    flat = [channel for color in colors for channel in color]
    palette.putpalette(flat + [0] * (768 - len(flat)))
    return palette


def pixelate(image: Image.Image, grid: int = 24) -> Image.Image:
    """Shrink to `grid` pixels square, snap to the icon colours, harden the edges."""
    small = image.convert("RGBA").resize((grid, grid), Image.Resampling.BOX)
    alpha = small.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    palette = palette_image(ICON_COLORS)
    snapped = small.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE)
    result = snapped.convert("RGBA")
    result.putalpha(alpha)
    return result


def scale(image: Image.Image, size: int) -> Image.Image:
    """Resize without smoothing, so pixels stay hard-edged."""
    return image.resize((size, size), Image.Resampling.NEAREST)


def icon_frames(image: Image.Image, sizes: Iterable[int] = ICON_SIZES) -> list[Image.Image]:
    return [scale(image, size) for size in sizes]


def alpha_from_renders(on_black: Image.Image, on_white: Image.Image) -> Image.Image:
    """Recover RGBA from one image drawn over black and again over white.

    A GDI device bitmap loses the icon's alpha channel. Over black a pixel contributes
    `alpha * colour`, over white `alpha * colour + (1 - alpha)`, so the difference between
    the two renders is exactly `1 - alpha`.
    """
    difference = ImageChops.difference(on_white.convert("RGB"), on_black.convert("RGB"))
    alpha = ImageChops.invert(difference.convert("L"))
    result = on_black.convert("RGBA")
    result.putalpha(alpha)
    return result
