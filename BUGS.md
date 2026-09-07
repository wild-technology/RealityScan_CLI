# BUGS.md — faults found and fixed, 2026-09-06

Branch `na165-h2060-directives`. Raised while implementing the owner directives
for the NA165 / H2060 run and audited beforehand by a 19-agent read-only pass
over the repo (9 subsystem investigations, 9 adversarial verifications, 1
completeness critic; 3.4 M tokens, 1,129 tool calls, 0 errors).

Every fault below is one of two kinds, and the distinction is the point:

* **Fail-open** — the run continues, exits 0, and produces something that
  looks like a result. These are the expensive ones; each cost GPU-hours or
  shipped a wrong deliverable at least once already.
* **Silent shadow** — a value the operator set is quietly replaced by another,
  and nothing says so.

Test baseline: 727 passed / 1 skipped before, **746 passed / 1 skipped after**
(+19 new guards). The 11 remaining failures are a pre-existing environment
artifact of this shell — `test_attach_mode.py` and `test_harvest_guard.py`
raise `OSError [WinError 6] The handle is invalid` inside
`subprocess.Popen._make_inheritable` on **stdin**, because the harness runs
with no console stdin. They fail identically on a pristine checkout, involve no
repo logic, and pass in a real terminal.

---

## B1 — A missing flight log warned, then spent the whole GPU budget anyway

**Kind:** fail-open. **Severity:** blocker.
**Sites:** `modules/realityscan_interface/realityscan_interface.py:345`,
`main.py` (no preflight at all), `modules/flight_logs.py` (no strict lookup).

`__align_zone` treated an absent trajectory as a `logger.warning` and set
`flight_log_path = ""`. The zone then aligned to completion — hours of GPU —
and returned success. The component it produced has no georeferencing priors,
no metric scale and no placement, and is indistinguishable in the logs from a
good one until the merge's scale gate rejects it much later, or fails to.

Only one stage refused without a log (`BatchDirectory.validate_parameters`),
and it is bypassed the moment batching is skipped or already done — i.e. on
exactly the align-only resume where the refusal matters most.

**Why the obvious fix was wrong.** Adding the check to
`RealityScanAlignment.validate_parameters` is *not* fail-fast: `main.py` calls
`validate_parameters()` inside the module loop, immediately before each module
runs. On this dive that check would fire only after Georeference and Preprocess
had processed 21,023 frames and the batcher had copied ~25,000 files.

**Fix.** A real preflight (`main.preflight_flight_log`) before the loop, plus
`flight_logs.require_flight_log`. Existence is not the test — three states are
all "no usable flight log" and all three have shipped:

| state | why it passes an existence check | what it does |
|---|---|---|
| absent | — | aligns with no priors |
| header-only, 0 rows | the file exists | reachable production state (pool layout writes one when no row resolves); imports cleanly, georeferences nothing |
| wrong column count | the file exists and has rows | RealityScan **silently drops** trailing columns — the accuracy and `FocalLength` priors — rather than erroring |

The requirement is also conditional on the enabled stages, because the
georeference stage is what *creates* the flight log: with it enabled the
preflight requires the **nav source**; without it, an actual log.
`RS_ALLOW_NO_FLIGHT_LOG=1` is the documented escape hatch and warns loudly.

**Found on this dive.** The only flight log in the folder was the previous
run's `flight_log_scalegate_2L_UTM.txt`: 3,870 rows covering **3,580 of 21,023
frames (17.0%)**, **13 columns** against the 14-column `{D1F2A3B4-…}` format
the params XML names, and image paths under a `C:\…\Desktop\…` tree that no
longer exists. Every one of the three failure modes above, in one file.

---

## B2 — Zone sizing resolved from four disagreeing places

**Kind:** silent shadow. **Severity:** high.
**Sites:** `modules/image_batcher/batch_directory.py` — `run()`, the
interactive reject branch, `validate_parameters`, `_stored_default`.

The owner asked for zone sizes "baked into code as default". Four separate
resolutions existed:

1. `run()` prompted for min and max but read **target** straight off the
   Parameter — so target skipped the stored-answer layer the other two went
   through.
2. The `(r)eject and set new params` branch prompted for target only and then
   **derived** `min = target*0.2`, `max = target*1.5`, discarding both the
   operator's values and the code defaults. At target 6500 that silently
   becomes min 1300 / max 9750 against a declared 4000/8000 policy, and it
   bypassed every invariant.
