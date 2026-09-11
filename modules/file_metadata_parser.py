#!/usr/bin/env python3
import sys
import re
from datetime import datetime, timedelta

# ——————————————————————————————————————————————————————————————
# Timestamp extraction
# ——————————————————————————————————————————————————————————————

# Matches either:
#   • WCA/Zeuss style:  20250705T020039Z
#   • Modified style:   20250705020039
# Optionally preceded by camlower_, cammid_, or camupper_
# superseded-by modules/cameras.json families (legacy prefixes + timestamp_formats) - pending migration step (c+)
_TIMESTAMP_REGEX = re.compile(r'(?<!\d)(\d{8}T\d{6}Z|\d{14})(?!\d)')

def parse_timestamp_str(filename: str) -> str | None:
    """
    Extract the timestamp string from a filename.
    Returns YYYYMMDDTHHMMSSZ, or None for missing/invalid/ambiguous evidence.
    Parent directory timestamps are never evidence about an image or video.
    """
    basename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    timestamps = set()
    for match in _TIMESTAMP_REGEX.finditer(basename):
        ts = match.group(1)
        try:
            value = datetime.strptime(
                ts, "%Y%m%d%H%M%S" if len(ts) == 14 else "%Y%m%dT%H%M%SZ")
        except ValueError:
            return None
        timestamps.add(value.strftime("%Y%m%dT%H%M%SZ"))
    return next(iter(timestamps)) if len(timestamps) == 1 else None

def parse_timestamp(filename: str) -> datetime | None:
    """
    Return naive UTC (matching navigation readers), or None, never an epoch fallback.
    """
    ts_str = parse_timestamp_str(filename)
    return datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ") if ts_str is not None else None


def navigation_match_timestamp(timestamp: datetime | None) -> datetime | None:
    """Correct raw image UTC for matching only; never rewrite filename time.

    Positive project clock_offset_seconds moves image time forward. Callers
    always pass the raw TIMESTAMP, preserving repeatability across matching
    passes and preventing extraction from applying the correction twice.
    """
    if timestamp is None:
        return None
    from .camera_registry import navigation_defaults
    try:
        return timestamp + timedelta(seconds=navigation_defaults()['clock_offset_seconds'])
    except OverflowError as exc:
        raise ValueError('Image clock correction exceeds datetime range') from exc

# ——————————————————————————————————————————————————————————————
# Frame‐number extraction (unchanged)
# ——————————————————————————————————————————————————————————————

def parse_frame_number_str(filename: str) -> str:
    """
    Extracts a frame number string from a filename (e.g. 'frame123').
    """
    match = re.search(r'frame(\d+)', filename or "")
    return match.group(1) if match else ""

def parse_frame_number(filename: str) -> int:
    """
    Extracts a frame number integer from a filename, or sys.maxsize if none.
    """
    s = parse_frame_number_str(filename)
    return int(s) if s.isdigit() else sys.maxsize
