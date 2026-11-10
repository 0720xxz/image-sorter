#!/usr/bin/env python3
"""Render the GUI under Xvfb and save a PNG screenshot.

Development helper: Xvfb keeps its framebuffer in an XWD file (``-fbdir``),
which this script decodes with the standard library alone.

    Xvfb :99 -screen 0 1280x900x24 -fbdir /tmp/fb -nolisten tcp &
    DISPLAY=:99 python tools/grab_screenshot.py docs/screenshot.png
"""

from __future__ import annotations

import struct

import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples  # noqa: E402
from imagesorter import gui  # noqa: E402


def _channel(value: int, mask: int) -> int:
    if not mask:
        return 0
    shift = (mask & -mask).bit_length() - 1
    return (value & mask) >> shift


def xwd_to_png(xwd: Path, out: Path, crop: tuple[int, int, int, int] | None = None) -> tuple[int, int]:
    raw = xwd.read_bytes()
    (header_size, _version, _fmt, _depth, width, height, _xoff, byte_order,
     _unit, _bit_order, _pad, bpp, stride, _vclass, red_mask, green_mask,
     blue_mask, _bits_rgb, _cmap_entries, ncolors, _ww, _wh, _wx, _wy, _bw) = struct.unpack(
        ">25I", raw[:100])

    pos = header_size + ncolors * 12
    step = max(bpp // 8, 1)
    order = "little" if byte_order == 0 else "big"

    left, top, right, bottom = crop or (0, 0, width, height)
    right = min(right, width)
    bottom = min(bottom, height)
    rows = []
    for y in range(top, bottom):
        line = raw[pos + y * stride: pos + y * stride + stride]
        row = bytearray()
        for x in range(left, right):
            chunk = line[x * step:(x + 1) * step]
            value = int.from_bytes(chunk, order) if chunk else 0
            row += bytes((
                _channel(value, red_mask),
                _channel(value, green_mask),
                _channel(value, blue_mask),
            ))
        rows.append(bytes(row))

    payload = b"".join(b"\x00" + row for row in rows)
    out.parent.mkdir(parents=True, exist_ok=True)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", right - left, bottom - top, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(payload, 9))
        + chunk(b"IEND", b"")
    )
    out.write_bytes(png)
    return right - left, bottom - top


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else ROOT / "docs" / "screenshot.png"
    fbdir = Path("/tmp/fb")

    tmp = tempfile.TemporaryDirectory()
    source = Path(tmp.name) / "photos"
    make_samples.make_samples(source)

    gui.messagebox.askyesno = lambda *a, **k: True
    gui.messagebox.showinfo = lambda *a, **k: None

    app = gui.App()
    app.geometry("1040x720+20+20")
    app.var_source.set(str(source))
    app.var_same.set(False)
    app._toggle_same()
    app.var_target.set(str(gui.default_output_dir()))
    app._start_scan()

    deadline = time.time() + 30
    while time.time() < deadline and app.plan is None:
        app.update()
        time.sleep(0.02)
    for _ in range(40):
        app.update()
        time.sleep(0.02)

    frame = fbdir / "Xvfb_screen0"
    if not frame.exists():
        print(f"找不到 framebuffer: {frame}（Xvfb 需要 -fbdir {fbdir}）", file=sys.stderr)
        app.destroy()
        return 1

    size = xwd_to_png(frame, target, crop=(20, 20, 1060, 740))
    print(f"已保存 {target}  {size[0]}x{size[1]}")

    settings_png = target.with_name("settings.png")
    dialog = gui.AdvancedDialog(app)
    for _ in range(30):
        app.update()
        time.sleep(0.02)
    x, y = dialog.winfo_rootx(), dialog.winfo_rooty()
    w, h = dialog.winfo_width(), dialog.winfo_height()
    size = xwd_to_png(frame, settings_png, crop=(x, y, x + w, y + h))
    print(f"已保存 {settings_png}  {size[0]}x{size[1]}")
    dialog.destroy()

    app.destroy()
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
