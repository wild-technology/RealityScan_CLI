# CLAUDE.md — project context for RealityScan_CLI

ROV underwater photogrammetry pipeline driving **RealityScan 2.2** (Epic
Games; the product formerly named RealityCapture) via its CLI. Runs on
Windows with a multi-GPU CUDA setup.

Continuation of `wild-technology/RC_Main` (created from its
`claude/realityscan-repo-cleanup-2gjmu5` branch, July 2026 overhaul, full
history preserved — `git log` reaches all the way back). RC_Main is frozen;
new work happens here.

---

## Starting a session

Read in this order, then say in one line what you are about to do:

1. **`HANDOFF.md`** — current state, what is running, ranked loose ends,
   exact next commands. Read this **before the first mutating action**.
2. **This file** — hard rules, working practices, invariants. The
   module-by-module map lives in `docs/ARCHITECTURE.md`; go there when
   you touch a subsystem, not to orient.
3. **`docs/rs-reference/README.md`** — the RealityScan manual's routing
   index. It sends any RealityScan question to one of 14 documents in one
   hop. Do not answer a CLI question from general knowledge; route it.

**Do not read `FINDINGS.md` cover to cover** (5,300+ lines). It is a
grep target: search it for the command, key, or symptom you care about.
Same for `docs/` and `testing/` — they are cited sources, not orientation
reading.

Baseline before touching anything:

```bash
py -3.13 -m pytest testing -q
```

639 tests pass (1 skipped offline: geoid grid), ~25 s. If they do not pass
on a clean checkout, stop and report — you have inherited a broken tree and
anything you build on it is suspect.

## Working practices for any session

These apply regardless of task. They exist because each was learned the
expensive way.

- **Verify by census, never by exit status.** RealityScan exits SUCCESS
  while doing nothing — merges that do not fuse, settings that never
  applied, exports that wrote zero files. Count cameras, count sidecars,
  diff manifests — `py -3.13 -m modules.verify --workspace <ws> --json`
  does all three and reports frame/nav/settings unanimity and measured
  scale besides. `docs/rs-reference/12-failure-modes-and-race-conditions.md`
  is the catalogue of every silent-success mode found so far.
- **Own your instance before you run anything.** A cross-session incident
  (2026-07-28) had one session running on `RS1` while believing it was
  isolated on `RS2`, and it overwrote another session's `rs_settings.json`.
  Resolve `RS_INSTANCE` and `RS_GPU_DEVICES` explicitly, check no other
  instance holds that name, and never write another session's settings.
- **Write findings at the moment of discovery**, in the same turn, to
  `FINDINGS.md`. Deferred logging is lost logging. Refuted hypotheses stay,
  marked SUPERSEDED — deleting one guarantees rediscovering it.
- **Declare a budget before any long run**: expected duration, expected
  resource peak, abort criterion. Then "is it stuck?" is a lookup, not a
  judgment call. Model generation has been measured to run 40–340 min per
  component and to peak near total system commit; watch RAM unasked.
- **Snapshot evidence immediately.** `RealityScan.log` is global and
  truncated on every instance boot — the reason line behind a generic
  failure exists only until the next boot. Copy it inside the driver, right
  after the failing call returns.
- **One variable per iteration.** Escalation ladders change exactly one
  thing per attempt with per-attempt evidence. A re-align that changed
  several things at once cannot attribute its result to any of them.
- **Checkpoint before mutating, and rehearse the restore.** A loop without
  a tested rollback is a ratchet toward corruption.
- **Prefer the mini fixture.** No workflow change touches production data
  until it passes a <5 min smoke fixture. Smoke fixtures have caught the
  large majority of workflow bugs at a fraction of the cost.
- **Report incompleteness in chat, not in the file.** No TODOs, stubs, or
  commented-out code left behind.

Escalate rather than work around: invariant violations, two monitors
disagreeing about one run, a resource trend projecting past capacity, a
result that would revise an ESTABLISHED finding, or anything on the
blindness list (GUI state, georeferencing correctness, seam quality)
becoming load-bearing for a conclusion.

## Ending a session

`HANDOFF.md` outlives the session and is what the next one reads first.
Before you stop: findings flushed to `FINDINGS.md`; running processes
documented with resume commands; work committed or explicitly stashed with
reasons; `HANDOFF.md` refreshed with done / running / ranked loose ends /
artifact locations / exact next commands.

## Environment

