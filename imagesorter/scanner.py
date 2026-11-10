"""Scanning: turn a directory tree into an explicit, reviewable plan."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .dates import (
    datetime_from_filename,
    long_path,
    path_exists,
    render_layout,
    unique_suffix_name,
)
from .exif import VIDEO_EXTS, read_meta

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".gif", ".bmp",
    ".tif", ".tiff", ".heic", ".heif", ".avif", ".hif",
    ".dng", ".cr2", ".nef", ".arw", ".orf", ".rw2", ".pef", ".srw",
}

# 没有内置解析器的容器也能被整理，只是时间会退到文件名或文件时间
OTHER_MEDIA_EXTS = {".avi", ".mkv", ".wmv", ".flv", ".webm"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS | OTHER_MEDIA_EXTS

SKIP_DIR_NAMES = {
    ".imagesorter_undo", "$recycle.bin", "system volume information",
    ".git", ".svn", "__pycache__",
}

FALLBACK_LABELS = {
    "auto": "文件名 → 文件时间",
    "file_time": "文件修改时间",
    "filename": "文件名中的日期",
    "unknown": "归入未标注日期文件夹",
    "skip": "跳过该文件",
}

CONFLICT_LABELS = {
    "rename": "自动改名（_001）",
    "skip": "跳过",
    "overwrite": "覆盖目标文件",
}

MODE_LABELS = {"move": "移动", "copy": "复制", "link": "链接"}

NO_DATE_DIR = "_undated"
NO_DATE_DIR_ZH = "_未标注日期"

# Shape of a folder name a layout can produce, used to recognise output we
# already created instead of re-sorting it every run.
_TOKEN_RE = {
    "{YYYY}": r"\d{4}", "{YY}": r"\d{2}", "{MM}": r"\d{2}", "{M}": r"\d{1,2}",
    "{MMM}": r"[A-Za-z]+", "{DD}": r"\d{2}", "{D}": r"\d{1,2}",
}


def layout_patterns(layout: str) -> list[re.Pattern]:
    text = layout or "{YYYY}-{MM}"
    for short, long in (("%Y", "{YYYY}"), ("%y", "{YY}"), ("%m", "{MM}"), ("%d", "{DD}")):
        text = text.replace(short, long)
    slots: list[str] = []

    def _stash(match):
        slots.append(match.group(0))
        return f"\x00{len(slots) - 1}\x00"

    text = re.sub(r"\{[A-Z]+\}", _stash, text)
    patterns = []
    for part in re.split(r"[\\/]", text):
        escaped = re.escape(part)
        for index, token in enumerate(slots):
            escaped = escaped.replace(f"\x00{index}\x00", _TOKEN_RE.get(token, ".*"))
        patterns.append(re.compile("^" + escaped + "$", re.IGNORECASE))
    return patterns


_STAMPED_NAME = re.compile(r"^\d{8}_\d{6}(?:_\d{3})?$")


def looks_renamed(path: Path) -> bool:
    """文件名已经是 YYYYMMDD_HHMMSS 这种形状时返回 True。"""
    return bool(_STAMPED_NAME.fullmatch(path.stem))


def looks_organized(path: Path, root: Path, patterns: list[re.Pattern]) -> bool:
    """True when the file already sits inside a folder this layout produces."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    parents = relative.parts[:-1]
    if len(parents) < len(patterns):
        return False
    tail = parents[-len(patterns):]
    return all(p.fullmatch(part) for p, part in zip(patterns, tail))


@dataclass
class Options:
    source: str
    target: str = ""
    mode: str = "move"
    layout: str = "{YYYY}-{MM}"
    recursive: bool = True
    fallback: str = "auto"
    conflict: str = "rename"
    rename_files: bool = True
    prune_empty: bool = False
    delete_duplicates: bool = False
    extensions: frozenset[str] = field(default_factory=lambda: frozenset(MEDIA_EXTS))

    def target_path(self) -> Path:
        return Path(self.target) if self.target else Path(self.source)



