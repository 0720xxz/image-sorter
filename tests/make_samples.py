"""Build synthetic image files with real EXIF structures.

Every sample here is written byte by byte, so the tests exercise the parser
against genuine container layouts instead of trusting Pillow to agree with us.
"""

from __future__ import annotations

import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

TAG_DATETIME = 0x0132
TAG_EXIF_IFD = 0x8769
TAG_DT_ORIGINAL = 0x9003
TAG_DT_DIGITIZED = 0x9004
TAG_MODEL = 0x0110


def _encode(typ: int, value, endian: str) -> tuple[int, bytes]:
    if typ == 2:
        raw = value.encode("ascii") + b"\x00" if isinstance(value, str) else value + b"\x00"
        return len(raw), raw
    if typ in (3, 4):
        values = list(value) if isinstance(value, (list, tuple)) else [value]
        code = "H" if typ == 3 else "I"
        return len(values), struct.pack(endian + code * len(values), *values)
    raise ValueError(f"unsupported type {typ}")


def build_tiff(ifd0, exif_ifd=None, little: bool = True) -> bytes:
    """Serialize a TIFF/EXIF block from [(tag, type, value), ...] pairs."""
    endian = "<" if little else ">"
    order = b"II" if little else b"MM"

    def prepare(pairs):
        return [(tag, typ) + _encode(typ, value, endian) for tag, typ, value in pairs]

    entries0 = prepare(ifd0)
    entries_e = prepare(exif_ifd or [])

    count0 = len(entries0) + (1 if entries_e else 0)
    size0 = 2 + 12 * count0 + 4
    exif_offset = 8 + size0
    size_e = (2 + 12 * len(entries_e) + 4) if entries_e else 0
    data_start = 8 + size0 + size_e

    if entries_e:
        entries0.append((TAG_EXIF_IFD, 4, 1, struct.pack(endian + "I", exif_offset)))
        entries0.sort(key=lambda item: item[0])

    def serialize(entries, cursor):
        body = struct.pack(endian + "H", len(entries))
        extra = b""
        for tag, typ, count, raw in entries:
            if len(raw) <= 4:
                body += struct.pack(endian + "HHI", tag, typ, count) + raw.ljust(4, b"\x00")
            else:
                body += struct.pack(endian + "HHII", tag, typ, count, cursor)
                extra += raw
                cursor += len(raw)
        body += struct.pack(endian + "I", 0)
        return body, extra, cursor

    body0, extra0, cursor = serialize(entries0, data_start)
    bodye, extrae, _ = serialize(entries_e, cursor) if entries_e else (b"", b"", cursor)
    header = order + struct.pack(endian + "HI", 42, 8)
    return header + body0 + bodye + extra0 + extrae


def exif_block(when: str, model: str = "TestCam") -> bytes:
    return build_tiff(
        ifd0=[
            (TAG_MODEL, 2, model),
            (TAG_DATETIME, 2, when),
        ],
        exif_ifd=[
            (TAG_DT_ORIGINAL, 2, when),
            (TAG_DT_DIGITIZED, 2, when),
        ],
    )


def wrap_jpeg(tiff: bytes, with_jfif: bool = True) -> bytes:
    out = b"\xff\xd8"
    if with_jfif:
        app0 = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        out += b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0
    payload = b"Exif\x00\x00" + tiff
    out += b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    out += b"\xff\xda\x00\x0c\x01\x01\x00\x00\x3f\x00" + b"\x00" * 16 + b"\xff\xd9"
    return out


def wrap_plain_jpeg(salt: int = 0) -> bytes:
    """无 EXIF 的 JPEG；salt 用来让多个样本内容不同，避免被当成重复文件。"""
    app0 = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    out = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0
    out += b"\xff\xda\x00\x0c\x01\x01\x00\x00\x3f\x00" + b"\x00" * 16 + b"\xff\xd9"
    return out + b"\x00" * salt


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def wrap_png(tiff: bytes) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"eXIf", tiff)
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00"))
        + _png_chunk(b"IEND", b"")
    )


def wrap_webp(tiff: bytes) -> bytes:
    chunk = b"EXIF" + struct.pack("<I", len(tiff)) + tiff
    if len(tiff) % 2:
        chunk += b"\x00"
    body = b"WEBP" + chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind + payload


