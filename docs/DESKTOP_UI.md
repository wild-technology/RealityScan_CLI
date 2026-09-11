# Native ROVScan desktop

The frontend is in `desktop/`; `app.py` is its production entry point. It requires
Python 3.13+, PySide6, NumPy, rasterio and Matplotlib from the deployment
environment. Packaging/dependency checks belong to `modules/deployment_preflight`
and the installation workflow. No frontend function installs packages, copies
source imagery, invokes RealityScan, starts a shell, or constructs science commands.

`python app.py [project.rovscan]` loads the real
`modules.project_controller.ProjectController`. An incomplete controller
installation produces an error and exit 2, not a simulated operating frontend.
For embedding and tests, instantiate
`desktop.main_window.MainWindow(controller=controller, project=document)`.
`app.main(argv, controller=controller)` also supports explicit injection.

The production entry point automatically opens the installation/storage check
dialog after showing the window. It calls `deployment_preflight.inspect_deployment`
on a background worker. The same dialog is available from Workspace. Checks
are read-only by default; a separate confirmed action enables temporary write
probes inside the selected existing project/cache directories. Sources are
passed as `protected_roots`. Blank growth estimates remain unknown; operators
can enter separate finite, nonnegative project/cache GiB estimates, which become
the existing `storage_policy.StorageDemand` objects. The dialog displays nested
dependency, installation, directory and capacity diagnostics and repair choices;
it does not install software. **Create approved cache** explicitly calls the
controller's `ensure_cache(project)` on a background worker, then reruns the
read-only checks. This action requires current operating approval and an idle
project; proposals never create or approve a cache. Errors leave the check
unready. Write probing remains a separate action. Editing inputs requires a new
check. Execution still rechecks readiness through the controller before work.

## Operator workflow

New/Open/Save/Save As operate on `ProjectDocument`. New and Open do not create
the data layout. Save writes the project/backup only. Save As retains project
identity and obeys containment/conflict checks. Unsaved document changes and
unapplied form drafts have distinct prompts. Backup recovery is offered only
after normal Open fails and requires an explicit decision. A stored running
attempt can be marked interrupted only through the separate recovery action,
which calls `controller.recover_project(project)` on a background worker.
The controller must prove ownership release and persist the recovered state;
a user assertion never substitutes for runtime evidence. A missing API,
exception, unconfirmed result, or still-running attempt keeps restart disabled
and displays the reason. Recovery is available for reopened running documents
and explicit `ownership_unconfirmed` events, not an ordinary active worker.

The phase sidebar follows `ProjectDocument.STAGES`: inventory, navigation,
georeference, preprocess, batch, align, merge, model, export. The right panel
shows phase state, attempt count, approval status, and applied settings. The
bottom panel shows controller progress, bounded logs, measured free disk,
memory, and reserve satisfaction. Unknown measurements remain unknown.

Open calls `controller.load_project_state(project)` on a background reader and
restores its persisted review events without writes. Results from an older
project load are ignored after switching projects. Stored cull selections are
shown as prior explicit decisions; new candidate suggestions still begin
unchecked. Loading review acknowledgements never recovers a stored running
attempt automatically. Read failures keep review gates unconfirmed.

Settings forms use the controller's ordered, typed schema. Numeric values,
booleans, enum choices, paths, and strings have appropriate controls and explicit
Apply. Proposed defaults are displayed but never saved or approved implicitly.
The settings filter finds camera/parameter names without altering hidden values;
repeated help is condensed while every field retains its tooltip.
Approval requires review of applied values plus an operator name. The camera
registry supplies detected Hercules profile defaults and any project overrides;
the UI contains no dive-specific paths or camera numeric presets. In particular,
mount pitch and pitch accuracy are separate fields, as are yaw/roll accuracy.

The controller's `operating` schema block (`operations` is also accepted by the
setup dialog) supplies the owned instance, cache location, and
disk reserve proposal. The controller owns `operations.json` persistence and
any compatibility mapping; the UI never derives instance ownership from a
process list or creates an alternate configuration store. `apply_settings`,
when provided by the controller, is used before the core fallback so the
controller can maintain that store and declare the earliest affected stage.

