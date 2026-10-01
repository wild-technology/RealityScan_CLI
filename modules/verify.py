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

    python -m modules.verify --workspace <root> --json
    python -m modules.verify --workspace <root> --require align,merge

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
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from . import nav_provenance
from .align_fingerprint import FINGERPRINT_NAME, _repo_sha, read_fingerprint
from .nav_provenance import sha256_file
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


def _nav_path_for(ws: Workspace, zone: str, fp: dict) -> Optional[str]:
    """The slice this zone recorded, wherever it is NOW.

    align_inputs.json stores an absolute path, so a workspace restored
    onto another drive would otherwise read as tampering. The recorded
    BASENAME under the located batched tree is offered as the same file -
    the caller still has to hash it against the recorded sha before
    believing it.
    """
    nav = fp.get("flight_log")
    if not isinstance(nav, dict):
        return None
    recorded = nav.get("path")
    if recorded and os.path.isfile(recorded):
        return recorded
    if recorded:
        cand = ws.batched / zone / os.path.basename(str(recorded))
        if cand.is_file():
            return str(cand)
    return None


def _resolve_anchor(ws: Workspace, batched_roots: set,
                    override: Optional[str]) -> tuple[Optional[str], str, str]:
    """(path, origin, why-not) for the table to prove the slices against.

    Pinned by CONTENT every time. A batch marker is never trusted for more
    than a sha - the file has to be FOUND by hashing - so a hand-written
    batch_inputs.json can only fail to resolve, never manufacture a pass.
    There is deliberately no "the only flight log lying around" fallback:
    an absent marker is missing evidence, not agreement about which table
    to prove against.
    """
    roots = [ws.root, ws.root.parent, ws.raw_images]

    if override:
        if os.path.isfile(override):
            return os.path.abspath(override), "operator", ""
        return None, "", "--source_flight_log %s is not a file" % override

    if len(batched_roots) != 1:
        return None, "", ("the aligned zones do not come from exactly one "
                          "batched tree, so no single batch marker governs "
                          "them")
    root = Path(next(iter(batched_roots)))
    marker = _load_json(root / "batch_inputs.json")
    sha = marker.get("flight_log_sha256")
    if not sha:
        return None, "", (
            "%s records no flight_log_sha256, so the table these slices "
            "were cut from is unknown - pass --source_flight_log"
            % (root / "batch_inputs.json"))
    search = roots + [root.parent, marker.get("input_dir")]
    hits = nav_provenance.find_by_sha(search, sha)
    if hits:
        return hits[0], "batch_marker", ""
    return None, "", (
        "no file hashing to %s... - the table %s that %s names is not on "
        "disk where this run can see it; pass --source_flight_log"
        % (sha[:12], marker.get("flight_log") or "?",
           root / "batch_inputs.json"))


