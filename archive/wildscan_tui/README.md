# WildScan TUI (archived 2026-09-05, kept functional)

The interactive Textual console over the pipeline. Archived because the
operating model is now the Claude-guided lane (`rs.py`, `.claude/skills`);
kept because it works and may come back as a front end over the same
oracles (`modules.verify`, `modules.run_plan`, `RUN_STATE.json`).

What lives here and what does not:

| Here (UI only) | Live in the repo (the TUI imports them) |
|---|---|
| `wildscan/app.py` screens, `branding.py`, `runner.py` (subprocess pump), `__main__.py` | the planner `modules/run_plan.py` (former `session.py` + `plan.py`) |
| `wildscan/session.py`, `plan.py`, `workspace.py` are re-export shims | the census `modules/workspace_census.py` |
| `requirements.txt` (`textual`, `rich`) | every driver the TUI launches |

Run (Windows for the RealityScan stages; anywhere for inspection):

```
python -m pip install -r archive/wildscan_tui/wildscan/requirements.txt
python archive/wildscan_tui/run_wildscan.py <workspace>
```

Smoke test: `testing/test_run_plan_session.py::test_portal_walks_session_to_stage_pick`
(skipped when `textual` is not installed). No other test touches this tree.
Do not add logic here; extend the live modules and let the shims carry it.
