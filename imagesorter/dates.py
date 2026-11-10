"""Date parsing, layout rendering and small path helpers.

No third-party dependencies: this module must work on a bare Windows
Python install as well as inside the frozen .exe.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

# --- parsing -------------------------------------------------------------

_EXIF_DT = re.compile(
    r"(\d{4})[:\-/.](\d{1,2})[:\-/.](\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.\d+)?)?)?"
)

_ISO_DT = re.compile(
    r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"
    r"(?:[T ](?P<H>\d{2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)

# 文件名里的日期时间：2019-05-06 12.34.56 / IMG_20190506_123456 / 20230506123456
_FN_PATTERNS = (
    re.compile(
        r"(20\d{2})[-_.:\s]?([01]\d)[-_.:\s]?([0-3]\d)"
        r"[-_.:\sT]?([0-2]\d)[-_.:\s]?([0-5]\d)[-_.:\s]?([0-5]\d)"
    ),
    re.compile(r"(20\d{2})[-_.:\s]?([01]\d)[-_.:\s]?([0-3]\d)"),
)


def _safe_dt(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> datetime | None:
    if not (1971 <= y <= 2999) or not (1 <= mo <= 12) or not (1 <= d <= 31):
        return None
    if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 60):
        return None
    try:
        return datetime(y, mo, d, h, mi, min(s, 59))
    except ValueError:
        return None


def parse_exif_datetime(value: str | None) -> datetime | None:
    """Parse EXIF style 'YYYY:MM:DD HH:MM:SS' (timezone suffixes tolerated)."""
    if not value:
        return None
    text = str(value).strip().strip("\x00")
    if not text or text.startswith("0000"):
        return None
    head = text.split("+")[0].split("Z")[0]
    m = _EXIF_DT.search(head)
    if not m:
        return None
    parts = [int(g) if g else 0 for g in m.groups()]
    return _safe_dt(*parts)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    m = _ISO_DT.search(str(value))
    if not m:
        return None
    g = m.groupdict()
    return _safe_dt(
        int(g["y"]),
        int(g["m"]),
        int(g["d"]),
        int(g["H"] or 0),
        int(g["M"] or 0),
        int(g["S"] or 0),
    )


def parse_datetime_any(value: str | None) -> datetime | None:
    """Try EXIF, then ISO/XMP, then compact numeric forms."""
    dt = parse_exif_datetime(value)
    if dt:
        return dt
    dt = parse_iso_datetime(value)
    if dt:
        return dt
    if value and str(value).isdigit() and len(str(value)) >= 8:
        digits = str(value)
        y, mo, d = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
        h = int(digits[8:10]) if len(digits) >= 10 else 0
        mi = int(digits[10:12]) if len(digits) >= 12 else 0
        s = int(digits[12:14]) if len(digits) >= 14 else 0
        return _safe_dt(y, mo, d, h, mi, s)
    return None


def datetime_from_filename(stem: str) -> datetime | None:
    """Recover a date from names like IMG_20190506_123456 or '2019-05-06 12.34.56'."""
    if not stem:
        return None
    for pattern in _FN_PATTERNS:
        for m in pattern.finditer(stem):
            nums = [int(g) if g else 0 for g in m.groups()]
            if len(nums) == 6:
                dt = _safe_dt(*nums)
            else:
                dt = _safe_dt(nums[0], nums[1], nums[2])
            if dt:
                return dt
    return _from_epoch_ms(stem)


# WeChat/QQ exports look like 'mmexport1687654321000.jpg': a 13 digit epoch
# in milliseconds. Nothing else in a normal filename matches that shape.
_EPOCH_MS = re.compile(r"(?<!\d)(1\d{12})(?!\d)")


def _from_epoch_ms(stem: str) -> datetime | None:
    match = _EPOCH_MS.search(stem)
    if not match:
        return None
    try:
        dt = datetime.fromtimestamp(int(match.group(1)) / 1000)
    except (OSError, OverflowError, ValueError):
        return None
    # WeChat only exists since 2011, so older "timestamps" are plain numbers.
    return dt if 2010 <= dt.year <= 2035 else None


# --- layout --------------------------------------------------------------

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_part(text: str) -> str:
    """Make one path component safe on Windows without touching separators."""
    cleaned = _BAD_CHARS.sub("_", text).strip().strip(".")
    return cleaned or "_"


def render_layout(template: str, dt: datetime | None) -> list[str]:
    """Render a layout template into a list of path components.

    Tokens: {YYYY} {YY} {MM} {M} {MMM} {DD} {D} plus strftime on any `%`.
    Separators '/' or '\\' inside the template create sub-directories, so
    '{YYYY}/{MM}' and '{YYYY}-{MM}' are both valid.
    """
    if not template or not template.strip():
        template = "{YYYY}-{MM}"
    if dt is None:
        return ["_undated"]
    values = {
        "{YYYY}": f"{dt.year:04d}",
        "{YY}": f"{dt.year % 100:02d}",
        "{MM}": f"{dt.month:02d}",
        "{M}": str(dt.month),
        "{MMM}": _MONTH_NAMES[dt.month - 1],
        "{DD}": f"{dt.day:02d}",
        "{D}": str(dt.day),
    }
    text = template
    for token, repl in values.items():
        text = text.replace(token, repl)
    if "%" in text:
        try:
            text = dt.strftime(text)
        except ValueError:
            pass
    parts: list[str] = []
    normalized = text.replace("\\", "/")
    for raw in PurePosixPath(normalized).parts:
        part = sanitize_part(raw)
        if part not in ("", "."):
            parts.append(part)
    return parts or ["_undated"]


def unique_suffix_name(stem: str, suffix: str, index: int) -> str:
    return f"{stem}_{index:03d}{suffix}"


def long_path(path: Path) -> str:
    """Return a Windows extended-length path when needed.

    Python's os layer accepts the \\\\?\\ prefix on Windows and it lifts the
    260 character MAX_PATH limit that deep photo libraries regularly hit.
    """
    text = str(path)
    if len(text) < 240:
        return text
    try:
        absolute = str(Path(text).resolve())
    except OSError:
        absolute = text
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def path_exists(path: Path) -> bool:
    """exists() that also works beyond MAX_PATH on Windows."""
    try:
        return os.path.exists(long_path(path))
    except (OSError, ValueError):
        return False


def display_path(path: Path) -> str:
    """Strip the extended-length prefix so the UI shows a normal path."""
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text