def check_nav_unanimity(ws: Workspace, present: dict,
                        source_flight_log: Optional[str] = None
                        ) -> tuple[dict, list[str], bool]:
    """Is ONE navigation table behind every aligned zone?

    Returns (report, findings, superseded). ``superseded`` is True only
    when this check reached a POSITIVE conclusion - every zone proved
    against one table - and is the single condition under which
    check_provenance stops emitting the raw byte-comparison verdict for
    ``flight_log``. Anything else, including every way of failing to
    measure, leaves the original guard in force.

    Three rungs, each stricter than the equality it can supersede:

      unrecorded - a zone with no nav sha at all. Today two such zones
                   both hash to None, group together and PASS; that is a
                   fail-open on the very incident class the guard exists
                   for (C-20260805-01).
      identical  - every zone recorded the same bytes. Unanimity by
                   content identity, plus a re-hash wherever the file
                   still resolves, so a post-align edit blocks too.
      slices     - the shas differ, which for a batched dive says nothing
                   on its own. One table then has to be SHOWN behind all
                   of them: each recorded slice still hashing to what it
                   recorded, one batched tree, an anchor pinned by hash,
                   every slice row matched field-for-field, and every
                   slice reconciled against the imagery its zone holds so
                   a truncated slice cannot prove itself vacuously.
    """
    nav: dict[str, Any] = {
        "method": "no_aligned_zones", "unanimous": None, "proven": False,
        "source": None, "source_origin": None, "zones": {},
        "pairwise": None, "findings": [], "unavailable": []}
    if not present:
        return nav, [], False

    shas = {z: _sha_of(fp.get("flight_log")) for z, fp in present.items()}
    for zone in sorted(present):
        nav["zones"][zone] = {"slice_sha256": shas[zone]}

    # Rung 1. Absence of evidence is never agreement.
    unrecorded = sorted(z for z, s in shas.items() if not s)
    if unrecorded:
        nav["method"] = "unrecorded"
        nav["unanimous"] = False
        msg = ("navigation flight log NOT RECORDED for %s - the align "
               "fingerprint carries no nav identity, so what those "
               "components were built from is unknown and cannot be shown "
               "to match the other zones" % ", ".join(unrecorded))
        nav["findings"].append(msg)
        return nav, [msg], False

    paths = {z: _nav_path_for(ws, z, present[z]) for z in present}
    for zone, path in paths.items():
        nav["zones"][zone]["path"] = path
        if path:
            nav["zones"][zone]["sha256_now"] = sha256_file(path)

    changed = sorted(z for z in present
                     if paths[z] and nav["zones"][z]["sha256_now"] != shas[z])
    if changed:
        nav["method"] = "changed_on_disk"
        nav["unanimous"] = False
        msg = ("navigation flight log CHANGED ON DISK since alignment for "
               "%s - the file the fingerprint names no longer hashes to "
               "what the fingerprint recorded" % ", ".join(changed))
        nav["findings"].append(msg)
        return nav, [msg], False

    # Rung 2. Same bytes everywhere: identity IS the agreement.
    if len(set(shas.values())) == 1:
        nav.update({"method": "identical", "unanimous": True, "proven": True,
                    "source": paths.get(sorted(present)[0])})
        return nav, [], True

    # Rung 3. Differing shas: prove one table behind all of them.
    nav["method"] = "slices"
    findings: list[str] = []
    missing = sorted(z for z in present if not paths[z])
    if missing:
        nav["unavailable"].append(
            "the recorded flight log for %s is not on disk, so its rows "
            "cannot be compared" % ", ".join(missing))
        nav["unanimous"] = False
        return nav, list(nav["unavailable"]), False

    nav["pairwise"] = nav_provenance.pairwise_agreement(paths)

    batched_roots = {str(Path(p).parent.parent) for p in paths.values()}
    zone_named = [z for z in present
                  if Path(paths[z]).parent.name.lower() != z.lower()]
    if zone_named:
        nav["unavailable"].append(
            "the flight log recorded for %s does not sit in a folder named "
            "for that zone, so which slice belongs to which zone cannot be "
            "established" % ", ".join(sorted(zone_named)))
        nav["unanimous"] = False
        return nav, list(nav["unavailable"]), False

    anchor, origin, why = _resolve_anchor(ws, batched_roots, source_flight_log)
    nav["source"], nav["source_origin"] = anchor, origin or None
    if not anchor:
        nav["unavailable"].append(
            "no navigation table could be pinned to prove the per-zone "
            "flight logs against: %s" % why)
        nav["unanimous"] = False
        return nav, list(nav["unavailable"]), False

    table = nav_provenance.read_nav(anchor)
    if table["error"]:
        nav["unavailable"].append(
            "the navigation table %s %s" % (anchor, table["error"]))
        nav["unanimous"] = False
        return nav, list(nav["unavailable"]), False

    by_full, by_base, conflicts = nav_provenance.index_rows(table["rows"])
    if conflicts:
        msg = ("the navigation table %s names %d image(s) twice with "
               "DIFFERENT navigation, so it cannot witness that the zones "
               "agree" % (anchor, len(conflicts)))
        nav["findings"].append(msg)
        nav["unanimous"] = False
        return nav, [msg], False

    nav["anchor_rows"] = len(by_full)
    for zone in sorted(present):
        slice_log = nav_provenance.read_nav(paths[zone])
        rec = nav["zones"][zone]
        if slice_log["error"]:
            nav["unavailable"].append(
                "%s: its flight log %s" % (zone, slice_log["error"]))
            continue
        if not nav_provenance.columns_compatible(table["header"],
                                                 slice_log["header"]):
            findings.append(
                "%s: its flight log does not share the navigation table's "
                "columns, so the two are not the same kind of record" % zone)
            continue
        if not slice_log["rows"]:
            findings.append(
                "%s: its flight log holds zero data rows - contained in "
                "every table, evidence of nothing" % zone)
            continue
        cmp = nav_provenance.compare_slice(by_full, by_base, conflicts,
                                           slice_log["rows"])
        rec.update(cmp)
        img_keys, layout = nav_provenance.zone_image_keys(ws.batched / zone)
        rec["images"] = None if img_keys is None else len(img_keys)
        rec["layout"] = layout
        if cmp["absent"] or cmp["differing"]:
            findings.append(
                "%s: %d row(s) differ from and %d row(s) are absent from the "
                "navigation table %s - these components were NOT built from "
                "it" % (zone, cmp["differing"], cmp["absent"], anchor))
            continue
        if cmp["ambiguous"]:
            nav["unavailable"].append(
                "%s: %d row(s) name an image the navigation table lists more "
                "than once, which leaves the zone unverified (a naming "
                "collision, not a navigation disagreement)"
                % (zone, cmp["ambiguous"]))
            continue
        if img_keys:
            # How much of the zone did the proof actually cover? Images
            # with no row are only a fault when the TABLE has a row for
            # them - that is a slice cut short of its own source, and the
            # containment proof then speaks for less than the zone. Images
            # the table has never heard of carry no navigation at all,
            # which is a real and legitimate condition (H2082 zone_1: 180
            # of them) and not a cross-zone disagreement.
            covered = {k[-1] for k, _tail in slice_log["rows"] if k}
            uncovered = sorted(k for k in img_keys if k[-1] not in covered)
            short = [k for k in uncovered
                     if nav_provenance.match_key(k, by_full, by_base)[0]]
            rec["images_without_a_row"] = len(uncovered)
            rec["omitted_rows_the_table_has"] = len(short)
            if short:
                findings.append(
                    "%s: %d image(s) in the zone have no row in its flight "
                    "log, yet the navigation table %s carries one for them - "
                    "the slice was cut short of its own source, so proving "
                    "it says nothing about those cameras"
                    % (zone, len(short), anchor))

    pair = nav["pairwise"] or {}
    if pair.get("conflicts"):
        findings.append(
            "zones that share images DISAGREE about their navigation in %d "
            "case(s): %s" % (pair["conflicts"], "; ".join(pair["examples"])))

    nav["findings"] = findings
    problems = findings + nav["unavailable"]
    nav["unanimous"] = not problems
    nav["proven"] = not problems
    return nav, problems, not problems


