---
name: charter
description: Drive-start intake with the owner - the six charter questions, RUN_CHARTER.json, preflight until READY, owner sign-off. Owner-invoked only (/charter); it precedes the first write of any driving session.
disable-model-invocation: true
---

# Charter a run

The charter is the contract every later write is checked against
(`docs/AGENT_OPERATIONS.md` sec.0). `python` = the interpreter with the deps.

## 1. ASK - one block, all six, never infer

1. ORIGINALS (imagery tree; read-only from now)   2. NAV (flight log / datatables; read-only)
3. OUTPUTS (results root)   4. PROTECTED (paths + WHY)   5. BUDGET (disk free, peak, delta, memory, abort criterion)
6. INSTANCE OWNERSHIP (agent's RealityScan instance + cache dir; the owner's instances)

A directory listing is not an answer. An answer already in the tasking is
RESTATED for a yes. Before sign-off you may READ (does a path exist, how many
files); you may not create, copy, hardlink or write anything but step 2.

## 2. SCAFFOLD - the one write allowed before sign-off

```bash
python rs.py charter init <results_root>/_agent/RUN_CHARTER.json
```

Exit 2 = a charter already exists: read it, tell the owner, ask. Never
overwrite a charter you did not write this session.

## 3. FILL it with the owner (schema 1)

| Answer | Key |
|---|---|
| campaign / dive | `campaign`, `dive` |
| 1, 2 | `locations.originals[]`, `locations.nav[]` |
| 3 | `locations.results_root`; `locations.agent_workspace` = `<results_root>/_agent` |
| 4 | `locations.protected[]` of `{"path","why"}` |
| 5 | `budget.expected_hours`, `memory_peak_gb`, `disk_delta_gb`, `free_disk_gb_now`, `abort_criteria` |
| 6 | `ownership.rs_instance`, `rs_cache_dir`, `user_instances[]` |
| science | `science.frame` (`utm:54N` or `local_euclidean`), `align_settings_xml`, `min_component_size` |
| run | `pipeline.stages[]`, `pipeline.answers{}` = `cli_long -> value` exactly as `main.py --help` names them |

Every science argument explicit; the untouched template fails on purpose.

## 4. PREFLIGHT until READY

```bash
python rs.py preflight --charter <C>
```

Every `ASK THE OWNER` line is a question for the owner - camera prefixes the
registry does not know, a required `main.py` answer, a path that does not
exist, a frame that disagrees with the log. Ask, put the answer in the
charter, run again. Never fill one in yourself. `BLOCKING` lines are
stop-and-report.

## 5. SIGN-OFF

Ask "Sign off this charter? Name and date." Put the reply verbatim into
`signed_off.by / .date / .quote`. Then `python rs.py charter validate <C>`
must exit 0 (1 = unsigned, still no writes; 2 = invalid, the message names
the key).

## 6. ARM

The owner sets `RS_RUN_CHARTER=<absolute C>` in the shell that launches
Claude Code (an `export` inside a harness Bash call does not survive). That
arms `.claude/hooks/guard_charter_writes.py` (refuses writes outside the
results root and the repo, and any write into originals/nav/protected),
pins `RS_INSTANCE`/`RS_CACHE_DIR` and sets `RS_NO_SETTINGS_INHERITANCE` on
every planned command. Next: `/drive-run`.

## This skill must NEVER

- write anything but the charter file before sign-off;
- fill `signed_off` itself, or treat validate exit 1 as signed;
- answer a preflight question from a listing, a previous campaign or a guess;
- flip any `confirmed: false`; boot, query or delegate to RealityScan;
- touch another session's charter, `rs_settings.json` or instance.
