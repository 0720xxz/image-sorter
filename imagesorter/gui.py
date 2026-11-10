"""Tkinter desktop UI - flat light theme in the spirit of modern desktop apps.

The look is built from three pieces:

* a ``clam`` ttk baseline whose colours are replaced wholesale (no more
  Win95 bevels),
* hand drawn Canvas widgets for the controls that matter most visually
  (rounded buttons, rounded text fields, a slim progress bar),
* one dark "card" for the log so the console reads as a console.

All behaviour lives in the App methods below; only the presentation layer
differs from a plain ttk build.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:  # the stub used by the headless smoke test has no tkinter.font
    from tkinter import font as tkfont
except ImportError:  # pragma: no cover
    tkfont = None  # type: ignore[assignment]

from . import __version__
from .config import DEFAULTS, load_settings, save_settings
from .organizer import execute, summarize_undo, undo, undo_files
from .scanner import (
    CONFLICT_LABELS,
    FALLBACK_LABELS,
    MEDIA_EXTS,
    MODE_LABELS,
    Options,
    Plan,
    build_plan,
)

MAX_ROWS = 5000
MAX_LOG_LINES = 4000

# --- palette -------------------------------------------------------------

BG = "#FFFFFF"
SURFACE = "#F6F5F3"
SURFACE_HOVER = "#EDEBE8"
BORDER = "#E4E1DC"
BORDER_STRONG = "#D5D1CB"
TEXT = "#1F1E1D"
TEXT_SUB = "#8B8781"
ACCENT = "#C4623F"
ACCENT_SOFT = "#F7EAE4"
PRIMARY = "#1F1E1D"
PRIMARY_HOVER = "#3B3835"
DANGER = "#B4322B"
LOG_BG = "#151514"
LOG_FG = "#E6E3DF"
TRACK = "#EDEAE6"


def _win_font_candidates() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei")
    return ("Noto Sans CJK SC", "WenQuanYi Zen Hei", "PingFang SC", "DejaVu Sans")


def app_dir() -> Path:
    """Folder holding main.py, or the exe when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def default_output_dir() -> Path:
    """Default output: a folder next to the program, not inside the photos."""
    return app_dir() / "整理结果"


def _mono_candidates() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("Cascadia Mono", "Consolas", "DejaVu Sans Mono")
    return ("DejaVu Sans Mono", "Noto Sans Mono")


# --- canvas widgets ------------------------------------------------------


