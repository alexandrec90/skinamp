"""Skinamp's own pixel art, drawn in code.

Every sprite here is original and generated at runtime. No artwork is copied from any
operating system: those files are not ours to redistribute, and the retro look comes
from the palette and the pixel grid rather than from anyone's specific drawing.
"""

from dataclasses import dataclass

from PIL import Image, ImageDraw

from skinamp.art.pixels import (
    AQUA,
    BLACK,
    BLUE,
    GRAY,
    NAVY,
    RED,
    SILVER,
    TEAL,
    WHITE,
    YELLOW,
)

CANVAS = 32
INK = {"X": BLACK, ".": WHITE, "g": GRAY, "y": YELLOW, "n": NAVY}

ARROW = """
X
XX
X.X
X..X
X...X
X....X
X.....X
X......X
X.......X
X........X
X.....XXXXX
X..X..X
X.X X..X
XX  X..X
X    X..X
     X..X
      X..X
      X..X
       XX
"""

HAND = """
     XX
    X..X
    X..X
    X..X
    X..XXX
    X..X..XXX
    X..X..X..XX
 XX X..X..X..X.X
X..XX........X.X
X...X..........X
 X.............X
 X.............X
  X............X
  X...........X
   X.........X
   X.........X
   XXXXXXXXXXX
"""

HOURGLASS = """
XXXXXXXXXXXXXXX
X.............X
XXXXXXXXXXXXXXX
 X...........X
 X..yyyyyyy..X
 X...yyyyy...X
  X...yyy...X
   X...y...X
    X..y..X
     X.y.X
     X...X
    X..y..X
   X...y...X
  X...yyy...X
 X..yyyyyyy..X
 X.yyyyyyyyy.X
 X...........X
XXXXXXXXXXXXXXX
X.............X
XXXXXXXXXXXXXXX
"""

IBEAM = """
 ... ...
.XXX.XXX.
 ...X...
   .X.
   .X.
   .X.
   .X.
   .X.
   .X.
   .X.
   .X.
   .X.
   .X.
   .X.
   .X.
   .X.
 ...X...
.XXX.XXX.
 ... ...
"""

CROSS = """
         .
        .X.
        .X.
        .X.
        .X.
        .X.
        .X.
   ......X......
  .XXXXXXXXXXXXX.
   ......X......
        .X.
        .X.
        .X.
        .X.
        .X.
        .X.
         .
"""

VERTICAL = """
     X
    X.X
   X...X
  X.....X
 X.......X
XXXX...XXXX
   X...X
   X...X
   X...X
   X...X
   X...X
   X...X
XXXX...XXXX
 X.......X
  X.....X
   X...X
    X.X
     X
"""

DIAGONAL = """
XXXXXXX
X....X
X...X
X....X
X.X...X
XX X...X
X   X...X
     X...X
      X...X   X
       X...X XX
        X...X.X
         X....X
          X...X
         X....X
        XXXXXXX
"""

QUESTION = """
  XXXXX
 X.....X
X..XXX..X
X..X X..X
 XX X...X
   X...X
   X..X
   XXX
   X..X
   XXXX
"""

SMALL_GLASS = """
XXXXXXX
X.....X
 X.y.X
  X.X
 X.y.X
X.yyy.X
XXXXXXX
"""


@dataclass(frozen=True)
class Cursor:
    image: Image.Image
    hotspot: tuple[int, int]


