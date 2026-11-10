"""End-to-end tests for the metadata reader, planner and executor."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples  # noqa: E402
from imagesorter.dates import (  # noqa: E402
    datetime_from_filename,
    parse_exif_datetime,
    render_layout,
)
from imagesorter.exif import read_meta  # noqa: E402
from imagesorter.organizer import execute, undo, undo_files  # noqa: E402
from imagesorter.scanner import Options, build_plan  # noqa: E402


class TestDateParsing(unittest.TestCase):
    def test_exif_style(self):
        self.assertEqual(parse_exif_datetime("2019:05:06 12:34:56"), datetime(2019, 5, 6, 12, 34, 56))
        self.assertEqual(parse_exif_datetime("2019-05-06 12:34:56"), datetime(2019, 5, 6, 12, 34, 56))
        self.assertEqual(parse_exif_datetime("2023:08:14 10:20:30+08:00"), datetime(2023, 8, 14, 10, 20, 30))

    def test_rejects_placeholders(self):
        self.assertIsNone(parse_exif_datetime("0000:00:00 00:00:00"))
        self.assertIsNone(parse_exif_datetime(""))
        self.assertIsNone(parse_exif_datetime(None))
        self.assertIsNone(parse_exif_datetime("2019:13:45 12:00:00"))

    def test_filename_patterns(self):
        self.assertEqual(datetime_from_filename("IMG_20191224_183000"), datetime(2019, 12, 24, 18, 30, 0))
        self.assertEqual(datetime_from_filename("2019-05-06 12.34.56"), datetime(2019, 5, 6, 12, 34, 56))
        self.assertEqual(datetime_from_filename("Screenshot_2021-03-04-05-06-07"), datetime(2021, 3, 4, 5, 6, 7))
        self.assertIsNone(datetime_from_filename("DSC_0042"))

    def test_wechat_epoch_filename(self):
        expected = datetime.fromtimestamp(1687654321)
        self.assertEqual(datetime_from_filename("mmexport1687654321000"), expected)
        self.assertEqual(datetime_from_filename("wx_camera_1687654321000"), expected)
        self.assertIsNone(datetime_from_filename("PHOTO_1234567890123"))

    def test_layout_tokens(self):
        dt = datetime(2023, 5, 9, 8, 7, 6)
        self.assertEqual(render_layout("{YYYY}-{MM}", dt), ["2023-05"])
        self.assertEqual(render_layout("{YYYY}/{MM}", dt), ["2023", "05"])
        self.assertEqual(render_layout("{YYYY}年{MM}月", dt), ["2023年05月"])
        self.assertEqual(render_layout("{YYYY}-{MMM}", dt), ["2023-May"])
        self.assertEqual(render_layout("{YY}-{M}", dt), ["23-5"])
        self.assertEqual(render_layout("%Y/%m", dt), ["2023", "05"])
        self.assertEqual(render_layout("{YYYY}-{MM}", None), ["_undated"])


class TestExifReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "samples"
        cls.expected = make_samples.make_samples(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assert_meta(self, name: str):
        meta = read_meta(self.root / name)
        self.assertIsNotNone(meta.when, f"{name} 没有读到拍摄时间")
        self.assertEqual(meta.when.strftime("%Y-%m-%d %H:%M:%S"), self.expected[name], name)
        return meta

    def test_jpeg_little_endian(self):
        self.assertEqual(self.assert_meta("jpeg_le.jpg").tag, "EXIF:DateTimeOriginal")

    def test_jpeg_big_endian(self):
        meta = self.assert_meta("jpeg_be.jpg")
        self.assertEqual(meta.tag, "EXIF:DateTimeOriginal")
        self.assertEqual(meta.camera, "BigEndian")

    def test_png_exif_chunk(self):
        self.assertEqual(self.assert_meta("photo.png").camera, "PngCam")

    def test_webp_exif_chunk(self):
        self.assert_meta("shot.webp")

    def test_tiff_file(self):
        self.assert_meta("scan.tiff")

    def test_heic_isobmff(self):
        meta = self.assert_meta("iphone.heic")
        self.assertEqual(meta.camera, "iPhone 14")

    def test_missing_metadata(self):
        meta = read_meta(self.root / "no_date.jpg")
        self.assertIsNone(meta.when)
        self.assertEqual(meta.tag, "")

    def test_unreadable_file_is_safe(self):
        broken = self.root / "broken.jpg"
        broken.write_bytes(b"\xff\xd8\xff\xe1\x00")
        self.assertIsNone(read_meta(broken).when)


class TestPlannerAndExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.source = self.base / "photos"
        self.expected = make_samples.make_samples(self.source)

    def tearDown(self):
        self.tmp.cleanup()

    def options(self, **kwargs) -> Options:
        params = {
            "source": str(self.source),
            "layout": "{YYYY}-{MM}",
            "mode": "move",
            "fallback": "auto",
            "rename_files": False,
        }
        params.update(kwargs)
        return Options(**params)

    def test_plan_groups_by_month(self):
        plan = build_plan(self.options())
        self.assertEqual(plan.scanned, 8)
        by_name = {item.src.name: item for item in plan.items}
        self.assertEqual(by_name["jpeg_le.jpg"].year_month, "2019-05")
        self.assertEqual(by_name["iphone.heic"].year_month, "2023-08")
        self.assertEqual(by_name["scan.tiff"].year_month, "2018-03")
        # No EXIF -> filename fallback
        self.assertEqual(by_name["IMG_20191224_183000.jpg"].source_tag, "文件名")
        self.assertEqual(by_name["IMG_20191224_183000.jpg"].year_month, "2019-12")
        # No EXIF, no date in name -> file mtime fallback
        self.assertEqual(by_name["no_date.jpg"].source_tag, "文件时间")

    def test_move_then_undo(self):
        plan = build_plan(self.options())
        result = execute(plan)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.done, 8)
        self.assertEqual(sorted(p.name for p in (self.source / "2019-05").iterdir()), ["jpeg_le.jpg"])
        self.assertTrue((self.source / "2023-08" / "iphone.heic").exists())
        self.assertTrue((self.source / "2018-03" / "scan.tiff").exists())
        self.assertEqual(len(list(self.source.glob("*.jpg"))), 0, "源目录不应残留已移动的文件")

        batches = undo_files(self.source)
        self.assertEqual(len(batches), 1)
        undone = undo(batches[0])
        self.assertEqual(undone.done, 8)
        self.assertEqual(undone.failed, 0)
        self.assertTrue((self.source / "jpeg_le.jpg").exists())
        self.assertFalse((self.source / "2019-05" / "jpeg_le.jpg").exists())
        self.assertFalse((self.source / "2019-05").exists(), "撤销后应清掉本次创建的空月份文件夹")
        self.assertFalse((self.source / ".imagesorter_undo").exists(), "撤销记录目录应一并清掉")

    def test_copy_leaves_source(self):
        plan = build_plan(self.options(mode="copy", target=str(self.base / "out")))
        result = execute(plan)
        self.assertEqual(result.done, 8)
        self.assertTrue((self.base / "out" / "2019-05" / "jpeg_le.jpg").exists())
        self.assertTrue((self.source / "jpeg_le.jpg").exists())

    def test_conflict_renames(self):
        nested = self.source / "sub"
        nested.mkdir()
        (nested / "jpeg_le.jpg").write_bytes(make_samples.wrap_plain_jpeg())
        plan = build_plan(self.options())
        targets = [str(item.dst) for item in plan.todo if item.dst and "jpeg_le" in item.dst.name]
        self.assertEqual(len(targets), 2)
        self.assertEqual(len(set(targets)), 2, "同名文件必须被改名而不是互相覆盖")

    def test_skip_mode(self):
        plan = build_plan(self.options(fallback="skip"))
        names = [item.src.name for item in plan.skipped]
        self.assertIn("no_date.jpg", names)

    def test_rename_files(self):
        plan = build_plan(self.options(rename_files=True))
        item = next(i for i in plan.todo if i.src.name == "jpeg_le.jpg")
        self.assertEqual(item.dst.name, "20190506_123456.jpg")

    def test_already_sorted_is_in_place(self):
        plan = build_plan(self.options())
        execute(plan)
        again = build_plan(self.options())
        self.assertEqual(len(again.todo), 0)
        self.assertEqual(len(again.skipped), 8)

    def test_undo_log_survives_partial_failure(self):
        plan = build_plan(self.options())
        target = plan.todo[0].dst
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"blocker")
        result = execute(plan)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.done, 7)
        self.assertIsNotNone(result.undo_file)


class TestRobustness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.source = self.base / "photos"
        self.source.mkdir(parents=True)
        self.jpg = make_samples.wrap_jpeg(make_samples.exif_block("2020-03-15 10:00:00"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_undo_records_never_overwrite_each_other(self):
        for i in range(3):
            (self.source / f"p{i}.jpg").write_bytes(self.jpg)
        opts = Options(source=str(self.source), mode="move", rename_files=False)
        execute(build_plan(opts))
        for i in range(3):
            (self.source / f"q{i}.jpg").write_bytes(self.jpg)
        execute(build_plan(opts))
        batches = undo_files(self.source)
        self.assertEqual(len(batches), 2, "两批整理必须留下两份撤销记录")

    def test_cancelled_scan_is_flagged(self):
        for i in range(5):
            (self.source / f"p{i}.jpg").write_bytes(self.jpg)
        plan = build_plan(Options(source=str(self.source), rename_files=False), should_cancel=lambda: True)
        self.assertTrue(plan.cancelled)
        self.assertEqual(plan.todo, [])

    def test_zero_byte_files_are_skipped(self):
        (self.source / "empty.jpg").write_bytes(b"")
        (self.source / "real.jpg").write_bytes(self.jpg)
        plan = build_plan(Options(source=str(self.source), rename_files=False))
        skipped = {item.src.name: item.note for item in plan.skipped}
        self.assertIn("empty.jpg", skipped)
        self.assertEqual(len(plan.todo), 1)

    def test_file_removed_after_scan_is_reported(self):
        victim = self.source / "gone.jpg"
        victim.write_bytes(self.jpg)
        plan = build_plan(Options(source=str(self.source), rename_files=False))
        victim.unlink()
        result = execute(plan)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.done, 0)

    def test_identical_file_is_not_duplicated(self):
        (self.source / "a.jpg").write_bytes(self.jpg)
        execute(build_plan(Options(source=str(self.source), mode="move", rename_files=False)))
        (self.source / "a.jpg").write_bytes(self.jpg)   # 同一张照片又放回来
        plan = build_plan(Options(source=str(self.source), mode="move", rename_files=False))
        dup = next(item for item in plan.items if item.src.name == "a.jpg")
        self.assertEqual(dup.action, "skip")
        execute(plan)
        self.assertEqual(len(list((self.source / "2020-03").iterdir())), 1,
                         "内容相同的文件不该产生副本")

    def test_link_mode_leaves_source_untouched(self):
        (self.source / "a.jpg").write_bytes(self.jpg)
        plan = build_plan(Options(source=str(self.source), target=str(self.base / "out"), mode="link", rename_files=False))
        result = execute(plan)
        self.assertEqual(result.done, 1)
        src = self.source / "a.jpg"
        dst = self.base / "out" / "2020-03" / "a.jpg"
        self.assertTrue(src.exists())
        self.assertTrue(dst.exists())
        self.assertEqual(src.stat().st_ino, dst.stat().st_ino, "应该是同一个 inode")
        undo(result.undo_file)
        self.assertFalse(dst.exists())
        self.assertTrue(src.exists(), "撤销只删链接，源文件必须还在")

    def test_prune_empty_removes_emptied_folders(self):
        for name in ("甲", "乙"):
            sub = self.source / name
            sub.mkdir()
            (sub / "p.jpg").write_bytes(self.jpg)
        keep = self.source / "keep"
        keep.mkdir()
        (keep / "note.txt").write_text("hi")
        result = execute(build_plan(Options(source=str(self.source), mode="move", prune_empty=True, rename_files=False)))
        self.assertEqual(result.pruned, 2)
        self.assertFalse((self.source / "甲").exists())
        self.assertTrue((self.source / "keep").exists(), "有其它文件的目录不能删")

    def test_default_rename_uses_capture_time(self):
        self.assertTrue(Options(source=str(self.source)).rename_files,
                        "默认就应该按拍摄时间命名")

    def test_video_time_comes_from_mvhd(self):
        from datetime import timezone
        (self.source / "clip.mp4").write_bytes(make_samples.wrap_mp4(datetime(2021, 1, 2, 3, 4, 5)))
        plan = build_plan(Options(source=str(self.source), rename_files=False))
        item = next(i for i in plan.items if i.src.name == "clip.mp4")
        expected = datetime(2021, 1, 2, 3, 4, 5, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        self.assertEqual(item.source_tag, "视频文件头")
        self.assertEqual(item.when, expected)

    def test_duplicate_content_is_quarantined(self):
        (self.source / "a.jpg").write_bytes(self.jpg)
        (self.source / "b.jpg").write_bytes(self.jpg)
        plan = build_plan(Options(source=str(self.source), rename_files=False))
        dups = [i for i in plan.items if i.action == "duplicate"]
        self.assertEqual(len(dups), 1, "内容相同的只留一张")
        result = execute(plan)
        self.assertEqual(result.done, 1)
        self.assertEqual(result.trashed, 1)
        self.assertEqual(len(list((self.source / ".imagesorter_undo" / "trash").rglob("*.jpg"))), 1)
        undo(result.undo_file)
        self.assertEqual(sorted(p.name for p in self.source.glob("*.jpg")), ["a.jpg", "b.jpg"])

    def test_month_folder_with_old_name_gets_renamed(self):
        folder = self.source / "2020-03"
        folder.mkdir()
        (folder / "IMG_0001.jpg").write_bytes(self.jpg)
        plan = build_plan(Options(source=str(self.source), rename_files=True))
        item = next(i for i in plan.items if i.src.name == "IMG_0001.jpg")
        self.assertEqual(item.action, "planned", "位置对了但名字不对，应该重新处理")
        self.assertEqual(item.dst.name, "20200315_100000.jpg")

    def test_readonly_target_is_replaced_in_overwrite_mode(self):
        target = self.source / "2020-03"
        target.mkdir()
        existing = target / "real.jpg"
        existing.write_bytes(b"old")
        os.chmod(existing, 0o444)
        (self.source / "real.jpg").write_bytes(self.jpg)
        plan = build_plan(Options(source=str(self.source), conflict="overwrite", rename_files=False))
        result = execute(plan)
        self.assertEqual(result.failed, 0)
        self.assertGreater(existing.stat().st_size, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
