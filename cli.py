#!/usr/bin/env python3
"""Command line interface - handy for scheduled runs and for testing.

    python cli.py --source "D:\\Photos"                 # dry run, prints the plan
    python cli.py --source "D:\\Photos" --apply         # actually organize
    python cli.py --source "D:\\Photos" --undo-list
    python cli.py --source "D:\\Photos" --undo-latest
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from imagesorter.organizer import execute, summarize_undo, undo, undo_files
from imagesorter.scanner import CONFLICT_LABELS, FALLBACK_LABELS, MEDIA_EXTS, Options, build_plan


def _fix_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    parser = argparse.ArgumentParser(
        prog="image-sorter",
        description="按拍摄时间把图片整理进以月份命名的文件夹（默认只预览，加 --apply 才动手）。",
    )
    parser.add_argument("--source", required=True, help="待整理的文件夹")
    parser.add_argument("--target", default="", help="输出根目录，默认与源目录相同")
    parser.add_argument("--mode", choices=("move", "copy", "link"), default="move",
                        help="link 建硬链接，不占额外空间，要求同一磁盘")
    parser.add_argument("--layout", default="{YYYY}-{MM}",
                        help="文件夹模板，例如 {YYYY}-{MM} 或 {YYYY}/{MM}")
    parser.add_argument("--fallback", choices=tuple(FALLBACK_LABELS), default="auto",
                        help="无拍摄时间时的兜底策略")
    parser.add_argument("--conflict", choices=tuple(CONFLICT_LABELS), default="rename")
    parser.add_argument("--rename", action="store_true", help="按拍摄时间重命名文件")
    parser.add_argument("--prune-empty", action="store_true", help="整理后删掉变空的文件夹")
    parser.add_argument("--delete-duplicates", action="store_true",
                        help="内容重复的文件直接删掉，默认是移入隔离区")
    parser.add_argument("--flat", action="store_true", help="不进入子文件夹")
    parser.add_argument("--ext", default="", help="覆盖扩展名列表，逗号分隔")
    parser.add_argument("--apply", action="store_true", help="真正执行（否则只打印计划）")
    parser.add_argument("--limit", type=int, default=25, help="预览时最多打印多少条")
    parser.add_argument("--undo-list", action="store_true", help="列出可撤销的批次")
    parser.add_argument("--undo-latest", action="store_true", help="撤销最近一次整理")
    args = parser.parse_args(argv)

    source = Path(args.source).expanduser()
    if not source.is_dir():
        print(f"源目录不存在: {source}")
        return 2

    if args.undo_list or args.undo_latest:
        root = Path(args.target).expanduser() if args.target else source
        batches = undo_files(root)
        if not batches:
            print("没有找到撤销记录。")
            return 0
        for path in batches[:15]:
            print(f"  {summarize_undo(path)}   {path.name}")
        if args.undo_latest:
            print("\n开始撤销:", batches[0].name)
            result = undo(batches[0], on_event=lambda kind, *_a: None)
            print(f"撤销完成: 回退 {result.done} 个，失败 {result.failed} 个")
            for item, message in result.errors[:10]:
                print(f"  [失败] {item} -> {message}")
        return 0

    extensions = MEDIA_EXTS
    if args.ext:
        extensions = {e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
                      for e in args.ext.split(",") if e.strip()}

    options = Options(
        source=str(source),
        target=str(Path(args.target).expanduser()) if args.target else "",
        mode=args.mode,
        layout=args.layout,
        recursive=not args.flat,
        fallback=args.fallback,
        conflict=args.conflict,
        rename_files=args.rename,
        prune_empty=args.prune_empty,
        delete_duplicates=args.delete_duplicates,
        extensions=frozenset(extensions),
    )

    print(f"扫描: {source}")
    plan = build_plan(options, progress=lambda n, _m: print(f"\r  已读取 {n} 个文件", end="", flush=True))
    print()

    counts = plan.month_counts()
    print(f"图片 {plan.scanned} 个，待整理 {len(plan.todo)} 个，跳过 {len(plan.skipped)} 个")
    if counts:
        print("月份分布:")
        for key, value in counts.items():
            print(f"  {key}  {value:5d} 个")
    tags = plan.tag_counts()
    if tags:
        print("日期来源:", "，".join(f"{k}={v}" for k, v in tags.items()))

    for item in plan.todo[: max(args.limit, 0)]:
        stamp = item.when.strftime("%Y-%m-%d %H:%M:%S") if item.when else "     无日期      "
        print(f"  {item.src.name}  [{item.source_tag}] {stamp} -> {item.dst}")

    if not args.apply:
        print("\n这是预览。确认无误后加 --apply 执行。")
        return 0

    if not plan.todo:
        print("没有需要整理的图片。")
        return 0

    result = execute(plan, on_event=lambda kind, item, *_: None)
    print(f"\n完成: 成功 {result.done} 个，失败 {result.failed} 个，取消={result.cancelled}")
    if result.fallbacks:
        print(f"其中 {result.fallbacks} 个位置不支持硬链接，已改为复制")
    if result.trashed:
        print(f"重复文件 {result.trashed} 个已处理")
    if result.pruned:
        print(f"清理了 {result.pruned} 个空文件夹")
    for item, message in result.errors[:10]:
        print(f"  [失败] {item} -> {message}")
    if result.undo_file:
        print(f"撤销记录: {result.undo_file}")
        print("撤销命令: python cli.py --source <源目录> --target <目标目录> --undo-latest")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
