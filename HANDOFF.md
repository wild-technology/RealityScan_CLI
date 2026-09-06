# HANDOFF — state of the July 2026 overhaul

## 2026-09-05 — AGENT-NATIVE CONSOLIDATION on branch `claude/agent-native-consolidation`, read this first

Roadmap Phases 2–4 landed in one pass (docs/history/AGENT_NATIVE_ROADMAP.md):
prompts fail fast headless, the planner is `modules/run_plan.py`, the TUI is
archived FUNCTIONAL, `rs.py` is the one command surface, `modules/preflight.py`
asks for every missing answer before a run, probes/campaign drivers/session
docs are archived, CLAUDE.md is routing-only. Suite on the macOS box that did
the work: **784 passed, 22 failed (platform-bound, listed in
testing/conftest.py), 4 skipped**; Windows expectation unchanged: fully green
(NOT run here — first thing to do on the Windows box). Nothing running. No
RealityScan workflow content changed; no science argument changed.

### Done

- `rs.py` — `charter | preflight | plan | run | launch | status | verify`.
  `run`: headless, `RUN_STATE.json` + per-stage logs under `<ws>/_agent/`,
  export `--project/--names` re-resolved at launch, refuses RealityScan
  stages from a `CLAUDECODE` shell. `launch`: CRLF `.cmd`+`.vbs` pair, prints
  the three `schtasks` commands (never runs them). `status`: read-only.
- `modules/preflight.py` — missing answers as QUESTIONS (`missing[]`), unsafe
  facts as `blocking[]`; derives required answers from the modules' own
  Parameters; unknown camera prefixes are questions, never assumed mounts.
- `modules/run_plan.py` — ex `wildscan/session.py` + `plan.py`, one planner;
  `refresh_export_command`; `IMAGE_EXTS` = `ALL_IMAGE_EXTS`.
- Unattended contract: `SettingsStore.unattended()` / `default_for()`;
  `main.py` fail-by-flag under `RS_NO_INTERACTIVE`/charter, lazy `inquirer`;
  batcher default via `default_for`; `geoall` no hardcoded paths;
  `decimator` argparse + `--yes`; `timestamp_rename --yes`.
- `testing/conftest.py` — the store never writes the repo root; `RS_*`
  scrubbed; session fails on a stray `rs_settings.json`. 3 new test files
  (+43 tests); 3 TUI test files retargeted to `modules.run_plan`.
- Archive (all functional, nothing deleted): `archive/wildscan_tui/`
  (`run_wildscan.py`), `archive/probes/` (9 `.bat`), `archive/campaign_drivers/`
  (+6), `archive/reference_data/sensorsdb.xml`, `archive/colmap/docs/`,
  `docs/history/` (5 docs + HANDOFF history + AUDIT). Map:
  `docs/history/README.md`.
- Docs: CLAUDE.md 128 lines (hard rule 10 added: the workflows are the
  product), README, ARCHITECTURE, AGENT_OPERATIONS compacted, `docs/DECISIONS.md`
  (D1–D14), skills rewritten around `rs.py`, rules/agents/hook updated,
  `.claude/settings.json` allow-list for `rs.py`/`modules.run_plan`/`preflight`.
- Second pass (same day): preflight also checks every module the stages
  import, every workflow script (present + CRLF), every Metadata preset
  (present, well-formed, format GUIDs defined, frame templates, no `app*`
  key, `.rsInfo` on) and `python` on PATH for the hooks. Three hooks added:
  `route_driving_prompts.py` (UserPromptSubmit: injects the /charter →
  /drive-run protocol on run phrasing), `guard_schtasks.py` (PreToolUse:
  `schtasks /Create` only for a launcher `rs launch` wrote), `pre_compact.py`
  + SessionStart on `compact` (re-orientation and an unflushed-facts warning
  after compaction). Agents: `run-monitor` on haiku, `rs-reference` on sonnet.
  `rs launch` prints the `/loop 30m` monitor line; `RUN_STATE.json` carries
  `poll_interval_min`. `docs/OPERATOR_SETUP.md` (per-box checklist).
