"""Drive the GUI through a full run and grab screenshots at random moments.

    Xvfb :99 -screen 0 1280x900x24 -fbdir /tmp/fb -nolisten tcp &
    DISPLAY=:99 python tools/gui_tour.py docs/shots

Also checks geometry while it goes: text that overflows its container and
widgets that grew past the window are reported as layout problems.
"""

from __future__ import annotations

import random
import shutil
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

FB_DIR = Path("/tmp/fb")
WINDOW = (1040, 720, 20, 20)  # w, h, x, y


def read_fb():
    """Full XWD header, in order - ncolors must come from field 19, not 23."""
    raw = (FB_DIR / "Xvfb_screen0").read_bytes()
    (header_size, _version, _fmt, _depth, width, height, _xoff, byte_order,
     _unit, _bit_order, _pad, bpp, stride, _vclass, red_mask, green_mask,
     blue_mask, _bits_rgb, _cmap_entries, ncolors, _ww, _wh, _wx, _wy,
     _bw) = struct.unpack(">25I", raw[:100])
    return dict(raw=raw, width=width, height=height, bpp=bpp,
                byte_order=byte_order, stride=stride,
                start=header_size + ncolors * 12,
                masks=(red_mask, green_mask, blue_mask))


def grab(out: Path, crop=(20, 20, 1060, 740)) -> tuple[int, int]:
    fb = read_fb()
    raw, stride, start = fb["raw"], fb["stride"], fb["start"]
    width, height, bpp = fb["width"], fb["height"], fb["bpp"]
    step = max(bpp // 8, 1)
    order = "little" if fb["byte_order"] == 0 else "big"
    red, green, blue = fb["masks"]
    left, top, right, bottom = crop
    right, bottom = min(right, width), min(bottom, height)
    rows = []
    for y in range(top, bottom):
        line = raw[start + y * stride: start + y * stride + stride]
        row = bytearray()
        for x in range(left, right):
            value = int.from_bytes(line[x * step:(x + 1) * step], order) if step else 0
            row += bytes((
                (value & red) >> 16,
                (value & green) >> 8,
                value & blue,
            ))
        rows.append(bytes(row))
    payload = b"".join(b"\x00" + r for r in rows)
    out.parent.mkdir(parents=True, exist_ok=True)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    out.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", right - left, bottom - top, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(payload, 6))
        + chunk(b"IEND", b"")
    )
    return right - left, bottom - top


def build_library(base: Path) -> Path:
    src = base / "照片库"
    src.mkdir(parents=True, exist_ok=True)
    jpg = make_samples.wrap_jpeg(make_samples.exif_block("2019-05-06 12:34:56"))
    png = make_samples.wrap_png(make_samples.exif_block("2021-11-02 08:15:00"))
    heic = make_samples.wrap_heic(make_samples.exif_block("2023-08-14 10:20:30"))

    for i in range(900):
        (src / f"IMG_{i:04d}.jpg").write_bytes(jpg)
    for i in range(200):
        (src / f"截图 {i:03d}.png").write_bytes(png)
    for i in range(120):
        (src / f"iPhone_{i:03d}.heic").write_bytes(heic)
    for i in range(150):
        (src / f"mmexport{1687654321000 + i * 86400000}.jpg").write_bytes(
            make_samples.wrap_plain_jpeg())
    for i in range(60):
        (src / f"无题_{i:02d}.jpg").write_bytes(make_samples.wrap_plain_jpeg())

    for name in ("甲", "乙", "丙"):
        sub = src / name
        sub.mkdir(exist_ok=True)
        (sub / "same.jpg").write_bytes(jpg)
    return src


def check_layout(app, tag: str, notes: list[str]) -> None:
    width = app.winfo_width()
    height = app.winfo_height()
    if width < 900 or height < 600:
        notes.append(f"[{tag}] 窗口尺寸异常 {width}x{height}")

    status = app.var_status.get()
    # 状态栏用 9pt 中文字体，一个字约 12px，留出进度条的 180px
    if len(status) * 12 > width - 260:
        notes.append(f"[{tag}] 状态栏文字可能溢出：{status}")

    tree_width = app.tree.winfo_width()
    columns = sum(int(app.tree.column(c, "width")) for c in app.tree["columns"])
    if columns > tree_width + 4:
        notes.append(f"[{tag}] 表格列宽 {columns} 超过可视宽度 {tree_width}")

    card_bottom = app.lbl_summary.winfo_rooty() + app.lbl_summary.winfo_height()
    tree_top = app.tree.winfo_rooty()
    if card_bottom > tree_top:
        notes.append(f"[{tag}] 卡片与表格重叠：{card_bottom} > {tree_top}")


