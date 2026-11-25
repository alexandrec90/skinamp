from PIL import Image

from skinamp.art.pixels import (
    BLUE,
    VGA_16,
    alpha_from_renders,
    icon_frames,
    palette_image,
    pixelate,
    scale,
)


def gradient():
    image = Image.new("RGBA", (32, 32))
    for x in range(32):
        for y in range(32):
            image.putpixel((x, y), (x * 8, y * 8, 128, 255))
    return image


def test_palette_image_holds_the_colours():
    palette = palette_image(VGA_16).getpalette()
    assert tuple(palette[:3]) == VGA_16[0]
    assert tuple(palette[45:48]) == VGA_16[15]


def test_pixelate_shrinks_to_the_grid():
    assert pixelate(gradient(), grid=24).size == (24, 24)


def distinct(image):
    return {color for _count, color in image.getcolors(1 << 16)}


def test_pixelate_uses_only_vga_colours():
    colors = {color[:3] for color in distinct(pixelate(gradient()))}
    assert colors <= set(VGA_16)


def test_pixelate_never_uses_the_desktop_colour():
    # Live finding: VS Code's and Edge's blues snapped to teal, the colour of the desktop
    # behind them, and most of each icon vanished.
    vs_code_blue = Image.new("RGBA", (24, 24), (0, 122, 204, 255))
    assert {color[:3] for color in distinct(pixelate(vs_code_blue))} == {BLUE}


def test_pixelate_hardens_alpha():
    soft = Image.new("RGBA", (24, 24), (255, 0, 0, 200))
    faint = Image.new("RGBA", (24, 24), (255, 0, 0, 40))
    assert distinct(pixelate(soft).getchannel("A")) == {255}
    assert distinct(pixelate(faint).getchannel("A")) == {0}


def test_scale_keeps_hard_edges():
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 255))
    image.putpixel((1, 0), (255, 255, 255, 255))
    grown = scale(image.resize((2, 2), Image.Resampling.NEAREST), 8)
    assert {color[:3] for color in distinct(grown)} == {(0, 0, 0), (255, 255, 255)}


def test_icon_frames_covers_each_size():
    assert [frame.size for frame in icon_frames(gradient(), (16, 48))] == [(16, 16), (48, 48)]


def test_alpha_from_renders_recovers_opaque_and_clear():
    on_black = Image.new("RGB", (2, 1), (0, 0, 0))
    on_white = Image.new("RGB", (2, 1), (255, 255, 255))
    on_black.putpixel((0, 0), (10, 20, 30))
    on_white.putpixel((0, 0), (10, 20, 30))
    result = alpha_from_renders(on_black, on_white)
    assert result.getpixel((0, 0)) == (10, 20, 30, 255)
    assert result.getpixel((1, 0))[3] == 0
