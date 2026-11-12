import io
import struct

from PIL import Image

from skinamp.art.ico import CURSOR_TYPE, ICON_TYPE, encode_cur, encode_dib, encode_ico


def solid(size, color=(255, 0, 0, 255)):
    return Image.new("RGBA", (size, size), color)


def directory(data):
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    entries = [struct.unpack_from("<BBBBHHII", data, 6 + 16 * i) for i in range(count)]
    return reserved, kind, entries


def test_dib_size_and_doubled_height():
    dib = encode_dib(solid(32))
    header_size, width, height, _planes, bits = struct.unpack_from("<IiiHH", dib)
    assert (header_size, width, height, bits) == (40, 32, 64, 32)
    assert len(dib) == 40 + 32 * 32 * 4 + 32 * 4


def test_dib_mask_marks_transparent_pixels():
    transparent = encode_dib(solid(8, (0, 0, 0, 0)))
    opaque = encode_dib(solid(8))
    mask_start = 40 + 8 * 8 * 4
    assert transparent[mask_start] == 0xFF
    assert opaque[mask_start] == 0x00


def test_dib_stores_bgra_bottom_up():
    image = solid(2, (0, 0, 0, 255))
    image.putpixel((0, 1), (1, 2, 3, 255))
    assert encode_dib(image)[40:44] == bytes((3, 2, 1, 255))


def test_ico_directory():
    data = encode_ico([solid(16), solid(32)])
    reserved, kind, entries = directory(data)
    assert (reserved, kind, len(entries)) == (0, ICON_TYPE, 2)
    assert [entry[0] for entry in entries] == [16, 32]
    assert entries[1][7] == entries[0][7] + entries[0][6]


def test_ico_is_readable_by_an_independent_decoder():
    with Image.open(io.BytesIO(encode_ico([solid(16), solid(32)]))) as loaded:
        assert loaded.format == "ICO"
        assert (32, 32) in loaded.info["sizes"]


def test_cur_directory_carries_each_hotspot():
    data = encode_cur([(solid(32), (6, 1)), (solid(64), (12, 2))])
    _, kind, entries = directory(data)
    assert kind == CURSOR_TYPE
    assert [(entry[4], entry[5]) for entry in entries] == [(6, 1), (12, 2)]


def test_cur_is_readable_by_an_independent_decoder():
    with Image.open(io.BytesIO(encode_cur([(solid(32), (0, 0))]))) as loaded:
        assert loaded.format == "CUR"
        assert loaded.size == (32, 32)