def check_provenance(ws: Workspace,
                     source_flight_log: Optional[str] = None
                     ) -> tuple[dict, list[str]]:
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

    # The nav ladder runs FIRST, but it can only ever SUPERSEDE the byte
    # comparison below, never relax it: `superseded` is true solely when
    # one navigation table was positively shown behind every zone. Every
    # other outcome - including every way of failing to measure - leaves
    # the original guard to speak, so a batched dive that cannot be proved
    # blocks exactly as it did before this check existed.
    nav, nav_findings, nav_superseded = check_nav_unanimity(
        ws, present, source_flight_log)
    blocking += nav_findings

    for key, label in _UNANIMITY_FIELDS:
        if key == "flight_log" and nav_superseded:
            continue
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
        "layout": ws.layout(),
        "zones": zones,
        "nav": nav,
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
                     require: Optional[list[str]] = None,
                     source_flight_log: Optional[str] = None) -> dict:
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

    provenance, prov_blocking = check_provenance(ws, source_flight_log)
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
        prog="python -m modules.verify",
        description="Census and verify a results workspace. Emits JSON.")
    parser.add_argument("--workspace", "-w", required=True,
                        help="results root to census")
    parser.add_argument("--require", default="",
                        help="comma-separated stages that must be 'done' "
                             "(default: every started stage). Valid: "
                             + ",".join(STAGE_ORDER))
    parser.add_argument(
        "--source_flight_log", default=None,
        help="the navigation table the per-zone flight logs were cut from. "
             "Only needed when the batch marker's table is no longer on "
             "disk where this run can see it; it still has to contain "
             "every row of every zone before it proves anything.")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON only (default: human text)")
    parser.add_argument("--out", default=None,
                        help="also write the JSON to this path")
    args = parser.parse_args(argv)

    require = [s.strip() for s in args.require.split(",") if s.strip()]
    try:
        payload = verify_workspace(args.workspace, require or None,
                                   args.source_flight_log)
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
