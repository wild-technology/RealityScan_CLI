---
paths:
  - "modules/realityscan_interface/*.py"
  - "merge_zones.py"
  - "grow_zone.py"
  - "run_models.py"
  - "finish_model.py"
---

# Rules for the execution layer and its drivers

- **`RealityScanCLI` is the only launcher.** New RealityScan-invoking code
  extends `realityscan_cli.py` (`run_batch_script` / `run_attach_script`) and
  the `:run` pattern - never a second `subprocess` path, never `tasklist`
  completion. [CLAUDE.md hard rules 1 and 2]
- **No overall timeouts on RealityScan operations** - 10+ h runs are normal.
  Startup and shutdown are the only bounds; their values are the constants
  `SHUTDOWN_VERIFY_TIMEOUT_SECONDS` / `STATUS_CALL_TIMEOUT_SECONDS` in
  `realityscan_cli.py`, never a new `timeout=`. [CLAUDE.md hard rule 3]
- **Verify by census, never by exit status.** RealityScan exits SUCCESS while
  merging nothing, applying no setting, exporting zero files; a verdict is a
  count read from disk (`modules.verify`). [CLAUDE.md; rs-reference 12 sec. 1]
- **Snapshot `RealityScan.log` inside the driver, right after the failing
  call returns.** It is global and truncated on every boot; the reason behind
  a generic `0x8000FFFF` lives only until then. `merge_zones.snapshot_rs_log`,
  validated by a run-unique token (splice risk). [CLAUDE.md; FINDINGS 2026-07-27]
- **`assert_bat_safe` is the boundary.** Both launch paths call it; an
  argument with cmd metacharacters is a `ValueError` - rename, or pass by
  file/env var, never escape. [CLAUDE.md hard rule 8; audit 2026-08-07]
- **Markers are cleared by `RealityScanCLI` only**, pre-run; attach mode never
  clears a foreign instance's markers and never touches `progress_<inst>.txt`
  (held open by `-writeProgress`). [CLAUDE.md hard rule 4; attach notes]
- **The identity switch, stated once:** `RS_LEGACY_XMP_IDENTITY` unset or `1`
  (main's default) runs the in-session `-exportXMP` harvest, which writes
  sidecars into the image tree; `RS_LEGACY_XMP_IDENTITY=0` selects the
  non-destructive `-exportRegistration` CSV capture. Which one RealityScan
  honours is open decision D1: flip no default and delete no branch until
  the probe result is in FINDINGS (`[RECON] 2026-09-03`). [CLAUDE.md hard
  rule 0 note; HANDOFF 2026-09-03]
