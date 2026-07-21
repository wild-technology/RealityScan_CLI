# Test plan — zone_9 CLI validation + preprocessing iteration

Target dataset: `C:\Users\jonat\Desktop\NA173_H2103a\batched_images_by_zone\zone_9`
(4 cameras, flight log `.txt` in the zone root).

Everything below is automated by `testing\run_tests.bat` /
`run_zone9_tests.py`. The runner drives RealityScan exclusively through
`RealityScanCLI` + `AlignImagesFromFolder.bat` (repo hard rule 1), so this
doubles as the first real-machine validation of the unified execution layer
from `HANDOFF.md`.

## How to run (on the Windows box)

```
cd RealityScan_CLI
testing\run_tests.bat            :: phases 0-2 (preflight, smoke, iteration)
testing\run_tests.bat --full     :: + full-zone confirmation of the winner
```

Outputs land in `C:\Users\jonat\Desktop\NA173_H2103a\rs_cli_tests\`
(changeable at the first prompt): `results.csv` (every run, machine-readable)
and `REPORT.md` (ranked table + current best). The original zone_9 folder is
never modified — every run works on copies.

## Success metric

RealityScan writes one XMP sidecar per **registered** camera during
`-exportXMP`, so the primary score is `registered images / total images`
(also broken out per camera — with four cameras, a variant that rescues a
weak camera shows up immediately). Tiebreakers: exported component count
(fewer = better connected) and alignment runtime.

## Phase 0 — Preflight (no RealityScan run)

Aborts with a clear message if anything fails: RealityScan 2.2 executable
discoverable; dataset exists with images from 4 `cam*` prefixes; exactly one
flight-log `.txt` in the zone root; `nvidia-smi` GPU inventory; python deps.

## Phase 1 — Smoke test (~32 images, minutes)

A stratified mini-subset through the complete pipeline. This is the
make-or-break check from `HANDOFF.md`:

- instance boots headless, workflow delegates, instance verifiably shuts down;
- **`results_RS1.log` must record finished processes** — if it doesn't, the
  `appProcessExecCmd` trigger is dead (usually quoting + spaces in the
  checkout path, e.g. `C:\Users\jonat\...` is fine but a path with spaces is
  the classic killer) and the runner hard-stops, because without it error
  detection is blind;
- component + `.rsproj` produced and detected by the Python layer.

## Phase 2 — Preprocessing iteration (~400-image subset per variant)

Same stratified subset for every variant (identical images, identical flight
log, XMP sidecars never carried between variants so no calibration-prior
contamination). Round 1:

| variant | treatment |
|---|---|
| `baseline` | untouched copy |
| `clahe_c2_t8` | CLAHE, clip 2.0, 8×8 tiles (L channel, LAB) |
| `clahe_c4_t8` | CLAHE, clip 4.0, 8×8 tiles |
| `wb_clahe_c2_t8` | gray-world white balance, then CLAHE 2.0/8 |

Round 2 (automatic): neighbors of the round-1 winner — clip halved/×1.5,
tiles 4/16, white-balance toggled. If `baseline` wins round 1, preprocessing
isn't helping this imagery and iteration stops honestly. More rounds:
`--rounds 3`.

Interpretation guide: CLAHE mainly helps low-contrast/turbid underwater
imagery by strengthening local features; it can also amplify noise (watch
for a *drop* at clip 4). White balance matters when the blue-green cast is
crushing channel contrast. If registration is already ~100% at baseline,
the metric is saturated — rerun with a sparser subset (`--subset-size 250`)
so differences become visible.

## Phase 3 — Full-zone confirmation (`--full`, hours)

Applies the winning variant to all of zone_9 and runs the complete
alignment. Only worth it after phase 2 shows a clear winner. Reminder: no
overall timeout exists by design; progress streams to the console via
`progress_RS1.txt` tailing.

## Manual follow-ups after a good run

- Inspect the best variant's `.rsproj` in the RealityScan GUI (camera poses,
  drift, per-camera coverage).
- If a preprocessing variant wins decisively, consider baking it into the
  pipeline as a pre-alignment step (new module or `geoall.py` stage) — keep
  originals for texturing, align on processed copies via `-importImageSelection`
  or texture-reprojection onto the original imagery.
- Update `HANDOFF.md` checklist items 1–5 with what was observed.