def main(argv: list[str]) -> int:
    outdir = Path(argv[1]) if len(argv) > 1 else ROOT / "docs" / "shots"
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    random.seed()  # 每次跑抽的位置都不一样
    tmp = tempfile.TemporaryDirectory()
    src = build_library(Path(tmp.name))
    files = sum(1 for p in src.rglob("*") if p.is_file())
    print(f"素材 {files} 个文件")

    gui.messagebox.askyesno = lambda *a, **k: True
    gui.messagebox.showinfo = lambda *a, **k: None
    gui.messagebox.showwarning = lambda *a, **k: print("   [warn]", a[0] if a else "")
    gui.messagebox.showerror = lambda *a, **k: print("   [err]", a)

    app = gui.App()
    app.geometry(f"{WINDOW[0]}x{WINDOW[1]}+{WINDOW[2]}+{WINDOW[3]}")
    app.var_source.set(str(src))
    app.var_same.set(False)
    app._toggle_same()
    app.var_target.set(str(Path(tmp.name) / "输出"))
    for _ in range(30):
        app.update()
        time.sleep(0.01)

    shots: list[str] = []
    notes: list[str] = []

    def shot(label: str) -> None:
        index = len(shots) + 1
        name = f"{index:02d}-{label}.png"
        grab(outdir / name)
        shots.append(name)
        print(f"   截图 {name}")

    def pump(seconds: float, label: str, until=None, quota: int = 1) -> None:
        """Run for a while and grab `quota` frames at random moments inside it."""
        deadline = time.time() + seconds
        taken = 0
        spread = max(seconds / 3.0, 0.12)
        next_at = time.time() + random.uniform(0.04, spread)
        while time.time() < deadline:
            app.update()
            if taken < quota and time.time() >= next_at:
                shot(label)
                taken += 1
                next_at = time.time() + random.uniform(0.06, spread)
            if until and until():
                break
            time.sleep(0.01)
        while taken < quota:          # 阶段太短，补拍到配额
            app.update()
            shot(label)
            taken += 1

    pump(0.6, "就绪", quota=1)
    check_layout(app, "就绪", notes)

    app._start_scan()
    pump(25, "扫描中", until=lambda: app.plan is not None, quota=2)
    check_layout(app, "扫描完成", notes)

    for index in range(3):
        app.tree.yview_moveto(0.33 * index)
        pump(0.28, "浏览列表", quota=1 if index == 1 else 0)
    app.tabs.select(1)
    pump(0.4, "日志", quota=1)
    app.tabs.select(0)
    pump(0.25, "计划", quota=0)

    dialog = gui.AdvancedDialog(app)
    pump(0.5, "高级设置", quota=1)
    dialog._reset()
    pump(0.25, "恢复默认", quota=0)
    dialog.destroy()
    pump(0.2, "关闭对话框", quota=0)

    app.tabs.select(1)      # 整理时用户会去看日志
    pump(0.2, "切到日志", quota=0)
    app._start_exec()
    pump(60, "整理中", until=lambda: not app.busy and app.plan is None, quota=2)

    app.var_source.set(str(Path(tmp.name) / "输出"))
    app.var_same.set(True)
    app._toggle_same()
    pump(0.5, "整理后", quota=1)
    app._undo_latest()
    pump(40, "撤销中", until=lambda: not app.busy, quota=1)

    while len(shots) < 10:
        pump(0.12, "收尾", quota=1)

    check_layout(app, "结束", notes)
    app.destroy()
    tmp.cleanup()

    print("\n截图 %d 张:" % len(shots))
    for name in shots:
        print("  ", name)
    print("\n布局检查:")
    for line in notes or ["  没发现问题"]:
        print("  ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