Inventory displays filename family and optical camera identity together. The
controller's `camera_family_summary` retains separate mount-profile families
even when legacy and WCA imagery shares one optical camera. Its counts include
total, within-window, duplicate, conflicting, unmatched and mask images. The
summary represents all inputs, independently of table filters. Confirming counts/flags requires an
operator name and delegates persistence of the current input inventory hash.
An inclusion/exclusion change requires an explicit reason and goes through
the controller. The UI never infers duplicate identity or timestamps.
Flagged masks can be explicitly excluded; valid paired masks follow their
parent image and cannot be stripped independently.

Source records use `QAbstractTableModel`/`QTableView` virtualization, with flags
shown by default and debounced text filtering. There is no widget per file.
Tests exercise 150,000 records. Full record payloads and filters still consume
memory/CPU; controllers should publish immutable snapshots and avoid repeated
full-inventory events for progress-only updates. Logs keep only 5,000 blocks.

## Culling precedes batching

The preprocessing phase has two review panels. Image screening shows candidate
reasons and controller-supplied tolerance proposals. Selection starts empty:
candidate status never automatically excludes an image. A useful partial scene
is eligible to remain even if most of the image is blue water. The image-quality
engine owns that decision rule and its tests; the frontend displays its evidence.
Operators may adjust tolerances, rerun, explicitly select exclusions, or apply
an empty set to keep all candidates. Edited tolerances invalidate the displayed
assessment for Apply until a new scan returns. Only a selected image is decoded
for its thumbnail, asynchronously; thumbnails never rewrite originals.

Track/density review plots float64 UTM Easting/Northing, with independent kept,
culled, outlier, density and track layers. Hexbin colors show kept images per
display cell. The map has Matplotlib pan/zoom; picking a point selects its
virtualized record and lazy thumbnail, without checking it for exclusion.
Explicit segments or a controller-supplied gap distance prevent track lines
from bridging missing samples. Without continuity evidence, track positions
are shown as points, not an invented continuous line. Missing/nonfinite image
coordinates block confirmation.

Spatial exclusions must be applied explicitly, then density review refreshed
and confirmed for its current assessment hash. `spatial_excluded_paths` restores
the applied replacement set independently of quality exclusions. Editing this
set blocks confirmation until Apply; an empty replacement clears spatial culls.
Changed inventory, cull selections or tolerances revoke
the visible pre-batch gate. Batch and every later phase are disabled until the
current inventory, quality culling and spatial/density review are confirmed.
The controller's `ReviewStore.selection` must independently enforce this with
current input hashes before building batches. UI booleans and project status
are display state, never an alternative runtime authorization mechanism.
`ProjectDocument.skip_stage("preprocess", ...)` is refused.

Start delegates asynchronous work to the controller. Stop offers distinct
`after_step` and `abort_current` requests. A pending stop-after-step request can
be escalated to Abort current operation. A request, error, or terminal status
alone does not release the active flag: restart, project switching, settings
editing and close remain blocked until a terminal event explicitly includes
`ownership_released: true`. The UI does not terminate processes. Restart
invalidates the selected phase/downstream metadata and retains all outputs.

## Injected controller contract

`desktop/controller_api.py` records the protocol. Calls are:

- `subscribe(callback) -> unsubscribe`: callback receives immutable event dicts
  from any thread; the window forwards them through a Qt signal.
- `settings_schema(project) -> list[dict]`: ordered fields described below.
- `load_project_state(project) -> list[dict]`: read-only saved-review events;
  called on a background reader when a document is opened.
- `save_project(project, path=None) -> Path`: validate/claim root ownership, then
  delegate to the document's atomic Save. A missing ownership-aware save method
  fails closed. Save As uses the same boundary.
- `adopt_workspace(project)`: explicit Workspace menu action after a dialog
  identifies the root and UUID and explains that existing files are retained.
- `ensure_cache(project) -> Path`: explicitly create the approved cache after
  validating operating approval, root ownership and containment under `proc/tmp`.
- `recover_project(project) -> dict`: verify runtime release and persist recovered
  attempts. Success requires `ownership_released: true` and no running attempt;
  return `recovered_stages` and an optional actionable `message`. Failure raises
  or returns `ownership_released: false`. The GUI never recovers attempts itself.