- Windows 11, native. **No WSL** — cmd, `.bat`, PowerShell, VBS are the
  substrate. `.bat` and `.vbs` must be CRLF (`.gitattributes` pins it);
  LF breaks cmd's byte-offset label search nondeterministically.
- Python is `py -3.13` where the launcher exists; a box without it (the
  NA165/NA168 machine has Microsoft Store 3.13 and no launcher) uses plain
  `python`. The committed `.claude/settings.json` hooks call `python` for
  that reason. `ruff` is **not installed** here — the style check
  in the account-level agreement cannot run; say so rather than claiming it
  passed.
- ASCII-only console output; the cp1252 console crashes on non-ASCII. Set
  `PYTHONIOENCODING=utf-8` when parsing UTF-8 sources.
- Data lives on large local/NAS volumes with user-specific paths. Never
  hardcode them — prompt through `SettingsStore`.

---

## RealityScan reference

**`docs/rs-reference/`** is the consolidated manual: the shipped offline
Help (`C:\Program Files\Epic Games\RealityScan_2.2\Help\en-US\`, which is
the only reliably readable form of the official docs — the public site is
JS-rendered), the install-tree XML format dictionaries, and this repo's
empirical record. 218 command names, 740 settings keys, 88 numbered failure
modes. Every claim carries a provenance tag; `[CONTRADICTED]` entries state
both what the docs claim and what was observed.

Consult it before writing any new RealityScan workflow. Start at its
`README.md`; the "facts that silently destroy a run" table is the highest
-value page in the repo.

The few facts worth carrying in context without a lookup:

- Delegated commands (`-delegateTo <instance> <cmd>`) are QUEUED; the
  delegating process returns at hand-over, not completion.
- `-waitCompleted <instance>` returns prematurely if issued before the
  instance picks up the queued command — hence the double-wait in `:run`.
- `-getStatus <instance>` → errorlevel 0 iff the instance exists, but
  "gone" precedes process teardown by seconds (file handles outlive it).
  It also prints a live progress line on stdout (capture by redirecting;
  RealityScan is a GUI-subsystem binary): `id:<op> progress:<pct>
  runtime:<s> endEstimation:<s> rev:<n> lastError:<code>`. `rev:` tracks
  scene MUTATIONS, not operations.
- **`*` is a valid instance argument** meaning "first available instance",
  accepted by `-delegateTo`, `-waitCompleted`, `-getStatus`,
  `-pauseInstance`, `-unpauseInstance` and `-abortInstance`. A GUI or
  Epic-Launcher RealityScan has no `-setInstanceName` and answers no named
  lookup, but IS reachable via `*`. Ambiguous once two instances run — use
  explicit names for multi-GPU, `*` only to attach to a single interactive
  session.
- App settings use `app*` key names. The legacy `RealityCapture*` names are
  dead.
- Exit codes: 0 = success; with `appQuitOnError=true` the error's decimal
  code; 3 = crash (minidump at the `-silent` path).
- Multi-GPU: RealityScan uses all CUDA GPUs by default. Pin via
  `RS_INSTANCE` + `RS_GPU_DEVICES` (exported as `CUDA_VISIBLE_DEVICES`),
  one instance name per GPU set.

## Findings log

`FINDINGS.md` at the repo root is the running log of every discovered fact
— CLI behaviors, merge semantics, rig data, process conventions — each with
HOW it was discovered. Append whenever a fact is established; keep entries
short and dated. It is the raw log; the distilled counterpart is
`docs/rs-reference/`, and deep rationale lives in `docs/`.

## Naming

Everything in this repo says **RealityScan** (`RS`), never RealityCapture.
Exceptions that must NOT be renamed:

- RealityScan API identifiers that happen to be current product strings
  (e.g. `reader="RealityScan.Import.CSVFlightLog"` in `flightlogs.xml`,
  feature-detector ids in `Metadata/AlignmentParams.xml`);
- legacy file extensions `.rcalign`/`.rcproj`, still accepted when reading
  old outputs (new saves use `.rsproj`).

---

## Architecture

Full module-by-module map: **`docs/ARCHITECTURE.md`** — grep it when you
touch a subsystem. The shape worth knowing before the first action:

- **`main.py`** — interactive orchestrator (Extract → Georeference →
  Preprocess → Batch → Align). `RS_MODULES` / `RS_NO_INTERACTIVE` drive
  it without a TTY.
- **`wildscan/`** — TUI portal over the same drivers. `wildscan/session.py`
  is a PURE PLANNER (`build_commands`); the TUI, `wildscan/runner.py` and
  `wildscan/plan.py` are its three consumers. Add a fourth consumer rather
  than a second planner.
- **`modules/realityscan_interface/`** — the ONLY place RealityScan is
  executed. `realityscan_cli.py` (`RealityScanCLI`) owns executable
  discovery, per-instance locks, marker-file hygiene, progress tailing and
  verified shutdown; `RS_CLI/Scripts/*.bat` are the workflows, every one
  through the shared `:run` subroutine.
- **Post-align drivers** — `merge_zones.py`, `grow_zone.py`,
  `run_models.py`, `finish_model.py`, and `publish_cesium.py` /
  `publish_nira.py` / `publish_batch.py`.
- **`modules/`** — domain logic: camera registry, flight logs,
  calibration sidecars, batching, scale oracle, component
  analysis/manifest, workspace census, feature merge, align fingerprints,
  Cesium placement.
- **`module_base/`** — `RSModule`, `Parameter`, `SettingsStore`.

### Agent-facing entry points

These exist so a Claude-guided run reads a fixed schema instead of
re-deriving verdicts and flags in prose. Prefer them over ad-hoc greps.

- `py -3.13 -m modules.verify --workspace <ws> --json` — the census/verify
  **oracle**: "did it actually work", as JSON, read from artifacts on disk.
  Exit 0 ok / 1 incomplete / 2 blocked / 3 absent.
- `py -3.13 -m modules.run_charter --validate <charter>` — the run
  contract as DATA, plus the write-guard and instance-guard the drivers
  and hooks call.
- `py -3.13 -m wildscan.plan --charter <charter> --validate` — the run
  plan, headless, proven against `main.py`'s own parser before anyone runs
  it.
- `.claude/skills/` — per-procedure guides: `rs-lookup` (routes every
  RealityScan question into `docs/rs-reference/`), `drive-run`,
  `merge-zones`, `publish-cesium`, `finish-model`.
- `.claude/hooks/` — mechanical enforcement of hard rule 1, the charter's
  touch rules, and CRLF on `.bat`/`.vbs`. Liveness-tested by
  `testing/test_agent_hooks.py`; a guard nobody tests is a rule nobody
  enforces.

---

## When an AI agent is DRIVING (owner said "run this against that dataset")

MANDATORY — full contract in `docs/AGENT_OPERATIONS.md`; on conflict this
section wins. Every rule traces to a recorded incident.

1. **No writes before the charter.** Ask the user — never infer —
   where the ORIGINALS are, where the NAV is, where OUTPUTS go, and what
   is PROTECTED. Owner signs off; then work. The charter is DATA, not
   prose: `py -3.13 -m modules.run_charter --init <ws>/_agent/
   RUN_CHARTER.json`, then `--validate` it and export `RS_RUN_CHARTER`.
   That one variable arms the write guard, pins the agent's instance, and
   refuses stored-settings inheritance for every child process.
   (`docs/RUN_CHARTER.template.md` is the prose companion; the
   `drive-run` skill is the full walkthrough.)
2. **Source data is read-only, forever.** This pipeline writes sidecars
   into input folders (hard rule 0 forbids this; main's default identity
   harvest is exactly such a writer, pending D1) — an agent aligns only
   from trees it created (hardlinks/copies) or with explicit consent.
3. **Protected paths** (charter list) are never touched, cleaned, or
   reorganized. Deliverables are never overwritten — collisions are
   stop-and-ask.
4. **Agent working files live in ONE place**: `<results_root>/_agent/`.
   Never in the repo, never beside source data. It is the only tree the
   agent may delete freely. Rules 2–4 are enforced mechanically by
   `.claude/hooks/guard_charter_writes.py` whenever `RS_RUN_CHARTER` is
   set — a refusal there is an owner decision to revisit, never something
   to work around.
5. **Own instance, own processes.** Charter-named RS instance (never the
   user's), own cache. Never kill/quit/delegate-to anything the agent
   did not start; identify by PID+cmdline first.
6. **Long runs are scheduler-owned** (schtasks + CRLF launcher, never a
   harness shell — job objects killed 14.4 h once), with a written
   budget declaration and liveness-tested monitors BEFORE launch.
7. **Frames and fingerprints**: honor FRAME_WARNING markers and
   align_inputs.json; never mix coordinate frames; components without a
   current-nav fingerprint are not "done".
8. **Every science argument explicit** — no rs_settings inheritance
   unattended (`RS_NO_SETTINGS_INHERITANCE=1` makes the store refuse it).
   Plan with `py -3.13 -m wildscan.plan --charter <charter> --validate`
   rather than hand-writing a command line: it proves the argv against
   `main.py`'s own parser and names any charter answer that reached no
   command. **Owner gates (`confirmed: false`) are stops, never flags to
   flip.**
9. **Destructive ops need per-instance user approval**: anything outside
   the agent workspace, force-pushes, killing user processes, app-global
   RealityScan settings (they leak into the user's GUI), raising safety
   ceilings.

## Hard rules

0. **NO XMP SIDECARS. The input image tree is READ-ONLY to this
   pipeline.** Owner directive 2026-08-16: "Sidecars are forbidden in the
   workflow — they keep messing things up." The reason is structural, not
   stylistic: an `.xmp` beside an image is READ BY RealityScan on import,
   so anything left there silently becomes a PRIOR for the next run (7,694
   inherited sidecars once confounded a distortion A/B; 6,024 were
   re-created on H2080 in a tree that had just been certified clean).
   Priors travel IN via the flight log — position, orientation, their
   accuracies, and `FocalLength` (a documented CSV flight-log variable,
   along with PrincipalU/V, Skew, AspectRatio and the distortion
   coefficients) — plus `-setPriorCalibrationGroup` / `-setPriorLensGroup`
   in-session. Identity travels OUT via `-exportRegistration` into the
   OUTPUT tree. Anything a stage produces goes to the output tree; if a
   new writer needs to put a file next to an image, the design is wrong.
   NOTE (merge 2026-09-03): main's `AlignZone` identity default still
   harvests `-exportXMP` sidecars in-session (and `realityscan_interface.py`
   repairs calibration XMPs on every exit path); the non-destructive
   `-exportRegistration` CSV path is kept behind `RS_LEGACY_XMP_IDENTITY=0`,
   the VOYIS sidecar writer stays env-gated off (`RS_VOYIS_CALIB_SIDECARS`),
   and `prior_groups.py` groups run on every align — which mechanism
   RealityScan honours is open decision D1, FINDINGS `[RECON] 2026-09-03 -
   prior-groups claim: main and remove-xmp-sidecars disagree`.
1. Never add a second way to launch/monitor RealityScan — extend
   `RealityScanCLI` and the `:run` pattern instead.
2. Never infer completion from process names (`tasklist`); the pre-2.x code
   did that with `RealityCapture.exe` and silently broke at the rename.
3. No overall timeouts on RealityScan operations — 10+ hour runs are
   normal. Startup and shutdown are the only bounds; the authoritative
   values are the constants in `realityscan_cli.py`
   (`SHUTDOWN_VERIFY_TIMEOUT_SECONDS`, `STATUS_CALL_TIMEOUT_SECONDS`),
   not a number quoted in prose.
4. Clear `progress.txt` / `errors.txt` / `results.log` only through
   `RealityScanCLI` (it does this pre-run); they are the source of truth
   while a run is live.
5. Data lives on large local/NAS volumes with user-specific paths — never
   hardcode them. Use `SettingsStore` prompts with the previous value as
   default.
6. `geoall.py` is the canonical georeferencing implementation; port
   improvements from it into `modules/georeference/` rather than letting
   the two diverge further.
7. Import components (`-importComponent`) ONLY from their original export
   location — a relocated `.rsalign` hangs the instance forever in a
   `#timeout` state.
8. Never pass delimited data as `.bat` arguments: cmd splits unquoted
   `;` `,` `=` and Python's subprocess only quotes on whitespace. Lists
   cross the boundary as files (`.complist`/`.imagelist`); settings as
   `key:value` (converted inside the workflow).
9. `docs/rs-reference/` is the RealityScan documentation of record —
   consult it before writing any new workflow. The historical test matrices
   (`testing/MERGE_TEST_PLAN.md`,
   `testing/ALIGN_MERGE_HARDENING_PLAN.md`,
   `testing/PRIORS_DISTORTION_TEST_PLAN.md`) track design assumptions not
   settled by documentation; cells graduate into `FINDINGS.md` with
   results. `testing/NA167_SESSION_NOTES.md` is a **frozen** raw log kept
   as the citation target for `NA167 B*`/`#*` references — read it for
   provenance, not for current behavior.

## History notes

An earlier, richer iteration (delegation client, GUI, tests, docs) was
reverted by the `main_v2` merge — it survives only in git history around
commit `4bc8549`. Its race-condition lessons are baked into the current
execution layer; consult it before re-deriving old solutions.
