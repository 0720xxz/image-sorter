"""格式矩阵：README 里承诺的每个扩展名都要真跑一遍。

分两类断言：
  * 有解析路径的格式（EXIF / XMP / 容器），必须读到正确时间
  * 没有解析路径的格式（GIF、BMP、AVI 等），必须不崩、不误判，
    交给文件名或文件时间兜底
"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples  # noqa: E402
from imagesorter.exif import read_meta  # noqa: E402

STAMP = "2019-05-06 12:34:56"
EXPECTED = datetime(2019, 5, 6, 12, 34, 56)          # EXIF 存的是本地时间，原样返回

# 视频容器的 mvhd 按 QuickTime 规范存 UTC，读出来会转成本地时区，
# 所以期望值要跟着时区走，否则在 UTC+8 的机器上会差 8 小时。
VIDEO_UTC = datetime(2019, 5, 6, 12, 34, 56, tzinfo=timezone.utc)
VIDEO_EXPECTED = VIDEO_UTC.astimezone().replace(tzinfo=None)


# --- 只求结构合法、能被识别成该格式的最小样本 ---------------------------

def tiny_gif() -> bytes:
    return (b"GIF89a" + struct.pack("<HH", 1, 1) + b"\x80\x00\x00"
            + b"\x00\x00\x00\xff\xff\xff"
            + b"\x2c" + struct.pack("<HHHH", 0, 0, 1, 1) + b"\x00"
            + b"\x02\x02\x44\x01\x00" + b"\x3b")


def tiny_bmp() -> bytes:
    header = struct.pack("<2sIHHI", b"BM", 58, 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0)
    return header + dib + b"\x00\x00\x00\x00"


def tiny_avi() -> bytes:
    body = b"AVI " + b"LIST" + struct.pack("<I", 4) + b"hdrl" + b"\x00" * 64
    return b"RIFF" + struct.pack("<I", len(body)) + body


def tiny_ebml(brand: bytes) -> bytes:
    # Matroska / WebM 都是 EBML，头部 magic 相同
    head = b"\x1a\x45\xdf\xa3" + struct.pack("<I", 0x1000) + brand + b"\x00" * 64
    return head


def tiny_asf() -> bytes:
    guid = bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")
    return guid + struct.pack("<Q", 512) + b"\x01\x02" + b"\x00" * 64


def tiny_flv() -> bytes:
    return b"FLV\x01\x05" + struct.pack(">I", 9) + b"\x00\x00\x00\x00" + b"\x00" * 32


def tiff_renamed(ext: str) -> bytes:
    """RAW 基本都是 TIFF 容器，用同一份 TIFF 结构换后缀验证。"""
    return make_samples.build_tiff(
        ifd0=[(make_samples.TAG_MODEL, 2, "RawCam"),
              (make_samples.TAG_DATETIME, 2, STAMP)],
        exif_ifd=[(make_samples.TAG_DT_ORIGINAL, 2, STAMP)],
    )


def heif_brand(brand: bytes) -> bytes:
    return make_samples.wrap_heic(make_samples.exif_block(STAMP, "PhoneCam")).replace(
        b"heic" + struct.pack(">I", 0), brand + struct.pack(">I", 0), 1)


def video_brand(brand: bytes) -> bytes:
    base = make_samples.wrap_mp4(VIDEO_UTC)
    # ftyp 里的第一处 brand 换成目标品牌
    return base.replace(b"isom" + struct.pack(">I", 512) + b"isommp41",
                        brand + struct.pack(">I", 512) + b"isommp41", 1)


# --- 用例表：扩展名 -> (内容, 是否应读出时间) ---------------------------

def cases() -> list[tuple[str, bytes, bool, datetime | None]]:
    jpeg = make_samples.wrap_jpeg(make_samples.exif_block(STAMP))
    png = make_samples.wrap_png(make_samples.exif_block(STAMP))
    webp = make_samples.wrap_webp(make_samples.exif_block(STAMP))
    tiff = tiff_renamed(".tif")
    return [
        (".jpg", jpeg, True, EXPECTED),
        (".jpeg", jpeg, True, EXPECTED),
        (".jpe", jpeg, True, EXPECTED),
        (".jfif", jpeg, True, EXPECTED),
        (".png", png, True, EXPECTED),
        (".webp", webp, True, EXPECTED),
        (".tif", tiff, True, EXPECTED),
        (".tiff", tiff, True, EXPECTED),
        (".heic", make_samples.wrap_heic(make_samples.exif_block(STAMP)), True, EXPECTED),
        (".heif", heif_brand(b"heif"), True, EXPECTED),
        (".avif", heif_brand(b"avif"), True, EXPECTED),
        (".hif", heif_brand(b"heic"), True, EXPECTED),
        (".dng", tiff_renamed(".dng"), True, EXPECTED),
        (".cr2", tiff_renamed(".cr2"), True, EXPECTED),
        (".nef", tiff_renamed(".nef"), True, EXPECTED),
        (".arw", tiff_renamed(".arw"), True, EXPECTED),
        (".orf", tiff_renamed(".orf"), True, EXPECTED),
        (".rw2", tiff_renamed(".rw2"), True, EXPECTED),
        (".pef", tiff_renamed(".pef"), True, EXPECTED),
        (".srw", tiff_renamed(".srw"), True, EXPECTED),
        (".mp4", video_brand(b"isom"), True, VIDEO_EXPECTED),
        (".mov", video_brand(b"qt  "), True, VIDEO_EXPECTED),
        (".m4v", video_brand(b"M4V "), True, VIDEO_EXPECTED),
        (".3gp", video_brand(b"3gp4"), True, VIDEO_EXPECTED),
        (".3g2", video_brand(b"3g2a"), True, VIDEO_EXPECTED),
        (".gif", tiny_gif(), False, None),
        (".bmp", tiny_bmp(), False, None),
        (".avi", tiny_avi(), False, None),
        (".mkv", tiny_ebml(b"matroska"), False, None),
        (".webm", tiny_ebml(b"webm"), False, None),
        (".wmv", tiny_asf(), False, None),
        (".flv", tiny_flv(), False, None),
    ]


class TestFormatMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_advertised_extension(self):
        parsed, fallback = [], []
        for ext, payload, should_parse, expected in cases():
            with self.subTest(ext=ext):
                path = self.root / f"sample{ext}"
                path.write_bytes(payload)
                meta = read_meta(path)
                if should_parse:
                    self.assertIsNotNone(meta.when, f"{ext} 应该能读出拍摄时间")
                    self.assertEqual(meta.when, expected, f"{ext} 时间不对: {meta.when}")
                    parsed.append(ext)
                else:
                    self.assertIsNone(meta.when, f"{ext} 不该声称能读时间")
                    fallback.append(ext)
        # 用 ASCII 输出，Windows 控制台默认不是 UTF-8
        print(f"\n  parsed  {len(parsed):2d}: {' '.join(parsed)}")
        print(f"  fallback {len(fallback):2d}: {' '.join(fallback)}")

    def test_unknown_garbage_does_not_crash(self):
        for name in ("x.bin", "x.raw", "noext"):
            path = self.root / name
            path.write_bytes(b"\x00\x13\x37" * 100)
            self.assertIsNone(read_meta(path).when)

    def test_truncated_variants_are_safe(self):
        for ext, payload, *_rest in cases():
            path = self.root / f"cut{ext}"
            path.write_bytes(payload[: max(len(payload) // 3, 8)])
            read_meta(path)   # 只要不抛异常


if __name__ == "__main__":
    unittest.main(verbosity=2)
