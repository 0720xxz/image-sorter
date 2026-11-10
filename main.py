#!/usr/bin/env python3
"""Image Sorter - entry point.

    python main.py                     # open the GUI
    python main.py --cli --source DIR  # command line mode (see cli.py --help)
"""

from __future__ import annotations

import sys


def _enable_dpi_awareness() -> None:
    """Crisp text on high-DPI Windows displays; must run before Tk starts."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001 - older Windows
            ctypes.windll.user32.SetProcessDPIAware()
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ImageSorter.App.1"
        )
    except Exception:  # noqa: BLE001
        pass


def _fatal(message: str) -> int:
    try:
        import tkinter.messagebox as mb

        mb.showerror("启动失败", message)
    except Exception:  # noqa: BLE001
        print(message, file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] == "--cli":
        from cli import main as cli_main

        return cli_main(args[1:])
    if args:
        from cli import main as cli_main

        return cli_main(args)

    _enable_dpi_awareness()
    try:
        from imagesorter.gui import run
    except ImportError as exc:
        return _fatal(
            "无法加载图形界面（tkinter）。\n\n"
            f"详细信息：{exc}\n\n"
            "如果用官方 Python 安装包，请重新运行安装程序并勾选 tcl/tk。"
        )
    try:
        return run()
    except Exception as exc:  # noqa: BLE001
        return _fatal(f"程序异常退出：{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