- Optional `apply_settings(project, block, values)`: persist effective settings,
  operation configuration, and proper invalidation; otherwise `set_settings`.
- `start(project, stage)`: starts background work. A synchronous exception means
  rejection before acquiring worker/process ownership.
- `stop(mode="after_step" | "abort_current")`: requests cancellation.
- `scan_inventory(project)` and
  `set_inventory_decision(project, path, included, reason)`.
- `confirm_inventory(project, input_inventory_hash, confirmed_by)`.
- `scan_image_quality(project, tolerances=None)` and
  `apply_image_culling(project, assessment_hash, excluded_paths, confirmed_by)`.
- `scan_spatial_review(project, options=None)`,
  `apply_spatial_culling(project, assessment_hash, excluded_paths, confirmed_by)`,
  and `confirm_spatial_review(project, assessment_hash, confirmed_by)`.

The controller owns document lifecycle mutation during execution, census-based
completion, source inventory hashing, duplicate/window rules, persisted review
decisions, preflight, async workers and runtime ownership. It must enforce a
root ownership marker and explicit adoption policy before creating a layout,
saving a new identity into an occupied root, or starting work; the GUI does not
silently adopt existing raw/proc namespaces. Controllers should serialize
project mutation/saving and emit terminal/released state only after cleanup.

Schema fields are `{block, key, label, type, default?, min?, max?, required?,
help?, choices?, path_kind?}`. `key` may be dotted for nested values. Types are
`str`, `int`/`integer`, `float`/`number`, `bool`, `choice`/`enum`, and `path`.
Choice entries can be scalars, `[label, value]` pairs, or `{label, value}`
objects. `path_kind: "file"` selects a file chooser; other paths use a directory
chooser. Fields and blocks retain controller order. Undeclared stored values
are preserved, not silently dropped when an editable field is applied.

Events may include `project_id`; events for another open project are ignored.
All kinds may include `message` for the log. Recognized kinds:

| Kind | Payload |
|---|---|
| `log`, `error` | `message`; errors do not imply released ownership |
| `progress` | `stage`, `current`, `total`, `message`; unknown totals show indeterminate progress |
| `resources` | `free_bytes`, `reserve_bytes`, `memory_bytes` |
| `state` | `stage`, `state`, `ownership_released`; `quality_confirmed` also supplies the newly saved `assessment_hash`; terminal states include succeeded, failed, interrupted, cancelled, stopped, completed, idle, review_ready, quality_confirmed, selection_confirmed |
| `inventory`, `navigation` | `items: [{path, family, camera, kind, size_bytes, included, exception, reason?}]`; optional `camera_family_summary`, `camera_summary`, `input_inventory_hash`, `inventory_confirmed` |
| `image_quality` | `assessment_hash`, `candidates: [{path, reason, score}]`, `tolerances`, optional `tolerance_schema`, `summary`, `culling_confirmed` |
| `spatial_review` | `assessment_hash`, `points: [{path,x,y,camera,time,excluded,outlier,reason}]`, `spatial_excluded_paths`, `epsg`, `track`, optional `track_segments`/`track_gap_distance`, `confirmed` |

`camera_family_summary` is a list of `{family,camera,total,in_window,
identical_duplicates,conflicting_names,unmatched,masks}`. It takes precedence
over the optical-only `camera_summary`; legacy `duplicates`/`conflicts` keys
remain display-compatible. The hash covers the controller's canonical inventory and
decisions. `tolerance_schema` is a list of `{key,label,type?,min?,max?,help?}` for
the engine-supplied scalar tolerance values. `track` permits `None`/nonfinite
positions as breaks; explicit `track_segments` must already encode temporal
gaps. UTM coordinates must never be converted to float32 for this UI.

## Float-map preview and verification

Setup stays open across New/Open and applied settings changes, rebinding to the
current project, installation, cache and reserve. Previous readiness results are
cleared; late check/cache callbacks from an earlier context are ignored. Recheck
readiness for the new selection. Browsing or editing setup fields also invalidates
previous results.

