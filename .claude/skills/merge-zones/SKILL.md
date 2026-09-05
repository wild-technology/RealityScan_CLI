---
name: merge-zones
description: Merge aligned per-zone components into larger assemblies, or grow a zone that will not align standalone. Use when asked to merge components, assemble a wreck or feature, fuse zones, fix a merge that "succeeded" without fusing, or when merge_report.json / EVALUATION_READY needs interpreting.
disable-model-invocation: true
---

# Merging components

`python` = the interpreter with the deps (CLAUDE.md "Environment";
`py -3.13` where the launcher exists).

Merge is the stage with the most silent-success modes in the pipeline. A
merge that reports success and fuses nothing looks identical to one that
worked, unless you count.

Read `docs/rs-reference/08-components-and-merge.md` before changing merge
behaviour - it documents what actually fuses and what does not.

## Run it through the driver

On the charter lane: `python rs.py launch --charter <C> --stages merge`
(the plan pins every argument below). By hand, or to inspect the argv:

```bash
python merge_zones.py --components_root <ws>/aligned_components \
    --images_root <ws>/batched_images_by_zone \
    --output <ws>/merged --name "<LABEL>_Assembly" --project_label "<LABEL>" \
    --min_size 50 --target 0.95 --ladder merge_first --merge_scope neighbour \
    --pair_gate overlap --loss_tolerance 0.0025 \
    --scale_gate true --scale_min 0.9 --scale_max 1.1
```

**Pin every argument explicitly.** Drivers that left merge options unpinned
inherited another session's stored values (recorded, 2026-07-29). On a
charter-driven lane `RS_NO_SETTINGS_INHERITANCE` refuses that
automatically; state them anyway so the run says what it did.

The numbers above are decisions, not defaults:
- `loss_tolerance 0.0025` - the owner's bounded-loss decision, 0.25% of
  input cameras, sized from the hull's real loss with an order of
  magnitude of headroom.
- `scale_min/max 0.9-1.1` - the metric-scale oracle gate, set after two
  align-time scale collapses (0.175, 0.236) shipped with camera-count
  oracles green.
- `--resume` (default true) reuses CONVERGED clusters from a prior
  `merge_report.json` whose `run_fingerprint` (ladder, scope, pair gate,
  loss tolerance, min size, input set) matches; a differently-posed prior
  run is refused, a mid-ladder cluster is re-merged. Pass `--resume false`
  to force a clean re-merge.

## Before launching

- **Check the scene ceiling.** 34,000 cameras took 262 GB on a 192 GB box
  (C-20260802-01). `merge_zones` enforces `--max_scene_cameras`
  pre-launch; do not raise it without owner approval.
- **Verify frame and settings unanimity first.** Merging across
  coordinate frames is never recoverable:
  ```bash
  python rs.py verify --workspace <ws> --require align
  ```
  A `blocked` verdict here means the inputs are not comparable. Stop.
- **Import components ONLY from their original export location.** A
  relocated `.rsalign` hangs the instance forever in a `#timeout` state
  (hard rule 7).
- Lists cross the cmd boundary as files (`.complist`), never as arguments
  - cmd splits unquoted `;` `,` `=` (hard rule 8).

## Verify by census

`EVALUATION_READY.txt` alone is not proof: it used to be written BEFORE
the assembly workflow's result was checked, so a failed assembly left a
document declaring a terminal state for a project that was never saved.

```bash
python rs.py verify --workspace <ws> --require merge --json
```

Then read `merge_report.json` for per-attempt evidence. Each escalation
rung changes exactly ONE thing, with its own `RealityScan.log` snapshot -
a re-merge that changed several things at once cannot attribute its
result to any of them.

## When a zone will not align standalone

`grow_zone.py` is the incremental grow-from-neighbour workaround. Per-step
reload against current nav (`--flight_log`) is what keeps a grown
component nav-aware.