def wrap_heic(tiff: bytes) -> bytes:
    ftyp = _box(b"ftyp", b"heic" + struct.pack(">I", 0) + b"mif1heic")

    infe = _box(
        b"infe",
        b"\x02\x00\x00\x00" + struct.pack(">H", 1) + struct.pack(">H", 0)
        + b"Exif" + b"Exif\x00",
    )
    iinf = _box(b"iinf", b"\x00\x00\x00\x00" + struct.pack(">H", 1) + infe)

    item_payload = struct.pack(">I", 0) + b"Exif\x00\x00" + tiff

    # iloc has a fixed size, so build it twice: once to learn the layout,
    # once with the real absolute offset of the Exif item.
    def build_iloc(item_offset: int) -> bytes:
        body = (
            b"\x00\x00\x00\x00"
            + b"\x44"
            + b"\x00"
            + struct.pack(">H", 1)
            + struct.pack(">H", 1)
            + struct.pack(">H", 0)
            + struct.pack(">H", 1)
            + struct.pack(">II", item_offset, len(item_payload))
        )
        return _box(b"iloc", body)

    iloc = build_iloc(0)
    meta = _box(b"meta", b"\x00\x00\x00\x00" + iinf + iloc)
    data_offset = len(ftyp) + len(meta)
    iloc = build_iloc(data_offset)
    meta = _box(b"meta", b"\x00\x00\x00\x00" + iinf + iloc)
    return ftyp + meta + item_payload


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind + payload


def wrap_mp4(when: datetime, timescale: int = 1000) -> bytes:
    """最小可解析的 MP4：ftyp + moov/mvhd + mdat，时间按 1904 纪元写入。

    naive 的 when 一律当 UTC 处理，跟 QuickTime 规范一致。
    """
    epoch = datetime(1904, 1, 1, tzinfo=timezone.utc)
    moment = when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)
    seconds = int((moment - epoch).total_seconds())
    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">II", seconds, seconds)
                + struct.pack(">I", timescale) + struct.pack(">I", 5000) + b"\x00" * 80)
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isommp41")
    return ftyp + _box(b"moov", mvhd) + _box(b"mdat", b"\x00" * 64)


def make_samples(root: Path) -> dict[str, str]:
    """Write sample files under root; return name -> expected 'YYYY-MM-DD HH:MM:SS'."""
    root.mkdir(parents=True, exist_ok=True)
    expected = {
        "jpeg_le.jpg": "2019-05-06 12:34:56",
        "jpeg_be.jpg": "2021-11-02 08:15:00",
        "photo.png": "2022-07-09 18:30:01",
        "shot.webp": "2020-02-29 23:59:59",
        "scan.tiff": "2018-03-11 07:00:00",
        "iphone.heic": "2023-08-14 10:20:30",
    }
    (root / "jpeg_le.jpg").write_bytes(wrap_jpeg(exif_block(expected["jpeg_le.jpg"])))
    (root / "jpeg_be.jpg").write_bytes(
        wrap_jpeg(build_tiff(
            ifd0=[(TAG_MODEL, 2, "BigEndian"), (TAG_DATETIME, 2, expected["jpeg_be.jpg"])],
            exif_ifd=[(TAG_DT_ORIGINAL, 2, expected["jpeg_be.jpg"])],
            little=False,
        ))
    )
    (root / "photo.png").write_bytes(wrap_png(exif_block(expected["photo.png"], "PngCam")))
    (root / "shot.webp").write_bytes(wrap_webp(exif_block(expected["shot.webp"], "WebCam")))
    (root / "scan.tiff").write_bytes(
        build_tiff(
            ifd0=[(TAG_DATETIME, 2, expected["scan.tiff"])],
            exif_ifd=[(TAG_DT_ORIGINAL, 2, expected["scan.tiff"])],
        )
    )
    (root / "iphone.heic").write_bytes(wrap_heic(exif_block(expected["iphone.heic"], "iPhone 14")))
    # No metadata at all: falls back to filename / mtime.
    (root / "IMG_20191224_183000.jpg").write_bytes(wrap_plain_jpeg(salt=17))
    (root / "no_date.jpg").write_bytes(wrap_plain_jpeg(salt=41))
    return expected
