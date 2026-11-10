# Windows 极限场景实测：长路径、只读、0 字节、中文路径、批量。
# 在项目根目录执行：python tools/stress_windows.py
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "tests")

import make_samples  # noqa: E402
from imagesorter.scanner import Options, build_plan  # noqa: E402
from imagesorter.organizer import execute, undo  # noqa: E402

BASE = Path(r"C:\PhotoSort\stress")
SRC = BASE / "照片 库"


def reset():
    shutil.rmtree(BASE, ignore_errors=True)
    SRC.mkdir(parents=True)


def count_files(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file())


def main() -> int:
    reset()
    jpg = make_samples.wrap_jpeg(make_samples.exif_block("2021-07-01 09:00:00"))

    for i in range(500):
        (SRC / f"IMG_{i:04d}.jpg").write_bytes(jpg)

    (SRC / "中文 名字.jpg").write_bytes(jpg)
    (SRC / "emoji 😀.jpg").write_bytes(jpg)

    deep = SRC
    for i in range(10):
        deep = deep / f"子目录{i:02d}"
    deep.mkdir(parents=True)
    (deep / "deep.jpg").write_bytes(jpg)

    readonly = SRC / "readonly.jpg"
    readonly.write_bytes(jpg)
    os.chmod(readonly, 0o444)

    (SRC / "empty.jpg").write_bytes(b"")

    for name in ("甲", "乙"):
        sub = SRC / name
        sub.mkdir()
        (sub / "same.jpg").write_bytes(jpg)

    # 超长路径：目标文件路径超过 260 个字符
    segment = "很长的目录名称" * 8
    long_dir = SRC
    for _ in range(5):
        long_dir = long_dir / segment
    raw_dir = "\\\\?\\" + str(long_dir)
    os.makedirs(raw_dir, exist_ok=True)
    with open("\\\\?\\" + str(long_dir / "longpath.jpg"), "wb") as handle:
        handle.write(jpg)

    longest = max(len(str(p)) for p in SRC.rglob("*"))
    print(f"files={count_files(SRC)} longest_path={longest}")

    opts = Options(source=str(SRC), target=str(BASE / "out"), mode="move")
    plan = build_plan(opts)
    print(f"plan todo={len(plan.todo)} skipped={len(plan.skipped)}")

    result = execute(plan)
    print(f"move done={result.done} failed={result.failed}")
    for path, message in result.errors[:6]:
        print(f"  ERR {path[-45:]} {message}")

    months = sorted(p.name for p in (BASE / "out").iterdir() if p.is_dir())
    print(f"out_dirs={months}")

    if result.undo_file:
        back = undo(result.undo_file)
        print(f"undo done={back.done} failed={back.failed}")
        for path, message in back.errors[:6]:
            print(f"  UNDO-ERR {path[-45:]} {message}")

    print(f"restored={count_files(SRC)}")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
