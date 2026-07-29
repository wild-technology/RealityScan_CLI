"""Workspace model: pure artifact-census logic, no UI, no subprocesses.

Everything the app shows is derived from artifacts the canonical pipeline
already writes - the same signals the unattended drivers use to resume:

    raw_images/                     extraction output / user input
    flight_log_*_UTM.txt            georeference terminal artifact
    preprocessed_images/            CLAHE output
    batched_images_by_zone/         zoning + batch_inputs.json fingerprint
    aligned_components/<zone>/      *.rsalign + *.rsalign.manifest.json
    <merge>/merge_report.json       merge terminal + EVALUATION_READY.txt
    <merge>/assembly/*.rsproj       the assembly project
    final_report.json               modelled components
    fused_models_report.json        fused-component models + measured scale
    exports/<comp>/{obj,fbx,ply}    deliverable exports

Detection is deliberately read-only and cheap (no image hashing) so opening
a workspace is instant even on a NAS.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heif"}

STAGE_ORDER = [
    "extract", "georeference", "preprocess", "batch",
    "align", "merge", "model", "export", "publish",
]

STAGE_TITLES = {
    "extract": "Extract Images",
    "georeference": "Georeference",
    "preprocess": "Preprocess (CLAHE)",
    "batch": "Batch into Zones",
    "align": "Align Zones",
    "merge": "Merge Components",
    "model": "Generate Models",
    "export": "Export Deliverables",
    "publish": "Publish (Cesium / Nira)",
}


@dataclass
class StageStatus:
    key: str
    status: str = "pending"            # pending | partial | done | blocked
    summary: str = ""                  # one-line human summary
    details: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return STAGE_TITLES.get(self.key, self.key)


@dataclass
class ComponentInfo:
    key: str
    cameras: Optional[int] = None
    scale: Optional[float] = None
    scale_status: str = ""
    modelled: bool = False
    model_minutes: Optional[float] = None
    exported: list[str] = field(default_factory=list)


def _count_images(root: Path) -> int:
    if not root.is_dir():
        return 0
    n = 0
    for _dir, _sub, files in os.walk(root):
        n += sum(1 for f in files if Path(f).suffix.lower() in IMAGE_EXTS)
    return n


def _find_flight_logs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("flight_log*_UTM.txt"))


def _load_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


class Workspace:
    """A results root as the pipeline understands it."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    # ------------------------------------------------------------ locations
    @property
    def raw_images(self) -> Path:
        return self.root / "raw_images"

    @property
    def preprocessed(self) -> Path:
        return self.root / "preprocessed_images"

    @property
    def batched(self) -> Path:
        return self.root / "batched_images_by_zone"

    @property
    def aligned(self) -> Path:
        return self.root / "aligned_components"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    def merge_dirs(self) -> list[Path]:
        """Merge outputs, newest report last. Any directory carrying a
        merge_report.json counts - names vary (merged*, nonhull,
        final_assembly)."""
        if not self.root.is_dir():
            return []
        hits = [p.parent for p in self.root.glob("*/merge_report.json")]
        return sorted(hits, key=lambda p: (p / "merge_report.json").stat().st_mtime)

    def latest_merge(self) -> Optional[Path]:
        dirs = self.merge_dirs()
        return dirs[-1] if dirs else None

    def assembly_project(self) -> Optional[Path]:
        merge = self.latest_merge()
        if not merge:
            return None
        for cand in sorted((merge / "assembly").glob("*.rsproj")):
            return cand
        return None

    # ------------------------------------------------------------ detection
    def detect(self) -> dict[str, StageStatus]:
        return {key: getattr(self, f"_detect_{key}")() for key in STAGE_ORDER}

    def _detect_extract(self) -> StageStatus:
        n = _count_images(self.raw_images)
        if n:
            return StageStatus("extract", "done", f"{n:,} images in raw_images/")
        loose = _count_images(self.root) if self.root.is_dir() else 0
        if loose:
            return StageStatus("extract", "done",
                               f"{loose:,} images at workspace root")
        return StageStatus("extract", "pending", "no imagery found yet")

    def _detect_georeference(self) -> StageStatus:
        logs = _find_flight_logs(self.raw_images) or _find_flight_logs(self.root)
        logs = [p for p in logs if self.batched not in p.parents]
        if logs:
            rows = 0
            try:
                with open(logs[0], encoding="utf-8") as fh:
                    rows = max(0, sum(1 for _ in fh) - 1)
            except OSError:
                pass
            return StageStatus("georeference", "done",
                               f"{logs[0].name} ({rows:,} rows)")
        return StageStatus("georeference", "pending", "no flight_log_*_UTM.txt")

    def _detect_preprocess(self) -> StageStatus:
        n = _count_images(self.preprocessed)
        if n:
            return StageStatus("preprocess", "done",
                               f"{n:,} CLAHE images in preprocessed_images/")
        return StageStatus("preprocess", "pending",
                           "not run (align falls back to raw imagery)")

    def _detect_batch(self) -> StageStatus:
        if not self.batched.is_dir():
            return StageStatus("batch", "pending", "no batched_images_by_zone/")
        zones = sorted(p for p in self.batched.iterdir() if p.is_dir())
        marker = self.batched / "batch_inputs.json"
        details = []
        for z in zones:
            n = _count_images(z)
            has_log = bool(_find_flight_logs(z))
            details.append(f"{z.name}: {n:,} images"
                           + ("" if has_log else "  [no flight log]"))
        if zones and marker.is_file():
            return StageStatus("batch", "done",
                               f"{len(zones)} zones, fingerprint present",
                               details)
        if zones:
            return StageStatus("batch", "partial",
                               f"{len(zones)} zones but NO batch_inputs.json "
                               "fingerprint - provenance unknown", details)
        return StageStatus("batch", "pending", "zone folders absent")

    def _detect_align(self) -> StageStatus:
        if not self.aligned.is_dir():
            return StageStatus("align", "pending", "no aligned_components/")
        zones = sorted(p for p in self.aligned.iterdir() if p.is_dir())
        details, comp_total, cam_total = [], 0, 0
        for z in zones:
            manifests = sorted(z.glob("*.rsalign.manifest.json"))
            cams = 0
            for m in manifests:
                cams += _load_json(m).get("camera_count") or 0
            comp_total += len(manifests)
            cam_total += cams
            details.append(f"{z.name}: {len(manifests)} component(s), "
                           f"{cams:,} cameras")
        batched_zones = ([p.name for p in self.batched.iterdir() if p.is_dir()]
                         if self.batched.is_dir() else [])
        aligned_names = {z.name for z in zones if list(z.glob('*.rsalign'))}
        missing = [z for z in batched_zones if z not in aligned_names]
        if comp_total and not missing:
            return StageStatus("align", "done",
                               f"{comp_total} components / {cam_total:,} "
                               f"cameras across {len(zones)} zones", details)
        if comp_total:
            return StageStatus("align", "partial",
                               f"{comp_total} components; zones not aligned: "
                               f"{', '.join(missing)}", details)
        return StageStatus("align", "pending", "no components exported")

    def _detect_merge(self) -> StageStatus:
        merge = self.latest_merge()
        if not merge:
            return StageStatus("merge", "pending", "no merge_report.json")
        report = _load_json(merge / "merge_report.json")
        finals = [c for rec in report.get("clusters", [])
                  for c in rec.get("final_components", [])]
        gate = merge / "EVALUATION_READY.txt"
        cams = sum(c.get("camera_count") or 0 for c in finals)
        if finals and gate.is_file():
            return StageStatus("merge", "done",
                               f"{merge.name}: {len(finals)} final "
                               f"component(s), {cams:,} cameras",
                               [c.get("key", "?") for c in finals])
        if finals:
            return StageStatus("merge", "partial",
                               f"{merge.name}: report exists but no "
                               "EVALUATION_READY gate")
        return StageStatus("merge", "partial", f"{merge.name}: no finals yet")

    def _detect_model(self) -> StageStatus:
        done: list[str] = []
        for name in ("final_report.json", "fused_models_report.json"):
            report = _load_json(self.root / name)
            models = report.get("models") or report.get("components") or []
            done += [m.get("component") for m in models if m.get("success")]
        merge = self.latest_merge()
        finals = []
        if merge:
            rep = _load_json(merge / "merge_report.json")
            finals = [c.get("key", "").split("/")[-1]
                      for rec in rep.get("clusters", [])
                      for c in rec.get("final_components", [])]
        if done and finals and set(finals) <= set(done):
            return StageStatus("model", "done",
                               f"{len(done)} of {len(finals)} components "
                               "modelled", sorted(done))
        if done:
            missing = sorted(set(finals) - set(done))
            return StageStatus("model", "partial",
                               f"{len(done)} modelled, missing: "
                               f"{', '.join(missing) or '?'}", sorted(done))
        return StageStatus("model", "pending", "no model reports")

    def _detect_export(self) -> StageStatus:
        if not self.exports.is_dir():
            return StageStatus("export", "pending", "no exports/")
        comps = sorted(p for p in self.exports.iterdir() if p.is_dir())
        details = []
        for c in comps:
            kinds = [k.name for k in c.iterdir()
                     if k.is_dir() and any(k.iterdir())]
            if kinds:
                details.append(f"{c.name}: {', '.join(sorted(kinds))}")
        if details:
            return StageStatus("export", "partial" if len(details) < max(len(comps), 1)
                               else "done",
                               f"{len(details)} component(s) exported", details)
        return StageStatus("export", "pending", "exports/ is empty")

    def _detect_publish(self) -> StageStatus:
        report = _load_json(self.root / "publish_report.json")
        assets = report.get("assets", [])
        if assets:
            ok = sum(1 for a in assets
                     if (a.get("cesium") or {}).get("success")
                     or (a.get("nira") or {}).get("success"))
            return StageStatus("publish",
                               "done" if ok == len(assets) else "partial",
                               f"{ok} of {len(assets)} asset(s) published",
                               [a.get("asset_name", "?") for a in assets])
        if self.exports.is_dir() and any(self.exports.iterdir()):
            return StageStatus("publish", "pending",
                               "exports ready - needs CESIUM_ION_TOKEN "
                               "and/or NIRACLIENT_DIR")
        return StageStatus("publish", "pending", "nothing exported yet")

    # ------------------------------------------------------------ inventory
    def components(self) -> list[ComponentInfo]:
        """Merged final components joined with scale verdicts, model results
        and export presence - the results-browser table."""
        merge = self.latest_merge()
        if not merge:
            return []
        report = _load_json(merge / "merge_report.json")
        scales = report.get("input_scales", {})
        out: dict[str, ComponentInfo] = {}
        for rec in report.get("clusters", []):
            for c in rec.get("final_components", []):
                key = c.get("key", "?")
                name = key.split("/")[-1]
                v = scales.get(key, {})
                out[name] = ComponentInfo(
                    key=name, cameras=c.get("camera_count"),
                    scale=v.get("median"), scale_status=v.get("status", ""))
        for rep_name in ("final_report.json", "fused_models_report.json"):
            rep = _load_json(self.root / rep_name)
            for m in rep.get("models") or rep.get("components") or []:
                name = m.get("component")
                if name in out and m.get("success"):
                    out[name].modelled = True
                    out[name].model_minutes = m.get("duration_min")
                    if m.get("scale") is not None:
                        out[name].scale = m.get("scale")
                        out[name].scale_status = m.get("status", "pass")
        if self.exports.is_dir():
            for name, info in out.items():
                comp_dir = self.exports / name
                if comp_dir.is_dir():
                    info.exported = sorted(
                        k.name for k in comp_dir.iterdir()
                        if k.is_dir() and any(k.iterdir()))
        return sorted(out.values(), key=lambda c: -(c.cameras or 0))
