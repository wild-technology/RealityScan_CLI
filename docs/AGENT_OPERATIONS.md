# Agent operations contract — mandatory when an AI agent drives

Scope: any session where the owner asks an agent to operate this pipeline
("run this against that dataset", "process this dive", "drive"). These are
MANDATES. Every rule traces to a recorded incident (cited in brackets).
`CLAUDE.md` carries one-line pointers; this file is the full text and wins
on conflict. `/drive-run` is the executable path; `rs.py` is the surface.

## 0. Drive-start protocol — before the first write of any kind

1. Orient: the SessionStart hook output, then `HANDOFF.md`'s current
   section, `docs/DECISIONS.md`, `docs/PRODUCT_READINESS.md` if the task
   touches a listed item.
2. Intake with the owner — ONE block, all six questions, in chat. A
   directory listing is not an answer; an answer already in the tasking is
   RESTATED for a yes [wizard-prefill and stale-settings incidents 2026-08-08].
3. `python rs.py charter init <results_root>/_agent/RUN_CHARTER.json` (the
   one write allowed before sign-off), fill it WITH the owner, then
   `python rs.py preflight --charter <C>`. Every `missing` line is a
   question back to the owner; never fill one from a listing, a previous
   campaign or a plausible guess. Repeat until READY.
4. Owner sign-off, in their own words, into `signed_off.by/.date/.quote`.
   `python rs.py charter validate <C>` exits 0. The owner sets
   `RS_RUN_CHARTER=<C>` in the shell that launches Claude Code — that arms
   the write guard, pins the instance, refuses stored-settings inheritance.

### The six intake questions
1. ORIGINALS — the imagery tree(s). Read-only from this moment.
2. NAV — flight log / datatables. Read-only.
3. OUTPUTS — the results root. Created if missing; everything lands under it.
4. PROTECTED — in-progress transfers, other campaigns, GUI project dirs,
   prior deliverables. Each with a WHY.
5. BUDGET — disk free now, expected peak, expected delta, memory line,
   abort criterion (`/status` reads what can be read).
6. INSTANCE OWNERSHIP — the agent's RealityScan instance name and cache dir;
   every instance/process that is the owner's (never touched).

Plus, per dataset, what `preflight` derives: the chain modules' required
answers (`g_type`, input dirs, nav table, ...), every camera family in the
imagery (an unknown prefix is asked about — name, lens, MEASURED mount or
"unknown"; nothing is invented [PRODUCT_READINESS 17]), and the coordinate
frame.

## 1. Data classification and touch rules

- SOURCE DATA (originals, nav): read-only, forever. Never write, rename,
  delete, or point an output at it. The align stage writes into the folder
  it is given (identity harvest), so an agent aligns only from trees it
  created or with explicit consent [README "input folder is WRITTEN INTO";
  NA173/ON2026 hardlink practice].
- PROTECTED PATHS (charter list): never read into outputs, never cleaned,
  never "reorganised" [RUMI transfer exclusion 2026-07-30].
- DELIVERABLES (`final/`, `exports/`, dated project copies): never
  overwritten, never deleted; a name collision is stop-and-ask
  [ModelToFinal silent overwrite 2026-08-08].
- Nothing of the agent's goes inside the repo except code/docs/tests for
  commit. No scratch, probe output or logs in-repo.

## 2. Agent workspace

All agent working files — charter, plan, `RUN_STATE.json`, launchers,
probes, fixtures, evidence snapshots, monitor state — live under ONE tree:
`<results_root>/_agent/`. It is the only tree the agent may delete from,
and only its own session's files. Snapshot evidence at the moment of
observation: `RealityScan.log` is global and truncated on every boot
[merge_zones per-attempt snapshots].

## 3. Process and instance hygiene

- Own instance (charter-declared; never `RS1` unless assigned), own cache dir.
- Never kill, quit or delegate to a process/instance the agent did not
  start. Before any kill: identify by PID + command line; a query that
  matches its own search string is not evidence [GUI-vs-RS1 confusion
  2026-08-03/08; orphaned-driver kills 2026-08-01].
- One orchestrator per instance; drivers only (direct `.bat` bypasses the
  lock — the hook refuses it anyway).

## 4. Long runs

- Anything past the session or >30 min unattended is SCHEDULER-OWNED:
  `python rs.py launch --charter <C>` writes the CRLF launcher pair and
  prints the `schtasks` commands; the agent runs them (ask-gate) and polls
  with `rs status` or the `run-monitor` agent. `rs run` refuses RealityScan
  stages from an agent shell for this reason [job-object kill lost 14.4 h,
  C-20260729-01].
- Budget declared in the charter BEFORE launch (duration, memory peak, disk
  delta, abort criteria); monitors armed and liveness-tested first
  [C-20260802-01: 319.5 GB commit OOM after 19 unattended hours].