3. `validate_parameters` read the Parameters a fourth time.
4. `_stored_default` let `rs_settings.json [batch]` beat the code default
   permanently and without comment — `_prompt_int` persists its resolved value
   on **every** run including unattended ones, so one run freezes a value
   forever. This is the recorded incident where a stored `min_zone_size=300`
   from NA173 beat `--b_min 2000`, and where `max_zone_size=8000` produced a
   7,842-image zone against a 6,000 cap.

**Fix.** One function, `_resolve_zone_sizing()`, called by every consumer
including the reject branch; `_coerce_zone_sizing()` for the invariants; and a
warning whenever a stored answer shadows a code default. Precedence is
unchanged and now stated once: **CLI > stored answer > code default**.

---

## B3 — `min 5000 / max 8000` creates a permanent dead band

**Kind:** fail-open. **Severity:** high.
**Sites:** `batch_directory.py:568` (split), `:598` (merge), `:1444` (derive).

The requested numbers are structurally unsatisfiable. A zone splits only when
`zone_size > max_size`, and an undersized zone merges only when
`combined_size <= max_size`. Whenever `2 * min > max`, a pair of sub-minimum
zones can **neither merge** (their sum exceeds max) **nor split** (each is
under max). They stay below the floor permanently, and nothing reports it.

* requested: 2 × 5000 = 10,000 > 8,000 → **dead band 2,000 wide**
* historical: 2 × 1000 = 2,000 < 4,000 → no band

Not hypothetical here: `initial_k = ceil(21023 / 6500) = 4`, so base zones
average 5,256 — **5% above a 5,000 floor**. Density-aware k-means on a real ROV
track is not balanced, so landing under it was likely.

Nothing validated `min <= target <= max` anywhere; `validate_parameters`
checked only `target < 100`.

**Fix.** Min lowered to **4000** (2 × 4000 = 8000 = max, the boundary that
closes the band), `validate_parameters` refuses an inconsistent triple with the
arithmetic spelled out, and `_coerce_zone_sizing` repairs values arriving later.

---

## B4 — `max_zone_size` caps the base zone, not the delivered one

**Kind:** silent shadow. **Severity:** high.
**Sites:** `batch_directory.py:568` (cap), `:727` (donation, uncapped).

Overlap donation runs **after** the max cap and is never re-capped. At the
stored 20% overlap an 8,000 base zone **delivers 9,600 images**, and nothing
printed the delivered figure. This is exactly how a 7,842-image zone
(6,535 base + 1,307 donated) shipped against a 6,000 cap.

It matters more than usual now: the largest zone ever aligned on this box is
4,124 images, so every memory figure must be read against 9,600, not 8,000.

**Fix.** Delivered per-zone sizes are computed, logged, returned in the stage
output, and warned about when they exceed `max_zone_size`; sub-minimum zones
are named individually.

---

## B5 — A zone with zero registered cameras reported success

**Kind:** fail-open. **Severity:** blocker.
**Site:** `realityscan_interface.py` (`__align_zone`, success path).

A zone that exported component files but produced **no manifests** returned
`{'Success': True, 'Registered Cameras': 0}`. FINDINGS records a 4,244-image
zone that aligned to zero components with a clean exit and normal shutdown —
19% of a dive registered nothing and the run said so nowhere. The merge side
already holds the correct invariant (it refuses to score an empty peel); the
align side had no equivalent.

This is the guard that had to exist **before** zone sizes went up, because
bigger zones make the failure more likely and it is the one thing the align
path could not detect.

**Fix.** Zero registered cameras fails the zone, naming the cause — a component
with no manifest cannot be attributed, scaled or merged. Also: a warning when
the identity loop hits its 20-lap ceiling, which is not hypothetical either —
this dive's previous delivery was exactly **20 components**, the literal value
of `MAX_IDENTITY_COMPONENTS`, and nothing logged whether it was truncated.

---

## B6 — `RS_PROJECT_CRS` leaked between zones

**Kind:** fail-open. **Severity:** high.
**Site:** `realityscan_interface.py:391` (set), never popped.

Set only when a zone's flight log carries a UTM tag, never unset, and zones
align sequentially in one process — so every zone after the first inherited the
previous zone's EPSG, and `AlignZone.bat:135` then actively pinned it with
`-setProjectCoordinateSystem` / `-setOutputCoordinateSystem`. It leaks in from
the parent shell too.

A wrong-but-authoritative CRS is worse than an absent one: the geometry is
correct while every export declares the wrong frame. **This dive's own
deliverables carry the defect** — H2060 exports are labelled 55N for a 2S dive.

