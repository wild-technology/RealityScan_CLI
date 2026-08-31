# Agent operations contract — mandatory when an AI agent "drives"

Scope: any session where the owner has asked an AI agent to operate this
pipeline ("pull this CLI and run it against this dataset", "run
autonomously", "drive"). These are MANDATES, not suggestions. Every rule
below traces to a recorded incident in this program's fact bases — the
citation is the reason the rule exists.

The compact version of this contract lives in CLAUDE.md (auto-loaded);
this document is the full protocol. On conflict, CLAUDE.md wins.

## 0. Drive-start protocol (before the first write of any kind)

1. Read CLAUDE.md, this file, HANDOFF.md, and docs/PRODUCT_READINESS.md.
2. Run the INTAKE below with the user and write the answers to a
   RUN_CHARTER.md in the agent workspace (template:
   docs/RUN_CHARTER.template.md).
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
