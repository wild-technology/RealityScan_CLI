"""Texture census of an exported component - the answer to "is it textured?"
read from the export tree itself, no report file needed (decision D10,
owner 2026-09-06).

``rs verify`` used to count FILES per export folder, so an OBJ whose
``.mtl`` carried no ``map_Kd`` and no texture page passed as exported
(H2060 c5, FINDINGS 2026-09-03: the unwrap failed silently, the bake had
nothing to write into, the export reported success). The policy since D13
is also mechanical here: every texture page is JPEG and no page side
exceeds 4096.

Only the file headers are read (JPEG SOF / PNG IHDR), so a 45-page export
censuses in milliseconds and no imaging library is needed.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

MAX_PAGE_SIDE = 4096
TEXTURE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".tga", ".dds")
JPEG_EXTS = (".jpg", ".jpeg")
_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB,
                0xCD, 0xCE, 0xCF}


def image_size(path: str | Path) -> tuple[int, int] | None:
    """(width, height) from a JPEG SOF or PNG IHDR header, else None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
                w, h = struct.unpack(">II", head[16:24])
                return w, h
            if not head.startswith(b"\xff\xd8"):
                return None
            fh.seek(2)
            while True:
                marker = fh.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                code = marker[1]
                if code == 0xD8 or 0xD0 <= code <= 0xD7 or code == 0x01:
                    continue                      # standalone markers
                length = fh.read(2)
                if len(length) < 2:
                    return None
                seg = struct.unpack(">H", length)[0]
                if code in _SOF_MARKERS:
                    body = fh.read(5)
                    if len(body) < 5:
                        return None
                    h, w = struct.unpack(">HH", body[1:5])
                    return w, h
                if code == 0xD9 or code == 0xDA:
                    return None                   # EOI / SOS before any SOF
                fh.seek(seg - 2, os.SEEK_CUR)
    except OSError:
        return None


@dataclass
class TextureCensus:
    folder: str
    pages: int = 0
    max_side: int = 0
    formats: dict = field(default_factory=dict)      # ext -> count
    mtl_files: int = 0
    mtl_with_map: int = 0
    problems: list = field(default_factory=list)

    @property
    def textured(self) -> bool:
        """At least one texture page AND (no .mtl, or an .mtl that maps it)."""
        if self.pages == 0:
            return False
        if self.mtl_files and not self.mtl_with_map:
            return False
        return True

    @property
    def ok(self) -> bool:
        return self.textured and not self.problems

    def as_dict(self) -> dict:
        return {"folder": self.folder, "pages": self.pages, "max_side": self.max_side,
                "formats": dict(self.formats), "mtl_files": self.mtl_files,
                "mtl_with_map": self.mtl_with_map, "textured": self.textured,
                "ok": self.ok, "problems": list(self.problems)}


def census_folder(folder: str | Path, max_side: int = MAX_PAGE_SIDE,
                  require_jpeg: bool = True) -> TextureCensus:
    """Census one export folder (an ``obj/`` or ``fbx/`` deliverable dir)."""
    folder = Path(folder)
    out = TextureCensus(folder=str(folder))
    if not folder.is_dir():
        out.problems.append("folder missing")
        return out
    for entry in sorted(folder.iterdir()):
        if not entry.is_file():
            continue
        ext = entry.suffix.lower()
        if ext == ".mtl":
            out.mtl_files += 1
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if "map_Kd" in text:
                out.mtl_with_map += 1
            continue
        if ext not in TEXTURE_EXTS:
            continue
        out.pages += 1
        out.formats[ext] = out.formats.get(ext, 0) + 1
        if require_jpeg and ext not in JPEG_EXTS:
            out.problems.append(f"{entry.name}: not JPEG (D13 - deliverable textures are JPG)")
        size = image_size(entry)
        if size is None:
            out.problems.append(f"{entry.name}: unreadable image header")
            continue
        side = max(size)
        out.max_side = max(out.max_side, side)
        if side > max_side:
            out.problems.append(f"{entry.name}: {size[0]}x{size[1]} exceeds the {max_side} cap (D13)")
    if out.pages == 0:
        out.problems.append("no texture page in the export folder")
    elif out.mtl_files and not out.mtl_with_map:
        out.problems.append("the .mtl carries no map_Kd - the OBJ references no texture")
    return out


def census_component(component_dir: str | Path,
                     kinds: tuple[str, ...] = ("obj", "fbx")) -> dict:
    """{kind: TextureCensus} for the deliverable folders that exist."""
    component_dir = Path(component_dir)
    return {k: census_folder(component_dir / k) for k in kinds
            if (component_dir / k).is_dir()}


def untextured_components(exports_dir: str | Path, names: list[str] | None = None,
                          kinds: tuple[str, ...] = ("obj", "fbx")) -> list[str]:
    """'<component>/<kind>: <problem>' lines for every deliverable that is
    untextured, non-JPEG or over the page cap. Empty = every textured
    deliverable passes."""
    exports_dir = Path(exports_dir)
    if names is None:
        names = sorted(p.name for p in exports_dir.iterdir() if p.is_dir()) \
            if exports_dir.is_dir() else []
    lines: list[str] = []
    for name in names:
        for kind, census in census_component(exports_dir / name, kinds).items():
            for problem in census.problems:
                lines.append(f"{name}/{kind}: {problem}")
    return lines
