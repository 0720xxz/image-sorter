#!/usr/bin/env python3
"""Manual GUI check - needs a real display (X11, Xvfb or Windows desktop).

Not part of the unit test run; use it when touching gui.py:

    Xvfb :99 -screen 0 1280x900x24 &
    DISPLAY=:99 python tests/manual_gui_check.py

It drives the real widgets through scan -> execute -> undo and prints what
happened. Any TclError raised by a bad widget option fails here instead of
in front of a user.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples  # noqa: E402
from imagesorter import gui  # noqa: E402


def pump(app, seconds: float, until=None) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        if until and until():
            return
        time.sleep(0.02)


def main() -> int:
    tmp = tempfile.TemporaryDirectory()
    source = Path(tmp.name) / "photos"
    make_samples.make_samples(source)

    answer = {"yes": True}
    gui.messagebox.askyesno = lambda *a, **k: answer["yes"]
    gui.messagebox.showinfo = lambda *a, **k: None
    gui.messagebox.showwarning = lambda *a, **k: None
    gui.messagebox.showerror = lambda *a, **k: print("ERROR DIALOG:", a[1] if len(a) > 1 else a)

    app = gui.App()
    app.var_source.set(str(source))
    app.var_same.set(True)
    pump(app, 0.3)

    print("[1] 扫描")
    app._start_scan()
    pump(app, 30, until=lambda: app.plan is not None)
    assert app.plan is not None, "扫描没有完成"
    print("    待整理:", len(app.plan.todo), "跳过:", len(app.plan.skipped))
    print("    状态栏:", app.var_status.get())
    print("    规则摘要:", app.lbl_summary.cget("text"))
    print("    预览行数:", len(app.tree.get_children()))

    print("[1.5] 高级设置")
    app._open_advanced()
    app.update()
    print("    摘要:", app.lbl_summary.cget("text"))
    for child in app.winfo_children():
        if child.winfo_class() == "Toplevel":
            child.destroy()
    pump(app, 0.2)

    print("[2] 整理")
    app._start_exec()
    pump(app, 30, until=lambda: app.plan is None and not app.busy)
    months = sorted(p.name for p in source.iterdir() if p.is_dir() and p.name[:4].isdigit())
    print("    生成目录:", months)
    assert months, "没有生成月份目录"
    assert not any(p.is_file() and p.suffix == ".jpg" for p in source.iterdir()), "源目录还有未整理的图片"

    print("[3] 撤销")
    app._undo_latest()
    pump(app, 30, until=lambda: not app.busy)
    restored = sorted(p.name for p in source.iterdir() if p.is_file())
    print("    恢复文件:", len(restored))
    assert len(restored) == 8, f"撤销后文件数不对: {len(restored)}"

    print("[4] 关闭")
    app._on_close()
    tmp.cleanup()
    print("GUI 冒烟测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
