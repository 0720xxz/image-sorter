"""Executing a plan, plus the undo log that makes bulk moves reversible."""

from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .dates import long_path, path_exists, unique_suffix_name
from .scanner import Plan

UNDO_DIR = ".imagesorter_undo"
UNDO_VERSION = 1


@dataclass
class ExecResult:
    done: int = 0
    failed: int = 0
    fallbacks: int = 0
    pruned: int = 0
    trashed: int = 0
    cancelled: bool = False
    errors: list[tuple[str, str]] = field(default_factory=list)
    undo_file: Path | None = None


def _ensure_dir(path: Path) -> None:
    os.makedirs(long_path(path), exist_ok=True)


def _make_writable(path: Path) -> None:
    """Clear the read-only bit so Windows lets us replace or delete the file."""
    try:
        mode = os.stat(long_path(path)).st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(long_path(path), mode | stat.S_IWRITE)
    except OSError:
        pass


def _place(src: Path, dst: Path, mode: str, overwrite: bool) -> str:
    """Put the file at dst; returns what actually happened."""
    if path_exists(dst):
        if not overwrite:
            raise FileExistsError(f"目标已存在: {dst}")
        _make_writable(dst)
        os.unlink(long_path(dst))
    if mode == "copy":
        shutil.copy2(long_path(src), long_path(dst))
        return "copy"
    if mode == "link":
        try:
            # 硬链接：不占额外空间，源文件原地不动
            os.link(long_path(src), long_path(dst))
            return "link"
        except OSError:
            # 跨卷、exFAT、FAT32 都不支持硬链接，退回复制
            shutil.copy2(long_path(src), long_path(dst))
            return "link_fallback"
    # Across volumes a move is copy+delete, and Windows refuses to delete
    # a read-only source. copy2 keeps the attribute on the destination.
    _make_writable(src)
    shutil.move(long_path(src), long_path(dst))
    return "move"