- Killing a driver does NOT cancel RealityScan work — check the whole
  process tree [PRODUCT_READINESS 8].

## 5. Scientific integrity

- Never mix coordinate frames: honour FRAME_WARNING markers and
  `align_inputs.json`; components without a fingerprint matching the current
  nav are not "done" [two-frames incident C-20260805-01].
- Every science argument explicit on every invocation; no
  `rs_settings.json` inheritance unattended (`RS_NO_SETTINGS_INHERITANCE`
  is set for every chartered child) [stored-merge-options 2026-07-29].
- Owner gates are STOPS: `confirmed: false` in `features.json` or the
  charter means ask — never flip it.
- New tool behaviour is written to `FINDINGS.md` in the same session, with
  how it was found.
- **The workflows are the product** (CLAUDE.md hard rule 10): the order of
  operations in the `.bat` workflows, drivers and modules changes only for a
  verified bug or on the owner's instruction — never to tidy.

## 6. Destructive operations — explicit owner approval, every time

Delete/overwrite anything outside `_agent/`; `git push --force` or history
rewrites; killing owner processes; changing owner scheduled tasks; app-global
RealityScan settings (they persist into the owner's GUI [2026-08-04]);
flipping any owner gate; raising a safety ceiling (`--max_scene_cameras`)
past its measured envelope.

## 7. Hard enforcement

Instructions bind the agent that reads them; guards bind every agent.
`.claude/settings.json` (allow / ask / deny) and the hooks enforce hard rule
1, the charter's touch rules (`RS_RUN_CHARTER`) and CRLF. Per-campaign deny
lists for data paths live in the campaign root, not the repo (paths are
per-machine); the charter records where.

## Working practices — any session

- **Verify by census, never by exit status.** RealityScan exits SUCCESS
  while doing nothing; `rs verify` / `rs status` count what landed
  [rs-reference 12 sec.1].
- **Own your instance before you run anything** [cross-session RS1/RS2
  incident 2026-07-28].
- **Write findings at the moment of discovery**; refuted hypotheses stay,
  marked SUPERSEDED.
- **Declare a budget before any long run** (models: 40–340 min per
  component, peak near total commit).
- **Snapshot evidence immediately** (`RealityScan.log` truncates on boot).
- **One variable per iteration**; escalation ladders change one thing per
  attempt with per-attempt evidence.
- **Checkpoint before mutating and rehearse the restore.**
- **Prefer the mini fixture**: no workflow change touches production data
  before a <5 min smoke fixture passes.
- **Report incompleteness in chat, not in the file** — no TODOs or stubs.
- **Escalate rather than work around**: invariant violations, two monitors
  disagreeing, a resource trend past capacity, a result that would revise an
  ESTABLISHED finding, or GUI state / georeferencing correctness / seam
  quality becoming load-bearing.

## The nine mandates

1. **No writes before the charter.** Six answers from the owner (never
   inferred), preflight READY, owner sign-off; then `RS_RUN_CHARTER` armed.
2. **Source data is read-only, forever.** Align only from trees the agent
   created (hardlinks/copies) or with explicit consent.
3. **Protected paths are never touched**; deliverables are never
   overwritten — collisions are stop-and-ask.
4. **Agent working files live in ONE place**: `<results_root>/_agent/`.
   Mandates 2–4 are enforced by `.claude/hooks/guard_charter_writes.py`; a
   refusal there is an owner decision to revisit, never something to work
   around.
5. **Own instance, own processes.** Never kill/quit/delegate-to anything the
   agent did not start; identify by PID + cmdline first.
6. **Long runs are scheduler-owned** (`rs launch` + `schtasks`, never a
   harness shell), with a declared budget and liveness-tested monitors.
7. **Frames and fingerprints** are honoured; never merge across frames.
8. **Every science argument explicit**; plan with `rs plan --validate`, never
   a hand-written command line. Owner gates are stops.
9. **Destructive operations need per-instance approval** (section 6).

## RealityScan facts to carry without a lookup

Everything else: `docs/rs-reference/README.md` (its "facts that silently
destroy a run" table first), or the `rs-lookup` skill.

- Delegated commands are QUEUED; `-delegateTo` returns at hand-over.
- `-waitCompleted` returns early if issued before pickup — hence the double
  wait in `:run`. Never gate on `results_<inst>.log` growth (heartbeats).
- `-getStatus` errorlevel 0 iff the instance exists; "gone" precedes process
  teardown by seconds. `*` = "first available instance" (attach only).
- App settings use `app*` keys; the `RealityCapture*` names are dead.
- Exit codes: 0 success; `appQuitOnError=true` → the error's decimal code;
  3 = crash (minidump at the `-silent` path). The errors file is STICKY for
  the session.
