# ROVScan project documents

`modules.project_workspace.ProjectDocument` is the GUI persistence and lifecycle
API. `.rovscan` files contain UTF-8 JSON only: no executable payload, pickles,
imports, commands, process launcher, or second science planner.

## Schema 1

The root fields are `format: "rovscan"`, `schema: 1`, `id` (UUID),
`expedition` (`NA` plus three ASCII digits), `dive` (`H` plus four ASCII digits),
`root` (absolute native path), `sources` (absolute read-only paths), `layout`,
`created_at`, `updated_at`, `settings`, `stages`, and `outputs`. Unknown root or
structural fields and unsupported versions are rejected. Settings values are
extensible JSON objects. Duplicate JSON keys, nonfinite numbers, excessive
nesting, and files over 16 MiB are rejected.

The fixed layout is `raw/`, `proc/`, `proc/tmp/`, `logs/`, and `metadata/` under
the user-selected root. The pipeline results root is `proc/`; its existing
internal layout is unchanged. Creation describes this layout without making it.
`create_layout()` explicitly creates the empty directories. `save()` creates
only the document parent if needed. Neither method copies source data.

Root/source overlap is refused in both directions, including equal paths.
Paths are checked using resolved junction/symlink destinations and the existing
charter's Windows-aware containment comparison. Relative output paths must be
normalized, slash-separated, and contained in the root. Windows device paths,
streams, reserved names, trailing-dot/space aliases, and traversal are refused.
Existing documents and backups must be regular files without hardlinks.
Filesystem validation is not an OS sandbox against a hostile process changing
junctions during an operation; execution controllers must retain exclusive
ownership of their workspace.

## Public API

```python
from modules.project_workspace import ProjectDocument

# All paths are supplied by the user/controller; this call performs no writes.
project = ProjectDocument.create(expedition, dive, root, sources=[source])
project.set_settings("science", {"min_component_size": 50})
project.approve_settings("science", approved_by=operator_name)
project.create_layout()                  # explicit directory creation
path = project.save()                   # root/<expedition>_<dive>.rovscan
project = ProjectDocument.load(path)     # no directory creation or repairs

attempt_id = project.start_stage("inventory")
# Controller produces an artifact, then records evidence:
project.record_output("inventory", artifact_path, attempt_id=attempt_id)
project.complete_stage("inventory", attempt_id=attempt_id)
project.save()
```

`root` and `path` are `Path` properties (`path` is `None` before Save).
`project_id` and `settings_hash` are strings. `to_dict()` returns a deep copy;
`ProjectDocument(data)` validates and deep-copies an existing mapping.
`resolve_path(path)` validates absolute or root-relative output paths.
`backup_path(path)` returns the sibling `<name>.rovscan.bak` path.

`save(path=None)` supports Save As to a new contained `.rovscan` path and keeps
the project UUID. It refuses unrelated existing destinations and detects changes
since this object last loaded/saved the destination. The controller must serialize
concurrent saves; optimistic change detection is not a cross-process lock.
The module raises `ProjectError` for schema/path/lifecycle errors and
`ProjectConflictError` for conflicting saves. Filesystem failures remain
`OSError`, so the GUI can distinguish access and capacity failures.

## Save, Open, and recovery

Save writes a uniquely named temporary sibling, flushes it, calls `fsync`, and
atomically replaces the destination using `os.replace`. Before replacing a valid
primary, the exact previous bytes are atomically written to `.rovscan.bak`.
Failed writes clean up their own temporary file. No deliverable is removed.
This is filesystem-level atomic replacement, not a claim of guaranteed recovery
from disk/controller hardware failure or network filesystem durability.

Ordinary `load(path)` fails on a malformed/missing primary. Explicit
`load(path, recover_backup=True)` tries the backup only when the primary cannot
be opened as a valid project and sets `recovered_from_backup`. It writes nothing.
Subsequent explicit Save repairs the primary while retaining the valid backup;
corrupt primary bytes are never promoted to the backup. A usable primary always
wins, even with recovery enabled.

Open never changes a running stage to interrupted. After the operator confirms
the old worker is no longer active, call `recover_interrupted(reason=...)`.
It updates memory only and returns the recovered stage names. Save is separate.
This module neither probes nor stops processes.

## Lifecycle and provenance

Stage order is inventory, navigation, georeference, preprocess, batch, align,
merge, model, export. Preprocessing includes explicit image-quality cull review
and spatial density review before batching; the controller owns these science
and review gates. States are pending, running, succeeded, failed, interrupted, invalidated,
and skipped. Start requires all predecessors succeeded or explicitly skipped,
no running stage, and every settings block approved. Failed/interrupted/completed
stages require an explicit restart before another attempt. `skip_stage(stage,
reason)` records an operator decision for a pending/invalidated stage.

`start_stage(stage, required_blocks=None)` returns the new attempt UUID. The
default checks every settings block. A controller may pass an explicit sequence
of required block names to permit early inventory/navigation before later
science approvals. Every named block must exist and carry a current approval.
The controller must specify all blocks actually consumed by that operation;
an empty sequence is not permission to bypass science or review gates.
`record_output(stage, path,
attempt_id=...)`, `complete_stage(stage, attempt_id=...)`, and
`fail_stage(stage, message, attempt_id=...)` reject stale callbacks. Attempts
retain sequential numbers, timestamps, the settings content hash, terminal state,
and message. Stage success is a controller assertion, not proof of successful
science or a conversion of an exit code. The controller uses the existing census
and verification layer before completing a stage. Completion also refuses
recorded outputs that changed or disappeared.