def _write_undo(root: Path, mode: str, pairs: list[dict]) -> Path | None:
    if not pairs:
        return None
    folder = root / UNDO_DIR
    _ensure_dir(folder)
    # Microseconds matter: two runs inside the same second must not collide,
    # otherwise the second undo record silently replaces the first.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = folder / f"undo-{stamp}-{os.getpid()}.json"
    payload = {
        "version": UNDO_VERSION,
        "created": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "root": str(root),
        "count": len(pairs),
        "items": pairs,
    }
    tmp = path.with_suffix(".json.tmp")
    with open(long_path(tmp), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    os.replace(long_path(tmp), long_path(path))
    return path


def execute(plan: Plan, on_event=None, should_cancel=None) -> ExecResult:
    """Apply every 'planned' item. Never raises on per-file errors."""
    options = plan.options
    mode = options.mode if options else "move"
    overwrite = bool(options and options.conflict == "overwrite")
    result = ExecResult()
    pairs: list[dict] = []
    todo = plan.todo
    total = len(todo)

    for index, item in enumerate(todo, 1):
        if should_cancel and should_cancel():
            result.cancelled = True
            break
        dst = item.dst
        if dst is None:
            continue
        try:
            _ensure_dir(dst.parent)
            action = _place(item.src, dst, mode, overwrite)
        except Exception as exc:  # noqa: BLE001 - surface every failure to the UI
            result.failed += 1
            result.errors.append((str(item.src), f"{type(exc).__name__}: {exc}"))
            if on_event:
                on_event("error", item, f"{type(exc).__name__}: {exc}")
            continue
        result.done += 1
        if action == "link_fallback":
            result.fallbacks += 1
            if on_event:
                on_event("fallback", item, "这个位置不支持硬链接，已改为复制")
        pairs.append({"src": str(item.src), "dst": str(dst)})
        if on_event:
            on_event("done", item, f"{index}/{total}")

    # 重复文件：默认挪进撤销目录下的 trash，直接删是可选项
    duplicates = [item for item in plan.items if item.action == "duplicate"]
    if duplicates:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        trash_root = plan.root / UNDO_DIR / "trash" / stamp
        for item in duplicates:
            if should_cancel and should_cancel():
                result.cancelled = True
                break
            try:
                if options is not None and getattr(options, "delete_duplicates", False):
                    _make_writable(item.src)
                    os.unlink(long_path(item.src))
                    pairs.append({"src": str(item.src), "dst": "", "kind": "deleted"})
                else:
                    _ensure_dir(trash_root)
                    dst = trash_root / item.src.name
                    index = 1
                    while path_exists(dst):
                        dst = trash_root / unique_suffix_name(item.src.stem, item.src.suffix, index)
                        index += 1
                    _make_writable(item.src)
                    shutil.move(long_path(item.src), long_path(dst))
                    pairs.append({"src": str(item.src), "dst": str(dst), "kind": "trash"})
            except Exception as exc:  # noqa: BLE001
                result.failed += 1
                result.errors.append((str(item.src), f"{type(exc).__name__}: {exc}"))
                if on_event:
                    on_event("error", item, str(exc))
                continue
            result.trashed += 1
            if on_event:
                on_event("trash", item, item.note)

    result.undo_file = _write_undo(plan.root, mode, pairs)

    if options is not None and getattr(options, "prune_empty", False) and mode == "move":
        source_root = Path(options.source).expanduser().absolute()
        removed = _prune_empty_dirs({Path(entry["src"]).parent for entry in pairs}, source_root)
        result.pruned = removed
        if on_event and removed:
            on_event("pruned", None, f"清理了 {removed} 个空文件夹")

    return result


# --- undo ----------------------------------------------------------------


def undo_files(root: Path) -> list[Path]:
    folder = root / UNDO_DIR
    if not folder.is_dir():
        return []
    files = [p for p in folder.glob("undo-*.json")]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def read_undo(path: Path) -> dict:
    with open(long_path(path), "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("version") != UNDO_VERSION:
        raise ValueError("撤销记录格式不认识")
    return data


def undo(undo_path: Path, on_event=None, should_cancel=None) -> ExecResult:
    """Reverse one logged batch: move back, or delete the copy."""
    data = read_undo(undo_path)
    mode = data.get("mode", "move")
    items = list(data.get("items", []))
    result = ExecResult()

    for entry in reversed(items):
        if should_cancel and should_cancel():
            result.cancelled = True
            break
        src = Path(entry.get("src", ""))
        kind = entry.get("kind") or mode   # move / copy / link 三种整批模式
        if kind == "deleted":
            # dst 是空的，先判掉，不能掉进下面的 Path("") 分支
            result.failed += 1
            result.errors.append((str(src), "这个文件当时是直接删掉的，恢复不了"))
            continue
        dst = Path(entry.get("dst", ""))
        if not str(entry.get("dst") or "") or not path_exists(dst):
            continue
        try:
            if kind in ("copy", "link"):
                os.unlink(long_path(dst))
            else:
                if path_exists(src):
                    raise FileExistsError(f"原位置已有同名文件: {src}")
                _ensure_dir(src.parent)
                shutil.move(long_path(dst), long_path(src))
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append((str(dst), f"{type(exc).__name__}: {exc}"))
            if on_event:
                on_event("error", dst, str(exc))
            continue
        result.done += 1
        if on_event:
            on_event("undo", dst, str(src))

    _prune_empty_dirs({Path(entry.get("dst", "")).parent for entry in items}, Path(data.get("root", "")))

    if not result.cancelled and result.failed == 0:
        try:
            os.unlink(long_path(undo_path))
        except OSError:
            pass
        folder = undo_path.parent
        try:
            if not any(folder.iterdir()):
                os.rmdir(long_path(folder))
        except OSError:
            pass
    return result


def _prune_empty_dirs(dirs: set[Path], root: Path) -> int:
    """Remove the month folders this program created, deepest first.

    Only empty directories are removed and never the target root itself, so a
    folder the user filled with something else stays untouched.
    """
    removed = 0
    if not str(root):
        return removed
    for start in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        current = start
        while current != root and root in current.parents:
            try:
                os.rmdir(long_path(current))
            except OSError:
                break
            removed += 1
            current = current.parent
    return removed


def summarize_undo(path: Path) -> str:
    try:
        data = read_undo(path)
    except (OSError, ValueError):
        return path.name
    return (
        f"{data.get('created', '?')}  "
        f"{'移动' if data.get('mode') == 'move' else '复制'} "
        f"{data.get('count', len(data.get('items', [])))} 个文件"
    )
