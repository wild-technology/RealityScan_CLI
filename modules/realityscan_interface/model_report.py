#!/usr/bin/env python3
"""Read the model report RealityScan renders from ``Reports\\SelectedModel.html``.

``-exportReport <out.html> "<install>\\Reports\\SelectedModel.html"`` is the
repo's model-measurement primitive (FINDINGS 2026-09-03): it runs headless
in ~4 s, does not block, and renders the SELECTED model's name, triangle
count, textured state, texture count, unwrap style and texture resolution.
It is also the only way to PROVE a ``-selectModel`` took - a missing name
inside a populated component is a silent no-op with ``lastError:0``
(rs-reference 12 F-102), so every destructive step in the workflows reads
the name back through this module before it acts.

Standalone on purpose: the workflow scripts call it as a plain script
(``"%RS_PYTHON%" "...\\model_report.py" <report.html> --write <out.txt>``)
from cmd, where a package import would need PYTHONPATH. ``run_decimate.py``
imports the same parser.

Template layout (verified against the shipped file, 2026-09-06): each value
sits in a ``<td>`` on the line AFTER its ``<th>`` label; labels are the
en-US strings below.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from typing import Optional

LABELS = {
    "name": "Model name",
    "triangles": "Triangles' count",
    "vertices": "Vertices' count",
    "textured": "Textured",
    "textures": "Textures' count",
    "unwrap_style": "Unwrapping style",
    "resolution": "Texture resolution",
}

#: Keys written by ``--write`` (cmd reads ``KEY=value`` lines into
#: ``RS_MODEL_<KEY>``).
WRITE_KEYS = ("NAME", "TRIS", "TEXTURED", "TEXTURES", "UNWRAP", "RESOLUTION")


def field(html: str, label: str) -> Optional[str]:
    match = re.search(r"<th>" + re.escape(label) + r"</th>\s*<td>([^<]*)</td>", html)
    return match.group(1).strip() if match else None


def _int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    digits = value.replace(",", "").replace(" ", "")
    return int(digits) if digits.isdigit() else None


def parse_report(html: str) -> dict:
    """The selected model as a dict: name, triangles, vertices, textured,
    textures, unwrap_style, resolution (max page side, int) or None."""
    res = field(html, LABELS["resolution"]) or ""
    sides = [int(n) for n in re.findall(r"\d+", res.replace(",", ""))]
    return {
        "name": field(html, LABELS["name"]),
        "triangles": _int(field(html, LABELS["triangles"])),
        "vertices": _int(field(html, LABELS["vertices"])),
        "textured": (field(html, LABELS["textured"]) or "").strip().lower() == "true",
        "textures": _int(field(html, LABELS["textures"])) or 0,
        "unwrap_style": field(html, LABELS["unwrap_style"]) or None,
        "resolution": max(sides) if sides else None,
    }


def read_report(path: str) -> Optional[dict]:
    """parse_report over a file; None when the file is missing or empty."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            html = fh.read()
    except OSError:
        return None
    if not html.strip():
        return None
    return parse_report(html)


def passes_needed(triangles: Optional[int], target: int, ratio: float) -> int:
    """Passes of a relative simplification keeping ``ratio`` per pass that
    bring ``triangles`` to at or under ``target``; 0 when already there.
    ``ceil(log(target / N0) / log(ratio))``, the arithmetic H2060 confirmed
    to four decimals for ratio 0.8 (FINDINGS 2026-09-03)."""
    if triangles is None or triangles <= target:
        return 0
    if not 0 < ratio < 1:
        raise ValueError(f"ratio must be in (0, 1), got {ratio}")
    return max(1, math.ceil(math.log(target / triangles) / math.log(ratio)))


def _write_lines(info: dict) -> list[str]:
    return [
        f"NAME={info.get('name') or ''}",
        f"TRIS={info.get('triangles') if info.get('triangles') is not None else ''}",
        f"TEXTURED={'true' if info.get('textured') else 'false'}",
        f"TEXTURES={info.get('textures') or 0}",
        f"UNWRAP={info.get('unwrap_style') or ''}",
        f"RESOLUTION={info.get('resolution') if info.get('resolution') is not None else ''}",
    ]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="model_report.py",
        description="Parse a RealityScan SelectedModel report (ASCII output).")
    parser.add_argument("report", help="the .html -exportReport wrote")
    parser.add_argument("--field", choices=sorted(LABELS), default=None,
                        help="print ONE value (empty line when absent)")
    parser.add_argument("--write", default=None,
                        help="write KEY=value lines (NAME, TRIS, TEXTURED, "
                             "TEXTURES, UNWRAP, RESOLUTION) to this file")
    parser.add_argument("--passes", nargs=2, metavar=("TARGET", "RATIO"),
                        default=None,
                        help="print the simplification passes needed to reach "
                             "TARGET triangles keeping RATIO per pass")
    args = parser.parse_args(argv)
    info = read_report(args.report)
    if info is None or not info.get("name"):
        print(f"ERROR: no readable model report at {args.report}", file=sys.stderr)
        return 2
    if args.write:
        with open(args.write, "w", encoding="ascii", errors="replace", newline="\n") as fh:
            fh.write("\n".join(_write_lines(info)) + "\n")
    if args.field:
        value = info.get(args.field)
        if args.field == "textured":
            value = "true" if value else "false"
        print("" if value is None else str(value))
    if args.passes:
        target, ratio = int(args.passes[0]), float(args.passes[1])
        print(passes_needed(info.get("triangles"), target, ratio))
    if not (args.write or args.field or args.passes):
        for line in _write_lines(info):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