`restart_stage(stage, reason=...)` invalidates that stage and every downstream
stage, marks their output records invalid, and retains every attempt and file.
Pending downstream stages remain pending with an invalidation reason. Restart
is refused while a stage is running. A new attempt must use new output paths;
previous deliverable paths cannot be recorded again. The controller is still
responsible for refusing overwrite before it creates a deliverable.

Outputs record root-relative path, stage, attempt UUID, full SHA-256, byte size,
nanosecond modification time, recording time, and validity. Hashing reuses
`align_fingerprint.sha256_file` and checks file identity/size/time before and
after. Directory outputs must be represented by individual files or a manifest
file. `verify_outputs(stage=None)` reads contents and returns path/stage/attempt/
validity plus status `ok`, `changed`, `missing`, or `unavailable`; it does not edit
the document. Verification compares bytes/hash, so timestamp-only changes do
not invalidate identical contents.

## Settings approval and existing planner adapters

Each named settings block holds `values` and an optional approval containing
`content_hash`, `by`, and `at`. Each approval uses `settings_signature([block])`:
project/path identity plus that block's actual values, independent of other blocks.
`settings_signature(blocks)` accepts unique, order-independent block names; absent
blocks are encoded as null, distinct from present empty values. Approval metadata
and progress are excluded. The global `settings_hash` retains its original algorithm
over identity, roots, sources, layout and all settings values for exact attempt
provenance; historical attempt hashes are never rewritten.
`set_settings(block, values, affects_stage=None)` revokes the edited block's approval
on a semantic change; identical content/key reordering is a no-op. The shared
`settings_stage(block)` determines the earliest invalidated science stage:

| Block | Earliest affected stage |
|---|---|
| `operating`, `budget` | None; preserve completed science, reapprove the edited block |
| `science` | `align` |
| `cameras` | `georeference` |
| A stage name, including `navigation` | That stage |
| Unknown block | `inventory` conservatively |

Edits while running are refused. Approval is an operator acknowledgement, not a
cryptographic signature or identity verification.

The optional `affects_stage` explicitly names the earliest affected stage. This
lets the controller edit camera settings beginning at georeference while
preserving completed inventory/navigation. Omission uses the shared map above.
Unchanged blocks keep valid approvals; lifecycle/status edits do not invalidate
approval. `settings_approved(required_blocks=None)`
supports the same explicit approval subset as `start_stage`.

Legacy approvals migrate in memory only when their hash exactly equals the current
legacy global hash, checked on load and before any settings edit. Migration retains
`by`/`at`, changes no attempts and does not automatically write a project file.
Hashes matching neither the current global proof nor the scoped block signature
are revoked; unaccounted external edits conservatively invalidate from inventory.

New georeference review payloads declare
`settings_scope=["navigation", "cameras", "georeference"]` and a scoped
`settings_hash`, alongside inventory content identity, navigation byte hash and
flight-log byte hashes. Consumers validate these inputs. Legacy georeference
records without `settings_scope` retain the exact current-global-hash guard: a
changed global hash requires rerunning georeferencing, not inferred migration.
Unknown scopes are rejected. This stricter legacy artifact rule is separate from
the proven-current legacy settings-approval migration.

Controller review invalidation follows the same stage map: early inventory/nav/geo
changes invalidate georeference and downstream reviews; preprocess affects quality
onward; batch affects workflow and mask review only. Late science/resource edits
preserve quality, density and mask reviews while affected science stages and the
edited approval still follow their guards.

Reported focused evidence (2026-09-11): 100 workspace tests passed in 3.46 s and
four graph regressions passed (alignment edit preserves geo; budget preserves
science; legacy geo accepts unchanged global proof and rejects changed proof).
A read-only load of `F:/NA171/NA171_H2101.rovscan` retained camera/navigation/operating
approvals, signer/time and attempts, with project file bytes unchanged. This proves
that checked migration case, not automatic approval or a file save. The scope fix
is now reported complete with 152 UI/store passes in 19.37 s and 11 controller
dependency/legacy passes in 8.79 s. The later full Windows snapshot is green;
see VERIFICATION_STATUS.md for its count and subsequent-change exclusions.
The two graph defects found after the historical 2653/1/17 run are not in that count.

`skip_stage("preprocess", ...)` is refused: culling and spatial/density review
are mandatory before batching. The controller additionally validates its
persisted input hashes and ReviewStore selection; project status alone cannot
prove a current cull set or substitute for that runtime gate.

`approve_settings(block, approved_by)` records acknowledgement of the current
content. `settings_approved()` checks every block. No blocks means no declared
settings awaiting approval; the controller must establish all required blocks
before processing. Loading externally edited data clears stale approvals and
retires cached results in memory; active attempts require explicit recovery.

The `pipeline` settings block uses existing charter structure: `stages` and
`answers` (`cli_long` to JSON scalar/null). The `science` block carries existing
charter science values without introducing defaults. `to_charter()` calls
`run_charter.parse_charter` and returns an **unsigned** charter with `proc/` as
results root and declared sources as originals. It grants no process ownership
or agent authorization. `to_session(stages=None)` calls
`run_plan.session_from_charter`, leaves automatic continuation off, and accepts
only existing planner stages. Inventory/navigation are frontend bookkeeping
stages and are never translated to invented science commands. Empty stage lists
stay empty. Controller planning continues through the existing `run_plan` API.

Validation: `python -m pytest testing/test_project_workspace.py -q`. These are
offline tests with temporary fixtures; they never operate on a real source or
project dataset. Do not run the entire existing suite concurrently with another
worker: legacy attach tests share marker/lock names.
