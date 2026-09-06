"""A textured deliverable for export-census tests.

Since D10 (2026-09-06) the export census reads the export TREE: an OBJ or
FBX folder must hold a JPEG texture page at or under 4096 px and, for OBJ,
an .mtl carrying map_Kd. Tests that used to drop a one-byte placeholder
mesh now write this shape, so they keep testing what they tested (missing
folders, empty files, the PLY exemption) without tripping the texture
census. Not a test module: no ``test_`` names here.
"""
from __future__ import annotations

import struct
from pathlib import Path


def jpeg_bytes(width: int = 4096, height: int = 4096) -> bytes:
    """A minimal JPEG (SOI, APP0, a baseline SOF0 carrying the size, EOI):
    enough for a header reader, not a decodable image."""
    app0 = (b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00"
            + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    sof = (b"\xff\xc0" + struct.pack(">H", 11) + b"\x08"
           + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00")
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def textured_deliverable(folder: Path, comp: str, kind: str,
                         payload: bytes = b"x") -> Path:
    """Write ``<comp>.<kind>`` (``payload`` bytes) plus, for obj/fbx, one
    4096 px JPEG page and (obj) an .mtl that maps it. Returns the mesh path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    mesh = folder / f"{comp}.{kind}"
    mesh.write_bytes(payload)
    if kind in ("obj", "fbx"):
        page = folder / f"{comp}_u1_v1_0.jpg"
        page.write_bytes(jpeg_bytes())
        if kind == "obj":
            (folder / f"{comp}.mtl").write_text(
                f"newmtl material_0\nmap_Kd {page.name}\n", encoding="utf-8")
    return mesh
