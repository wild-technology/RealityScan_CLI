---
name: drive-run
description: Drive this pipeline against a dataset end to end - charter, preflight, plan, run/launch, verify - when the owner says "run this against that data", "process this dive", "align these zones", or asks for an unattended or overnight run. Use BEFORE the first write of any driving session.
disable-model-invocation: true
---

# Driving the pipeline

Contract: `docs/AGENT_OPERATIONS.md` (wins on conflict). Surface: `rs.py`.
`python` = the interpreter with the deps. `<C>` = the charter, `<ws>` =
its `locations.results_root`.

## 0. No writes before a signed, READY charter

`/charter`: six answers from the owner, `python rs.py preflight --charter <C>`
READY, owner sign-off, `RS_RUN_CHARTER` set by the owner. A `missing` line
is a question, never something to infer. Owner gates (`confirmed: false`)
are stops.

## 1. Plan - never hand-write a command line

```bash
python rs.py plan --charter <C> --validate
```

Non-zero = a command `main.py`'s own parser rejects, or a charter answer
that reaches no command. Fix the charter, not the command.

## 2. Run short stages, LAUNCH RealityScan stages

```bash
python rs.py run --charter <C> --stages extract,georeference,preprocess,batch
python rs.py launch --charter <C> --stages align            # also merge, model, export
```

`run` executes headless with `RUN_STATE.json` under `<ws>/_agent/` and stops
at the first failure. It REFUSES RealityScan stages from this shell (mandate
6: a harness job object killed a 14.4 h run). `launch` writes the CRLF
launcher pair and PRINTS three `schtasks` commands: run them exactly (the
permission ask-gate fires - that is intended; `guard_schtasks.py` refuses
any launcher `rs launch` did not write).

## 2a. Start the 30-minute monitor - ALWAYS, for every scheduled run

`launch` also prints a `/loop 30m ...` line. Run it as printed. Each tick
delegates one poll to the `run-monitor` agent (a small read-only worker on
a small model) and reports only its verdict block; the main context pays
for a summary, not for logs. Stop the loop and tell the owner on `failed`,
`stalled`, or a budget line. Manual poll at any time:

```bash
python rs.py status --charter <C>
```

The budget lives in the charter; `status` compares against it.

## 3. Verify by census, never by exit status

```bash
python rs.py verify --workspace <ws> --json
```

Exit 0 ok / 1 incomplete / 2 blocked / 3 absent. `blocked` = stop and quote
every `blocking[]` line verbatim; do not re-run, "fix" or push past it. It
catches what a camera count cannot: zones aligned from different nav or
settings, components without `align_inputs.json`, mixed frames, measured
scale outside 0.90-1.10.

## 4. Working files

Everything the agent produces lives under `<ws>/_agent/` - the only tree it
may delete from. Snapshot `RealityScan.log` at the moment of observation (it
is global and truncated on every boot).

## Escalate rather than work around

Invariant violation or rollback storm; two monitors disagreeing; a resource
trend past capacity; a result that would revise an ESTABLISHED finding; GUI
state, georeferencing correctness or seam quality becoming load-bearing.

## Session end

`/handoff`. Findings go to `FINDINGS.md` at the moment of discovery.