**Fix.** `os.environ.pop('RS_PROJECT_CRS', None)` at the top of each zone
iteration — the same discipline already applied to `RS_PRIOR_GROUPS_FILE` sixty
lines below.

---

## B7 — `RS_CACHE_DIR` was never set on the `main.py` path

**Kind:** fail-open. **Severity:** high.
**Sites:** `module_base/settings_store.py` (`realityscan_env`), callers.

`realityscan_env()` is the single source of truth for `RS_INSTANCE` /
`RS_HEADLESS` / `RS_CACHE_DIR`, but its only callers were the standalone
drivers — **never `main.py`, never `modules/realityscan_interface/`**. A run
driven through `main.py` therefore reached `startRealityScan.bat` with
`RS_CACHE_DIR` unset and `RS_CACHE_ARGS` empty.

That is not a benign default. `appCacheCustomLocation` **persists across
instances** (measured on this dive), so an instance that sets nothing inherits
whatever the last one chose — which on this box can put a ~72 GB-per-component
cache on C:, the one volume the run charter forbids.

**Fix.** `RealityScanCLI.__init__` exports the machine constants, in the one
class that owns RealityScan execution (hard rule 1). Environment values still
win, so an explicit export is unaffected.

---

## B8 — `RS_NO_SETTINGS_INHERITANCE` did not reach the two places that matter

**Kind:** silent shadow. **Severity:** high.
**Sites:** `main.py:191`, `batch_directory.py` (`_stored_default`).

`SettingsStore` has two readers: `get` (ungated, correct for machine constants
read on purpose) and `_default_for` (gated, for **prompt defaults** — the
hazard the flag exists to stop). Both prompt paths used `get`:

* `main.py` resolved **every module parameter** — zone sizes, prior accuracies,
  output paths — from the store ungated. The strict agent lane never reached
  the orchestrator's own parameters at all.
* `BatchDirectory` had a hand-copied clone of `SettingsStore.ask` that had
  drifted the same way, making the batcher the one module strict mode could
  not make strict.

**Fix.** Both use `_default_for`, duck-typed so `get`-only test doubles keep
working. `BatchDirectory._prompt_int/_prompt_float` now delegate to new shared
typed lookups `SettingsStore.ask_int` / `ask_float`, so the precedence rule
lives in one place. `geoall.py`'s `float(settings.ask(...))` sites moved to
`ask_float` so coercion happens inside the lookup rather than at six call sites.

---

## B9 — `batch_xmp_priors` was absent from the reuse fingerprint

**Kind:** silent shadow. **Severity:** medium.
**Site:** `batch_directory.py` (`_input_fingerprint`).

It does not change zone *membership*, but it changes what is on disk inside the
zone tree — and `__copy_files` skips any destination that already exists **by
name**. Flipping the flag against an existing tree therefore wrote no sidecars
and recorded nothing, the same fail-open shape the overlap-distance ceiling was
added to close. **Fix:** added to the fingerprint key set.

---

## B10 — Turning on `batch_xmp_priors` would have killed every pool run

**Kind:** fail-open→hard-fail. **Severity:** blocker (introduced by the directive).
**Site:** `batch_directory.py` (`__create_batch_folders`, pool branch).

Pool layout raised `ValueError` when `batch_xmp_priors` was set. `run()` catches
that into `{'Success': False}` and `main.py` turns it into `sys.exit(1)`. That
was defensible while the flag defaulted to False — an operator who typed it got
told. It became indefensible the moment it became a **default**: every pool run
would die before writing a single zone, over a default nobody chose.

**Fix.** Warn and skip. The incompatibility is real and unchanged — pool zones
hold only an `.imagelist`, so the only place a sidecar could go is beside the
canonical source image, and that tree is read-only (hard rule 0) — but it is a
property of the layout, not an operator error.

### Standing caveats on this directive (not defects; recorded because they are unmeasured)

* `docs`-recorded A/B on NA167 zone_13 measured this prior content **reducing**
  registration, 96.3% → 89.6%.
* `cameras.json` gives `zeuss` `DistortionModel = brown3` while
  `AlignmentParams.xml` sets a **global** `sfmDistortionModel = Division`.
  Which wins is unmeasured. On a single-camera dive the *grouping* half of the
  prior is a no-op, so this contradiction is the only thing the flag introduces
  here.