def render(art: str) -> Image.Image:
    """Turn a text grid into an RGBA image. A space is a transparent pixel."""
    rows = art.strip("\n").splitlines()
    width = max(len(row) for row in rows)
    image = Image.new("RGBA", (width, len(rows)), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, pixel in enumerate(row):
            if pixel != " ":
                image.putpixel((x, y), (*INK[pixel], 255))
    return image


def _on_canvas(*layers: tuple[Image.Image, tuple[int, int]]) -> Image.Image:
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    for layer, position in layers:
        canvas.alpha_composite(layer, position)
    return canvas


def _centred(art: Image.Image) -> Cursor:
    left = (CANVAS - art.width) // 2
    top = (CANVAS - art.height) // 2
    return Cursor(_on_canvas((art, (left, top))), (left + art.width // 2, top + art.height // 2))


def _no_entry() -> Image.Image:
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, 19, 19), fill=WHITE)
    draw.ellipse((1, 1, 18, 18), fill=RED)
    draw.ellipse((4, 4, 15, 15), fill=WHITE)
    draw.line((4, 4, 15, 15), fill=RED, width=3)
    return image


def _crosshair_arrows() -> Image.Image:
    vertical = render(VERTICAL)
    image = Image.new("RGBA", (18, 18), (0, 0, 0, 0))
    image.alpha_composite(vertical, (3, 0))
    image.alpha_composite(vertical.rotate(90, expand=True), (0, 3))
    return image


def cursors() -> dict[str, Cursor]:
    """Every cursor role Windows has, keyed by its `Control Panel\\Cursors` value name."""
    arrow = render(ARROW)
    vertical = render(VERTICAL)
    diagonal = render(DIAGONAL)
    return {
        "Arrow": Cursor(_on_canvas((arrow, (0, 0))), (0, 0)),
        "Help": Cursor(_on_canvas((arrow, (0, 0)), (render(QUESTION), (12, 12))), (0, 0)),
        "AppStarting": Cursor(_on_canvas((arrow, (0, 0)), (render(SMALL_GLASS), (13, 13))), (0, 0)),
        "Hand": Cursor(_on_canvas((render(HAND), (0, 0))), (6, 0)),
        "Wait": _centred(render(HOURGLASS)),
        "IBeam": _centred(render(IBEAM)),
        "Crosshair": _centred(render(CROSS)),
        "NWPen": Cursor(_on_canvas((arrow.rotate(-90, expand=True), (0, 0))), (0, 0)),
        "No": _centred(_no_entry()),
        "UpArrow": _centred(vertical.crop((0, 0, vertical.width, 9))),
        "SizeNS": _centred(vertical),
        "SizeWE": _centred(vertical.rotate(90, expand=True)),
        "SizeNWSE": _centred(diagonal),
        "SizeNESW": _centred(diagonal.transpose(Image.Transpose.FLIP_LEFT_RIGHT)),
        "SizeAll": _centred(_crosshair_arrows()),
    }


def _sheet() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def computer() -> Image.Image:
    image, draw = _sheet()
    draw.rectangle((5, 3, 26, 19), fill=SILVER, outline=BLACK)
    draw.rectangle((8, 6, 23, 16), fill=TEAL, outline=BLACK)
    draw.line((6, 4, 25, 4), fill=WHITE)
    draw.rectangle((12, 20, 19, 21), fill=GRAY, outline=BLACK)
    draw.rectangle((3, 22, 28, 28), fill=SILVER, outline=BLACK)
    draw.line((4, 23, 27, 23), fill=WHITE)
    draw.rectangle((16, 25, 25, 26), fill=BLACK)
    return image


def folder(opened: bool = False) -> Image.Image:
    image, draw = _sheet()
    draw.rectangle((3, 6, 13, 10), fill=YELLOW, outline=BLACK)
    draw.rectangle((3, 9, 28, 26), fill=YELLOW, outline=BLACK)
    draw.line((4, 10, 27, 10), fill=WHITE)
    draw.line((27, 11, 27, 25), fill=GRAY)
    draw.line((4, 25, 27, 25), fill=GRAY)
    if opened:
        draw.polygon(((3, 26), (9, 14), (31, 14), (25, 26)), fill=YELLOW, outline=BLACK)
        draw.line((10, 15, 29, 15), fill=WHITE)
    return image


def recycle_bin(full: bool = False) -> Image.Image:
    image, draw = _sheet()
    if full:
        draw.polygon(((9, 9), (13, 2), (20, 4), (23, 9)), fill=WHITE, outline=BLACK)
        draw.line((13, 5, 19, 7), fill=BLUE)
    draw.polygon(((6, 9), (25, 9), (23, 29), (8, 29)), fill=SILVER, outline=BLACK)
    draw.line((7, 11, 24, 11), fill=WHITE)
    for x in (11, 15, 19):
        draw.line((x, 13, x, 26), fill=GRAY)
    return image


def document() -> Image.Image:
    image, draw = _sheet()
    draw.polygon(((7, 3), (20, 3), (25, 8), (25, 28), (7, 28)), fill=WHITE, outline=BLACK)
    draw.polygon(((20, 3), (20, 8), (25, 8)), fill=SILVER, outline=BLACK)
    for y in range(11, 26, 3):
        draw.line((10, y, 22, y), fill=NAVY)
    return image


def network() -> Image.Image:
    image, draw = _sheet()
    draw.rectangle((3, 3, 15, 13), fill=SILVER, outline=BLACK)
    draw.rectangle((5, 5, 13, 11), fill=AQUA, outline=BLACK)
    draw.rectangle((16, 15, 28, 25), fill=SILVER, outline=BLACK)
    draw.rectangle((18, 17, 26, 23), fill=AQUA, outline=BLACK)
    draw.line((9, 14, 9, 28), fill=BLACK)
    draw.line((9, 28, 22, 28), fill=BLACK)
    draw.line((22, 26, 22, 28), fill=BLACK)
    return image
