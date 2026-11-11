"""Dependency-free image metadata reader.

Formats covered: JPEG, PNG, WebP, TIFF family (tif/tiff/cr2/nef/arw/dng/orf/
rw2/pef/srw) and ISOBMFF (heic/heif/avif). Only the few tags needed to answer
"when was this photo taken" are decoded, which keeps scanning fast even on
libraries with tens of thousands of files.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .dates import long_path, parse_datetime_any

# --- EXIF tag ids --------------------------------------------------------

TAG_MODEL = 0x0110
TAG_DATETIME = 0x0132
TAG_EXIF_IFD = 0x8769
TAG_GPS_IFD = 0x8825
TAG_DT_ORIGINAL = 0x9003
TAG_DT_DIGITIZED = 0x9004
TAG_OFFSET_ORIGINAL = 0x9011

_TYPE_SIZES = {
    1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1,
    8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4,
}

READ_LIMIT = 1 << 20  # 1 MiB is plenty: EXIF lives right after the header
_XMP_PREFIX = b"http://ns.adobe.com/xap/1.0/\x00"
_XMP_DATE = re.compile(
    rb'(?:xmp:CreateDate|photoshop:DateCreated|xmp:ModifyDate)\s*=\s*"([^"]{4,40})"'
)

HEIF_EXTS = {".heic", ".heif", ".avif", ".hif"}
# 这些容器的拍摄时间存在 moov/mvhd 里，和 EXIF 完全无关
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".3gp", ".3g2"}
EPOCH_1904 = datetime(1904, 1, 1, tzinfo=timezone.utc)
TIFF_EXTS = {".tif", ".tiff", ".cr2", ".nef", ".arw", ".dng", ".orf", ".rw2", ".pef", ".srw"}


@dataclass(frozen=True)
class Meta:
    """What we could learn from one file's metadata."""

    when: datetime | None = None
    tag: str = ""
    camera: str = ""


# --- TIFF / IFD ----------------------------------------------------------


def _tag_value(buf: bytes, endian: str, typ: int, count: int, inline: bytes):
    size = _TYPE_SIZES.get(typ)
    if size is None or count <= 0:
        return None
    total = size * count
    if total <= 4:
        raw = inline[:total]
    else:
        if count > 0x100000:
            return None
        offset = struct.unpack(endian + "I", inline)[0]
        if offset < 0 or offset + total > len(buf):
            return None
        raw = buf[offset:offset + total]
    try:
        if typ == 2:
            return raw.split(b"\x00")[0].decode("utf-8", "replace").strip()
        if typ in (1, 7):
            return raw[0] if count == 1 else tuple(raw)
        if typ in (3, 8):
            values = struct.unpack(endian + ("H" if typ == 3 else "h") * count, raw)
            return values[0] if count == 1 else values
        if typ in (4, 9):
            values = struct.unpack(endian + ("I" if typ == 4 else "i") * count, raw)
            return values[0] if count == 1 else values
        if typ in (5, 10):
            values = struct.unpack(endian + ("II" if typ == 5 else "ii") * count, raw)
            ratios = [a / b if b else 0.0 for a, b in zip(values[0::2], values[1::2])]
            return ratios[0] if count == 1 else tuple(ratios)
        if typ in (11, 12):
            values = struct.unpack(endian + ("f" if typ == 11 else "d") * count, raw)
            return values[0] if count == 1 else values
    except (struct.error, ZeroDivisionError, IndexError):
        return None
    return None


def _read_ifd(buf: bytes, endian: str, offset: int, tags: dict, seen: set, depth: int) -> None:
    if depth > 3 or offset in seen or offset < 8 or offset + 2 > len(buf):
        return
    seen.add(offset)
    try:
        entry_count = struct.unpack(endian + "H", buf[offset:offset + 2])[0]
    except struct.error:
        return
    if entry_count <= 0 or entry_count > 512:
        return
    pos = offset + 2
    children: list[int] = []
    for _ in range(entry_count):
        if pos + 12 > len(buf):
            break
        tag, typ, count = struct.unpack(endian + "HHI", buf[pos:pos + 8])
        inline = buf[pos + 8:pos + 12]
        pos += 12
        value = _tag_value(buf, endian, typ, count, inline)
        if tag in (TAG_EXIF_IFD, TAG_GPS_IFD):
            if isinstance(value, int) and value > 8:
                children.append(value)
            continue
        if value is not None:
            tags.setdefault(tag, value)
    for child in children:
        _read_ifd(buf, endian, child, tags, seen, depth + 1)