* On the default identity path `ensure_calibration_sidecars()` already recreates
  a calibration sidecar for every known camera on every exit path. The flag does
  not decide *whether* sidecars exist — only whether they exist **before** the
  first align. The delta is the `FocalLength35mm` / `DistortionModel` numerics.

---

## B11 — Declination would have injected error, not removed it

**Kind:** would-be fail-open. **Severity:** blocker (prevented).
**Sites:** `georeference_images.py:545`, `:255`.

The directive asked for declination "estimated from the UTM Zone if available".
Two findings changed the implementation:

1. **A UTM zone cannot give a usable declination.** It is a 6-degree longitude
   band with no latitude, and declination varies with both. What the code holds
   at the point of need is far better: the per-image `LAT`/`LONG` it just
   computed and a parsed UTC timestamp. The estimate keys off the **median
   accepted position and timestamp**.

2. **This project's nav must not be corrected.** `kalman_yaw_deg` comes from an
   **Octans fibre-optic gyrocompass**, which finds true north directly and has
   no magnetic sensor. `HANDOFF.md`: *"no declination is applied anywhere,
   kalman_yaw_deg comes from an Octans gyrocompass, so it is TRUE north and
   decl = 0 is correct — the repo's `HEADING_MAG` name is a misnomer."* The
   dive folder corroborates it: `NA165_H2060_pitch_roll_heading_octans.csv`.

The code does `true_heading = heading_mag + decl_deg`. WMM-2020 gives
**+12.19° E** at this site and date, against a **15°** declared yaw accuracy —
so applying it would have spent 81% of the orientation budget on a pure
systematic offset, in a solve where over-tight orientation priors are already
recorded as *fragmenting* results.

**Fix.** `modules/declination.py`: **estimate always, apply only when the source
is magnetic.** The heading reference is detected by column name first
(`kalman_yaw_deg` → true) and filename token second; anything unrecognised
applies 0.0 and says so. Both the applied and the estimated value are recorded
with the run, so the decision is auditable and reproducible. An explicit
`--g_declination` always wins.

Two implementation traps worth recording:

* **Epoch selection is mandatory.** Each WMM release is valid five years and
  `pygeomag` **raises** outside that window; a 2024 dive must select
  `WMM_2020.COF` even though `WMM_2025` is the library default.
* `WMMHR_*.COF` are broken in `pygeomag` 1.1.0 (`IndexError`) and are excluded.
* `0.0` is a legitimate declination, so it must never double as "could not
  compute" — the estimator raises `DeclinationUnavailable` instead.

---

## B12 — Every parameter looked "explicitly supplied" on an unattended run

**Kind:** silent shadow. **Severity:** high.
**Site:** `main.py` (`parse_arguments`, the EOF branch).

On an EOF stdin — i.e. every unattended run — the prompt loop takes
`last_value` and then sets `supplied = True`. But `last_value` falls back to
`p.get_default_value()` when nothing is stored, so an **untouched declared
default** was recorded as an explicit operator answer. The file's own comment
claims the opposite ("Only the declared-default fallback below is unanswered"),
which is precisely the case it got wrong.

Two consumers read that lie:

* `BatchDirectory._explicit_param`, whose entire job is to distinguish a typed
  flag from an untouched default. With every parameter "explicit", the
  stored-answer layer it guards was bypassed wholesale — the mechanism added
  after the NA168 incident was inert on exactly the unattended runs it was
  written for.
* The new declination resolver, which treats an explicit value as the operator
  overriding the estimate. An untouched `0.0` would have silently disabled
  auto-detection on every unattended run — the fix in B11 would have been dead
  code on this very dive.

**Fix.** A stored answer is still an answer; the declared default is not.
`supplied` is now true only when the value was typed or came from
`rs_settings.json`.

Found by asking, before launching, which `prompt_user` parameters the launcher
did **not** supply — the answer was `magnetic_declination_deg`, which is what
made the interaction visible.

---

## Not fixed — recorded for the owner

* **`geoall.py` writes 13 columns; `modules/georeference` writes 14.**
  `CLAUDE.md` names geoall the canonical implementation, and the installed
  format declares `<FocalLength index="13">`. Whether the 14-column format
  tolerates 13-column rows is **unmeasured**. This run uses the 14-column
  module path.
* **Prior groups are unproven (open decision D1).** They are emitted and fed to
  `AlignZone.bat` in the right order, but nothing reads back whether
  `-setPriorCalibrationGroup` took effect, and the repo's two lines disagree.
  On this dive it is moot — one camera family means one group, which is what
  RealityScan does anyway — so the directive is only satisfiable by a readback,
  never by a solve-quality argument.
