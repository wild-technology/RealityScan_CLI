# docs/history - session records and completed plans

Frozen. Read for provenance; the current state is `HANDOFF.md`, the current
rules are `CLAUDE.md`, the current design is `docs/ARCHITECTURE.md`.

| File | What it was | Moved from |
|---|---|---|
| `AGENT_NATIVE_ROADMAP.md` | The 2026-09-03 plan for the Claude-guided lane. Phases 0-1 landed 2026-09-03; Phases 2-4 landed 2026-09-05 (this consolidation). Owner decisions D1-D6 now live in `docs/DECISIONS.md`. | `docs/` |
| `AUDIT_2026-09-05.md` | The code audit that preceded the consolidation. | written here |
| `code-review-2026-07.md` | First-machine validation of the CLI layer (July 2026). | `docs/` |
| `FRESH_RUN_2026-07-24.md` | NA156 H2023 end-to-end run record. | `docs/` |
| `GOAL_VERIFICATION_SESSION.md` | 2026-08-08 goal re-assessment Q&A. | `docs/` |
| `MERGE_REWORK_RECOMMENDATIONS.md` | The Q1-Q10 merge-stage rework proposal (implemented in `merge_zones.py`). | `docs/` |
| `HANDOFF_2026-07_to_2026-09.md` | Every HANDOFF section older than the current one. | `HANDOFF.md` |

Other relocations on 2026-09-05 (a stale path in an older FINDINGS/HANDOFF
entry resolves through this table):

| Old path | New path |
|---|---|
| `wildscan/` (TUI) | `archive/wildscan_tui/wildscan/` (planner extracted to `modules/run_plan.py`) |
| `wildscan/plan.py`, `python -m wildscan.plan` | `modules/run_plan.py`, `python -m modules.run_plan` (or `python rs.py plan`) |
| `docs/COLMAP_CROSSOVER.md`, `docs/COLMAP_FINDINGS_UNIFIED.md` | `archive/colmap/docs/` |
| `sensorsdb.xml` | `archive/reference_data/sensorsdb.xml` |
| `RS_CLI/Scripts/Probe*.bat`, `NightGrow.bat`, `CalibCellAlign.bat` | `archive/probes/` |
| `testing/run_on2026_{run3,union,wreck}.py`, `run_workbench_night.py`, `run_calib_ladder.py`, `yellow_filter.py` | `archive/campaign_drivers/` |
