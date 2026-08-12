"""yellow_filter.py — score underwater survey images for yellow-tether contamination.

The ROV tether is YELLOW; frames that show it are trash for photogrammetry.
This tool computes, per image, the fraction of pixels that are "strongly
yellow" (hue in a tunable band, saturation and value above tunable floors)
after downscaling to ~256 px. Underwater blue-green scenes contain almost no
saturated yellow, so tether frames should stand out as a high tail.

Analysis only: never modifies or deletes any image.

CALIBRATION (2026-08-11, 600-image seed-42 sample of M:\ON2026_run2\rs_images):
The DEFAULT band (hue 35-70, sat 0.35) fires on quagga-mussel encrustation in
close, well-lit wreck frames (mussel px: hue ~37-47 deg, sat 0.36-0.61) — it is
a mussel-proximity detector, NOT a tether detector; do not cull with it.
The TETHER-STRICT profile (--hue-min 40 --hue-max 70 --sat-min 0.65) suppresses
mussels ~30-100x (sample max 0.00067) while a true saturated-yellow tether
crossing the frame should score >~0.01. Zero tether frames existed in the
sample, so the positive side is UNCALIBRATED — verify against a known tether
frame before trusting the strict threshold.

Usage:
    python yellow_filter.py --root M:\\ON2026_run2\\rs_images --sample 600 \
        --threshold 0.01 --out results\\yellow_sample600.csv

    # score every image (no sampling):
    python yellow_filter.py --root <dir> --out all.csv

Hue is specified in DEGREES (0-360) on the CLI and converted internally to
PIL's 0-255 hue scale. Saturation/value floors are fractions (0-1) converted
to 0-255.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # survey frames are trusted local data


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Score images for yellow-tether pixel fraction.")
    p.add_argument("--root", default=None, help="Directory containing .jpg images (searched recursively).")
    p.add_argument("--files", default=None,
                   help="Text file listing image paths (one per line) - scores exactly these instead of --root.")
    p.add_argument("--sample", type=int, default=0,
                   help="Random sample size (seed 42). 0 or omitted = score ALL images.")
    p.add_argument("--seed", type=int, default=42, help="Random seed for sampling (default 42).")
    p.add_argument("--threshold", type=float, default=None,
                   help="yellow_fraction above which an image is flagged in the CSV/summary.")
    p.add_argument("--out", default=None, help="Output CSV path (default: yellow_scores.csv in cwd).")
    p.add_argument("--max-side", type=int, default=256,
                   help="Downscale so the longest side is ~this many px (default 256).")
    p.add_argument("--hue-min", type=float, default=35.0,
                   help="Yellow band lower hue bound, degrees 0-360 (default 35).")
    p.add_argument("--hue-max", type=float, default=70.0,
                   help="Yellow band upper hue bound, degrees 0-360 (default 70).")
    p.add_argument("--sat-min", type=float, default=0.35,
                   help="Minimum saturation as fraction 0-1 (default 0.35).")
    p.add_argument("--val-min", type=float, default=0.25,
                   help="Minimum value/brightness as fraction 0-1 (default 0.25).")
    p.add_argument("--workers", type=int, default=16,
                   help="Decode threads (PIL releases the GIL; default 16).")
    return p.parse_args(argv)


def yellow_fraction(path: str, max_side: int,
                    hue_lo: int, hue_hi: int, sat_lo: int, val_lo: int) -> float:
    """Fraction of pixels in the yellow band. Thresholds already on 0-255 scale."""
    with Image.open(path) as im:
        # draft() lets the JPEG decoder do 1/2..1/8 DCT scaling — far cheaper
        # than decoding 2816x2816 and resizing afterwards.
        im.draft("RGB", (max_side, max_side))
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
        hsv = np.asarray(im.convert("HSV"))
    h = hsv[..., 0]
    s = hsv[..., 1]
    v = hsv[..., 2]
    if hue_lo <= hue_hi:
        hue_mask = (h >= hue_lo) & (h <= hue_hi)
    else:  # band wraps around 0 (not the case for yellow, but keep it correct)
        hue_mask = (h >= hue_lo) | (h <= hue_hi)
    mask = hue_mask & (s >= sat_lo) & (v >= val_lo)
    return float(np.count_nonzero(mask)) / mask.size


def collect_images(root: str) -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith((".jpg", ".jpeg")):
                out.append(os.path.join(dirpath, name))
    out.sort()  # deterministic order so seeded sampling is reproducible
    return out


def main(argv=None) -> int:
    args = parse_args(argv)

    if not args.root and not args.files:
        print("ERROR: one of --root/--files is required.", file=sys.stderr)
        return 2
    if args.root and not os.path.isdir(args.root):
        print(f"ERROR: --root not a directory: {args.root}", file=sys.stderr)
        return 2
    if not (0.0 <= args.hue_min <= 360.0 and 0.0 <= args.hue_max <= 360.0):
        print("ERROR: hue bounds must be within 0-360 degrees.", file=sys.stderr)
        return 2

    # Degrees -> PIL 0-255 hue scale; fractions -> 0-255.
    hue_lo = int(round(args.hue_min / 360.0 * 255.0))
    hue_hi = int(round(args.hue_max / 360.0 * 255.0))
    sat_lo = int(round(args.sat_min * 255.0))
    val_lo = int(round(args.val_min * 255.0))

    if args.files:
        with open(args.files, encoding="ascii") as fh:
            images = [ln.strip() for ln in fh if ln.strip()]
        images = [p for p in images if os.path.isfile(p)]
    else:
        images = collect_images(args.root)
    if not images:
        print("ERROR: no images to score.", file=sys.stderr)
        return 2
    total_found = len(images)

    if args.sample and args.sample > 0 and args.sample < total_found:
        rng = random.Random(args.seed)
        images = sorted(rng.sample(images, args.sample))

    print(f"root: {args.root}")
    print(f"images found: {total_found}; scoring: {len(images)}")
    print(f"yellow band: hue {args.hue_min:.0f}-{args.hue_max:.0f} deg "
          f"(PIL {hue_lo}-{hue_hi}), sat>={args.sat_min:.2f} ({sat_lo}), "
          f"val>={args.val_min:.2f} ({val_lo}); max_side={args.max_side}")

    t0 = time.time()
    errors: list[tuple[str, str]] = []

    def score(path: str):
        try:
            return path, yellow_fraction(path, args.max_side, hue_lo, hue_hi, sat_lo, val_lo)
        except Exception as exc:  # unreadable/corrupt file: record, keep going
            errors.append((path, repr(exc)))
            return path, None

    results: list[tuple[str, float]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for i, (path, frac) in enumerate(pool.map(score, images), 1):
            if frac is not None:
                results.append((path, frac))
            if i % 200 == 0:
                print(f"  scored {i}/{len(images)} ({time.time() - t0:.1f}s)")

    results.sort(key=lambda r: r[1], reverse=True)
    elapsed = time.time() - t0
    print(f"scored {len(results)} images in {elapsed:.1f}s "
          f"({len(results) / elapsed:.1f} img/s); {len(errors)} errors")
    for path, err in errors[:10]:
        print(f"  ERROR {path}: {err}")

    out_path = args.out or "yellow_scores.csv"
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        header = ["path", "yellow_fraction"]
        if args.threshold is not None:
            header.append("flagged")
        w.writerow(header)
        for path, frac in results:
            row = [path, f"{frac:.6f}"]
            if args.threshold is not None:
                row.append("1" if frac >= args.threshold else "0")
            w.writerow(row)
    print(f"wrote {out_path}")

    # Distribution summary
    fracs = np.array([f for _, f in results], dtype=np.float64)
    if fracs.size:
        print("distribution of yellow_fraction:")
        print(f"  max    {fracs.max():.6f}")
        for q in (99.9, 99, 95, 90, 75, 50):
            print(f"  p{q:<5g} {np.percentile(fracs, q):.6f}")
        print(f"  min    {fracs.min():.6f}")
        if args.threshold is not None:
            n_flag = int(np.count_nonzero(fracs >= args.threshold))
            print(f"  flagged at threshold {args.threshold}: {n_flag}/{fracs.size} "
                  f"({100.0 * n_flag / fracs.size:.2f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
