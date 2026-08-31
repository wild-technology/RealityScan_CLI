"""Workspace verification oracle - "did it actually work", as JSON.

ONE call that answers what previously took a session of grepping logs,
diffing manifests and re-deriving verdicts by hand. Written for the
agent-driven lane (an LLM reading a fixed schema) but equally usable by a
human or a monitor.

Why this exists as its own module rather than as prose in a runbook: the
project's standing rule is "verify by census, never by exit status", and
an agent that re-derives the census in prose derives it DIFFERENTLY each
run. A machine-readable oracle is the only form of that rule that cannot
drift - and, per the core principle, its evidence is independent of the
thing being tested: everything here is read from artifacts ON DISK
(manifests, fingerprints, reports, export trees), never from a driver's
claim about its own success.

    py -3.13 -m modules.verify --workspace <root> --json
    py -3.13 -m modules.verify --workspace <root> --require align,merge

Exit codes (the JSON is the product; these are for shell gating):
    0  ok         - every required stage is done, no invariant violated
    1  incomplete - something required is pending/partial
    2  blocked    - a silent-success failure or invariant violation
    3  absent     - the workspace does not exist / cannot be read

Stage statuses come from modules.workspace_census (which already encodes
the "silence is not success" detections: a header-only flight log, zone
folders holding zero images, EVALUATION_READY over a failed assembly).
This module adds what a census alone cannot see:

  - PROVENANCE: the batch fingerprint and every zone's align_inputs.json,
    surfaced rather than assumed;
  - FRAME UNANIMITY: components built in different coordinate frames are
    an invariant violation, not a warning - merging across them is the
    recorded two-frames incident class (C-20260805-01);
  - SETTINGS UNANIMITY: zones aligned from different nav or different
    alignment settings, which a camera-count census reports as healthy;
  - SCALE: components outside the metric acceptance band, which shipped
    twice with camera-count oracles green.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .align_fingerprint import FINGERPRINT_NAME, _repo_sha, read_fingerprint
from .workspace_census import STAGE_ORDER, Workspace, _load_json

SCHEMA = 1

EXIT_CODES = {"ok": 0, "incomplete": 1, "blocked": 2, "absent": 3}

#: Metric-scale acceptance band (modules.scale_oracle; the merge stage's
#: --scale_min/--scale_max default to the same numbers).
SCALE_MIN = 0.90
SCALE_MAX = 1.10

#: Fingerprint fields whose disagreement across zones is a science fault
#: rather than a nuisance. Mirrors align_fingerprint._COMPARED, keyed for
#: cross-ZONE comparison instead of before/after comparison.
_UNANIMITY_FIELDS = (
    ("flight_log", "navigation flight log"),
    ("align_settings", "alignment settings XML"),
    ("flight_log_params", "coordinate-frame template"),
)


def _sha_of(entry: Any) -> Optional[str]:
    return entry.get("sha256") if isinstance(entry, dict) else None


def _zone_fingerprints(ws: Workspace) -> dict[str, Optional[dict]]:
    """Every aligned zone's align_inputs.json, None where absent.

    A zone with components but NO fingerprint is not "done": its
    provenance is unknown, which is exactly the nav-blind resume the
    fingerprint mechanism was added to close.
    """
    out: dict[str, Optional[dict]] = {}
    if not ws.aligned.is_dir():
        return out
    for zone in sorted(p for p in ws.aligned.iterdir() if p.is_dir()):
        if not list(zone.glob("*.rsalign")):
            continue
        out[zone.name] = read_fingerprint(str(zone))
    return out


def check_provenance(ws: Workspace) -> tuple[dict, list[str]]:
    """Provenance block + the invariant violations it reveals.

    Returns (provenance, blocking). ``blocking`` is empty when every
    aligned zone carries a fingerprint and they agree on frame, nav and
    settings.
    """
    blocking: list[str] = []
    fingerprints = _zone_fingerprints(ws)

    zones: dict[str, dict] = {}
    for zone, fp in fingerprints.items():
        if fp is None:
            zones[zone] = {"present": False}
            blocking.append(
                f"align/{zone}: components exist but no {FINGERPRINT_NAME} - "
                "the nav, frame and settings that built them are unknown, so "
                "this zone cannot be called done or safely merged")
            continue
        zones[zone] = {
            "present": True,
            "frame": fp.get("frame"),
            "flight_log_sha256": _sha_of(fp.get("flight_log")),
            "align_settings_sha256": _sha_of(fp.get("align_settings")),
            "flight_log_params_sha256": _sha_of(fp.get("flight_log_params")),
            "min_component_size": fp.get("min_component_size"),
            "repo_sha": fp.get("repo_sha"),
            "created": fp.get("created"),
        }

    present = {z: fp for z, fp in fingerprints.items() if fp is not None}

    # Frame unanimity is the hard one: mixing frames is never recoverable
    # downstream, and nothing else in the pipeline notices.
    frames = {z: fp.get("frame") for z, fp in present.items()}
    distinct_frames = sorted({f for f in frames.values() if f})
    if len(distinct_frames) > 1:
        listing = ", ".join(f"{z}={frames[z]}" for z in sorted(frames))
        blocking.append(
            f"COORDINATE FRAMES DISAGREE across aligned zones ({listing}) - "
            "never merge across frames")

    for key, label in _UNANIMITY_FIELDS:
        seen: dict[Optional[str], list[str]] = {}
        for zone, fp in present.items():
            seen.setdefault(_sha_of(fp.get(key)), []).append(zone)
        if len(seen) > 1:
            groups = "; ".join(
                f"{sha or 'absent'} <- {', '.join(sorted(zs))}"
                for sha, zs in sorted(seen.items(), key=lambda kv: str(kv[0])))
            blocking.append(
                f"{label} DIFFERS across aligned zones ({groups}) - "
                "components built from different inputs are not comparable "
                "and must not be merged as if they were")

    provenance = {
        "repo_sha": _repo_sha(),
        "batch_fingerprint": _load_json(ws.batched / "batch_inputs.json")
        or None,
        "zones": zones,
        "frames": distinct_frames,
        "frame_unanimous": len(distinct_frames) <= 1,
        "zones_without_fingerprint": sorted(
            z for z, fp in fingerprints.items() if fp is None),
    }
    return provenance, blocking


def check_scale(components: list) -> list[str]:
    """Components whose measured scale is outside the acceptance band.

    Only MEASURED values are judged. A component with no scale record is
    reported through ``counts.scale_unmeasured``, not blocked here -
    asserting a scale nobody measured is the fault this guards against,
    and inventing a verdict for it would repeat it.
    """
    out = []
    for comp in components:
        if comp.scale is None:
            continue
        if not (SCALE_MIN <= comp.scale <= SCALE_MAX):
            out.append(
                f"component {comp.key}: measured scale {comp.scale:.3f} is "
                f"outside the metric band {SCALE_MIN:.2f}-{SCALE_MAX:.2f} - "
                "the geometry is not metric")
    return out


def verify_workspace(root: str | Path,
                     require: Optional[list[str]] = None) -> dict:
    """The full census + invariant report for one workspace.

    ``require`` names the stages that must reach 'done' for an "ok"
    verdict. Default: every stage the census does not report as 'pending'
    - i.e. "finish what you started", which is the useful default
    mid-campaign. Pass an explicit list to gate a specific stage.
    """
    ws = Workspace(root)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "workspace": str(Path(root).absolute()),
        "exists": ws.root.is_dir(),
    }

    if not ws.root.is_dir():
        payload.update({
            "verdict": "absent",
            "blocking": [f"workspace does not exist: {payload['workspace']}"],
            "incomplete": [],
            "stages": {}, "components": [], "counts": {}, "provenance": {},
            "required": [],
        })
        return payload

    statuses = ws.detect()
    components = ws.components()

    started = [k for k in STAGE_ORDER if statuses[k].status != "pending"]
    required = list(require) if require else started
    unknown = [s for s in required if s not in STAGE_ORDER]
    if unknown:
        raise ValueError(
            f"unknown stage(s) {unknown}; valid stages: {list(STAGE_ORDER)}")

    blocking: list[str] = []
    incomplete: list[str] = []
    for key in STAGE_ORDER:
        st = statuses[key]
        # A blocked stage is a finding wherever it appears - the census
        # only reports 'blocked' for a DETECTED silent-success failure,
        # and those do not become acceptable by not being required this
        # run.
        if st.status == "blocked":
            blocking.append(f"{key}: {st.summary}")
        elif key in required and st.status != "done":
            incomplete.append(f"{key}: {st.summary}")

    provenance, prov_blocking = check_provenance(ws)
    blocking += prov_blocking
    blocking += check_scale(components)

    if blocking:
        verdict = "blocked"
    elif incomplete:
        verdict = "incomplete"
    else:
        verdict = "ok"

    payload.update({
        "verdict": verdict,
        "required": required,
        "blocking": blocking,
        "incomplete": incomplete,
        "stages": {
            key: {"key": key, "title": st.title, "status": st.status,
                  "summary": st.summary, "details": list(st.details)}
            for key, st in statuses.items()
        },
        "components": [
            {"key": c.key, "cameras": c.cameras, "scale": c.scale,
             "scale_status": c.scale_status, "modelled": c.modelled,
             "model_minutes": c.model_minutes, "exported": list(c.exported)}
            for c in components
        ],
        "counts": {
            "components": len(components),
            "cameras": sum(c.cameras or 0 for c in components),
            "modelled": sum(1 for c in components if c.modelled),
            "exported": sum(1 for c in components if c.exported),
            "scale_measured": sum(1 for c in components if c.scale is not None),
            "scale_unmeasured": sum(1 for c in components if c.scale is None),
            "zones_aligned": len(provenance["zones"]),
            "zones_without_fingerprint":
                len(provenance["zones_without_fingerprint"]),
        },
        "provenance": provenance,
    })
    return payload


def format_text(payload: dict) -> str:
    """ASCII-only human rendering (the cp1252 console crashes otherwise)."""
    lines = [f"workspace : {payload['workspace']}",
             f"verdict   : {payload['verdict'].upper()}"]
    if not payload.get("exists"):
        lines += [f"  ! {b}" for b in payload.get("blocking", [])]
        return "\n".join(lines)

    counts = payload["counts"]
    lines.append(
        f"components: {counts['components']} / {counts['cameras']:,} cameras"
        f"  modelled {counts['modelled']}  exported {counts['exported']}")
    lines.append("")
    required = set(payload["required"])
    for key in STAGE_ORDER:
        st = payload["stages"][key]
        mark = "*" if key in required else " "
        lines.append(f" {mark} {st['status']:8s} {st['title']:22s} "
                     f"{st['summary']}")
    if payload["blocking"]:
        lines += ["", "BLOCKING:"]
        lines += [f"  ! {b}" for b in payload["blocking"]]
    if payload["incomplete"]:
        lines += ["", "INCOMPLETE (required, not done):"]
        lines += [f"  - {i}" for i in payload["incomplete"]]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="py -3.13 -m modules.verify",
        description="Census and verify a results workspace. Emits JSON.")
    parser.add_argument("--workspace", "-w", required=True,
                        help="results root to census")
    parser.add_argument("--require", default="",
                        help="comma-separated stages that must be 'done' "
                             "(default: every started stage). Valid: "
                             + ",".join(STAGE_ORDER))
    parser.add_argument("--json", action="store_true",
                        help="emit JSON only (default: human text)")
    parser.add_argument("--out", default=None,
                        help="also write the JSON to this path")
    args = parser.parse_args(argv)

    require = [s.strip() for s in args.require.split(",") if s.strip()]
    try:
        payload = verify_workspace(args.workspace, require or None)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_CODES["absent"]

    print(json.dumps(payload, indent=2) if args.json else format_text(payload))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return EXIT_CODES[payload["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