* **The format gate has one call site.** `assert_format_installed` runs only on
  the standard align path; `grow_zone.py`, `merge_zones.py`, `NightGrow.bat`
  and `GuiWorkbench.bat` import flight logs with no gate. Both managed formats
  are verified present in the RealityScan install on this box today, so it is
  not live for this run.
* **The registration census is circular.** "N cameras registered (census from M
  manifests)" is summed from the manifests it is meant to validate. B5's guard
  is a floor, not a proof.

---

## B13 — The identity loop stopped on its lap cap and corrupted the last manifest

**Kind:** fail-open + silent corruption. **Severity:** blocker.
**Sites:** `AlignZone.bat` `:identityLoop`, `realityscan_interface.py`
`MAX_IDENTITY_COMPONENTS`.

**Measured on NA165/H2060 zone_1** (8,757 images), not inferred:

* 20 `.rsalign` exported — the literal value of the cap
* `identity_r19` still held **915** pose sidecars
* `identity_r20` was **never written**

That combination can only mean the loop ran out of **laps**, not components.
Everything past `c19` was dropped from the merge inputs with no record. The
audit had said this was undecidable from the artifacts; it is now decided.

**The second-order damage is worse than the truncation.** Membership is
`stems(r<K>) − stems(r<K+1>)`. With `r20` absent, `c19` absorbed all 915
remaining stems and its manifest claimed a bbox of **181 × 487 m** against
3–90 m for every genuine component. `merge_zones` gates merge candidates on
bbox overlap within a 10 m margin, so a zone-spanning component borders
*everything* — it would have polluted the merge plan globally, not cosmetically.

**Fix.** Cap 20 → **50**, overridable by `RS_MAX_IDENTITY_COMPONENTS`, with a
new `:identityCeiling` branch that performs one final `-exportXMP` harvest
before finishing. That keeps the last component's membership computable and
leaves a **non-empty** `identity_r<N>` as durable evidence of truncation — a
clean exhaustion still leaves an empty one, so the two remain distinguishable.
Python reads the same variable with the same default.

**Why 50 is enough for zone_1, arithmetically:** `-setMinComponentSize 50` and
915 residual stems bound it at `floor(915/50) = 18` further components, so
zone_1 cannot exceed 38. The observed tail decay (~10 %/lap: 175 → 173 → 147)
puts the real figure near 30–31, reached by genuine exhaustion.

**Three subsidiary faults fixed with it:**

1. *The `.bat` did not validate the override.* Python sanitises; cmd does not,
   and the value reaches an unquoted `if %comp_index% GEQ %max_components%`.
   `0`/negative exports **nothing**; a non-numeric makes cmd compare as
   **strings** so the ceiling never fires; an embedded space is a syntax error
   hours in. Now validated with `findstr /r /x "[1-9][0-9]*"`.
2. *Off-by-one in the warning.* `comp_index == max_components` in that branch,
   but the last exported component is `c<max−1>` — the message sent an operator
   hunting a `.rsalign` that does not exist.
3. *Nested parenthesised blocks.* The first draft of the validation used them;
   this script runs under a plain `setlocal` with **no delayed expansion**, so
   a `set` read in the same block expands to its parse-time value. Rewritten
   goto-style to match the rest of the file.

**No test would have caught the original defect** — nothing in 53 test modules
referenced the ceiling. Six new tests pin it, the most important being that the
`.bat` literal and `DEFAULT_MAX_IDENTITY_COMPONENTS` agree: that is the only
check that can catch writer/reader drift.

### Not fixed, recorded

* `CalibCellAlign.bat` still hardcodes `GEQ 20` with no ceiling harvest, while
  its header claims it is "identical to AlignZone.bat". Not in the production
  path (`RS_ALIGN_SCRIPT` is unset) but now *below* the Python warning
  threshold, so a calibration-ladder truncation would be silent on both sides.
* `MergeZoneComponents.bat` caps the peel at 40 with `-setMinComponentSize 1`,
  and `merge_zones.peel_counts_from` is an unbounded loop that cannot tell a cap
  from exhaustion. **This is the next wall**, at the merge stage, on a dive whose
  zones have just been shown to fragment past 20.
* The raised ceiling is a warning, not a gate: a zone that truncates still
  returns `Success: True`. Per-zone check after each align — if
  `zone_N_c49.rsalign` or a non-empty `identity_r50/` exists, that zone was
  truncated.
