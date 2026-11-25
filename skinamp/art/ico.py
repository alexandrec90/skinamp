"""Encoders for Windows `.ico` and `.cur` files.

Pillow writes `.ico` but not `.cur`, so both are done here with the one layout they
share. Frames are 32-bit DIBs rather than PNG: the cursor loader is the older code path,
and DIB frames are what it has always accepted.
"""

import struct
from collections.abc import Sequence

from PIL import Image

ICON_TYPE = 1
CURSOR_TYPE = 2
DIRECTORY_SIZE = 6
ENTRY_SIZE = 16
OPAQUE_FROM = 128


def _mask_row(pixels: bytes) -> bytes:
    """One row of the AND mask: 1 bit per pixel, 1 = transparent, padded to 4 bytes."""
    width = len(pixels)
    packed = bytearray((width + 31) // 32 * 4)
    for x, alpha in enumerate(pixels):
        if alpha < OPAQUE_FROM:
            packed[x // 8] |= 0x80 >> (x % 8)
    return bytes(packed)


def encode_dib(image: Image.Image) -> bytes:
    """A headered 32-bit bottom-up bitmap followed by its AND mask."""
    width, height = image.size
    flipped = image.convert("RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    bgra = flipped.tobytes("raw", "BGRA")
    alpha = flipped.getchannel("A").tobytes()
    mask = b"".join(_mask_row(alpha[row * width : (row + 1) * width]) for row in range(height))
    # The height is doubled: an icon DIB counts the colour rows and the mask rows.
    header = struct.pack(
        "<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, len(bgra) + len(mask), 0, 0, 0, 0
    )
    return header + bgra + mask


def _encode(kind: int, frames: Sequence[tuple[Image.Image, int, int]]) -> bytes:
    offset = DIRECTORY_SIZE + ENTRY_SIZE * len(frames)
    directory = struct.pack("<HHH", 0, kind, len(frames))
    bodies = []
    for image, first, second in frames:
        body = encode_dib(image)
        width, height = image.size
        directory += struct.pack(
            "<BBBBHHII", width % 256, height % 256, 0, 0, first, second, len(body), offset
        )
        bodies.append(body)
        offset += len(body)
    return directory + b"".join(bodies)


def encode_ico(frames: Sequence[Image.Image]) -> bytes:
    return _encode(ICON_TYPE, [(frame, 1, 32) for frame in frames])


def encode_cur(frames: Sequence[tuple[Image.Image, tuple[int, int]]]) -> bytes:
    """Each frame carries its own hotspot, in that frame's pixels."""
    return _encode(CURSOR_TYPE, [(frame, hot[0], hot[1]) for frame, hot in frames])