@dataclass
class Item:
    src: Path
    when: datetime | None
    source_tag: str
    dst: Path | None = None
    action: str = "planned"  # planned | in_place | skip | duplicate
    note: str = ""
    size: int = 0
    digest: str = ""

    @property
    def year_month(self) -> str:
        if self.when is None:
            return NO_DATE_DIR_ZH
        return f"{self.when.year:04d}-{self.when.month:02d}"


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    root: Path = Path()
    options: Options | None = None
    scanned: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def todo(self) -> list[Item]:
        return [i for i in self.items if i.action == "planned"]

    @property
    def skipped(self) -> list[Item]:
        return [i for i in self.items if i.action != "planned"]

    def month_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.todo:
            counts[item.year_month] = counts.get(item.year_month, 0) + 1
        return dict(sorted(counts.items()))

    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.todo:
            counts[item.source_tag] = counts.get(item.source_tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def iter_files(root: Path, recursive: bool, skip_roots: list[Path], should_cancel=None):
    """Yield files under root, skipping hidden/system dirs and target subtrees."""
    stack = [root]
    while stack:
        if should_cancel and should_cancel():
            return
        current = stack.pop()
        try:
            entries = list(os.scandir(long_path(current)))
        except OSError:
            continue
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            path = Path(entry.path)
            if is_dir:
                if not recursive:
                    continue
                if entry.name.startswith(".") or entry.name.lower() in SKIP_DIR_NAMES:
                    continue
                if any(_is_inside(path, skip) for skip in skip_roots):
                    continue
                stack.append(path)
            else:
                if entry.name.startswith("."):
                    continue
                yield path


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _file_time(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(os.stat(long_path(path)).st_mtime)
    except (OSError, ValueError):
        return None


def decide_time(path: Path, fallback: str) -> tuple[datetime | None, str]:
    """Return (timestamp, provenance label) for one image file."""
    meta = read_meta(path)
    if meta.when:
        return meta.when, meta.tag

    stem = path.stem
    by_name = datetime_from_filename(stem)
    by_mtime = _file_time(path)

    if fallback == "filename":
        if by_name:
            return by_name, "文件名"
    elif fallback == "file_time":
        if by_mtime:
            return by_mtime, "文件时间"
    elif fallback == "auto":
        if by_name:
            return by_name, "文件名"
        if by_mtime:
            return by_mtime, "文件时间"
    # 'unknown' and 'skip' both fall through with no timestamp
    return None, "无日期"


def same_content(a: Path, b: Path) -> bool:
    """Byte-for-byte comparison, bailing out early on the first difference."""
    try:
        if os.stat(long_path(a)).st_size != os.stat(long_path(b)).st_size:
            return False
        with open(long_path(a), "rb") as handle_a, open(long_path(b), "rb") as handle_b:
            while True:
                chunk_a = handle_a.read(1 << 20)
                chunk_b = handle_b.read(1 << 20)
                if chunk_a != chunk_b:
                    return False
                if not chunk_a:
                    return True
    except OSError:
        return False


def file_digest(path: Path) -> str:
    """整个文件算 SHA256，读不了就返回空串。"""
    hasher = hashlib.sha256()
    try:
        with open(long_path(path), "rb") as handle:
            while True:
                chunk = handle.read(1 << 20)
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError:
        return ""
    return hasher.hexdigest()


def mark_duplicates(plan: Plan) -> None:
    """同一批里内容完全相同的，只留拍摄时间最早的那张。

    先按文件大小分组，只有大小相同的才去算哈希，避免对整库做全量摘要。
    """
    by_size: dict[int, list[Item]] = {}
    for item in plan.todo:
        if item.size > 0:
            by_size.setdefault(item.size, []).append(item)

    for group in by_size.values():
        if len(group) < 2:
            continue
        by_hash: dict[str, list[Item]] = {}
        for item in group:
            digest = item.digest or file_digest(item.src)
            if not digest:
                continue
            item.digest = digest
            by_hash.setdefault(digest, []).append(item)
        for same in by_hash.values():
            if len(same) < 2:
                continue
            same.sort(key=lambda i: (i.when is None, i.when or datetime.max, str(i.src)))
            keeper = same[0]
            for item in same[1:]:
                item.action = "duplicate"
                item.dst = None
                item.note = f"与 {keeper.src.name} 内容相同，保留更早的"


def _unique_target(dst: Path, reserved: set[str], on_conflict: str) -> tuple[Path | None, str]:
    """Resolve collisions against disk and against earlier plan entries."""
    key = str(dst).lower()
    exists = path_exists(dst) or key in reserved
    if not exists:
        reserved.add(key)
        return dst, ""
    if on_conflict == "skip":
        return None, "目标已存在"
    if on_conflict == "overwrite":
        reserved.add(key)
        return dst, "将覆盖"
    stem, suffix = dst.stem, dst.suffix
    for index in range(1, 1000):
        candidate = dst.with_name(unique_suffix_name(stem, suffix, index))
        ckey = str(candidate).lower()
        if not path_exists(candidate) and ckey not in reserved:
            reserved.add(ckey)
            return candidate, f"改名 {candidate.name}"
    return None, "同名文件过多"


def build_plan(options: Options, should_cancel=None, progress=None) -> Plan:
    # Absolute paths keep undo records valid no matter where the app was started.
    source = Path(options.source).expanduser().absolute()
    target = options.target_path().expanduser().absolute()
    plan = Plan(root=target, options=options)

    skip_roots = []
    if _is_inside(target, source) and target.resolve() != source.resolve():
        skip_roots.append(target)

    organized = layout_patterns(options.layout)
    reserved: set[str] = set()
    files_seen = 0
    for path in iter_files(source, options.recursive, skip_roots, should_cancel):
        if should_cancel and should_cancel():
            plan.cancelled = True
            break
        if path.suffix.lower() not in options.extensions:
            continue
        files_seen += 1
        if progress and files_seen % 25 == 0:
            progress(files_seen, "")
        try:
            size = os.stat(long_path(path)).st_size
        except (OSError, ValueError):
            plan.items.append(Item(src=path, when=None, source_tag="", size=0,
                                   action="skip", note="读不到这个文件"))
            continue
        if size == 0:
            plan.items.append(Item(src=path, when=None, source_tag="", size=0,
                                   action="skip", note="空文件"))
            continue

        if options.mode in ("move", "link") and looks_organized(path, target, organized):
            # 位置对了还要看名字：要求按拍摄时间命名时，老名字得放行重新处理
            if not options.rename_files or looks_renamed(path):
                plan.items.append(Item(src=path, when=None, source_tag="—", size=size,
                                       dst=path, action="in_place",
                                       note="已在月份文件夹里"))
                continue

        when, tag = decide_time(path, options.fallback)
        item = Item(src=path, when=when, source_tag=tag, size=size)

        if when is None and options.fallback == "skip":
            item.action = "skip"
            item.note = "无日期，按设置跳过"
            plan.items.append(item)
            continue

        parts = render_layout(options.layout, when)
        if when is None:
            parts = [NO_DATE_DIR_ZH]

        name = path.name
        if options.rename_files and when is not None:
            # 直接用拍摄时间做文件名，时间相同就靠后面的冲突处理加序号
            name = f"{when:%Y%m%d_%H%M%S}{path.suffix}"

        dst = target.joinpath(*parts, name)
        if options.mode == "move":
            try:
                if dst.resolve() == path.resolve():
                    item.dst = dst
                    item.action = "in_place"
                    item.note = "已在正确位置"
                    plan.items.append(item)
                    continue
            except OSError:
                pass

        if path_exists(dst) and same_content(path, dst):
            item.dst = dst
            item.action = "skip"
            item.note = "输出里已经有一样的文件"
            plan.items.append(item)
            continue

        resolved, note = _unique_target(dst, reserved, options.conflict)
        if resolved is None:
            item.action = "skip"
            item.note = note
            item.dst = dst
        else:
            item.dst = resolved
            item.note = note
        plan.items.append(item)

    plan.scanned = files_seen
    if should_cancel and should_cancel():
        plan.cancelled = True
    if not plan.cancelled:
        mark_duplicates(plan)
    if progress:
        progress(files_seen, "")
    return plan