def parse_tiff(buf: bytes) -> dict:
    """Parse a TIFF header + IFD0 (+ Exif sub-IFD) into a tag dict."""
    tags: dict = {}
    if len(buf) < 8:
        return tags
    if buf[:2] == b"II":
        endian = "<"
    elif buf[:2] == b"MM":
        endian = ">"
    else:
        return tags
    if struct.unpack(endian + "H", buf[2:4])[0] != 42:
        return tags
    try:
        first_ifd = struct.unpack(endian + "I", buf[4:8])[0]
    except struct.error:
        return tags
    _read_ifd(buf, endian, first_ifd, tags, set(), 0)
    return tags


# --- container extraction ------------------------------------------------


def _jpeg_sections(buf: bytes):
    exif = xmp = None
    pos = 2
    total = len(buf)
    while pos + 4 <= total:
        if buf[pos] != 0xFF:
            pos += 1
            continue
        marker = buf[pos + 1]
        pos += 2
        if marker == 0xFF or marker == 0x00 or marker == 0x01 or 0xD0 <= marker <= 0xD9:
            continue
        if pos + 2 > total:
            break
        seg_len = (buf[pos] << 8) | buf[pos + 1]
        if seg_len < 2:
            break
        segment = buf[pos + 2:pos + seg_len]
        if marker == 0xE1:
            if exif is None and segment[:6] == b"Exif\x00\x00":
                exif = segment[6:]
            elif xmp is None and segment.startswith(_XMP_PREFIX):
                xmp = segment[len(_XMP_PREFIX):]
        elif marker == 0xDA:
            break
        pos += seg_len
    return exif, xmp


def _png_payloads(buf: bytes):
    """Return (tiff_bytes, xmp_bytes, creation_time_text)."""
    exif = xmp = ctime = None
    pos = 8
    total = len(buf)
    while pos + 8 <= total:
        length = struct.unpack(">I", buf[pos:pos + 4])[0]
        ctype = buf[pos + 4:pos + 8]
        data = buf[pos + 8:pos + 8 + length]
        if ctype == b"eXIf" and exif is None:
            exif = data[6:] if data[:6] == b"Exif\x00\x00" else data
        elif ctype in (b"tEXt", b"iTXt", b"zTXt"):
            key, _, rest = data.partition(b"\x00")
            if key.strip().lower() == b"creation time" and ctime is None:
                text = rest.split(b"\x00")[-1] or rest
                ctime = text.decode("latin-1", "replace").strip()
            if key.strip().lower() == b"xml:com.adobe.xmp" and xmp is None:
                xmp = data
        elif ctype == b"IEND":
            break
        pos += 12 + length
    return exif, xmp, ctime


def _webp_payloads(buf: bytes):
    if len(buf) < 16 or buf[:4] != b"RIFF" or buf[8:12] != b"WEBP":
        return None, None
    pos = 12
    total = len(buf)
    while pos + 8 <= total:
        fourcc = buf[pos:pos + 4]
        size = struct.unpack("<I", buf[pos + 4:pos + 8])[0]
        data = buf[pos + 8:pos + 8 + size]
        if fourcc == b"EXIF":
            return (data[6:] if data[:6] == b"Exif\x00\x00" else data), None
        if fourcc == b"VP8X":
            pos += 8 + size + (size & 1)
            continue
        pos += 8 + size + (size & 1)
    return None, None


