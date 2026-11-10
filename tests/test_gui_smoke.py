"""Headless smoke test for the Tkinter layer.

Real Tk needs a display, so this installs a minimal stand-in for `tkinter`
and walks the whole widget-construction path. It catches the class of bug
that a display-less environment otherwise hides: attribute typos, missing
handlers, wrong option wiring.
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples  # noqa: E402


class _Var:
    def __init__(self, value=None, **_kw):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class _Tk(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__()

    def configure(self, *args, **kwargs):
        return None

    config = configure

    def _get_child_mock(self, **kwargs):
        # Without this, child attributes would be built as App(...) instances.
        return MagicMock(**kwargs)


class _Style:
    def __init__(self, *args, **kwargs):
        pass

    def theme_names(self):
        return ["clam", "default"]

    def theme_use(self, _name):
        pass

    def configure(self, *args, **kwargs):
        pass

    def map(self, *args, **kwargs):
        pass

    def layout(self, *args, **kwargs):
        pass


def _widget(*_args, **_kwargs):
    widget = MagicMock()
    widget.index.return_value = "1.0"
    widget.cget.return_value = 100
    widget.get_children.return_value = ()
    return widget


def _install_stub() -> dict:
    saved = {name: sys.modules.get(name) for name in
             ("tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox")}

    tk = types.ModuleType("tkinter")
    tk.Tk = _Tk
    tk.Toplevel = _Tk
    tk.Canvas = _Tk
    tk.Frame = _Tk
    tk.TclError = RuntimeError
    tk.StringVar = _Var
    tk.BooleanVar = _Var
    tk.Text = _widget
    tk.END = "end"
    tk.__getattr__ = lambda name: _widget

    ttk = types.ModuleType("tkinter.ttk")
    ttk.Style = _Style
    ttk.__getattr__ = lambda name: _widget

    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askdirectory = lambda **_kw: ""

    messagebox = types.ModuleType("tkinter.messagebox")
    for name in ("showwarning", "showerror", "showinfo"):
        setattr(messagebox, name, lambda *a, **k: None)
    messagebox.askyesno = lambda *a, **k: False

    tk.ttk = ttk
    tk.filedialog = filedialog
    tk.messagebox = messagebox

    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.messagebox"] = messagebox
    sys.modules.pop("imagesorter.gui", None)
    return saved


def _restore(saved: dict) -> None:
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
    sys.modules.pop("imagesorter.gui", None)


class TestGuiShell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = _install_stub()
        from imagesorter import config, gui

        cls.gui = gui
        cls.gui.load_settings = lambda: dict(config.DEFAULTS)
        cls.gui.save_settings = lambda _data: None
        cls.app = gui.App()

    @classmethod
    def tearDownClass(cls):
        _restore(cls.saved)

    def test_defaults_are_wired(self):
        self.assertEqual(self.app.var_mode.get(), "move")
        self.assertEqual(self.app.var_layout.get(), "{YYYY}-{MM}")
        self.assertTrue(self.app.var_recursive.get())
        self.assertIn(".jpg", self.app._parse_extensions(self.app.var_ext.get()))

    def test_extension_parsing(self):
        parse = self.app._parse_extensions
        self.assertEqual(parse("jpg, .PNG, ,heic"), {".jpg", ".png", ".heic"})
        self.assertEqual(parse(""), set())

    def test_label_lookup_roundtrip(self):
        from imagesorter.scanner import CONFLICT_LABELS, FALLBACK_LABELS

        for key, label in FALLBACK_LABELS.items():
            self.assertEqual(self.app._key_of(FALLBACK_LABELS, label, "x"), key)
        for key, label in CONFLICT_LABELS.items():
            self.assertEqual(self.app._key_of(CONFLICT_LABELS, label, "x"), key)

    def test_empty_source_is_rejected(self):
        self.app.var_source.set("")
        self.assertIsNone(self.app._collect_options())

    def test_settings_roundtrip(self):
        self.app.var_source.set(str(ROOT))
        self.app.var_same.set(True)
        settings = self.app._current_settings()
        self.assertEqual(settings["source"], str(ROOT))
        self.assertEqual(settings["target"], "")
        self.assertEqual(settings["fallback"], "auto")

    def test_plan_rendering_into_tree(self):
        from imagesorter.scanner import Options, build_plan

        with tempfile.TemporaryDirectory() as tmp:
            make_samples.make_samples(Path(tmp))
            plan = build_plan(Options(source=tmp))
            self.app._on_scan_done(plan)
            self.applicable = plan
            self.assertIn("个待整理", self.app.var_status.get())
            self.assertTrue(self.app.tree.insert.called)
            self.assertTrue(self.app.btn_run.enabled, "扫描出结果后「开始整理」应可用")

    def test_default_output_is_next_to_program(self):
        out = self.gui.default_output_dir()
        self.assertEqual(out.name, "整理结果")
        self.assertEqual(out.parent, self.gui.app_dir())

    def test_reset_notifies_summary(self):
        self.app.var_mode.set("copy")
        self.app.var_recursive.set(False)
        dialog = self.gui.AdvancedDialog(self.app)
        dialog._reset()
        self.assertEqual(self.app.var_mode.get(), "move")
        self.assertTrue(self.app.var_recursive.get())
        dialog.destroy()

    def test_event_handlers_all_exist(self):
        for kind in ("log", "progress_text", "progress_value", "scan_done",
                     "exec_done", "undo_done", "failed"):
            self.assertTrue(callable(getattr(self.app, f"_on_{kind}", None)), kind)


if __name__ == "__main__":
    unittest.main(verbosity=2)
