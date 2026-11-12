import pytest

from skinamp.art import sprites

ROLES = set(
    "Arrow Help AppStarting Wait Crosshair IBeam NWPen No SizeNS "
    "SizeWE SizeNWSE SizeNESW SizeAll UpArrow Hand".split()
)


def test_render_maps_ink_and_transparency():
    image = sprites.render("\nX.\n y\n")
    assert image.size == (2, 2)
    assert image.getpixel((0, 0)) == (0, 0, 0, 255)
    assert image.getpixel((1, 0)) == (255, 255, 255, 255)
    assert image.getpixel((0, 1))[3] == 0
    assert image.getpixel((1, 1))[:3] == sprites.YELLOW


def test_cursors_cover_every_windows_role():
    assert set(sprites.cursors()) == ROLES


@pytest.mark.parametrize("name", sorted(ROLES))
def test_each_cursor_fits_and_its_hotspot_is_on_canvas(name):
    cursor = sprites.cursors()[name]
    assert isinstance(cursor, sprites.Cursor)
    assert cursor.image.size == (sprites.CANVAS, sprites.CANVAS)
    assert cursor.image.getbbox() is not None
    x, y = cursor.hotspot
    assert 0 <= x < sprites.CANVAS and 0 <= y < sprites.CANVAS


def test_arrow_points_at_its_hotspot():
    cursor = sprites.cursors()["Arrow"]
    assert cursor.image.getpixel(cursor.hotspot)[3] == 255


@pytest.mark.parametrize(
    "image",
    [
        sprites.computer(),
        sprites.folder(),
        sprites.folder(opened=True),
        sprites.recycle_bin(),
        sprites.recycle_bin(full=True),
        sprites.document(),
        sprites.network(),
    ],
)
def test_icons_are_drawn_on_the_canvas(image):
    assert image.size == (sprites.CANVAS, sprites.CANVAS)
    assert image.getbbox() is not None


def test_variants_differ():
    assert sprites.folder().tobytes() != sprites.folder(opened=True).tobytes()
    assert sprites.recycle_bin().tobytes() != sprites.recycle_bin(full=True).tobytes()