def _iter_boxes(buf: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", buf[pos:pos + 4])[0]
        typ = buf[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield typ, pos + header, min(pos + size, end)
        pos += size


def _heif_item_id_for_exif(buf: bytes, start: int, end: int) -> int | None:
    if start + 6 > end:
        return None
    version = buf[start]
    pos = start + 4
    pos += 2 if version == 0 else 4
    for typ, body, bend in _iter_boxes(buf, pos, end):
        if typ != b"infe" or body + 4 > bend:
            continue
        infe_version = buf[body]
        p = body + 4
        if infe_version >= 2:
            if p + 8 > bend:
                continue
            item_id = struct.unpack(">H", buf[p:p + 2])[0]
            if buf[p + 4:p + 8] == b"Exif":
                return item_id
        else:
            if p + 4 > bend:
                continue
            item_id = struct.unpack(">H", buf[p:p + 2])[0]
            name_end = buf.find(b"\x00", p + 4, bend)
            if name_end == -1:
                continue
            if b"exif" in buf[p + 4:name_end].lower():
                return item_id
    return None


def _heif_item_bytes(buf: bytes, start: int, end: int, item_id: int):
    if start + 6 > end:
        return None
    version = buf[start]
    pos = start + 4
    if pos + 2 > end:
        return None
    sizes = buf[pos]
    pos += 1
    offset_size = sizes >> 4
    length_size = sizes & 0x0F
    base_size = buf[pos] >> 4
    index_size = buf[pos] & 0x0F
    pos += 1
    if version < 2:
        if pos + 2 > end:
            return None
        count = struct.unpack(">H", buf[pos:pos + 2])[0]
        pos += 2
    else:
        if pos + 4 > end:
            return None
        count = struct.unpack(">I", buf[pos:pos + 4])[0]
        pos += 4
    for _ in range(count):
        if version < 2:
            if pos + 2 > end:
                return None
            current = struct.unpack(">H", buf[pos:pos + 2])[0]
            pos += 2
        else:
            if pos + 4 > end:
                return None
            current = struct.unpack(">I", buf[pos:pos + 4])[0]
            pos += 4
        construction = 0
        if version in (1, 2):
            if pos + 2 > end:
                return None
            construction = struct.unpack(">H", buf[pos:pos + 2])[0] & 0x0F
            pos += 2
        if pos + 2 > end:
            return None
        pos += 2  # data_reference_index
        base = int.from_bytes(buf[pos:pos + base_size], "big") if base_size else 0
        pos += base_size
        if pos + 2 > end:
            return None
        extent_count = struct.unpack(">H", buf[pos:pos + 2])[0]
        pos += 2
        extents = []
        for _ in range(extent_count):
            if version in (1, 2) and index_size:
                pos += index_size
            offset = int.from_bytes(buf[pos:pos + offset_size], "big") if offset_size else 0
            pos += offset_size
            length = int.from_bytes(buf[pos:pos + length_size], "big") if length_size else 0
            pos += length_size
            extents.append((offset, length))
        if current != item_id or not extents:
            continue
        if construction != 0:
            return None  # stored inside 'idat', not supported
        offset, length = extents[0]
        start_abs = base + offset
        if length <= 0 or start_abs + length > len(buf):
            return None
        return buf[start_abs:start_abs + length]
    return None


def _heif_exif(buf: bytes):
    meta = None
    for typ, body, end in _iter_boxes(buf, 0, len(buf)):
        if typ == b"meta":
            meta = (body, end)
            break
    if meta is None:
        return None
    mstart, mend = meta
    children = list(_iter_boxes(buf, mstart + 4, mend))
    item_id = None
    iloc = None
    for typ, body, end in children:
        if typ == b"iinf":
            item_id = _heif_item_id_for_exif(buf, body, end) or item_id
        elif typ == b"iloc":
            iloc = (body, end)
        if item_id is not None and iloc is not None:
            break
    if item_id is None or iloc is None:
        return None
    data = _heif_item_bytes(buf, iloc[0], iloc[1], item_id)
    if not data or len(data) < 8:
        return None
    offset = struct.unpack(">I", data[:4])[0]
    body = data[offset:] if offset + 8 <= len(data) else data[4:]
    if body[:6] == b"Exif\x00\x00":
        body = body[6:]
    if body[:2] in (b"II", b"MM"):
        return body
    for marker in (b"II*\x00", b"MM\x00*"):
        found = data.find(marker)
        if found != -1:
            return data[found:]
    return None


def _mvhd_to_datetime(seconds: int) -> datetime | None:
    if not seconds:
        return None
    moment = EPOCH_1904 + timedelta(seconds=seconds)
    if not (1970 <= moment.year <= 2100):
        return None
    # QuickTime 存的是 UTC，转成本地时间才和用户的印象对得上
    return moment.astimezone().replace(tzinfo=None)


def _parse_mvhd_at(buf: bytes, start: int, end: int) -> datetime | None:
    """start 指向 mvhd 的 version 字段。"""
    if start + 8 > end:
        return None
    version = buf[start]
    try:
        if version == 1:
            seconds = struct.unpack(">Q", buf[start + 4:start + 12])[0]
        else:
            seconds = struct.unpack(">I", buf[start + 4:start + 8])[0]
    except struct.error:
        return None
    return _mvhd_to_datetime(seconds)


def _video_time(buf: bytes) -> datetime | None:
    """先按 box 结构找 moov/mvhd，找不到再扫签名，应付 moov 落在文件尾部的情况。"""
    for kind, body, end in _iter_boxes(buf, 0, len(buf)):
        if kind != b"moov":
            continue
        for inner, ibody, iend in _iter_boxes(buf, body, end):
            if inner == b"mvhd":
                found = _parse_mvhd_at(buf, ibody, iend)
                if found:
                    return found

    start = 0
    while True:
        index = buf.find(b"mvhd", start)
        if index < 0:
            return None
        start = index + 4
        if index >= 4:
            size = struct.unpack(">I", buf[index - 4:index])[0]
            if 20 <= size <= 4096:
                found = _parse_mvhd_at(buf, index + 4, len(buf))
                if found:
                    return found


def _find_tiff_header(buf: bytes) -> bytes | None:
    if buf[:2] in (b"II", b"MM") and buf[2:4] in (b"*\x00", b"\x00*"):
        return buf
    for marker in (b"II*\x00", b"MM\x00*"):
        found = buf.find(marker, 0, 256 * 1024)
        if found != -1:
            candidate = buf[found:]
            if candidate[:2] == b"II" and struct.unpack("<H", candidate[2:4])[0] == 42:
                return candidate
            if candidate[:2] == b"MM" and struct.unpack(">H", candidate[2:4])[0] == 42:
                return candidate
    return None


# --- public API ----------------------------------------------------------


def _xmp_when(xmp: bytes | None) -> datetime | None:
    if not xmp:
        return None
    match = _XMP_DATE.search(xmp)
    if not match:
        return None
    return parse_datetime_any(match.group(1).decode("latin-1", "replace"))


def read_all_times(path: str | Path) -> dict[str, str]:
    """把这个文件里能找到的时间字段原样列出来，用来查时间不对的原因。"""
    p = Path(path)
    suffix = p.suffix.lower()
    out: dict[str, str] = {}
    try:
        with open(long_path(p), "rb") as handle:
            head = handle.read(READ_LIMIT)
    except (OSError, ValueError):
        return out
    if len(head) < 16:
        return out

    exif = xmp = None
    png_ctime = None
    if head[:2] == b"\xff\xd8":
        exif, xmp = _jpeg_sections(head)
    elif head[:8] == b"\x89PNG\r\n\x1a\n":
        exif, xmp, png_ctime = _png_payloads(head)
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        exif, xmp = _webp_payloads(head)
    elif head[4:8] == b"ftyp" or suffix in HEIF_EXTS or suffix in VIDEO_EXTS:
        exif = _heif_exif(head)

    tags = parse_tiff(exif) if exif else {}
    for tag, label in (
        (TAG_DT_ORIGINAL, "EXIF:DateTimeOriginal"),
        (TAG_DT_DIGITIZED, "EXIF:DateTimeDigitized"),
        (TAG_DATETIME, "EXIF:DateTime"),
        (TAG_OFFSET_ORIGINAL, "EXIF:OffsetTimeOriginal"),
        (TAG_MODEL, "EXIF:Model"),
    ):
        if tag in tags:
            value = tags[tag]
            out[label] = value if isinstance(value, str) else str(value)

    if xmp:
        match = _XMP_DATE.search(xmp)
        if match:
            out["XMP:CreateDate"] = match.group(1).decode("latin-1", "replace")
    if png_ctime:
        out["PNG:Creation Time"] = png_ctime
    if head[4:8] == b"ftyp" or suffix in VIDEO_EXTS:
        moment = _video_time(head)
        if moment:
            out["视频:mvhd"] = moment.strftime("%Y-%m-%d %H:%M:%S")
    return out


def read_meta(path: str | Path) -> Meta:
    """Read capture time (and camera model when present) from a file."""
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        with open(long_path(p), "rb") as handle:
            head = handle.read(READ_LIMIT)
    except (OSError, ValueError):
        return Meta()
    if len(head) < 16:
        return Meta()

    exif = xmp = None
    png_ctime = None
    if head[:2] == b"\xff\xd8":
        exif, xmp = _jpeg_sections(head)
    elif head[:8] == b"\x89PNG\r\n\x1a\n":
        exif, xmp, png_ctime = _png_payloads(head)
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        exif, xmp = _webp_payloads(head)
    elif head[4:8] == b"ftyp" or suffix in HEIF_EXTS or suffix in VIDEO_EXTS:
        exif = _heif_exif(head)
        if not exif:
            moment = _video_time(head)
            if moment:
                return Meta(moment, "视频文件头", "")
    elif suffix in TIFF_EXTS or head[:2] in (b"II", b"MM"):
        exif = _find_tiff_header(head)
    else:
        exif = _find_tiff_header(head) if head[:2] in (b"II", b"MM") else None

    tags = parse_tiff(exif) if exif else {}
    camera = str(tags.get(TAG_MODEL) or "").strip()

    for tag, label in (
        (TAG_DT_ORIGINAL, "EXIF:DateTimeOriginal"),
        (TAG_DT_DIGITIZED, "EXIF:DateTimeDigitized"),
        (TAG_DATETIME, "EXIF:DateTime"),
    ):
        raw = tags.get(tag)
        if isinstance(raw, str):
            dt = parse_datetime_any(raw)
            if dt:
                return Meta(dt, label, camera)

    dt = _xmp_when(xmp)
    if dt:
        return Meta(dt, "XMP:CreateDate", camera)
    if png_ctime:
        dt = parse_datetime_any(png_ctime)
        if dt:
            return Meta(dt, "PNG:Creation Time", camera)
    return Meta(None, "", camera)