- FINDINGS ↔ rs-reference RECONCILED: every RealityScan-behaviour entry
  through 2026-09-03 is in the manual (per-file `## Addenda`, 13 files);
  in-place corrections: 06 §3.2 CRS scopes RESOLVED, 09/10 export CRS type 3
  = ECEF VERIFIED, 10 §9.2 texture registry (8K, not 16K; live 16K
  fallthrough), 11 §10 recipe order (settings → CRS → flight log), 13 §10
  rig table (cinema 0°, upper 45°), 12 result codes + F-101…F-106. FINDINGS
  header states the organisation and the reconciliation rule; the 08-08
  "GUID is decorative" probe is marked SUPERSEDED by 08-16.

### Running

Nothing.

### Ranked loose ends

1. **Run the suite on the Windows box** and confirm fully green; the
   alignment tests and `M:\` basename tests could not run on macOS. Then
   run `python rs.py preflight --charter <existing charter>` against a real
   workspace (NA165/H2063) — the first live use of the oracle.
2. **D1** (`RS_LEGACY_XMP_IDENTITY` default) is still open — the
   solved-focal-equality probe on the smoke fixture settles it.
3. **D6** — the five staging scripts under `coyotethings\tools` are still
   outside the repo (`modules/staging/` never created).
4. **D9/D10** — promote `stage_features` out of `testing/run_on2026_run2.py`;
   per-stage `<stage>_report.json` for extract/georeference/preprocess/export.
5. `test_rig_mounts.py` leaks `logging.disable(CRITICAL)`; trivial fix.
6. `rs launch` has never been exercised on Windows end to end (the launcher
   pair is unit-tested for content and CRLF only); nor has the `/loop 30m`
   monitor been run against a live task.
7. **D12/D13** — `ModelToFinal.bat`'s blind `-selectModel`+`-deleteSelectedModel`
   pattern and the 16K unwrap fallthrough for non-`4x8k` presets are owner
   calls; both are documented (rs-reference 12 F-102, 10 A4), neither changed.
8. The new hooks arm only in a NEW Claude Code session; the UserPromptSubmit
   routing hook's phrasing list will need tuning on real prompts.

### Artifact locations

Branch `claude/agent-native-consolidation` on `origin`; nothing on any data
volume was touched (no dataset, no RealityScan instance, no schtasks).

### Exact next commands

```bash
python -m pytest testing -q                                   # Windows: expect fully green
python rs.py --help
python rs.py charter init <results_root>/_agent/RUN_CHARTER.json
python rs.py preflight --charter <C>
python rs.py plan --charter <C> --validate
python rs.py status --charter <C>
```

---

## 2026-09-03 — RECONCILED: one `main` again, agent-native lane adopted, read this first

Three lines became one. `main` now = the NA165/H2060 line + the
`remove-xmp-sidecars` line (merge `b640c81`) + the agent-native tooling
(`d38d5f3`, cherry-pick of `37d6d41`). Suite **725 passed, 1 skipped,
~22 s** with `python -m pytest testing -q`. Nothing running. Tag
`manual-era-final` marks `b640c81`, the last tree before the restructure
(the WildScan TUI and campaign drivers are recoverable from it).

Owner rule for the merge: main is the base and carries the latest actual
processes; every additive sidecars feature kept; nothing dropped except
literal duplicates. The plan is `docs/AGENT_NATIVE_ROADMAP.md`; this
session executed its Phase 0.

### What landed

- **Align identity: both mechanisms, main's default.** `AlignZone.bat` and
  `realityscan_interface.py` keep main's in-session `-exportXMP` harvest as
  the DEFAULT; `RS_LEGACY_XMP_IDENTITY=0` selects the sidecars line's
  non-destructive `-exportRegistration` CSV capture. The calibration-sidecar
  repair follows the same switch. `prior_groups.py` + `RS_PRIOR_GROUPS_FILE`
  replay run on EVERY align, walking the pool root.
- **Export CRS unified on `RS_PROJECT_CRS`**; `export_deliverables.py` keeps
  `--flight-log` / `--crs` and feeds it. `RS_OUTPUT_CRS` is gone.
- **cameras.json / MOUNTS**: full union; `wca_cinema` pitch 0.0 per the
  2026-08-14 owner correction, 45 on `wca_upper` / `na168_upper`.
- **Agent-native lane**: `modules/run_charter.py`, `modules/verify.py`,
  `wildscan/plan.py`, `RS_NO_SETTINGS_INHERITANCE`, `.claude/hooks/` +
  `settings.json`, five skills, `docs/ARCHITECTURE.md` (now carrying the
  merged architecture detail that left CLAUDE.md).
- **Hooks call `python`, not `py -3.13`** — this box has Microsoft Store
  Python 3.13 and NO `py` launcher, so the guards would never have fired.
  Proof they fire now: this session's own Bash call was BLOCKED by
  `guard_rs_launch.py` because its text quoted `ProbeCalibGroups3.bat`.
  Consequence to know: a non-read-only shell command that merely MENTIONS a
  workflow script name is refused; put such text in a file, or start the
  command with a read-only tool (`grep`, `cat`, `git`, `python`, ...).
- `guard_rs_launch` now covers every script under `RS_CLI/Scripts`
  (Probe*, AlignImagesFromFolder, and any future one).

### OPEN — owner decisions (numbered as in the roadmap)

1. **D1 — do CLI prior groups take effect?** main's FINDINGS 2026-08-08 says
   `-setPriorCalibrationGroup` is silently non-functional from the
   delegated CLI; the sidecars line ran H2080/H2063 with `prior_groups.py`
   and never measured it. FINDINGS `[RECON] 2026-09-03 - prior-groups
   claim: main and remove-xmp-sidecars disagree`. The solved-focal-equality
   oracle on the smoke fixture settles it; flipping the default is one line
   in each of the two files.
2. **D3 — `85c556a` (Zeuss 25/45, orientation hardness 2.0) NOT adopted.**
   Science, un-A/B'd by its own message. Preserved as tag
   `agent-native-execution-final`; review on its own.
3. **D6 — the old checkout** `C:\Users\produ\coyotethings\tools\RealityScan_CLI`
   sits on the now-deleted `remove-xmp-sidecars`; the five
   `coyotethings\tools\*.py` staging scripts hardcode that path. Roadmap
   Phase 2 moves them into `modules/staging/`.

### Branches

Deleted on origin after this push: `remove-xmp-sidecars` (merged),
`agent-native-execution` (cherry-picked; its head tagged). Left alone:
`claude/cesium-ion-georeferenced-ue5-vvpoau` (4 unmerged `cesium2unreal`
commits — not stale, unreviewed) and `archive/on2026-model-to-final-pre-rebase`.

### Next

Roadmap Phase 1 (`.claude/` substrate: permissions allow/ask, a
`SessionStart` status hook, CLAUDE.md to ≤150 lines, `charter` / `status` /
`handoff` skills, `run-monitor` + `rs-reference` agents, path-scoped rules),
then Phase 2 (prompts fail fast, TUI removal with the planner extracted to
`modules/run_plan.py`, stage reports, `modules/launch.py`, staging scripts
in).

### Exact next commands

```bash
python -m pytest testing -q
python -m modules.run_charter --init <results_root>/_agent/RUN_CHARTER.json
python -m modules.run_charter --validate <charter>
python -m wildscan.plan --charter <charter> --validate
python -m modules.verify --workspace <results_root> --json
```

---

## 2026-09-02 — NA165 / H2060 delivered end to end, read this first

**First full run of this pipeline from raw nav to exported deliverables.**
ExportDeliverables had never produced output on this machine before today.

### Done

| stage | result |
|---|---|
| ROVDataConcat stage 1+2 | 17 dives; H2049/H2050 excluded (degenerate `dives.tsv` rows) |
| georeference | 29,069 / 29,069 images matched, all exact |
| align | 20 components, 2,813 / 3,870 cameras (72.7%) |
| merge | one evolution (owner-capped); the abort was a real bug, now fixed |
| model | **20 / 20**, 14.3 h, census-verified |
| export | **20 / 20 with OBJ + FBX + dense PLY**, 91 GB |

Artifacts on the NAS, verified 2026-09-03 by a LIST-ONLY robocopy pass
(61,642 files / 253.9 GB across the three trees; 0 to copy, 0 mismatch,
0 failed, 0 extras). Robocopy's default compare is name+size+timestamp,
so this is size/mtime parity plus matching aggregate byte totals - NOT a
content hash. Use /BYTES-level hashing if a checksum is ever required:
`Y:\RUMI Projects and Output\NA165_H2060\{master,exports,preprocessed_images}`
Master project: `master\assembly\NA165_H2060_master.rsproj` (119.5 GB).

### What made this run hard (all fixed, all in FINDINGS.md)

Ten defects. The expensive ones shared two shapes:

1. **Pool layout moved where data lives and consumers kept looking in the old
   place.** FIVE of them: `bbox_from_flight_log`, `build_union_flight_log`,
   `scale_oracle.load_nav_positions`, the align stage's pool gate, and the
   merge's identity harvest. Grep `RS_MERGE_IMAGES_ROOT`, `images_root` and
   `split(';')[0]` before adding a sixth.
2. **A guard that answers the wrong question.** `run_models` wrote a full
   119.5 GB dated project copy immediately after aborting for low disk, and
   again when 157 GB free "passed" a fixed threshold - taking C: to 0.01 GB
   once. Now sized against the actual project.

Also: the dense-PLY "missing model" was a missing `-selectComponent`;
`0x80070057` from process 21856 is RealityScan's **-selectModel-cannot-resolve**
signature, and it is fatal in export because `:run` reads a STICKY errors file.

### Running

Nothing. All background tasks stopped, all scheduled tasks removed.

### Ranked loose ends

1. **`:run`'s sticky errors file** — one tolerated failure poisons every later
   command in the session, and errors get misattributed to whatever ran last.
   The primitive already exists (`try_delete_model` MOVEs to
   `expected_<reason>_<inst>.txt`); a shared `:try_run <tag> <cmd...>` would
   generalise it. This is the single highest-value cleanup left.
2. **Verify the CRS pin on the next dive.** `5c545e3` sets project + output CRS
   from the flight log's zone before `-importFlightLog`. Confirm a fresh
   `.rsInfo` declares the dive's own EPSG rather than a leftover. H2060's
   exports still carry the old arbitrary `55N` label — the GEOMETRY is correct
   ECEF (verified: 300k vertices resolve to the H2060 site), only the label is
   wrong, so re-export if a downstream tool trusts that attribute.
3. **`exportCoordinateSystemType=3` writes ECEF**, not the project CRS. Closes
   rs-reference OPEN question 16. Type 0 (PLY) still unobserved.
4. **Cache capacity.** ~72 GB per mid-size component, and `-clearCache` does
   NOT reliably reclaim it (148 GB -> 2.7 GB once, 148 -> 90.6 GB the next
   time). A COLD directory reset does. Budget accordingly.
5. **C: is at 43 GB free.** Local copies under `NA165_H2060_RS` are redundant
   now the NAS copy is verified; `master` + `exports` alone is ~210 GB.
   Owner decision — nothing deleted.

### Exact next commands

```bat
:: push from this machine (GCM CANNOT auth headless; gh device flow works)
gh auth status
git push origin main

:: re-verify the NAS copy (rc=0 means already in sync)
"C:\Users\produ\Desktop\CoyoteThings\NA165_H2060_RS\_agent\sync_to_nas.bat"
```

`gh` 2.99.0 is installed at `C:\Users\produ\bin\gh.exe` and registered as git's
credential helper for github.com. Git Credential Manager 2.5 hangs on a GUI
dialog from a non-interactive shell (rc=124); forcing
`credential.gitHubAuthModes=device` produced no output either. Never accept a
PAT pasted into chat — use the gh device flow.
