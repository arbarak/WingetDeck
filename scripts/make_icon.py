"""Draw assets/wingetdeck.ico from the app's own box picture. Standard library only.

    python scripts/make_icon.py OUTPUT.ico
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

from rich.color import Color

from wingetdeck.ui.pixels import BOX, PALETTE

SIZES = (16, 32, 48, 256)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _png(size: int) -> bytes:
    width = max(len(row) for row in BOX)
    height = len(BOX)
    scale = size / max(width, height)
    left = (size - width * scale) / 2
    top = (size - height * scale) / 2
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            column, line = int((x - left) // scale), int((y - top) // scale)
            mark = BOX[line][column] if 0 <= line < height and 0 <= column < width else "."
            if mark in PALETTE:
                rows += bytes(Color.parse(PALETTE[mark]).get_truecolor()) + b"\xff"
            else:
                rows += b"\x00\x00\x00\x00"
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _chunk(b"IEND", b"")
    )


def write_icon(path: Path) -> None:
    images = [(size, _png(size)) for size in SIZES]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = len(out) + 16 * len(images)
    for size, data in images:
        side = 0 if size == 256 else size  # 0 means 256 in this format
        out += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out + b"".join(data for _, data in images))


if __name__ == "__main__":
    write_icon(Path(sys.argv[1]))