The right panel describes the sidebar's selected phase, independently of the
settings block being edited. It obtains required blocks exclusively from
`controller.required_settings_blocks(stage)` and displays their applied values
using schema labels and typed choice labels. Inventory and Preprocess have review
gates; approvals for future processing phases are not listed as their blockers.

New schema defaults shown alongside previously saved settings remain proposals:
Apply is required before the displayed block can be approved. Ownership-uncertain
controller rejections retain the active/recovery state and keep Restart disabled.
This also applies when a short mutation fails on a background worker.

Settings approvals are bound to individual blocks. Saving unchanged values
preserves approvals and reviews. The frontend and controller use the shared
`settings_stage` dependency map: operating/budget edits require fresh execution
approval but preserve completed science; alignment/science and later-stage edits
preserve image culling and mask decisions. Batch edits invalidate the mask gate;
inventory, navigation, camera, georeference and preprocessing edits invalidate
image reviews. Georeference provenance binds its navigation/camera/georeference
settings only. Older records with a global settings hash require an exact global
match, otherwise a one-time georeferencing rerun is necessary.

Navigation assessments display row counts, UTC coverage, CRS, pose coverage,
gaps, depth range and limitations above the exception list. Image match exceptions
use the current inventory's inclusion and camera family, allowing one reviewed
bulk exclusion. Unknown paths cannot be toggled. Invalid navigation/density review
events remove density readiness while retaining a still-valid quality decision.
New inventory and explicit preprocessing restart retire obsolete review tokens.

Inventory supports extended row selection and **Exclude selected flagged files**.
Per-file camera assignment, filename mapping/renaming, and timestamp correction
are not supported in the current frontend. Unknown camera/time filename formats
stay flagged and cannot be included: explicitly exclude them with a reason, or
provide a corrected separate delivery and review it. Supported camera families
continue to use the deterministic registry. Legacy exception messages promising
assignment/correction are clarified only for display, including tooltips/search;
their stored evidence, counts, flags and inclusion decisions remain unchanged.
The UI never automatically excludes unknown images or rewrites their originals.

One reason covers the selected included, flagged image/mask rows. The UI calls
`controller.set_inventory_decisions(project, paths, False, reason)` once on a
worker thread. The controller validates the complete selection before saving it;
success requires renewed inventory/quality/density confirmation. Native inventory
scans retire existing source masks with the persisted `ignore_existing` policy;
older projects must rescan before georeference/quality. This excludes mask records
without deleting source files and survives subsequent inclusion edits/rescans.

After Batch succeeds, the **ROV masks** tab presents an optional temporal hardware
masking decision before Align. Native projects support **copy-layout batching
only**: the typed schema exposes no pool option, and the controller refuses pool
layout before copying. The separate legacy pool workflow is unchanged.
**Generate / rerun masks** calls
`scan_occlusion_masks(project, options)` asynchronously through the controller;
sample counts and tolerances use typed controls from its `parameter_schema`.
The UI checks that proposed values fit the supplied schema and can be represented
without rounding or clamping. An inconsistent schema disables Generate/Apply and
shows the offending field; it never silently substitutes a different proposal.
Generation does not approve masks. Select a camera/dimensions/time group to view
the first sampled original and the **Temporal review: first / middle / last**
contact sheet. Its rows pair sampled originals with red candidate exclusions;
it is not an overlay of only the first frame. **Open enlarged temporal review**
opens that same evidence in a read-only scrolling viewer with Fit, 100%, and
10–400% zoom. Opening, scrolling, or zooming never checks groups or approves masks.
Full-resolution decoding runs asynchronously with the same project/source path
containment and unchanged Qt allocation guard. Zoom paints the visible canvas
without allocating enlarged copies of the image. Decode/refusal errors are shown
inside the viewer; changing group/project or invalidating the review closes it.
Only selected previews are loaded; the groups table uses model/view rows. The engine assigns
stable group identities and the controller distributes each image's mask
consistently across overlapping batches.
Group status and blocker columns explain abstentions such as insufficient motion,
detail, time span or samples. The summary distinguishes supported candidates from
masked/unmasked groups; nothing is masked before Apply. Supported generated
groups start unchecked. Checking a group's **Use** box explicitly selects it;
selecting a row to preview it does not. Apply covers only checked groups, while
unchecked and blocked groups remain unmasked. Blocked groups cannot be checked.
The confirmation states selected and uncovered group counts. With no selection,
Apply is disabled and the panel directs the operator to select groups or Skip.
With no supported
candidate, Apply is disabled and the operator can adjust/rerun or explicitly Skip.
When supplied, canonical `start_unix` and `block_seconds` display each group's UTC
interval with an exclusive end. The tooltip retains the complete stable group
identifier. Older records without valid interval fields retain a shortened ID
and full-value tooltip; no timestamp is inferred from a filename or hash.