def _int_or(value, default: int) -> int:
    """Coerce Tk geometry to int without exploding on stubs or unmapped widgets."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text_width(widget, text: str, font) -> int:
    if tkfont is not None:
        try:
            return int(tkfont.Font(root=widget, font=font).measure(text))
        except Exception:  # noqa: BLE001
            pass
    return len(text) * 13


class RoundedButton(tk.Canvas):
    """Flat button with rounded corners, hover state and a disabled look."""

    KINDS = ("primary", "secondary", "ghost")

    def __init__(self, master, text: str, command=None, kind: str = "secondary",
                 height: int = 34, radius: int = 8, font=None, min_width: int = 0,
                 parent_bg: str = BG):
        super().__init__(master, highlightthickness=0, bd=0, cursor="hand2", takefocus=0)
        self._text = text
        self._command = command
        self._kind = kind if kind in self.KINDS else "secondary"
        self._radius = radius
        self._height = height
        self._font = font
        self._parent_bg = parent_bg
        self._state = "normal"
        self._hover = False
        self._pressed = False
        width = max(self._measure(text) + 34, min_width)
        self._width = width
        super().configure(width=width, height=height, bg=parent_bg)
        self.enabled = True
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # -- behaviour
    def _measure(self, text: str) -> int:
        return _text_width(self, text, self._font)

    def invoke(self) -> None:
        if self.enabled and callable(self._command):
            self._command()

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event=None) -> None:
        if not self.enabled:
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _event=None) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed:
            self.invoke()

    # -- drawing
    def _palette(self) -> tuple[str, str, str]:
        if not self.enabled:
            return SURFACE, "#B9B4AD", BORDER
        if self._kind == "primary":
            bg = PRIMARY_HOVER if (self._hover or self._pressed) else PRIMARY
            return bg, "#FFFFFF", bg
        if self._kind == "ghost":
            bg = SURFACE if (self._hover or self._pressed) else self._parent_bg
            return bg, TEXT_SUB if not self._hover else TEXT, self._parent_bg
        bg = SURFACE_HOVER if (self._hover or self._pressed) else SURFACE
        return bg, TEXT, BORDER

    def _draw(self) -> None:
        self.enabled = self._state != "disabled"
        bg, fg, border = self._palette()
        width = _int_or(self._width, 80)
        height = _int_or(self._height, 34)
        self.delete("all")
        self._rounded_rect(0.5, 0.5, width - 0.5, height - 0.5, self._radius,
                           fill=bg, outline=border)
        self.create_text(width / 2, height / 2 + 0.5, text=self._text, fill=fg,
                         font=self._font)

    def _rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1 + r, x2, y2 - r,
            x2 - r, y2, x1 + r, y2, x1, y2 - r, x1, y1 + r,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    # -- ttk-ish compatibility
    def configure(self, **kwargs):
        state = kwargs.pop("state", None)
        text = kwargs.pop("text", None)
        if state is not None:
            self._state = state
        if text is not None:
            self._text = text
        if kwargs:
            super().configure(**kwargs)
        self._draw()

    config = configure

    def cget(self, key):
        if key == "state":
            return self._state
        return super().cget(key)


class RoundedEntry(tk.Canvas):
    """Borderless entry sitting on a rounded surface; focus darkens the ring."""

    def __init__(self, master, textvariable, height: int = 36, radius: int = 8,
                 font=None, parent_bg: str = BG):
        super().__init__(master, highlightthickness=0, bd=0, takefocus=0)
        self._height = height
        self._radius = radius
        self._state = "normal"
        self._focused = False
        super().configure(height=height, bg=parent_bg)
        self.entry = tk.Entry(
            self, textvariable=textvariable, bd=0, relief="flat", bg=SURFACE,
            fg=TEXT, insertbackground=TEXT, highlightthickness=0, font=font,
            disabledbackground=SURFACE, disabledforeground=TEXT_SUB,
            selectbackground=ACCENT_SOFT, selectforeground=TEXT,
        )
        self.entry.place(x=13, y=8, relwidth=1.0, width=-26, height=height - 16)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    def _on_focus_in(self, _event=None) -> None:
        self._focused = True
        self._draw()

    def _on_focus_out(self, _event=None) -> None:
        self._focused = False
        self._draw()

    def _draw(self) -> None:
        width = max(_int_or(self.winfo_width(), 200), 1)
        height = self._height
        self.delete("all")
        outline = BORDER_STRONG if self._focused else SURFACE
        points = [
            self._radius, 0.5, width - self._radius, 0.5, width - 0.5, self._radius,
            width - 0.5, height - self._radius, width - self._radius, height - 0.5,
            self._radius, height - 0.5, 0.5, height - self._radius, 0.5, self._radius,
        ]
        self.create_polygon(points, smooth=True, fill=SURFACE, outline=outline)

    def configure(self, **kwargs):
        state = kwargs.pop("state", None)
        if state is not None:
            self._state = state
            self.entry.configure(state=state)
        if kwargs:
            super().configure(**kwargs)
        self._draw()

    config = configure

    def set_focus(self) -> None:
        self.entry.focus_set()


class CheckBox(tk.Canvas):
    """Flat checkbox: rounded square, accent fill and a real tick mark."""

    SIZE = 17
    GAP = 9

    def __init__(self, master, text: str, variable, command=None, font=None,
                 parent_bg: str = BG, wrap_width: int = 0):
        super().__init__(master, highlightthickness=0, bd=0, cursor="hand2", takefocus=0)
        self._var = variable
        self._text = text
        self._command = command
        self._font = font
        self._hover = False
        width = self.SIZE + self.GAP + _text_width(self, text, font) + 2
        super().configure(width=width, height=24, bg=parent_bg)
        self._draw()
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        try:
            self._trace = variable.trace_add("write", lambda *_a: self._draw())
        except Exception:  # noqa: BLE001
            self._trace = None

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._draw()

    def _toggle(self, _event=None) -> None:
        try:
            self._var.set(not bool(self._var.get()))
        except Exception:  # noqa: BLE001
            return
        if callable(self._command):
            self._command()

    def _draw(self) -> None:
        try:
            checked = bool(self._var.get())
        except Exception:  # noqa: BLE001
            checked = False
        self.delete("all")
        size = self.SIZE
        x, y = 1, 3
        if checked:
            fill = ACCENT if not self._hover else "#B0563A"
            outline = fill
        else:
            fill = SURFACE_HOVER if self._hover else BG
            outline = BORDER_STRONG
        r = 4
        points = [
            x + r, y, x + size - r, y, x + size, y + r, x + size, y + size - r,
            x + size - r, y + size, x + r, y + size, x, y + size - r, x, y + r,
        ]
        self.create_polygon(points, smooth=True, fill=fill, outline=outline)
        if checked:
            self.create_line(x + 4, y + 8.5, x + 7.2, y + 12,
                             x + 13, y + 5, fill="#FFFFFF", width=2,
                             capstyle="round", joinstyle="round")
        self.create_text(size + self.GAP, 12, text=self._text, anchor="w",
                         fill=TEXT, font=self._font)


class RadioButton(tk.Canvas):
    """Matching radio: thin ring, accent dot when selected."""

    SIZE = 17
    GAP = 9

    def __init__(self, master, text: str, variable, value: str, font=None,
                 parent_bg: str = BG):
        super().__init__(master, highlightthickness=0, bd=0, cursor="hand2", takefocus=0)
        self._var = variable
        self._value = value
        self._text = text
        self._font = font
        self._hover = False
        width = self.SIZE + self.GAP + _text_width(self, text, font) + 2
        super().configure(width=width, height=24, bg=parent_bg)
        self._draw()
        self.bind("<Button-1>", self._select)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        try:
            variable.trace_add("write", lambda *_a: self._draw())
        except Exception:  # noqa: BLE001
            pass

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._draw()

    def _select(self, _event=None) -> None:
        try:
            self._var.set(self._value)
        except Exception:  # noqa: BLE001
            pass

    def _draw(self) -> None:
        try:
            active = str(self._var.get()) == str(self._value)
        except Exception:  # noqa: BLE001
            active = False
        self.delete("all")
        cx, cy, r = self.SIZE / 2 + 1, 12, self.SIZE / 2 - 1
        if active:
            ring = ACCENT
        elif self._hover:
            ring = "#B5B0A9"
        else:
            ring = BORDER_STRONG
        self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=ring, width=1.4,
                         fill=BG)
        if active:
            self.create_oval(cx - 3.6, cy - 3.6, cx + 3.6, cy + 3.6,
                             fill=ACCENT, outline=ACCENT)
        self.create_text(self.SIZE + self.GAP, 12, text=self._text, anchor="w",
                         fill=TEXT, font=self._font)


class _SegmentedTab(tk.Canvas):
    def __init__(self, master, title: str, font, on_click, parent_bg: str = BG):
        super().__init__(master, highlightthickness=0, bd=0, cursor="hand2", takefocus=0)
        self._title = title
        self._font = font
        self._active = False
        self._hover = False
        self._width = _text_width(self, title, font) + 30
        super().configure(width=self._width, height=38, bg=parent_bg)
        self.bind("<Button-1>", lambda _e: on_click())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._draw()

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._draw()

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self._draw()

    def _draw(self) -> None:
        width = _int_or(self._width, 100)
        height = 38
        self.delete("all")
        if self._active:
            fg = TEXT
        elif self._hover:
            fg = TEXT
        else:
            fg = TEXT_SUB
        self.create_text(width / 2, height / 2 - 2, text=self._title, fill=fg, font=self._font)
        if self._active:
            self.create_rectangle(13, height - 4, width - 13, height - 2,
                                  fill=ACCENT, outline=ACCENT)


class SegmentedTabs(tk.Frame):
    """Two-to-three section switcher with an accent underline."""

    def __init__(self, master, font, parent_bg: str = BG):
        super().__init__(master, bg=parent_bg)
        self._font = font
        self._parent_bg = parent_bg
        self._tabs: list[tuple[_SegmentedTab, tk.Widget]] = []
        self._index = -1
        self._bar = tk.Frame(self, bg=parent_bg)
        self._bar.pack(side="top", fill="x")
        self._body = tk.Frame(self, bg=parent_bg)
        self._body.pack(side="top", fill="both", expand=True)

    def add(self, title: str, widget: tk.Widget) -> None:
        index = len(self._tabs)
        tab = _SegmentedTab(self._bar, title, self._font,
                            on_click=lambda i=index: self.select(i), parent_bg=self._parent_bg)
        tab.pack(side="left", padx=(0, 6))
        self._tabs.append((tab, widget))
        if self._index < 0:
            self.select(0)

    def select(self, index: int) -> None:
        if not (0 <= index < len(self._tabs)):
            return
        for i, (tab, widget) in enumerate(self._tabs):
            if i == index:
                widget.pack(fill="both", expand=True)
                tab.set_active(True)
            else:
                widget.pack_forget()
                tab.set_active(False)
        self._index = index


class SlimProgress(tk.Canvas):
    """Thin rounded progress bar; mimics the ttk API the app calls."""

    def __init__(self, master, length: int = 200, height: int = 6, parent_bg: str = BG):
        super().__init__(master, highlightthickness=0, bd=0)
        self._value = 0.0
        self._maximum = 100.0
        self._mode = "determinate"
        self._phase = 0.0
        self._job = None
        super().configure(width=length, height=height, bg=parent_bg)
        self.bind("<Configure>", lambda _e: self._redraw())
        self._redraw()

    # -- ttk-compatible surface
    def configure(self, **kwargs):
        if "value" in kwargs:
            self._value = float(kwargs.pop("value") or 0)
        if "maximum" in kwargs:
            self._maximum = float(kwargs.pop("maximum") or 1) or 1.0
        if "mode" in kwargs:
            self._mode = kwargs.pop("mode")
        if kwargs:
            super().configure(**kwargs)
        self._redraw()

    config = configure

    def cget(self, key):
        if key == "maximum":
            return self._maximum
        if key == "value":
            return self._value
        return super().cget(key)

    def start(self, interval: int = 30) -> None:
        self._mode = "indeterminate"
        self._phase = 0.0
        self._tick(max(int(interval), 25))

    def stop(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:  # noqa: BLE001
                pass
            self._job = None

    def _tick(self, interval: int) -> None:
        self._phase = (self._phase + 0.035) % 1.0
        self._redraw()
        self._job = self.after(interval, lambda: self._tick(interval))

    # -- drawing
    def _redraw(self) -> None:
        width = max(_int_or(self.winfo_width(), 180), 1)
        height = max(_int_or(self.winfo_height(), 6), 6)
        self.delete("all")
        r = height / 2
        self._bar(0, 0, width, height, r, TRACK)
        if self._mode == "indeterminate":
            span = max(int(width * 0.3), 20)
            travel = width + span
            left = int(self._phase * travel) - span
            start = max(left, 0)
            end = min(left + span, width)
            if end > start:
                self._bar(start, 0, end, height, r, ACCENT)
        else:
            ratio = 0.0 if self._maximum <= 0 else min(max(self._value / self._maximum, 0.0), 1.0)
            filled = int(width * ratio)
            if filled > 1:
                self._bar(0, 0, filled, height, r, ACCENT)

    def _bar(self, x1, y1, x2, y2, r, color) -> None:
        r = min(r, (x2 - x1) / 2, (y2 - y1) / 2) or 0
        if r <= 0.5:
            self.create_rectangle(x1, y1, x2, y2, fill=color, outline=color)
            return
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1 + r, x2, y2 - r,
            x2 - r, y2, x1 + r, y2, x1, y2 - r, x1, y1 + r,
        ]
        self.create_polygon(points, smooth=True, fill=color, outline=color)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("图片整理")
        self.geometry("1040x720")
        self.minsize(960, 640)
        self.configure(bg=BG)

        self.plan: Plan | None = None
        self.events: queue.Queue = queue.Queue()
        self.cancel_flag = threading.Event()
        self.worker: threading.Thread | None = None
        self.busy = False
        self._rows: list = []
        self._rows_root = Path()
        self._row_index = 0
        self._fill_token = 0

        self._build_vars()
        self._build_style()
        self._build_ui()
        self._load_last_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._drain)

    # --- construction ----------------------------------------------------

    def _build_vars(self) -> None:
        settings = load_settings()
        same = bool(settings.get("same", False))
        target = settings["target"] or ("" if same else str(default_output_dir()))
        self.var_source = tk.StringVar(value=settings["source"])
        self.var_target = tk.StringVar(value=target)
        self.var_same = tk.BooleanVar(value=same)
        self.var_mode = tk.StringVar(value=settings["mode"])
        self.var_layout = tk.StringVar(value=settings["layout"])
        self.var_recursive = tk.BooleanVar(value=bool(settings["recursive"]))
        self.var_rename = tk.BooleanVar(value=bool(settings["rename_files"]))
        self.var_prune = tk.BooleanVar(value=bool(settings.get("prune_empty", False)))
        self.var_dedupe = tk.BooleanVar(value=bool(settings.get("delete_duplicates", False)))
        self.var_fallback = tk.StringVar(
            value=FALLBACK_LABELS.get(settings["fallback"], "文件名 → 文件时间"))
        self.var_conflict = tk.StringVar(
            value=CONFLICT_LABELS.get(settings["conflict"], "自动改名（_001）"))
        self.var_ext = tk.StringVar(value=", ".join(sorted(e.lstrip(".") for e in MEDIA_EXTS)))
        self.var_status = tk.StringVar(value="选好文件夹，点「扫描并预览」")

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        family = self._pick_family(_win_font_candidates())
        mono = self._pick_family(_mono_candidates())
        self.font_base = (family, 10)
        self.font_small = (family, 9)
        self.font_bold = (family, 10, "bold")
        self.font_title = (family, 15, "bold")
        self.font_mono = (mono, 9)

        style.configure(".", background=BG, foreground=TEXT, font=self.font_base,
                        borderwidth=0, focuscolor=BG)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Subtle.TLabel", background=BG, foreground=TEXT_SUB, font=self.font_small)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=self.font_title)

        # tables
        style.configure("Treeview", background=BG, fieldbackground=BG, foreground=TEXT,
                        rowheight=30, borderwidth=0, font=self.font_base)
        style.configure("Treeview.Heading", background=BG, foreground=TEXT_SUB,
                        relief="flat", borderwidth=0, font=self.font_small, padding=(10, 10))
        style.map("Treeview", background=[("selected", ACCENT_SOFT)],
                  foreground=[("selected", TEXT)])
        style.map("Treeview.Heading", background=[("active", SURFACE)])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        # tabs
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
        style.configure("TNotebook.Tab", background=BG, foreground=TEXT_SUB,
                        borderwidth=0, padding=(16, 9), font=self.font_base)
        style.map("TNotebook.Tab",
                  background=[("selected", BG), ("active", SURFACE)],
                  foreground=[("selected", TEXT), ("active", TEXT)])

        # inputs
        style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE,
                        foreground=TEXT, arrowcolor=TEXT_SUB, bordercolor=SURFACE,
                        lightcolor=SURFACE, darkcolor=SURFACE, padding=(12, 7),
                        relief="flat", borderwidth=0, arrowsize=13)
        style.map("TCombobox",
                  fieldbackground=[("readonly", SURFACE), ("disabled", SURFACE),
                                   ("active", SURFACE)],
                  background=[("active", SURFACE), ("pressed", SURFACE)],
                  selectbackground=[("readonly", SURFACE)],
                  selectforeground=[("readonly", TEXT)],
                  bordercolor=[("focus", SURFACE), ("active", SURFACE)],
                  lightcolor=[("focus", SURFACE)],
                  darkcolor=[("focus", SURFACE)],
                  arrowcolor=[("active", TEXT)])
        self.option_add("*TCombobox*Listbox.background", BG)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT_SOFT)
        self.option_add("*TCombobox*Listbox.selectForeground", TEXT)
        self.option_add("*TCombobox*Listbox.borderWidth", 1)
        self.option_add("*TCombobox*Listbox.font", self.font_base)

        style.configure("TCheckbutton", background=BG, foreground=TEXT,
                        font=self.font_base, padding=(0, 4), focusthickness=0,
                        indicatorcolor=BG)
        style.map("TCheckbutton",
                  background=[("active", BG)],
                  indicatorcolor=[("selected", ACCENT), ("!selected", BG)],
                  foreground=[("disabled", TEXT_SUB)])
        style.configure("TRadiobutton", background=BG, foreground=TEXT,
                        font=self.font_base, padding=(0, 4), indicatorcolor=BG)
        style.map("TRadiobutton",
                  background=[("active", BG)],
                  indicatorcolor=[("selected", ACCENT), ("!selected", BG)])
        style.configure("Card.TCheckbutton", background=BG)
        style.configure("Card.TRadiobutton", background=BG)

        # scrollbars
        for orient in ("Vertical", "Horizontal"):
            style.layout(
                f"{orient}.TScrollbar",
                [(f"{orient}.Scrollbar.trough", {
                    "sticky": "ns" if orient == "Vertical" else "ew",
                    "children": [
                        (f"{orient}.Scrollbar.thumb",
                         {"expand": "1", "sticky": "nswe"})]})],
            )
            style.configure(
                f"{orient}.TScrollbar", background=SURFACE_HOVER, troughcolor=BG,
                bordercolor=BG, lightcolor=SURFACE_HOVER, darkcolor=SURFACE_HOVER,
                arrowcolor=TEXT_SUB, relief="flat", borderwidth=0, width=9,
            )
            style.map(f"{orient}.TScrollbar",
                      background=[("active", BORDER_STRONG), ("pressed", BORDER_STRONG)])

        self._set_window_icon()

    def _set_window_icon(self) -> None:
        """A rounded accent tile, drawn pixel by pixel - no .ico needed."""
        try:
            size, radius = 32, 9
            image = tk.PhotoImage(width=size, height=size)
            for y in range(size):
                inset = 0
                if y < radius:
                    inset = int(radius - (radius * radius - (radius - y) ** 2) ** 0.5)
                elif y >= size - radius:
                    dy = y - (size - radius - 1)
                    inset = int(radius - (radius * radius - dy * dy) ** 0.5)
                if inset < size:
                    image.put(ACCENT, to=(inset, y, size - inset, y + 1))
            self.iconphoto(True, image)
            self._icon_image = image
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    def _pick_family(self, candidates: tuple[str, ...]) -> str:
        """Use the first installed font so Chinese never renders as boxes."""
        if tkfont is None:
            return "TkDefaultFont"
        try:
            available = set(tkfont.families(self))
        except Exception:  # noqa: BLE001 - headless or trimmed Tk build
            return "TkDefaultFont"
        for name in candidates:
            if name in available:
                return name
        return "TkDefaultFont"

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self._build_header()
        self._build_card()
        self._build_tabs()
        self._build_status()
        self._update_summary()

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 0))
        header.columnconfigure(0, weight=1)

        tk.Label(header, text="图片整理", bg=BG, fg=TEXT,
                 font=self.font_title).grid(row=0, column=0, sticky="w")
        tk.Label(header, text=f"v{__version__}", bg=BG, fg=TEXT_SUB,
                 font=self.font_small).grid(row=0, column=1, sticky="e")
        tk.Label(header, text="按拍摄时间分月归档 · MIT 许可",
                 bg=BG, fg=TEXT_SUB, font=self.font_small).grid(
            row=1, column=0, sticky="w", pady=(2, 0))
        tk.Label(header, text="内战狂热爱好者", bg=BG, fg=TEXT_SUB,
                 font=self.font_small).grid(row=1, column=1, sticky="e", pady=(2, 0))

        tk.Frame(self, bg=BORDER, height=1).grid(row=1, column=0, sticky="ew", pady=(16, 0))

    def _build_card(self) -> None:
        card = tk.Frame(self, bg=BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        card.grid(row=2, column=0, sticky="ew", padx=28, pady=(16, 10))
        card.columnconfigure(1, weight=1)

        tk.Label(card, text="图片文件夹", bg=BG, fg=TEXT, font=self.font_base).grid(
            row=0, column=0, sticky="w", padx=(18, 12), pady=(16, 0))
        self.entry_source = RoundedEntry(card, self.var_source, font=self.font_base)
        self.entry_source.grid(row=0, column=1, sticky="ew", pady=(16, 0))
        RoundedButton(card, "浏览", command=self._pick_source, kind="secondary",
                      height=34, font=self.font_base, min_width=64).grid(
            row=0, column=2, sticky="e", padx=(10, 18), pady=(16, 0))

        tk.Label(card, text="输出到", bg=BG, fg=TEXT, font=self.font_base).grid(
            row=1, column=0, sticky="w", padx=(18, 12), pady=(10, 0))
        self.entry_target = RoundedEntry(card, self.var_target, font=self.font_base)
        self.entry_target.grid(row=1, column=1, sticky="ew", pady=(10, 0))
        RoundedButton(card, "浏览", command=self._pick_target, kind="secondary",
                      height=34, font=self.font_base, min_width=64).grid(
            row=1, column=2, sticky="e", padx=(10, 18), pady=(10, 0))

        CheckBox(card, "直接在原文件夹里整理", self.var_same,
                 command=self._toggle_same, font=self.font_base).grid(
            row=2, column=1, sticky="w", pady=(8, 0))

        tk.Frame(card, bg=BORDER, height=1).grid(
            row=3, column=0, columnspan=3, sticky="ew", padx=18, pady=(14, 0))

        actions = tk.Frame(card, bg=BG)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", padx=18, pady=(14, 0))
        actions.columnconfigure(2, weight=1)

        self.btn_scan = RoundedButton(actions, "扫描并预览", command=self._start_scan,
                                      kind="primary", height=36, font=self.font_base,
                                      parent_bg=BG)
        self.btn_scan.grid(row=0, column=0, sticky="w")

        self.btn_run = RoundedButton(actions, "开始整理", command=self._start_exec,
                                     kind="secondary", height=36, font=self.font_base,
                                     parent_bg=BG)
        self.btn_run.configure(state="disabled")
        self.btn_run.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.btn_stop = RoundedButton(actions, "停止", command=self._request_stop,
                                      kind="ghost", height=36, font=self.font_base,
                                      parent_bg=BG, min_width=56)
        self.btn_stop.configure(state="disabled")
        self.btn_stop.grid(row=0, column=2, sticky="w", padx=(6, 0))

        self.btn_advanced = RoundedButton(actions, "高级设置", command=self._open_advanced,
                                          kind="ghost", height=36, font=self.font_base,
                                          parent_bg=BG)
        self.btn_advanced.grid(row=0, column=3, sticky="e")

        self.btn_undo = RoundedButton(actions, "撤销上次", command=self._undo_latest,
                                      kind="ghost", height=36, font=self.font_base,
                                      parent_bg=BG)
        self.btn_undo.grid(row=0, column=4, sticky="e", padx=(4, 0))

        RoundedButton(actions, "打开文件夹", command=self._open_target, kind="ghost",
                      height=36, font=self.font_base, parent_bg=BG).grid(
            row=0, column=5, sticky="e", padx=(4, 0))

        self.lbl_summary = tk.Label(card, text="", bg=BG, fg=TEXT_SUB,
                                    font=self.font_small, anchor="w")
        self.lbl_summary.grid(row=5, column=0, columnspan=3, sticky="ew",
                              padx=18, pady=(10, 16))

    def _update_summary(self) -> None:
        """One line that tells the user what the hidden rules actually are."""
        settings = self._current_settings()
        parts = [
            MODE_LABELS.get(settings["mode"], settings["mode"]),
            settings["layout"] or "{YYYY}-{MM}",
        ]
        if settings["recursive"]:
            parts.append("含子文件夹")
        if settings["rename_files"]:
            parts.append("按时间重命名")
        fallback = FALLBACK_LABELS.get(settings["fallback"])
        if fallback:
            parts.append(f"无日期时 {fallback}")
        self.lbl_summary.configure(text="规则：" + "  ·  ".join(parts))

    def _build_tabs(self) -> None:
        tabs = SegmentedTabs(self, self.font_base)
        tabs.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 6))

        preview = tk.Frame(tabs, bg=BG)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        columns = ("name", "when", "tag", "dest")
        self.tree = ttk.Treeview(preview, columns=columns, show="headings",
                                 selectmode="browse", height=8)
        for key, title, width, anchor in (
            ("name", "文件", 250, "w"),
            ("when", "拍摄时间", 145, "center"),
            ("tag", "日期来源", 135, "center"),
            ("dest", "放到哪里", 420, "w"),
        ):
            self.tree.heading(key, text=title, anchor=anchor)
            self.tree.column(key, width=width, anchor=anchor, stretch=(key in ("name", "dest")))
        scroll = ttk.Scrollbar(preview, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        tabs.add("计划预览", preview)

        logframe = tk.Frame(tabs, bg=LOG_BG)
        logframe.columnconfigure(0, weight=1)
        logframe.rowconfigure(0, weight=1)
        self.log = tk.Text(
            logframe, wrap="none", font=self.font_mono, height=8, bd=0,
            background=LOG_BG, foreground=LOG_FG, insertbackground=LOG_FG,
            padx=16, pady=12, highlightthickness=0, relief="flat",
            selectbackground="#33312E", selectforeground="#FFFFFF",
        )
        log_scroll = ttk.Scrollbar(logframe, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set, state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll.grid(row=0, column=1, sticky="ns")
        tabs.add("运行日志", logframe)
        self.tabs = tabs

    def _build_status(self) -> None:
        bar = tk.Frame(self, bg=BG)
        bar.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 14))
        bar.columnconfigure(0, weight=1)
        tk.Label(bar, textvariable=self.var_status, bg=BG, fg=TEXT_SUB,
                 font=self.font_small, anchor="w").grid(row=0, column=0, sticky="w")
        self.progress = SlimProgress(bar, length=180, height=6, parent_bg=BG)
        self.progress.grid(row=0, column=1, sticky="e")

    # --- settings --------------------------------------------------------

    def _load_last_settings(self) -> None:
        if self.var_same.get():
            self.entry_target.configure(state="disabled")

    def _toggle_same(self) -> None:
        same = self.var_same.get()
        self.entry_target.configure(state="disabled" if same else "normal")
        if same:
            self.var_target.set("")

    def _current_settings(self) -> dict:
        return {
            "source": self.var_source.get().strip(),
            "target": "" if self.var_same.get() else self.var_target.get().strip(),
            "same": bool(self.var_same.get()),
            "mode": self.var_mode.get(),
            "layout": self.var_layout.get().strip(),
            "recursive": bool(self.var_recursive.get()),
            "fallback": self._key_of(FALLBACK_LABELS, self.var_fallback.get(), "auto"),
            "conflict": self._key_of(CONFLICT_LABELS, self.var_conflict.get(), "rename"),
            "rename_files": bool(self.var_rename.get()),
            "prune_empty": bool(self.var_prune.get()),
            "delete_duplicates": bool(self.var_dedupe.get()),
        }

    @staticmethod
    def _key_of(mapping: dict, label: str, default: str) -> str:
        for key, value in mapping.items():
            if value == label:
                return key
        return default

    # --- validation ------------------------------------------------------

    def _collect_options(self) -> Options | None:
        source_text = self.var_source.get().strip()
        if not source_text:
            messagebox.showwarning("缺少源文件夹", "先选一个图片文件夹。")
            return None
        source = Path(source_text).expanduser()
        if not source.is_dir():
            messagebox.showerror("源文件夹无效", f"这个路径不是文件夹：\n{source}")
            return None

        target_text = "" if self.var_same.get() else self.var_target.get().strip()
        if target_text:
            target = Path(target_text).expanduser()
            if not target.exists():
                if not messagebox.askyesno("创建目标文件夹", f"输出文件夹还不存在，要现在建吗？\n{target}"):
                    return None
                try:
                    target.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    messagebox.showerror("创建失败", str(exc))
                    return None
            elif not target.is_dir():
                messagebox.showerror("目标无效", f"这个输出路径不是文件夹：\n{target}")
                return None

        extensions = self._parse_extensions()
        if not extensions:
            messagebox.showwarning("图片类型为空", "至少写一个扩展名，比如 jpg, png。")
            return None

        layout = self.var_layout.get().strip() or "{YYYY}-{MM}"
        options = Options(
            source=str(source),
            target=str(Path(target_text).expanduser()) if target_text else "",
            mode=self.var_mode.get(),
            layout=layout,
            recursive=bool(self.var_recursive.get()),
            fallback=self._key_of(FALLBACK_LABELS, self.var_fallback.get(), "auto"),
            conflict=self._key_of(CONFLICT_LABELS, self.var_conflict.get(), "rename"),
            rename_files=bool(self.var_rename.get()),
            prune_empty=bool(self.var_prune.get()),
            delete_duplicates=bool(self.var_dedupe.get()),
            extensions=frozenset(extensions),
        )
        save_settings(self._current_settings())
        return options

    def _parse_extensions(self, text: str | None = None) -> set[str]:
        raw = self.var_ext.get() if text is None else text
        result = set()
        for chunk in raw.replace(";", ",").replace(" ", ",").split(","):
            item = chunk.strip().lower()
            if not item:
                continue
            result.add(item if item.startswith(".") else "." + item)
        return result

    # --- worker plumbing -------------------------------------------------

    def _post(self, kind: str, *args) -> None:
        self.events.put((kind, args))

    def _drain(self) -> None:
        while True:
            try:
                kind, args = self.events.get_nowait()
            except queue.Empty:
                break
            handler = getattr(self, f"_on_{kind}", None)
            if handler is None:
                self._log(f"[{kind}] {args}")
                continue
            try:
                handler(*args)
            except Exception as exc:  # noqa: BLE001 - keep the UI alive
                self._log(f"[界面错误] {type(exc).__name__}: {exc}")
        self.after(80, self._drain)

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self.busy = busy
        normal = "disabled" if busy else "normal"
        self.btn_scan.configure(state=normal)
        self.btn_undo.configure(state=normal)
        self.btn_run.configure(state="disabled" if busy or not (self.plan and self.plan.todo) else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")
        if status:
            self.var_status.set(status)

    def _request_stop(self) -> None:
        if self.busy:
            self.cancel_flag.set()
            self.var_status.set("正在停止…（当前文件处理完就停）")

    def _start_worker(self, target, *args) -> None:
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    # --- actions ---------------------------------------------------------

    def _pick_source(self) -> None:
        path = filedialog.askdirectory(title="选择要整理的源文件夹", mustexist=True)
        if path:
            self.var_source.set(os.path.normpath(path))
            if self.var_same.get():
                self.var_target.set("")

    def _pick_target(self) -> None:
        path = filedialog.askdirectory(title="选择输出根文件夹", mustexist=True)
        if path:
            self.var_target.set(os.path.normpath(path))
            self.var_same.set(False)
            self.entry_target.configure(state="normal")

    def _open_advanced(self) -> None:
        if not self.busy:
            AdvancedDialog(self)

    def _start_scan(self) -> None:
        options = self._collect_options()
        if options is None:
            return
        self._clear_plan()
        self.cancel_flag.clear()
        self._set_busy(True, "正在扫描并读取拍摄时间…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._log(f"扫描 {options.source}")

        def work() -> None:
            try:
                plan = build_plan(
                    options,
                    should_cancel=self.cancel_flag.is_set,
                    progress=lambda n, _msg: self._post("progress_text", f"已读取 {n} 个图片文件…"),
                )
            except Exception as exc:  # noqa: BLE001
                self._post("failed", f"扫描失败：{type(exc).__name__}: {exc}")
                return
            self._post("scan_done", plan)

        self._start_worker(work)

    def _start_exec(self) -> None:
        if not self.plan or not self.plan.todo:
            return
        total = len(self.plan.todo)
        mode_key = self.plan.options.mode if self.plan.options else "move"
        mode = MODE_LABELS.get(mode_key, mode_key)
        target = str(self.plan.root)
        if not messagebox.askyesno(
            "确认整理",
            f"即将{mode} {total} 个图片文件到：\n{target}\n\n"
            f"文件夹格式：{self.plan.options.layout if self.plan.options else ''}\n"
            f"{'移动后想反悔就点「撤销上次」。' if mode_key == 'move' else '原文件不会动。'}",
        ):
            return

        self.cancel_flag.clear()
        self._set_busy(True, f"正在{mode}…")
        self.progress.configure(mode="determinate", maximum=max(total, 1), value=0)
        self._log(f"开始{mode}，共 {total} 个文件")

        plan = self.plan

        def on_event(kind: str, item, extra: str) -> None:
            if kind == "error":
                self._post("log", f"[失败] {item.src.name}: {extra}")
            else:
                self._post("log", f"[{extra}] {item.src.name} -> {item.dst}")
                self._post("progress_value", extra)

        def work() -> None:
            try:
                result = execute(plan, on_event=on_event, should_cancel=self.cancel_flag.is_set)
            except Exception as exc:  # noqa: BLE001
                self._post("failed", f"整理中断：{type(exc).__name__}: {exc}")
                return
            self._post("exec_done", result)

        self._start_worker(work)

    def _undo_latest(self) -> None:
        root = self._effective_target()
        if root is None:
            return
        batches = undo_files(root)
        if not batches:
            messagebox.showinfo("没有撤销记录",
                                f"在下面这个目录里没找到撤销记录：\n{root / '.imagesorter_undo'}")
            return
        latest = batches[0]
        if not messagebox.askyesno(
            "撤销上次整理",
            f"将回退最近一次操作：\n{summarize_undo(latest)}\n\n"
            f"记录文件：{latest.name}\n\n继续吗？",
        ):
            return
        self.cancel_flag.clear()
        self._set_busy(True, "正在撤销…")
        self.progress.configure(mode="determinate", maximum=100, value=0)

        def work() -> None:
            def on_event(kind: str, path, extra) -> None:
                if kind == "undo":
                    self._post("log", f"[撤销] {Path(path).name} → {extra}")
                elif kind == "error":
                    self._post("log", f"[失败] {path}: {extra}")

            try:
                result = undo(latest, on_event=on_event)
            except Exception as exc:  # noqa: BLE001
                self._post("failed", f"撤销失败：{type(exc).__name__}: {exc}")
                return
            self._post("undo_done", result)

        self._start_worker(work)

    def _effective_target(self) -> Path | None:
        if self.var_same.get():
            text = self.var_source.get().strip()
        else:
            text = self.var_target.get().strip() or self.var_source.get().strip()
        if not text:
            messagebox.showwarning("缺少文件夹", "请先选择源文件夹。")
            return None
        return Path(text).expanduser().absolute()

    def _open_target(self) -> None:
        root = self._effective_target()
        if root is None:
            return
        if not root.exists():
            messagebox.showinfo("文件夹不存在", str(root))
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(root))  # noqa: S606 - opening a folder is the point
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(root)])
            else:
                subprocess.Popen(["xdg-open", str(root)])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开失败", str(exc))

    # --- event handlers --------------------------------------------------

    def _on_progress_text(self, text: str) -> None:
        self.var_status.set(text)

    def _on_progress_value(self, text: str) -> None:
        try:
            done = int(str(text).split("/")[0])
        except (ValueError, IndexError):
            return
        self.progress.configure(value=done)

    def _on_log(self, text: str) -> None:
        self._log(text)

    def _on_failed(self, text: str) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._set_busy(False, text)
        self._log(text)
        messagebox.showerror("出错了", text)

    def _on_scan_done(self, plan: Plan) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        if plan.cancelled:
            self._clear_plan()
            self._set_busy(False, "已停止扫描")
            self._log("扫描已停止，没有生成计划。")
            return
        self.plan = plan
        self._fill_tree(plan)
        months = plan.month_counts()
        self._log(
            f"找到 {plan.scanned} 个图片，{len(plan.todo)} 个待整理，"
            f"{len(plan.skipped)} 个跳过，分成 {len(months)} 个月份"
        )
        for key, value in months.items():
            self._log(f"    {key}: {value} 个")
        if plan.options and plan.options.mode == "link":
            self._log("链接模式：文件留在原处，输出目录只是引用，不占额外空间")
        summary = f"找到 {plan.scanned} 个图片，{len(plan.todo)} 个待整理"
        if plan.skipped:
            summary += f"，{len(plan.skipped)} 个跳过"
        self._set_busy(False, summary)
        self.btn_run.configure(state="normal" if plan.todo else "disabled")
        if not plan.todo:
            messagebox.showinfo("没有要整理的图片", "这个文件夹里没有需要整理的图片。")

    def _on_exec_done(self, result) -> None:
        self._set_busy(False, f"整理完成 · 成功 {result.done} 个，失败 {result.failed} 个")
        self.progress.configure(value=self.progress.cget("maximum"))
        if result.trashed:
            self._log(f"{result.trashed} 个重复文件已移入 .imagesorter_undo/trash")
        if result.fallbacks:
            self._log(f"{result.fallbacks} 个位置不支持硬链接，已改为复制")
        if result.pruned:
            self._log(f"清理了 {result.pruned} 个空文件夹")
        if result.undo_file:
            self._log(f"撤销记录已写入: {result.undo_file}")
        text = f"成功 {result.done} 个，失败 {result.failed} 个"
        if result.trashed:
            text += f"，重复 {result.trashed} 个"
        if result.cancelled:
            text += "（已按用户要求停止）"
        self.var_status.set("整理完成 · " + text)
        for path, message in result.errors[:8]:
            self._log(f"[失败] {path} -> {message}")
        self._clear_plan()
        messagebox.showinfo("整理完成", text + ("\n\n想反悔就点「撤销上次」。" if result.done else ""))

    def _on_undo_done(self, result) -> None:
        self._set_busy(False, f"撤销完成 · 回退 {result.done} 个，失败 {result.failed} 个")
        self._clear_plan()
        messagebox.showinfo("撤销完成", f"回退 {result.done} 个文件，失败 {result.failed} 个。")

    # --- helpers ---------------------------------------------------------

    def _fill_tree(self, plan: Plan) -> None:
        self.tree.delete(*self.tree.get_children())
        self._rows_root = plan.root
        self._rows = plan.items[:MAX_ROWS]
        self._row_index = 0
        self._fill_token += 1
        self._pump_rows(self._fill_token)
        if len(plan.items) > MAX_ROWS:
            self._log(f"预览只显示前 {MAX_ROWS} 条，实际计划共 {len(plan.items)} 条。")

    def _pump_rows(self, token: int) -> None:
        """Insert rows in chunks so a huge library never freezes the window."""
        if token != self._fill_token:
            return
        chunk = self._rows[self._row_index:self._row_index + 400]
        for item in chunk:
            when = item.when.strftime("%Y-%m-%d %H:%M") if item.when else "—"
            dest = ""
            if item.dst is not None:
                try:
                    dest = item.dst.relative_to(self._rows_root).as_posix()
                except (ValueError, AttributeError):
                    dest = str(item.dst)
            name = item.src.name
            if item.action != "planned" and item.note:
                name += f"  ({item.note})"
            self.tree.insert("", "end", values=(name, when, item.source_tag, dest))
        self._row_index += len(chunk)
        if self._row_index < len(self._rows):
            self.after(1, lambda: self._pump_rows(token))

    def _clear_plan(self) -> None:
        self.plan = None
        self._rows = []
        self._row_index = 0
        self._fill_token += 1
        self.tree.delete(*self.tree.get_children())
        self.btn_run.configure(state="disabled")

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > MAX_LOG_LINES:
            self.log.delete("1.0", f"{lines - MAX_LOG_LINES}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        if self.busy and not messagebox.askyesno("正在处理", "当前任务还在进行，确定退出吗？"):
            return
        self.cancel_flag.set()
        self.busy = False
        self.destroy()


class AdvancedDialog(tk.Toplevel):
    """Every knob the main window hides behind one button."""

    def __init__(self, master: "App") -> None:
        super().__init__(master)
        self.app = master
        self.title("高级设置")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.transient(master)
        self.grab_set()
        self._snapshot = {name: var.get() for name, var in self._vars().items()}
        self._build()
        self._center()

    def _vars(self) -> dict:
        app = self.app
        return {
            "mode": app.var_mode,
            "layout": app.var_layout,
            "fallback": app.var_fallback,
            "conflict": app.var_conflict,
            "recursive": app.var_recursive,
            "rename": app.var_rename,
            "prune": app.var_prune,
            "dedupe": app.var_dedupe,
            "ext": app.var_ext,
        }

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        head = tk.Frame(self, bg=BG)
        head.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 0))
        tk.Label(head, text="高级设置", bg=BG, fg=TEXT,
                 font=(self.app.font_bold[0], 13, "bold")).pack(anchor="w")
        tk.Label(head, text="分类方式与文件名规则", bg=BG, fg=TEXT_SUB,
                 font=self.app.font_small).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(14, 0))
        body.columnconfigure(1, weight=1)
        app = self.app

        def label(text: str, row: int) -> None:
            tk.Label(body, text=text, bg=BG, fg=TEXT, font=app.font_base).grid(
                row=row, column=0, sticky="w", pady=(0, 12))

        label("方式", 0)
        modes = tk.Frame(body, bg=BG)
        modes.grid(row=0, column=1, sticky="w", pady=(0, 12))
        RadioButton(modes, "移动", app.var_mode, "move", font=app.font_base).pack(side="left")
        RadioButton(modes, "复制", app.var_mode, "copy", font=app.font_base).pack(
            side="left", padx=(20, 0))
        RadioButton(modes, "链接", app.var_mode, "link", font=app.font_base).pack(
            side="left", padx=(20, 0))

        label("文件夹格式", 1)
        ttk.Combobox(
            body, textvariable=app.var_layout, width=26,
            values=("{YYYY}-{MM}", "{YYYY}/{MM}", "{YYYY}年{MM}月", "{YYYY}-{MMM}", "{YYYY}/{MM}/{DD}"),
        ).grid(row=1, column=1, sticky="w", pady=(0, 12))

        label("无日期时", 2)
        ttk.Combobox(
            body, textvariable=app.var_fallback, width=26, state="readonly",
            values=tuple(FALLBACK_LABELS.values()),
        ).grid(row=2, column=1, sticky="w", pady=(0, 12))

        label("同名文件", 3)
        ttk.Combobox(
            body, textvariable=app.var_conflict, width=26, state="readonly",
            values=tuple(CONFLICT_LABELS.values()),
        ).grid(row=3, column=1, sticky="w", pady=(0, 12))

        label("其他", 4)
        checks = tk.Frame(body, bg=BG)
        checks.grid(row=4, column=1, sticky="w", pady=(0, 12))
        CheckBox(checks, "包含子文件夹", app.var_recursive,
                 font=app.font_base).pack(anchor="w")
        CheckBox(checks, "按拍摄时间重命名文件", app.var_rename,
                 font=app.font_base).pack(anchor="w", pady=(4, 0))
        CheckBox(checks, "整理后删掉变空的文件夹", app.var_prune,
                 font=app.font_base).pack(anchor="w", pady=(4, 0))
        CheckBox(checks, "重复文件直接删除（默认移入隔离区）", app.var_dedupe,
                 font=app.font_base).pack(anchor="w", pady=(4, 0))

        label("图片类型", 5)
        RoundedEntry(body, app.var_ext, font=app.font_base).grid(
            row=5, column=1, sticky="ew", pady=(0, 2))
        tk.Label(body, text="逗号分隔，例如 jpg, png, heic", bg=BG, fg=TEXT_SUB,
                 font=app.font_small).grid(row=6, column=1, sticky="w", pady=(4, 0))

        tk.Frame(self, bg=BORDER, height=1).grid(row=2, column=0, sticky="ew", pady=(18, 0))

        buttons = tk.Frame(self, bg=BG)
        buttons.grid(row=3, column=0, sticky="e", padx=24, pady=(14, 18))
        RoundedButton(buttons, "恢复默认", command=self._reset, kind="ghost",
                      height=34, font=app.font_base, parent_bg=BG).pack(side="left", padx=(0, 8))
        RoundedButton(buttons, "取消", command=self._cancel, kind="secondary",
                      height=34, font=app.font_base, parent_bg=BG, min_width=72).pack(
            side="left", padx=(0, 8))
        RoundedButton(buttons, "确定", command=self._ok, kind="primary",
                      height=34, font=app.font_base, parent_bg=BG, min_width=72).pack(side="left")

    def _center(self) -> None:
        try:
            self.update_idletasks()
            x = int(self.app.winfo_rootx()) + 150
            y = int(self.app.winfo_rooty()) + 130
            self.geometry(f"+{x}+{y}")
        except Exception:  # noqa: BLE001 - placement is cosmetic
            pass

    def _reset(self) -> None:
        vars_ = self._vars()
        vars_["mode"].set(DEFAULTS["mode"])
        vars_["layout"].set(DEFAULTS["layout"])
        vars_["fallback"].set(FALLBACK_LABELS[DEFAULTS["fallback"]])
        vars_["conflict"].set(CONFLICT_LABELS[DEFAULTS["conflict"]])
        vars_["recursive"].set(bool(DEFAULTS["recursive"]))
        vars_["rename"].set(bool(DEFAULTS["rename_files"]))
        vars_["prune"].set(bool(DEFAULTS["prune_empty"]))
        vars_["dedupe"].set(bool(DEFAULTS["delete_duplicates"]))
        vars_["ext"].set(", ".join(sorted(e.lstrip(".") for e in MEDIA_EXTS)))
        self.app._update_summary()

    def _cancel(self) -> None:
        for name, value in self._snapshot.items():
            self._vars()[name].set(value)
        self.app._update_summary()
        self.destroy()

    def _ok(self) -> None:
        self.app._update_summary()
        save_settings(self.app._current_settings())
        self.destroy()


def run() -> int:
    app = App()
    app.mainloop()
    return 0
