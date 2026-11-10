"""把巡检截图拼成一张总览图。

    python tools/contact_sheet.py docs/shots docs/shots-overview.png
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def read_png(path: Path) -> tuple[int, int, int, list[bytes]]:
    raw = path.read_bytes()
    pos, idat, width, height, bpp = 8, b"", 0, 0, 3
    while pos < len(raw):
        length = struct.unpack(">I", raw[pos:pos + 4])[0]
        kind = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, _depth, color_type = struct.unpack(">IIBB", data[:10])
            bpp = 3 if color_type == 2 else 4
        elif kind == b"IDAT":
            idat += data
        elif kind == b"IEND":
            break
        pos += 12 + length

    buf = zlib.decompress(idat)
    stride = width * bpp
    rows: list[bytes] = []
    prev = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filt = buf[cursor]
        cursor += 1
        line = bytearray(buf[cursor:cursor + stride])
        cursor += stride
        if filt == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif filt == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif filt == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, bpp, rows


def write_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    payload = b"".join(b"\x00" + row for row in rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(payload, 9))
        + chunk(b"IEND", b"")
    )


def scale(rows: list[bytes], width: int, height: int, bpp: int, factor: float):
    new_w = int(width * factor)
    new_h = int(height * factor)
    out = []
    step = 1.0 / factor
    for y in range(new_h):
        src_y = min(int(y * step), height - 1)
        line = rows[src_y]
        row = bytearray()
        for x in range(new_w):
            src_x = min(int(x * step), width - 1)
            offset = src_x * bpp
            row += line[offset:offset + 3]
        out.append(bytes(row))
    return new_w, new_h, out


def main(argv: list[str]) -> int:
    src_dir = Path(argv[1] if len(argv) > 1 else "docs/shots")
    out_path = Path(argv[2] if len(argv) > 2 else "docs/shots-overview.png")
    files = sorted(src_dir.glob("*.png"))
    if not files:
        print("没有截图")
        return 1

    factor = 0.42
    pad = 10
    cols = 3
    tiles = []
    for path in files:
        width, height, bpp, rows = read_png(path)
        w, h, small = scale(rows, width, height, bpp, factor)
        tiles.append((w, h, small))

    tile_w = max(t[0] for t in tiles)
    tile_h = max(t[1] for t in tiles)
    rows_count = (len(tiles) + cols - 1) // cols
    sheet_w = cols * tile_w + (cols + 1) * pad
    sheet_h = rows_count * tile_h + (rows_count + 1) * pad

    canvas = [bytearray(b"\x20" * (sheet_w * 3)) for _ in range(sheet_h)]
    for index, (w, h, small) in enumerate(tiles):
        col = index % cols
        row = index // cols
        x0 = pad + col * (tile_w + pad)
        y0 = pad + row * (tile_h + pad)
        for y in range(h):
            target = canvas[y0 + y]
            target[(x0) * 3:(x0 + w) * 3] = small[y]
    write_png(out_path, sheet_w, sheet_h, [bytes(r) for r in canvas])
    print(f"{out_path}  {sheet_w}x{sheet_h}  {len(tiles)} 张")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