**Apply reviewed masks** calls `apply_occlusion_masks(project, assessment_hash,
confirmed_by, accepted_block_ids=[...])` after explicit review. The UI always
passes an explicit list. On reopening an applied review, checked groups and
masked/unmasked counts come from canonical `mappings[].group_id`, not from the
list of all generated candidates. Changing an applied subset requires a new
Generate/rerun and explicit selection; a new proposal starts unchecked.
Approved excluded pixels are ignored during
both alignment and meshing. **Skip optional masks** calls
`skip_occlusion_masks(project, reason, confirmed_by)` with a nonblank reason and
operator. The UI enables Align only after a current `occlusion_masks` event
confirms an applied or skipped decision. It never treats a successful API return
or generated candidates as approval. Changing generation parameters, rebatching,
or changing upstream image/review inputs removes readiness. No new pipeline stage
is introduced; preprocessing culling/density gates still precede Batch.
After a prior Apply, Generate/rerun creates a new proposal for explicit review.
The helper replaces only previously validated, receipt-owned mask copies during
the subsequent Apply, after the new master masks are ready. Unowned source masks
are refused. A failed Skip clears visible readiness until a current controller
confirmation arrives; it cannot leave the previous Apply appearing ready.

The event uses `assessment_hash`, `batch_fingerprint`, `decision`, `confirmed`,
`parameters`, `parameter_schema`, `mappings`, and `groups`. Each group supplies `group_id`,
`camera`, `family`, `status`, `blockers`, counts, and `previews` with
`image_path`/`overlay_path`. The supported detector status is
`candidate_review_required` with no blockers; unknown statuses fail closed.

Backend operation errors appear in the log pane and status display; synchronous
action failures also show a warning dialog. Project event-log append failures
produce a persistent banner and one prominent log-pane entry per distinct error
per project. Normal progress does not clear that warning: the controller currently
provides no affirmative log-recovery event. Settings proposals can be edited or
left unapproved, but there is no separate action to revoke an existing settings
approval without changing that block's values.
Hydration emits this event after inventory/quality/spatial state. ReviewStore
persists `occlusion_review`; `require_occlusion_review(current_batch_fingerprint)`
refuses a missing, stale, unapproved or tampered decision. The controller computes
the current batch/image fingerprint and verifies generated mask artifacts before
Apply and alignment. UI previews never write or normalize source images.

Open TIFF Map uses rasterio read mode and a bounded nearest-neighbor preview,
at most 1,024 pixels on either side. Original dtype, raster values and nodata
remain untouched. Nodata/NaN/infinity are transparent. The preview shows raster
dimensions, band/dtype, CRS, bounds, nodata and units, plus editable display
range and a color legend. Range changes affect only an RGBA display copy.
It handles constant/all-nodata rasters and large finite float64 values. Preview
range is the sampled preview range, not an asserted full-resolution census.

Run only scoped offline checks while other agents are testing:

```text
python -m pytest testing/test_occlusion_review.py testing/test_project_review_gates.py testing/test_desktop_ui.py -q
```

Tests use a fake controller, offscreen Qt, temporary JSON/raster/image fixtures,
150k synthetic records, failed atomic saves, stale callbacks, source escapes,
approval changes, cancellation ownership, culling gates and float64 map checks.
An offscreen screenshot is rendered and visually reviewed; Windows Segoe UI is
loaded in-process if Qt's offscreen font database omits system fonts. No fonts
or settings are installed system-wide. General test acceptance is separate from
any particular expedition/dive's runtime evidence.
