---
name: finish-model
description: Finish a mesh that already exists in a running RealityScan instance - texture, simplify, unwrap, reproject, export, save - by ATTACHING to that instance instead of booting one. Use when asked to finish/texture/export a model in an open GUI or Epic-Launcher session, or to work with a scene the pipeline does not own. Also covers normal pipeline model generation.
disable-model-invocation: true
---

# Finishing a model in a running instance

`python` = the interpreter with the deps (CLAUDE.md "Environment";
`py -3.13` where the launcher exists).

## Pick the right path first

- **The pipeline owns the instance and must compute the mesh** -> the
  normal path, `GenerateModel` via `run_models.py`:
  ```bash
  python run_models.py --workspace <ws>
  ```
  On the charter lane: `python rs.py launch --charter <C> --stages model`
  (scheduler-owned; `rs run` refuses RealityScan stages from an agent shell).
  ```bash
  ```
- **The mesh ALREADY exists in a running instance** (a GUI or
  Epic-Launcher session) -> `ModelToFinal` via `finish_model.py`:
  ```bash
  python finish_model.py --instance "*" --outdir <exports> --name <comp> --source-model <model>
  ```
  Omit `--source-model` only when the target instance has a model
  actively selected (live gate B9, 2026-08-07).

## Why ModelToFinal is the one exception to the `:run` boot pattern

It **deliberately does NOT call `startRealityScan.bat`**. That script
issues `-newScene -deleteAutosave` when `-getStatus` finds an instance
already running - which would destroy the very scene it was asked to
finish.

Consequences, all deliberate:

- It delegates to `%RS_TARGET%`, not `%RS_INSTANCE%`.
- It accepts `*` as the instance. `*` means "first available instance"
  and is the ONLY way to reach a GUI or Epic-Launcher RealityScan: those
  have no `-setInstanceName` and answer no named lookup. `*` is ambiguous
  once two instances run - use it only to attach to a single interactive
  session.
- It gates on the `lastError:` and `rev:` fields of `-getStatus`, not on
  `errors_<instance>.txt`. That marker file only exists for an instance
  booted by `startRealityScan.bat`, so a GUI instance never writes one.
- `rev:` tracks scene MUTATIONS, not operations.

## Before attaching

**Own your instance.** A cross-session incident (2026-07-28) had one
session running on `RS1` while believing it was isolated on `RS2`, and it
overwrote another session's `rs_settings.json`. Resolve `RS_INSTANCE`
explicitly, confirm no other instance holds that name, and never write
another session's settings.

Never kill, quit, or delegate to a process the agent did not start.
Identify by PID + command line first - a query that matches its own
search string is not evidence. On a charter-driven lane:

```bash
python rs.py charter check <charter> --instance <name>
```

## Deliverables are never overwritten

A name collision in `final/` or `exports/` is a **stop-and-ask**, not an
overwrite (the ModelToFinal silent-overwrite finding, 2026-08-08).

## Verify

```bash
python rs.py verify --workspace <ws> --require model,export --json
```

Exit status from RealityScan proves nothing - count what landed on disk.

## Reference

`docs/rs-reference/10-reconstruction-texturing-export.md` for the model
lifecycle and export profiles; `01-cli-fundamentals.md` for the
instance/attach contract; `12-failure-modes-and-race-conditions.md` when
something hangs or succeeds without doing anything.
