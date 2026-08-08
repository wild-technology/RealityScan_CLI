# RUN CHARTER — <campaign> / <dive> / <date>

Filled by the driving agent at drive-start, SIGNED OFF by the owner
before the first write. Lives in the agent workspace. See
docs/AGENT_OPERATIONS.md for the contract this instantiates.

## Declared locations (owner-confirmed, not inferred)
- ORIGINALS (read-only from this moment): <path>
- NAV / flight log (read-only): <path>
- RESULTS ROOT (all outputs; created if missing): <path>
- AGENT WORKSPACE (scratch/evidence/charter): <results_root>/_agent/
- PROTECTED — never touched, never "cleaned", never reorganized:
  - <path> — <why>
- Hard-enforcement deny list location (if configured): <path or "none">

## Ownership
- Agent RealityScan instance: <name>   Cache: <path>
- User-owned instances/processes (never touched): <names/PIDs or "none">
- Scheduler task names the agent may create/run: <names>

## Budget declaration (before any long run)
- Expected duration: <h>   Expected memory peak: <GB> (envelope: 34k cams
  = 262 GB on 192 GB box, C-20260802-01)   Expected disk delta: <GB>
  (free now: <GB>)
- Abort criteria: <disk floor / silence window / memory line>
- Monitors armed (and liveness-tested): <list>

## Science parameters (explicit, no stored defaults)
- Coordinate frame: <utm zone | local:1 Euclidean> (source: <log name>)
- Alignment settings XML: <path> (sha256 <hash>)
- Priors accuracies: pos <m> / ori <deg>   min_component_size: <n>
- Merge: ladder <..> loss_tolerance <..> ceiling <..> pair_gate <..>
- Owner gates in play: <features.json confirmed? etc.>

## Sign-off
- Owner approved: <date/quote>          Agent session: <id/date>
