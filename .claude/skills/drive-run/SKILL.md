---
name: drive-run
description: Drive this pipeline against a dataset end to end - the charter/plan/run/verify protocol for when the owner says "run this against that data", "process this dive", "align these zones", or asks for an unattended or overnight run. Covers the run charter intake, the headless run plan, budget declaration, and the verification oracle. Use BEFORE the first write of any driving session.
disable-model-invocation: true
---

# Driving the pipeline

The contract is `docs/AGENT_OPERATIONS.md` ("The nine mandates" is the full
text) and it wins on conflict; CLAUDE.md's "When an AI agent is DRIVING"
section is one-line pointers to it (since 2026-09-03; before that the
CLAUDE.md section won). This skill is the executable path through it.
Every step exists because of a recorded incident.
`python` = the interpreter with the deps (CLAUDE.md "Environment";
`py -3.13` where the launcher exists).

## 0. Before the first write - the charter

No writes before the owner signs a charter. **Ask; never infer** from
directory listings:

- Where are the ORIGINALS (imagery)? Where is the NAV?
  (read-only, forever, from that moment)
- Where do OUTPUTS go?
- What must never be touched (in-progress transfers, other campaigns,
  prior deliverables)?
- Which RealityScan instance is the agent's, and which are the owner's?
- Disk free now, expected peak, expected delta.

If the owner pre-supplied an answer, restate it for confirmation rather
than re-asking.

```bash
python -m modules.run_charter --init <results_root>/_agent/RUN_CHARTER.json
```

Fill it in with the owner, get `signed_off.by` + `.date`, then:

```bash
python -m modules.run_charter --validate <charter>
```

Set `RS_RUN_CHARTER=<charter>` in the shell that launches Claude Code.
That arms `.claude/hooks/guard_charter_writes.py` (every Write/Edit and
obvious shell write outside the results root is refused). Instance
pinning, `RS_CACHE_DIR` and `RS_NO_SETTINGS_INHERITANCE=1` come from the
plan (sec.1) - each planned command carries them in its env; a driver
started by hand does not get them. See `/charter` sec.5.

**Owner gates (`confirmed: false`) are stops, never flags to flip.**

## 1. Plan before running

Never hand-write a pipeline command line. `main.py` builds its argparse
from the ENABLED modules only and rejects anything else with exit 2 -
before a single stage runs.

```bash
python -m wildscan.plan --charter <charter> --validate
```

Non-zero means a command would be rejected, or an answer you wrote in the
charter reached no command at all. Fix the charter, not the command.
`--json` emits the plan for a driver to execute.

## 2. Declare the budget, then run

Written before launch, so "is it stuck?" is a lookup: expected duration,
expected memory peak, abort criterion. Model generation runs 40-340 min
per component and peaks near total system commit - watch RAM unasked.

Long runs are **scheduler-owned** (`schtasks` + a CRLF launcher), never a
harness shell: job objects killed a 14.4 h run once. Liveness-test every
monitor the run depends on BEFORE launch - inject a known failure and
prove the detector fires.

## 3. Verify by census, never by exit status

RealityScan exits SUCCESS while doing nothing. After every stage:

```bash
python -m modules.verify --workspace <results_root> --json
```

Exit 0 ok / 1 incomplete / 2 blocked / 3 absent. It reads artifacts on
disk - manifests, fingerprints, reports, export trees - never a driver's
claim about itself, and it checks what a camera count cannot see:

- zones aligned from **different nav or settings** (a census calls this
  healthy);
- components with **no `align_inputs.json`** - provenance unknown, so not
  "done" and not safe to merge;
- **mixed coordinate frames** - never merge across them;
- **measured scale** outside 0.90-1.10.

A `blocked` verdict is a stop-and-report, not something to push past.

## 4. Working files, and what you may delete

Everything the agent produces lives under `<results_root>/_agent/`. It is
the only tree the agent may delete freely. Nothing in the repo, nothing
beside source data.

Snapshot evidence at the moment of observation: `RealityScan.log` is
global and truncated on every instance boot, so the reason line behind a
failure exists only until the next boot.

## Escalate rather than work around

Invariant violation or rollback storm; two monitors disagreeing about one
run; a resource trend projecting past capacity; a result that would revise
an ESTABLISHED finding; anything on the blindness list (GUI state,
georeferencing correctness, seam quality) becoming load-bearing.

## Session end

Findings flushed to `FINDINGS.md` at the moment of discovery, not at the
end. `HANDOFF.md` refreshed with done / running / ranked loose ends /
artifact locations / exact next commands.
