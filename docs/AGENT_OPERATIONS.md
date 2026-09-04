# Agent operations contract — mandatory when an AI agent "drives"

Scope: any session where the owner has asked an AI agent to operate this
pipeline ("pull this CLI and run it against this dataset", "run
autonomously", "drive"). These are MANDATES, not suggestions. Every rule
below traces to a recorded incident in this program's fact bases — the
citation is the reason the rule exists.

CLAUDE.md (auto-loaded) carries one-line pointers to the nine mandates;
this document is the full text — see "The nine mandates" below — and wins
on conflict (since 2026-09-03; before that the CLAUDE.md section won).
The `/drive-run` skill is the executable path.

## 0. Drive-start protocol (before the first write of any kind)

1. Read CLAUDE.md, this file, HANDOFF.md, and docs/PRODUCT_READINESS.md.
2. Run the INTAKE below with the user and write the answers to a
   RUN_CHARTER in the agent workspace. The charter is DATA the code
   enforces, not only prose: scaffold it with
   `python -m modules.run_charter --init <results_root>/_agent/RUN_CHARTER.json`,
   fill it in with the user, `--validate` it, and export `RS_RUN_CHARTER`
   for the session (that one variable arms the `.claude/` write guard and
   refuses stored-settings inheritance). docs/RUN_CHARTER.template.md is
   the prose companion, kept for the intake questions and the sign-off
   line.
3. Get explicit user sign-off on the charter. No writes before sign-off —
   reads and enumeration only.

### Intake — ask the user, never infer (same questions as the script)
The interactive pipeline asks these; a driving agent must ask the SAME
questions rather than guessing from directory listings:
- Where are the ORIGINALS (imagery)? Where is the NAV (flight log /
  datatables)? These are declared READ-ONLY at that moment.
- Where should OUTPUTS go (the campaign/results root)? Created if
  missing; everything the run produces lives under it.
- What may NOT be touched (protected paths: in-progress transfers, other
  campaigns' trees, GUI project dirs, prior deliverables)?
- Disk budget and machine constraints (free space now, the run's
  expected peak, the memory envelope).
- Which RealityScan instance name is the agent's, and which instances/
  processes belong to the user (never touched).
If the user pre-supplied any answer in their tasking, RESTATE it in the
charter for confirmation instead of re-asking.
[Provenance: wizard-prefill and stale-settings incidents 2026-08-08 —
inferred/persisted locations silently crossed campaigns.]

## 1. Data classification and touch rules

- SOURCE DATA (originals, nav): read-only, forever. Never write, rename,
  delete, or point any stage's OUTPUT at it. This pipeline WRITES INTO
  input folders (pose sidecars); therefore an agent aligns only from
  folders it created (copies or hardlinks) or after explicit owner
  consent to write into a user folder.
  [README "input folder is WRITTEN INTO"; NA173/ON2026 practice: hardlink
  trees, sources untouched.]
- PROTECTED PATHS (charter list): never read into outputs, never clean
  up, never "reorganize". Includes in-progress data transfers.
  [RUMI transfer exclusion, 2026-07-30.]
- DELIVERABLES (final/, exports, dated project copies): never overwrite,
  never delete. Re-exports version or supersede — a name collision is a
  STOP-and-ask, not an overwrite.
  [ModelToFinal silent-overwrite finding, 2026-08-08.]
- Nothing of the agent's goes inside the repo tree except code/docs/tests
  intended for commit. No scratch, no probe outputs, no logs in-repo.

## 2. Agent workspace ("keep your working files here")

- All agent working files — probes, fixtures, scratch, evidence
  snapshots, run charters, monitors' state — live under ONE declared
  workspace: `<results_root>/_agent/` (created at drive-start, named in
  the charter). Not in the repo, not beside source data, not in system
  temp on another volume.
- Evidence discipline: logs the tool truncates or rotates (RealityScan's
  instance log, per-attempt rslogs) are SNAPSHOTTED into the workspace at
  the moment of observation. [RealityScan.log truncation; per-attempt
  snapshot practice in merge_zones.]
- The workspace is the ONLY tree the agent may delete freely — and only
  its own session's files.

## 3. Process and instance hygiene

- The agent uses its OWN RealityScan instance name (charter-declared;
  never RS1 unless the user assigns it) and its own cache dir.
- Never kill, quit, or delegate to a process/instance the agent did not
  start. Before ANY kill: identify by PID + command line, and exclude
  the user's sessions. A query that matches its own search string is not
  evidence. [GUI-vs-RS1 confusion and self-matching process query,
  2026-08-03/08; orphaned-driver kills 2026-08-01.]
- One orchestrator per instance; respect the per-instance lock. Direct
  .bat invocation bypasses the lock layer — drivers only.

## 4. Long runs

- Anything expected to run past the session (or >30 min unattended) is
  SCHEDULER-OWNED (schtasks one-shot + CRLF launcher), never launched
  from the agent's harness shell. [Job-object kill lost 14.4 h,
  C-20260729-01.]
- Budget declaration in the charter before the first long run: expected
  duration, expected memory/disk peak, abort criteria. Monitors armed on
  the driver log, memory, and disk BEFORE launch; a monitor's liveness is
  itself tested. [C-20260802-01: 319.5 GB commit OOM after 19 unattended
  hours; "silence is not success".]
- Killing a driver does NOT cancel RealityScan work — verify the whole
  process tree when stopping anything (see PRODUCT_READINESS must-fix 8
  until fixed in code).

## 5. Scientific integrity while driving

- Never mix coordinate frames: honor FRAME_WARNING markers and
  align_inputs.json fingerprints; a components tree without a fingerprint
  matching the current nav is NOT "done". [Two-frames incident,
  C-20260805-01.]
- Every science-relevant argument explicit on every invocation — no
  rs_settings.json inheritance in unattended runs. [Stored-merge-options
  incident, final review 2026-07-29.]
- Owner gates are STOPS: a `confirmed: false` in an operator artifact
  (features.json, charter) means ask — never flip the flag to proceed.
- Findings discipline: new tool behavior discovered while driving is
  logged to FINDINGS.md in the same session, with how it was found.

## 6. Destructive-operation list (explicit user approval, every time)

Delete/overwrite anything outside the agent workspace; git push --force
or history rewrites; killing user processes; changing scheduled tasks the
user owns; modifying app-global settings (RealityScan persists them
across sessions — appProcessAction etc. leak into the user's GUI
[2026-08-04]); flipping any owner gate; raising a safety ceiling
(--max_scene_cameras) beyond its measured envelope.

## 7. Hard enforcement (recommended per campaign, beyond instructions)

Instructions bind the agent that reads them; deny-rules bind every agent.
For Claude Code, add campaign-specific guards to `.claude/settings.json`
(project) — example shape:

    {"permissions": {"deny": [
        "Edit(D:/H2018/Raw/**)",
        "Write(D:/H2018/Raw/**)",
        "Bash(rm* * D:/H2018/Raw*)"
    ]}}

and/or a PreToolUse hook that rejects writes under the charter's
protected paths. Keep the deny list in the campaign root (not the repo)
since paths are per-machine; the charter records where it lives.

## Working practices for any session

Moved verbatim from CLAUDE.md on 2026-09-03 (CLAUDE.md diet, roadmap Phase
1). These apply regardless of task — driving or not. They exist because
each was learned the expensive way.

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

## The nine mandates (moved from CLAUDE.md 2026-09-03)

This is the full text of the "When an AI agent is DRIVING" section that
lived in CLAUDE.md until 2026-09-03; CLAUDE.md now carries one one-line
pointer per mandate. This document is the full text of the driving contract
and wins on conflict, and the `/drive-run` skill
(`.claude/skills/drive-run/SKILL.md`) is the executable path through it.
Sections 0–7 above are the incident citations each mandate rests on. Every
rule traces to a recorded incident.

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

Interpreter note (2026-09-03): the commands above say `py -3.13` as they
did in CLAUDE.md. On a box without the `py` launcher (this one: Microsoft
Store 3.13, hooks call `python`), substitute `python -m ...` — see
CLAUDE.md "Environment".

## RealityScan facts to carry in context

Moved verbatim from CLAUDE.md "RealityScan reference" on 2026-09-03.
Everything else is a lookup: start at `docs/rs-reference/README.md` or
invoke the `rs-lookup` skill, and never answer a RealityScan CLI question
from general knowledge.

What the manual is (CLAUDE.md's former description, verbatim):
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
