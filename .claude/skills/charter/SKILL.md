---
name: charter
description: Drive-start intake with the owner - ask the six charter questions, scaffold RUN_CHARTER.json, fill it, get sign-off in chat, validate it, and tell the owner how to arm it. Owner-invoked only (/charter); it precedes the first write of any driving session.
disable-model-invocation: true
---

# Charter a run

The charter is the contract every later write is checked against
(`docs/AGENT_OPERATIONS.md` sec.0; `/drive-run` sec.0 is the summary).
This skill is the intake itself. `python` = the interpreter with the deps
(CLAUDE.md "Environment"; `py -3.13` where the launcher exists).

## 1. Ask - never infer

Ask the owner, in chat, one block, all six. A directory listing is not an
answer (wizard-prefill incident 2026-08-08: inferred locations crossed
campaigns). An answer already in the tasking is RESTATED for a yes.

1. ORIGINALS - the imagery tree(s). Read-only from this moment.
2. NAV - flight log / datatables. Read-only.
3. OUTPUTS - the results root. Created if missing; everything lands under it.
4. PROTECTED - in-progress transfers, other campaigns, GUI project dirs,
   prior deliverables. Each with a WHY.
5. DISK BUDGET - free now, expected peak, expected delta, memory line,
   abort criterion. Offer what you can read (`/status` sec.6 command).
6. INSTANCE OWNERSHIP - the agent's RealityScan instance name and cache
   dir; every instance/process that is the owner's (never touched).

Before sign-off you may READ (confirm a named path exists, count files).
You may not create, copy, hardlink, or write anything else.

## 2. Scaffold - the one write allowed before sign-off

```bash
python -m modules.run_charter --init <results_root>/_agent/RUN_CHARTER.json
```

Creates `<results_root>/_agent/` and the template (exit 0). An existing
file is refused (exit 2): read it, tell the owner, ask - never overwrite a
charter you did not write this session.

## 3. Fill it with the owner

Schema 1 (`modules/run_charter.py` `TEMPLATE`), question -> key:

| Answer | Key |
|---|---|
| campaign / dive | `campaign`, `dive` |
| 1 originals, 2 nav | `locations.originals[]`, `locations.nav[]` |
| 3 outputs | `locations.results_root`; `locations.agent_workspace` = `<results_root>/_agent` (must be inside it) |
| 4 protected | `locations.protected[]` of `{"path", "why"}` |
| 5 budget | `budget.expected_hours`, `memory_peak_gb`, `disk_delta_gb`, `free_disk_gb_now`, `abort_criteria` |
| 6 ownership | `ownership.rs_instance`, `rs_cache_dir`, `user_instances[]` |
| science | `science.frame`, `align_settings_xml`, `min_component_size`, `notes` |
| run plan | `pipeline.stages[]`, `pipeline.answers{}` = `cli_long -> value` as `main.py` accepts them; `wildscan.plan` reads THIS, nothing from `rs_settings.json` |

Every science argument goes in explicitly (stored-options incident
2026-07-29). Replace every `<...>`; the untouched template fails validation
on purpose. **Sign-off** is the owner's words in chat - ask "Sign off this
charter? Name and date." and put the reply verbatim in `signed_off.by`,
`.date`, `.quote`. The agent never writes its own name there.

## 4. Validate, then spot-check the guard

```bash
python -m modules.run_charter --validate <charter>
```

Exit 0 = valid and signed. Exit 1 = valid, NOT signed: still no writes.
Exit 2 = invalid; the message names the key. Then prove the rules bite:

```bash
python -m modules.run_charter --check <charter> --path <one originals path>
python -m modules.run_charter --check <charter> --instance <one user instance>
```

Both print `REFUSED` (exit 2); `--path <results_root>/x` prints `ALLOWED`.

## 5. Tell the owner how to arm it

The owner sets `RS_RUN_CHARTER=<absolute charter path>` in the shell that
launches Claude Code (an `export` inside a harness Bash call does not
survive to the next call). Say what that arms, and what it does not:

- ARMED: `.claude/hooks/guard_charter_writes.py` refuses every Write/Edit
  and the obvious shell writes (`>`, `rm`, `mv`, `cp`, `Set-Content`, ...)
  touching originals, nav, a protected path, or anything outside the
  results root and the repo. A set-but-broken charter blocks ALL writes.
- ARMED through the plan: `python -m wildscan.plan --charter <charter>
  --validate` stamps every command with `RS_INSTANCE`, `RS_CACHE_DIR`,
  `RS_NO_SETTINGS_INHERITANCE=1`, `RS_RUN_CHARTER` - a child launched from
  the plan is pinned to the charter's instance and refuses stored answers.
- NOT armed: no driver calls `guard_write` / `guard_instance` itself yet
  (HANDOFF 2026-08-31 loose end 2). A driver started by hand, outside the
  plan, needs `RS_INSTANCE` and `RS_NO_SETTINGS_INHERITANCE=1` set itself.
- Optional per-campaign `permissions.deny` list, kept in the campaign root
  (`docs/AGENT_OPERATIONS.md` sec.7).

Next: `/drive-run` sec.1 (plan) - never a hand-written command line.

## This skill must NEVER

- write anything but the charter file before sign-off, or any output
  before `--validate` exits 0;
- fill `signed_off` itself, or treat exit 1 as "signed";
- flip any `confirmed: false` (features.json, charter) - an owner gate is
  a stop;
- guess a path from a listing, or reuse a previous campaign's charter;
- boot, query or delegate to RealityScan - intake is reads only;
- touch another session's charter, `rs_settings.json`, or instance.
