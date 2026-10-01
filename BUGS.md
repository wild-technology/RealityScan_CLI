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

---

## B14 — The stall guard was mathematically incapable of firing

**Kind:** fail-open. **Severity:** blocker.
**Site:** `modules/realityscan_interface/realityscan_cli.py`, the progress
monitor loop.

NA165/H2060 zone_2 spent **11,880 s making provably zero progress** and the
monitor logged nothing. There is a stall guard — `STALL_WARNING_SECONDS =
7200` — and it never fired, in any of four run logs (grep count: 0).

**Why.** The guard keys on the progress LINE changing, then narrows that to
"not a `#timeout`". During the freeze RealityScan emitted a strict alternation:

```
<alg> 0.61 39859.34 25128.00 #progress    <- fraction unchanged
<alg> 0.61 40459.34 25506.00 #timeout     <- 600 s later, ignored as activity
<alg> 0.61 40468.86 25512.00 #progress    <- re-arms last_activity
```

The **elapsed counter advances on every line**, so the text is never equal to
the previous text, and the non-`#timeout` records arrived at most **800 s**
apart against a 7,200 s threshold. The timer re-armed forever.

**The threshold is not the bug and cannot be tuned around it.** Any value that
would have fired must sit below 800 s — and a healthy align is legitimately
quiet for one 600 s `-writeProgress` heartbeat (measured: zone_1's longest
genuine plateau was 600.0 s and 603.2 s across two runs).

**Fix.** Track the *recovered* fraction instead of the line text. RealityScan
computes `remaining = elapsed * (1 - p) / p` exactly, so
`p = elapsed / (elapsed + remaining)` inverts it and resolves ~100× finer than
the two decimals printed in the line — which read `0.61` for the entire 3.3 h
freeze.

* **Window 3,600 s of the operation's OWN elapsed clock**, never wall clock,
  so this stays a non-progress test and not a timeout (hard rule 3). Measured
  sweep: 900 s false-positives on a healthy zone_1 run; 1,800 s flags zone_2
  while it was still genuinely advancing; **3,600 s clears zone_1 by 255–568×
  and flags zone_2 2.2 h before the operator killed it**, while still clearing
  zone_2's own longest *recovered* freeze (1,825 s) by 2.0×.
* **Epsilon 1e-4**, not equality. All 35 values across the freeze differ at
  1e-9 — they jitter over a 6.0e-6 span **non-monotonically**, i.e. estimator
  noise around a constant. An equality test would never have fired. 1e-4 sits
  17× above that jitter and below the smallest genuine increment observed just
  before the freeze (~9e-5).
* **`#timeout` records are fed IN**, deliberately. Excluding them as
  "non-activity" is exactly what let the alternation re-arm the old guard.
* **Keyed per `algId`**: a new operation restarts elapsed near zero and would
  otherwise fabricate a huge delta against the previous one.

**It warns; it does not abort.** Verified reasons: `AlignZone.bat` runs
`-align` before its first `-save`, autosave is disabled at instance boot, and
delegated commands are FIFO — so a save injected mid-align would queue behind
it and capture nothing. An abort produces exactly the zero files the manual
kill produced. The value here is information at hour 12, not authority.

### Not fixed, recorded

* **zone_1 is a compromised reference.** Its r=3 m proximity graph is a single
  connected component, yet it solved 33 blocks of ≤604 cameras. Its 4 h runtime
  is not evidence that a ~9,000-camera connected solve is tractable — it is
  evidence RealityScan declined to attempt one. zone_2 was attempting a block
  **15× larger than anything zone_1 ever solved**.
* **The cost proxy is uncertain by ~55×.** `n·bandwidth²` gives zone_2/zone_1 =
  2,900×; `n·median_degree²` gives 53×. Both refuse zone_2 and pass zone_1 and
  zone_4; they disagree about zone_3, which has never been run undecimated, so
  there is no ground truth. Do not quote 2,900× as a calibrated figure.
* **`RealityScan.log` is session-scoped and has been overwritten three times.**
  It is the one artifact that could have turned "cannot be determined from
  outside" into an answer. Copy it into the per-zone output directory on every
  exit path.
* **Merge peel cap** (`MergeZoneComponents.bat`, `GEQ 40`) and **NightGrow
  census cap 24** have the same construction as the identity ceiling fixed in
  B13 — a cap indistinguishable from exhaustion. zone_1 alone produced 33
  components, so the NightGrow cap is already below the real count.

---

## B15 — Four review findings, 2026-09-08

External review of `na165-h2060-directives`. All four reproduced against the
code on disk; all four fixed. The first re-opened B12 through the one door B12
did not close.

### B15.1 — Strict mode re-marked the declared default as an operator answer

**Kind:** silent shadow. **Severity:** high. **Site:** `main.py`, EOF branch.

`last_value` came from the *gated* `_default_for`, but `_had_stored` came from
the *ungated* `settings.get`. Under `RS_NO_SETTINGS_INHERITANCE=1` with a
closed stdin and any leftover `main` entry in `rs_settings.json`:

1. `_default_for` refuses the stored value and returns the declared default
2. `_had_stored` is nonetheless `True`, because `get` still sees the key
3. the declared default is marked **explicit** and written back over the stored
   value

Georeference then sees an explicit declination of 0.0 and **disables WMM
auto-detection**. Invisible on NA165/H2060 — 0.0 is correct there for a
gyrocompass — but the recorded provenance is wrong, and any magnetic-heading
dive hits the full failure. Fix: `_had_stored` is now
`stored is not None and not inheritance_refused()`.

### B15.2 — The flight-log preflight over-rejected on two axes

**Kind:** false refusal. **Severity:** normal. **Site:** `main.py`.

* Any run *without* Georeference fell into the strict branch, so a documented
  **Extract-only or Extract+Preprocess** run was refused for lacking a file
  neither stage reads. Fix: return early unless Batch Directory or RealityScan
  Alignment is enabled — those are the only two stages that consume a log.
* An explicit `--b_flight_log_path` / `--r_flight_log` was checked for
  existence and then had only its **dirname** passed to `require_flight_log`,
  which re-globs for `flight_log*_UTM.txt`. A correctly named explicit file
  that does not match the glob failed preflight while every downstream consumer
  would have taken it verbatim. Fix: honour the explicit path directly, and
  still apply the content check so the fix does not reopen the header-only hole.

### B15.3 — The SHADOWING warning was test-only

**Kind:** lost observability. **Severity:** nit. **Site:** `batch_directory.py`.

Added in B2 to `_stored_default`, but once `_prompt_typed` began delegating to
`SettingsStore.ask_int/ask_float`, production stopped reaching it — only
`get`-only test doubles fell through to that branch. The whole point was to
make a stored answer shadowing a code default *visible on a real run*. Hoisted
into `SettingsStore._ask_typed`, the shared path.

### B15.4 — Dead `b_input` membership test

**Kind:** dead code. **Severity:** nit. **Site:** `main.py`.

`params` is keyed by parameter name (`batch_input_image_dir`), never by CLI
long option, so `'b_input' in params` was always false. Removed.

### Self-inflicted, caught by the suite

Wiring B14's tracker, `progress_tracker` was initialised in
`_monitor_until_exit` but consumed in `_monitor_loop` — a different method, so
it raised `NameError` on every attach-mode monitor. Now passed as a parameter
with a self-initialising default. The suite caught it immediately; it would
have taken down the monitor on the next attach-mode run.

---

## B16 — The merge peel cap was indistinguishable from exhaustion, at 40, with 43 components on disk

**Kind:** fail-open → wrong arithmetic. **Severity:** blocker.
**Sites:** `MergeZoneComponents.bat` peel loop; `merge_zones.peel_counts_from`.

Same defect class as B13, and worse in effect. The peel loop stopped at
`if %peel_index% GEQ 40` by jumping to `:after_export` — the **normal exit-0
label** — echoing nothing and writing no marker. `peel_counts_from` walks
`identity_r<K>` with an unbounded `while True` that breaks at the first missing
or empty directory, so **a cap at 40 and a genuine exhaustion at 40 are
byte-identical on disk.**

Why it is worse than losing components: those per-component counts are exactly
what `attribute_result` does its camera arithmetic with. A truncated peel does
not merely drop components from the merge — it makes **every downstream
attribution wrong**, silently, with a clean exit code.

**Not hypothetical.** NA165/H2060 finished its aligns with **43 components**
(33 + 6 + 4), already past the cap, before the merge was ever launched. And the
peel runs with `-setMinComponentSize 1`, so it exports every fragment however
small — the count climbs faster than the align's.

**Fix.**
* Cap 40 → **120**, overridable via `RS_MAX_PEEL_COMPONENTS`, validated with
  `findstr /r /x "[1-9][0-9]*"` (cmd compares a non-numeric value as a *string*,
  so an unsanitised override would silently never fire — same trap as B13.1).
* New `:peelCeiling` branch that says what happened, names the last peeled
  component, and writes **`PEEL_TRUNCATED.txt`** into the output directory.
* `peel_counts_from` reads that marker and **raises** rather than returning a
  short list. Scoring a truncated peel is the failure mode; refusing is cheap.

Flat gotos, not nested blocks — this script has no delayed expansion either.

**Caught by the suite, again:** my first version of the test sliced the `.bat`
on `:peelCeiling`, which matches the `goto` reference before the label
definition, so it asserted against the loop body. The same mistake I made in
the B13 test. Both now split on the line-initial label.

---

## B17 — The merge's pose export runs with no params file, breaking the measurement channel

**Kind:** silent fallback → blocked stage. **Severity:** high. **Status:** STILL OPEN, but DEMOTED - see B18, which is the defect that
actually cost the dive and which B17 was masking.
**Sites:** `MergeZoneComponents.bat` peel; `Metadata/XMPExportParams.xml`.

The merge ladder produced real components on NA165/H2060
(`cluster_0_a1_c0.rsalign`, 982 MB; five in total) and then aborted:

> `cluster_0 attempt 1: peel harvest returned EMPTY but …_c0.rsalign exists -
> the measurement channel is broken (pose sidecars were never written or never
> moved). Aborting the run instead of mis-scoring it.`

That abort is **correct** — `merge_zones` refuses to score a peel it cannot
measure, rather than mis-assigning cameras. The defect is upstream of it.

**Ruled out:** the calibration sidecars written by `b_xmp_priors=True`
occupying `<stem>.xmp`. zone_1's align harvested 7,655 pose sidecars from the
same tree with the same sidecars present, so the export can write pose over
them.

**Prime suspect:** the peel calls `-exportXMPForSelectedComponent` with **no
params file**. `Metadata/XMPExportParams.xml` exists and declares exactly the
relevant keys — `xmpMerge=true`, `xmpExGps=true`, `xmpCamera=3` — and a
repo-wide grep shows **nothing references it**. So the export inherits whatever
XMP settings the instance currently holds.

This is the same failure class the repo already documents for
`-exportRegistration`: *"an unresolved id does not error, it falls back to the
instance's current export settings and writes a different layout with exit code
0."* Here it produced no `xcr:Position` content at all — 23,822 sidecars in the
images root, zero pose-bearing — while `-exportXMPForSelectedComponent` itself
returned success.

**Consequence.** Cross-zone fusion cannot be scored, so the merge cannot run.
`--assemble_only` is unaffected (it carries components as-is and never peels),
which is how the NA165/H2060 assembly was delivered.

**Next step**, cheapest first: pass `XMPExportParams.xml` to
`-exportXMPForSelectedComponent` the way `AlignZone.bat` passes its params, and
gate on the export having produced pose-bearing files — the same fail-closed
treatment `flightlog_format.assert_format_installed` gives the import
direction. A params file that exists and is referenced by nothing is worth
grepping for elsewhere; this may not be the only one.

**Update 2026-09-08.** B17 is real but it is not why the NA165/H2060 merge
produced nothing. The delivered `merge_report.json` shows all 43 clusters with
`"attempts": []` and `"origin": "assemble_only - carried as-is"` — the ladder
never attempted a fusion, so the peel that B17 describes was never reached in
the final run. The reason no fusion was attempted is B18: the components had
free, mutually inconsistent scale, so `--pair_gate overlap` found no
overlapping bounding boxes and every cluster came out a singleton.

So the ordering is: **fix B18, then re-test B17.** With components that share a
scale the ladder will actually attempt fusions, and only then does the peel
harvest get exercised again. Chasing `XMPExportParams.xml` first would have
been debugging a stage the run was not reaching.

Still-valid B17 leads, unchanged: the params file exists and nothing references
it; and the H2024 precedent (FINDINGS 2026-07-27) established that RealityScan
writes **no** XMP sidecars, reporting success, when the scene's images resolve
through a junction — de-junctioning restored the whole chain there. Whether any
NA165/H2060 path involves a reparse point has not been checked.

---

## B18 — The calibration priors never reached any solve, on any zone, ever

**Kind:** silently non-functional command + wrong undocumented default.
**Severity:** critical — it cost the dive. **Status:** FIXED 2026-09-08,
verified by probe; the re-run is the confirmation.
**Sites:** `Metadata/FlightLogParams{,Local}.xml` (`ifKGrp`);
`modules/prior_groups.py`; `AlignZone.bat:151`.

### What was measured

3,000 pose XMPs sampled from `proc/aligned_components/zone_1/identity_r0`:

    xcr:CalibrationGroup="-1"    3000 / 3000
    xcr:DistortionGroup="-1"     3000 / 3000
    distinct FocalLength35mm     1,700 across 3,000 cameras
    range                        8.947 mm .. 4,640.580 mm   (prior: 23.0)

That is per-image self-calibration. Every camera invented its own focal.

### Why that is not a cosmetic complaint

Focal length and scale are the same degree of freedom in a monocular solve, so
a free focal is a **free scale**. The scale gate — which was never broken and
was telling the truth the whole time — reported:

    35 FAIL / 5 PASS / 3 UNMEASURED
    zone_1_c0    0.0000006      zone_1_c30   2.00757
    zone_4_c1    5.60837        zone_1_c32   2.00030   <- exactly 2x, the
                                                          focal doubling

And with scales that wrong, `--pair_gate overlap` compares bounding boxes that
do not share a metric. Nothing overlapped, so nothing paired, so nothing
merged: 43 singleton clusters, and an "assembly" that was 43 unmerged zone
components stacked in one project. The 4.1x-more-imagery claim over the
previous delivery stands; the word "merged" in it did not.

### Cause

`ifKGrp` in the flight-log import params — RealityScan's *"Automatically group
camera calibration"* — shipped at `2` for the life of this repo. Its value
mapping is undocumented (`docs/rs-reference/06` §557 marks it
`[UNDOCUMENTED]`) and had never been probed. Measured on 120 contiguous zone_2
frames, one variable per cell (`_agent/probe_ifkgrp`):

| cell | cameras | ungrouped | distinct focals | focal range |
|---|---|---|---|---|
| `ifKGrp=0` | 91 | 91 | 58 | 23.12 – 24.14 mm |
| **`ifKGrp=1`** | 95 | **0** | **1** | **25.09 mm flat** |
| `ifKGrp=2` | 93 | 93 | 55 | 29.50 – 30.42 mm |

Only `1` groups.

### The correction that matters

A fourth cell ran with **no flight log at all**, so nothing could override
anything. The prior groups *still* did not take: 16 cameras, 16 ungrouped, 12
distinct focals. So `-setPriorCalibrationGroup` was never working either —
which `FINDINGS` 2026-08-08 established ("silently NON-FUNCTIONAL from the
delegated CLI") and `CalibCellAlign.bat:93` has said in an error message ever
since, while the main align path kept calling it.

This supersedes the 2026-08-28 reading that the import "appears to stomp prior
groups". Nothing was stomped. **The flight-log import's auto-grouping is the
only working calibration-grouping channel this pipeline has**, and it was set
to a value that does not group.

### Why nothing caught it

Every channel reported success. The delegated command returned 0.
`prior_groups.write_command_file` logged "1 camera family". `AlignZone.bat`'s
`:run` saw no error. The run exited clean and produced components. The failure
was observable in exactly one place — the exported pose — and nothing looked
there.

That is the general lesson, and it is why the fix is not just a config change:
**a prior that cannot be observed in the output is not a prior, it is a hope.**
Configuring one is not evidence it applied.

### Fix

- `ifKGrp` 2 → 1 in both params templates, with the cell table recorded inline
  so the value cannot be "tidied" back, plus a test pinning both the value and
  the table (`testing/test_flight_log_params_template.py`).
- `modules/prior_census.py` (new): reads what the SOLVE used out of the pose
  XMPs after every zone align and refuses a run whose priors provably did not
  land. Two independent tests — the group echo and the solved-focal spread —
  because either alone has a blind spot, and an EMPTY harvest fails too, since
  "unmeasured" is the state that let this ship.
- An unrecognised rig, or a failed prior-group generation, is now a critical
  error instead of a warning-and-continue.

### Deliberately NOT done

The census does not assert solved focal against the prior VALUE. The
calibration ladder (FINDINGS 2026-08-09) measured full manufacturer priors at
**45.4%** registration against **97.3%** control and **97.7%** groups-only, and
run3 (2026-08-28) measured them corrupting metric scale by −2.55% while
steering solved focal away from both the prior and RealityScan's own free
solve. Grouping is the half that helps; the numeric value is the half that
halves the dive. Enforcing it would enforce the arm measured to be harmful.

### Open

Whether `ifKGrp=1` means "group all" or "group by focal length" is
**undetermined** — NA165/H2060 carries one camera and one focal column, so the
two are indistinguishable here. On a multi-camera rig they are not: "group all"
would calibrate the four EXIF-identical WCA cameras as one, which is the exact
fault the prior groups were introduced to prevent. Probe before the next
multi-camera dive. `prior_census`'s `expected_groups` will catch it, but
catching it after a 14 h align is not the same as knowing beforehand.

**Update 2026-09-09 — both stated hypotheses are DEAD, and the real fix is in.**

1. *Reparse-point write path* (the H2024 root cause, where RealityScan writes
   no sidecars and reports success): **ruled out by measurement.** Every path
   this dive touches — the root, `proc`, `batched_images_by_zone`, each zone,
   `zone_2/zeuss`, `aligned_components`, `merged`, `raw`, `rs_cache` — is a
   real directory, and a recursive sweep of the image tree finds no reparse
   point anywhere.

2. *"Pass `XMPExportParams.xml` to `-exportXMPForSelectedComponent` the way
   AlignZone.bat passes its params"* — the entry's own recommended next step:
   **impossible.** The command takes no params argument.
   `docs/rs-reference/05-metadata-xmp-and-sidecars.md` is explicit: it
   *"accepts none and always uses the current settings"* — i.e. whatever the
   instance's XMP export dialog happens to hold. Anyone following that
   instruction would have spent the session discovering it.

**But that sentence names the right lever, in the wrong place.** Those settings
are INSTANCE STATE, and `XMPExportParams.xml` holds exactly the keys that
govern it. Nothing in the repo referenced the file, so every peel export in
this pipeline's history ran on inherited dialog state.

Why that reproduces the symptom precisely: `xmpExGps` and `xmpCamera` decide
whether POSE is written at all, and the harvest filters sidecars on the literal
string `xcr:Position`. **A peel that writes sidecars WITHOUT position is
byte-indistinguishable on disk from a peel that writes nothing** — which is
exactly what NA165/H2060 showed ("23,822 sidecars in the images root, zero
pose-bearing") while the command returned success.

**Fix applied:** `MergeZoneComponents.bat` now applies every key from
`XMPExportParams.xml` via `-set` before the first export, using the same loop
`AlignZone.bat` uses for `AlignmentParams.xml`, and **fails closed on zero
applied** — a silently-empty apply would leave the export on instance state
and still exit 0, which is the original defect wearing a different hat. Six
keys are applied, including the two pose-bearing ones. Tests pin the
reference, the ordering, the zero-applied guard, the two keys, and that the
`delims="` parse still matches the file's attribute order.

**Status: fix in, UNCONFIRMED.** It cannot be confirmed until a merge actually
attempts a fusion, and no merge on this dive ever has — the first pass produced
43 singleton clusters because of B18. The zone_1/3/4 re-aligns now running are
the precondition. **Do not close B17 until a peel returns a non-empty harvest.**

One caution for whoever runs that merge: the calibration sidecars have been
moved out of the image trees (`_agent/sidecars_setaside/`), so the "23,822
sidecars, zero pose-bearing" count will not reproduce — the tree now starts
empty. That makes the next peel a cleaner test, but it also means an empty
`identity_r0` can no longer be blamed on ours being in the way.

---

## B19 — The align path never georegisters: no post-alignment fit to the priors

**Kind:** missing step. **Severity:** high — it makes metric scale a matter of
luck on every zone this pipeline has ever aligned. **Status:** DIAGNOSED, fix
identified, confirmation pending.
**Sites:** `RS_CLI/Scripts/AlignZone.bat` (the whole file — the defect is an
absence).

### The symptom that exposed it

NA165/H2060 zone_3 reconstructs ~1.27x larger than its nav, reproducibly:
1.26691 on the first pass and 1.2745 on a re-run with completely different
calibration handling. Its five components disagree with each other by up to
1.84x. Meanwhile zone_1, zone_2 and zone_4 come out near 1.0.

### zone_3's geometry is CORRECT — only its size is wrong

zone_2 and zone_3 SHARE 2,054 frames (the batcher donates overlap). The same
photographs, solved twice, agree on **shape to 1.2–22.8 mm on scenes 3.5–22.7 m
across** — 0.02–0.4% of the diagonal — while differing in SCALE by 1.2017–1.2391
(zone_3 c0) and 0.7115–0.7184 (c1..c4). Same images, same nav rows (byte
identical), same camera, one focal length. Only the gauge differs.

So this is not matching, not the nav, not the imagery, and not calibration.

### The mechanism

Rescaling a solved component about its own centroid is an **exact gauge freedom
of the reprojection term** — cameras and points scale together and every
projected pixel is unchanged. The **position priors are therefore the only term
in the objective that can see scale.**

Sweeping the weighted prior chi-squared against a rescale factor k, with the
rotation re-fitted at each k (per camera, so zones compare):

| component | cams | k\* (priors' optimum) | chi2(k\*) | chi2(k=1) | unclaimed |
|---|---|---|---|---|---|
| zone_3 c0 | 2248 | **0.777** | 0.10 | 0.22 | **54.6%** |
| zone_3 c1 | 656 | **1.524** | 0.03 | 0.15 | **82.0%** |
| zone_3 c2 | 171 | 1.404 | 0.02 | 0.03 | 39.6% |
| zone_3 c4 | 117 | 1.435 | 0.03 | 0.16 | 82.5% |
| zone_2 c0 | 1831 | 0.986 | 0.04 | 0.04 | 0.8% |
| zone_2 c5 | 329 | 0.984 | 0.04 | 0.04 | 0.8% |
| zone_1 c0 | 551 | 1.019 | 0.30 | 0.31 | 2.7% |
| zone_4 c0 | 219 | 1.008 | 0.21 | 0.21 | 0.1% |

Every zone_3 component stopped at a scale **its own priors score as strictly
worse**, leaving 40–83% of the residual unclaimed. And `1/0.777 = 1.287`, the
measured error. **The priors held the right answer and it was never applied.**

This also kills the "the priors were too loose" reading: k\* is essentially
weight-independent (isotropic weighting gives 0.760 for c0 against 0.770 under
5/5/1). Prior sigma sets the UNCERTAINTY on scale, not the LOCATION of its
optimum. At any positive weight, a solver that consulted the priors about scale
would have gone to k\*.

### The absence

    AlignZone.bat:225   -importFlightLog
    AlignZone.bat:229   -align
    AlignZone.bat:240   -save

Zero occurrences of `-update` in the file. The reference records
`-update` as *"a similarity/rigid fit to the scene's imported constraints,
applied after reconstruction: it can rotate or **rescale** a component"* and
*"the step that can **set scale**"*
(`docs/rs-reference/02-command-reference.md`). `MergeZoneComponents.bat:183`
calls it *"the step that actually georeferences"* and has always run it.

**The merge path georeferences. The align path imports priors, solves, and
saves whatever gauge the solver happened to pick.** Dive-wide corroboration:
across all 46 components with n>=100, as-placed position sits within a median
6.2% of the best RIGID (scale-1) fit of its own cloud to the priors, while
leaving a median 22.8% residual reduction unclaimed that only rescaling would
capture. That is the signature of rigid placement with no similarity fit.

### Why it was invisible

Most components land near scale 1.0 on their own, because a well-conditioned
solve over varied geometry recovers roughly the right relative scale from the
priors used during matching. The missing step only bites where the solve's own
gauge drifts — and then nothing corrects it. zone_1/2/4 hid the defect; zone_3
exposed it.

### Open

Why zone_3's gauge drifts and the others' do not is NOT established. Leading
candidate: the gauge is fixed at SfM initialisation from a seed pair's
baseline, and zone_3's nav residual over a 20 s window is 1.167 m against ~2 m
of travel, so a short seed baseline carries ~50% relative error — the right
order for both +27% and -34%. Not testable from finished output; needs a run.

Unexplained and suggestive: in the re-run (one calibration group, one focal)
zone_3's four small components converged on 0.6153–0.6644, where in the first
pass (five distinct focals) they were scattered 0.70/0.88/1.18/1.19. Four
nominally independent components landing within 5% of each other is not random
and nobody has an account of it.

### Fix

Add the post-alignment georegistration the merge path already has. It should
be gated and reported, not silent: a component that moves a long way under
`-update` is telling you its solve had drifted, and that is worth recording
rather than quietly correcting.

**Do not close this until measured.** The confirming test is cheap and needs no
re-align: load a saved zone project, `-exportRegistration` the maximal
component, `-update`, export again, compare scale against nav. If the component
moves to k\*, the diagnosis is confirmed.

### Confirmation attempt, 2026-09-09 — NOT achieved, and why

Three probes failed to produce a before/after measurement. All three failures
were in the probe harness, not in the finding, and each is worth recording
because the next person will hit them:

1. **`-exportXMP` on a loaded project exports nothing.** It covers only "the
   last alignment", and a `-load` leaves none in session. EXPORT_XMP (process
   20584) ran, returned 0, took 18 s, and wrote no pose sidecar. This is
   already in FINDINGS; I rediscovered it the slow way.
2. **A bare `%RealityScan% -delegateTo` chain silently no-ops against a busy or
   not-ready instance.** Every step "succeeded", both CSVs came back missing,
   exit 0 — the same silent-success class as B18 and B17.
3. **My `:run` error check was inert.** It tested `if exist "%ErrorsFile%"`,
   but `ErrorsFile` is set by `AlignZone.bat`/`MergeZoneComponents.bat`
   themselves, NOT by `SetVariables.bat`, so the variable was empty and the
   guard never fired. A copied `:run` without its variables is decoration.
4. **`RealityScan.exe` with a direct command chain detaches**, returning no
   exit code and doing nothing observable — which is why this repo drives it
   through the instance/delegate pattern with `-waitCompleted` at all.

**The cheapest real confirmation is the fix itself:** add the post-alignment
`-update` to `AlignZone.bat` and re-run zone_3 alone (~1.5 h). If its
components move to k\* — c0 from 1.2745 toward 1.0 — B19 is confirmed and
fixed in one step. That is a better use of the machine than more probe
scaffolding.

**Care required when adding it.** The reference also records `-update` as the
step that "will rotate geometry to satisfy mis-converted constraints" — it
trusts the nav. It should therefore log how far each component moved, and a
large move should be reported rather than silently applied: a component that
travels a long way under `-update` is evidence its solve drifted, which is
information worth keeping, not hiding.

---

## B20 — The align fingerprint records the repo SHA but never compares it

**Kind:** silent comparability. **Severity:** low, but it undermines an
invariant this pipeline takes seriously. **Status:** OPEN.
**Sites:** `modules/align_fingerprint.py` — `build_fingerprint` writes
`repo_sha`, `diff_fingerprints` never reads it.

`build_fingerprint` captures `repo_sha` alongside the flight log, params,
alignment settings and min component size. `diff_fingerprints` then compares
only the file content hashes in `_COMPARED`, plus `frame` and
`min_component_size`. **A change to the pipeline code itself is recorded and
then ignored.**

Observed live, 2026-09-09: zone_3 was re-aligned immediately after
`AlignZone.bat` gained the B19 `-update` step — a change that alters the
geometry of every component it touches. The run announced:

> `Re-run with IDENTICAL inputs (nav, frame, settings unchanged) for
> ...\aligned_components\zone_3 - redoing the zone from scratch.`

The inputs were not identical in any sense that matters. Nothing downstream
was harmed here because the zone is redone from scratch either way, and
because this particular comparison was deliberate and understood. The hazard
is the general case: this module exists to enforce "never merge components
built from different inputs", and a workflow-script change is exactly the kind
of difference that invariant is meant to catch. Two zones aligned either side
of a `.bat` edit will compare as identical.

Note the fingerprint hashes `AlignmentParams.xml` but not `AlignZone.bat`,
`MergeZoneComponents.bat`, or the prior-group command file — so the settings
are covered and the code that applies them is not.

**Fix options, owner's call on which:** compare `repo_sha` as MATERIAL (warns
on every commit, which is noisy but correct for a metrology pipeline);
or as INFORMATIONAL, printed but not blocking; or hash the workflow `.bat`
files into `_COMPARED` so only changes to the scripts that actually run are
material. The third is the most targeted and the least noisy.

### B19 addendum, 2026-09-09 — `-update` is not reliably corrective

The fix is confirmed for the case it was diagnosed on and **must not be
applied blind to existing zones**.

    zone            dominant component      in band before -> after
    zone_3          c0 = 71% of the zone     0.0%  ->  76.3%    HELPED
    zone_4          c0 = 35% of the zone    34.9%  ->  16.7%    HURT

zone_4's c0 was PASSING at 0.9377 and `-update` moved it to 1.1470.

**It fits each component separately — measured, not assumed.** Comparing the
georegistered solve against the original over the same cameras, each component
took its own factor, perfectly uniform within itself (IQR width 0.0000):

    c0 x1.2231    c1 x1.4506    c2 x2.3141    c3 x1.2382

Not one global transform. And the frame did not change: both exports carry
`ExportCoordinateSystemType 3`, `Coordinates absolute`, ECEF-magnitude
positions, the same focal and the same calibration group. It is a genuine
geometric rescale.

**But it does not move a component to its priors' optimum.** zone_4 c0's prior
chi-squared optimum was k\*=1.008 — essentially where it already sat — and
`-update` multiplied it by 1.2231. So whatever `-update` minimises, it is not
the weighted position-prior residual the B19 analysis used.

**The pattern that fits both zones is conditioning.** A similarity fit's scale
parameter is well determined by 2,334 cameras (zone_3 c0 -> 0.9771) and weakly
determined by 105-219 cameras against USBL noise (all four zone_4 components
moved the wrong way). zone_3's own small components corroborate it: c2 (171)
improved to 1.0508 while c1 (654) went to 1.3137 — a coin flip.

**Consequence for the retrofit.** zone_1's largest component is 9% of its zone
and zone_2's is 32%, so both resemble zone_4 more than zone_3. Applying
`RS_GEOREG_ONLY` in place could degrade them irrecoverably. The procedure is
therefore: run into a SIBLING COPY, measure both, keep whichever scores
better. zone_4 is decided — the original wins and the copy is discarded.

**What this does NOT change.** B19's diagnosis stands: the align path never
georegistered, the priors held the right answer, and adding the step rescued
zone_3 from 0% to 76.3%. What is now known is that the step is a fit like any
other, and an ill-conditioned fit can land anywhere. It belongs in the align
path, where it runs on a freshly solved scene; it is not a repair tool to be
sprayed at saved projects.

**OPEN:** what `-update` actually minimises. It is not the position-prior
chi-squared. Orientation priors, control points, or a robust/trimmed variant
are all candidates. Until that is known, treat a large `-update` correction as
a flag for inspection rather than a fix — which is what the B19 block in
AlignZone.bat already says, and now has evidence behind it.

## B21 — An unset RS_CACHE_DIR inherits the PREVIOUS run's cache directory, in another dive

**Kind:** silent cross-tree write. **Severity:** high — it filled a 3.7 TB
volume and aborted a 10-hour modelling run, and the evidence pointed at the
wrong dive the whole time. **Status:** OPEN, worked around per-run.
**Sites:** `RS_CLI/Scripts/startRealityScan.bat` lines 39-56 (the
`RS_CACHE_DIR` opt-in), and every launcher that leaves it unset.

`startRealityScan.bat` treats `RS_CACHE_DIR` as opt-in and documents the
unset case as "keeps RealityScan's own default". That is true only on a
machine where nobody has ever set one. When it IS set, the script issues

    -set "appCacheLocation=Custom" -set "appCacheCustomLocation=%RS_CACHE_DIR%"

and RealityScan PERSISTS both in its own application settings. From then on
"RealityScan's own default" is the last custom path any run chose. A later
run that leaves `RS_CACHE_DIR` unset does not get a neutral default — it
silently writes its cache into whatever tree the previous run named.

### Measured, 2026-09-24

NA165/H2060's modelling launcher set no `RS_CACHE_DIR`. NA168/H2082's merge
had set one to its own `merged_v1\cache`. The modelling run therefore wrote
into **H2082's tree**:

    NA168\H2082\proc\merged_v1\cache   631.6 GB total
      older than 12 h                   80.3 GB   4,994 files  (H2082's merge)
      last 12 h                        551.3 GB  34,674 files  (H2060 modelling)

The newest file was stamped 10:13:07 — the minute the H2060 run aborted on
its own 50 GB disk floor. H2060's `merged_v1` had grown to only 136.7 GB
while the volume lost ~700 GB, and three emergency reclaims (117, 128 and
180 GB) were all made in H2060's tree, which was never the consumer. The
run did not need to abort.

`RS_NO_SETTINGS_INHERITANCE=1` was set and is irrelevant here: it governs
this pipeline's own `SettingsStore` (`module_base/settings_store.py`), not
RealityScan's persisted application settings. Do not reach for it as the
fix.

### The fix

Make the cache location explicit rather than inherited. Either

- have `startRealityScan.bat` REFUSE to boot without `RS_CACHE_DIR`, or
- default it to a path derived from the output tree, so a cache always
  lands beside the work that creates it,

and in both cases log the resolved location at boot so an operator can see
which tree is about to absorb hundreds of GB. Until then every launcher
must set `RS_CACHE_DIR` inside its own dive; a run that omits it is not
using a default, it is using someone else's.

---

**B22 to B27 — found in review, 2026-10-01, all OPEN.** Raised by the
read-only review of the work since committed as the eight commits ending at
`35e3ca6` (branch `h2060-rerun`), then re-established one by one from the
code and reproduced on synthetic fixtures in a scratch folder. **None is
fixed here**; each entry states the proposed fix. Line numbers are as at
`35e3ca6`; in `publish_cesium.py` every cited line above `:326` sits 28
lines lower from the decoder refactor committed alongside these entries
(the `stage()` call `:538` is then `:566`, the dry-run gate `:550-556` is
`:578-584`). Nothing below needed RealityScan, and no reproduction wrote to a
dive folder or to Cesium ion (B24 and B27's sidecar census READ the dive
folders; nothing else touches them).

## B22 — The nested-tree locator also steers the planner: one plan writes flat and merges from an older subfolder

**Kind:** silent shadow — a path the plan implies is quietly replaced by
another tree. **Severity:** high when it bites (Merge runs to completion on a
previous attempt's components and exits 0), but it needs a particular
results root and nothing running today has one. **Status:** OPEN.
**Sites:** `modules/workspace_census.py:149-187` (`_locate`), `:203-217` (the
four properties it now backs). Consumers: `wildscan/session.py:646-647`
(Merge `--components_root` / `--images_root`), `:693-700` (Export
`--exports` / `--names`), `:829-830` (`export_names_file`: mkdir + write),
`wildscan/app.py:416`, `run_models.py:200`, `:545`.

Commit `315de32` taught `Workspace` to find a stage tree one level down
(`proc\rs\batched_images_by_zone`), because every real dive on this machine
kept its trees under a working subfolder and the flat-only census called
them "pending". The change was made inside the four `Workspace` properties
— `preprocessed`, `batched`, `aligned`, `exports` — which until then were
`self.root / "<name>"`, always.

Those properties are not only the census's eyes. `build_commands`, the pure
planner, builds command lines from them. The Batch + Align command does
not: `session.py:610-612` passes `--output_dir <results_root>` and the chain
creates its trees flat under it (the canonical layout,
`workspace_census.py:11-25`). So on a results root with no flat tree yet and
exactly one subfolder holding stage trees, a single plan disagrees with
itself.

### Measured, 2026-10-01 (planner only, nothing launched)

Results root holding only
`previous_attempt\{aligned_components,batched_images_by_zone,exports}\zone_1`;
enabled = batch, align, merge, export:

    Batch Directory + RealityScan Alignment
        --output_dir       <root>
    Merge Components
        --components_root  <root>\previous_attempt\aligned_components
        --images_root      <root>\previous_attempt\batched_images_by_zone
        --output           <root>\merged
    Export Deliverables
        --exports          <root>\previous_attempt\exports
        --names            <root>\previous_attempt\exports\components.names

Controls: an empty results root plans every path flat; so does the same
older tree placed under `archive\` (in `_LOCATOR_SKIP`).

The plan is built once, before anything runs (`wildscan/app.py:395`,
`wildscan/plan.py:136`); only the export command is re-resolved at launch
(`app.py:398-429`). By the time Merge starts, Batch + Align have written
the flat tree and the locator would now answer "flat" — re-planning the
same root after creating `<root>\aligned_components` does give the flat
paths — but the Merge command in hand still names the old one. Merge then
fuses the previous attempt's components against the previous attempt's
images into `<root>\merged` and reports success. Export is aimed INTO the
previous attempt's `exports\`, a deliverable tree this run did not create
(driving mandate 3).

The census side is honest about it: `provenance.layout` publishes which
tree was read and how it was found. The planner prints its command too —
but nobody reads twenty arguments looking for a folder name they did not
type.

### The fix (proposed)

The locator is a READ convenience for the oracle. A planner must not let it
choose where a stage reads when an earlier stage of the same plan writes
that tree. Either

- give `Workspace` a second, flat-only view (`root / name`) and have
  `build_commands`, `export_names_file` and `run_models.py` use it, leaving
  `_locate` to the census — this restores the pre-`315de32` behaviour for
  everything that executes; or
- keep one view and make `build_commands` stop and ask when
  `layout()[tree]["how"]` is `nested` for a tree a stage in the same plan is
  about to create flat.

Either way add the test that is missing: `build_commands` on the fixture
above must name one tree, not two.

---

## B23 — verify's cut-short-slice guard switches itself off when it cannot find the zone's images

**Kind:** fail-open. **Severity:** high — it is the guard that stops a
truncated flight-log slice proving itself, and it goes quiet exactly where a
layout is unusual, which on this machine is every dive. Masked today by B24
(the oracle sees no zones there at all). **Status:** OPEN.
**Sites:** `modules/verify.py:305-306` (imagery looked up at
`ws.batched / zone`), `:321` (`if img_keys:`), `:329-330` (coverage by bare
basename); `modules/nav_provenance.py:251-252` (`zone_image_keys` returns
`None, "unknown"` for a folder that is not there).

`check_nav_unanimity` proves one navigation table behind the per-zone flight
logs. A slice whose rows all match is "contained" in the table — and so is
a slice cut down to one row. The module says so itself (`verify.py:184-186`:
"every slice reconciled against the imagery its zone holds so a truncated
slice cannot prove itself vacuously"; `:199`: "Absence of evidence is never
agreement"). The reconciliation is `:321-341`: of the zone's images with no
row in the slice, how many does the TABLE have a row for?

It reads the zone's imagery from `ws.batched / zone` — the census locator's
answer — not from the folder the slice under test sits in. When the locator
has no answer (`how` is `absent` or `ambiguous`; both leave `path` at the
non-existent flat folder, `workspace_census.py:169`, `:182-185`),
`zone_image_keys` returns `None`, `:306` records `"images": null`, `:321`
is false, the block is skipped, nothing is added to `findings` or
`nav["unavailable"]`, and `:350-353` computes `proven = True`. An empty set
— the folder is there, the images are not — leaves by the same door.

### Measured, 2026-10-01 (the suite's own fixture)

The fixture of `test_a_slice_cut_short_of_its_own_source_blocks`: zone_2
holds images 2, 3 and 4; its slice is rewritten to row 2 alone and the
fingerprint re-pointed at it. Only the location of the batched tree varies.

| batched tree | located as | verdict | nav `proven` | zone_2 `images` | `omitted_rows_the_table_has` |
|---|---|---|---|---|---|
| `proc\rs\` (control) | nested | **blocked**, exit 2 | False | 3 | 2 |
| `proc\a\b\` (two levels down) | absent | **ok**, exit 0 | True | null | not computed |
| `proc\rs\` plus an empty `proc\rs_cinup\batched_images_by_zone` | ambiguous | **ok**, exit 0 | True | null | not computed |
| `proc\rs\images_batched_by_zone` (the Desktop name, B24) | absent | **ok**, exit 0 | True | null | not computed |
| `proc\rs\`, zone_2's images removed | nested | incomplete, exit 1 — from the batch census, not the nav check | True | 0 | not computed |

In the three "ok" rows the blocking list is empty and `provenance.nav.method`
is `slices`: the report reads as a positive proof. The `rs` + `rs_cinup`
pair is not exotic — it is the layout `_locate`'s own docstring cites
(H2080) as the reason it refuses to choose.

### The related reduction, `verify.py:329-330`

    covered = {k[-1] for k, _tail in slice_log["rows"] if k}
    uncovered = sorted(k for k in img_keys if k[-1] not in covered)

Coverage is decided on the bare filename. In pool layout a zone's imagelist
carries full paths and two pools can hold the same basename —
`nav_provenance.match_key` exists because of that, and
`test_two_pool_folders_sharing_a_basename_do_not_collide` pins it for ROWS.
Measured: zone_2's imagelist holds `poolA\wca\D1.JPG` and
`poolB\wca\D1.JPG`, its slice has a row for poolA's only, the table has a
row for each. Result: `images_without_a_row: 0`,
`omitted_rows_the_table_has: 0`, nav proven True. The truth is 1 and 1.

### The fix (proposed)

- Reconcile against the folder the slice is IN (`Path(paths[zone]).parent`;
  `:247-256` has already established it is named for the zone and that all
  slices share one batched root). The slice and its imagery cannot then be
  looked up in two different trees.
- Make "could not measure" a finding: `img_keys is None`, or an empty set
  beside a slice that has rows, goes to `nav["unavailable"]` ("zone_2: the
  images its flight log covers could not be found, so the slice cannot be
  shown to be whole"). `proven` stays False and the byte-comparison guard
  speaks, as it does for every other way of failing to measure.
- Decide coverage with the key matching the rows use (`match_key` on the
  full key), not `k[-1]`.
- Tests: the two-levels and ambiguous fixtures must block; the pool fixture
  must report 1 and 1.

---

## B24 — The oracle is blind to the reorganised Desktop layout, and says OK

**Kind:** fail-open — a census that finds nothing returns the verdict of a
census that finds everything in order. **Severity:** blocker for anything
that takes `modules.verify` exit 0 as evidence; CLAUDE.md calls it "the
census/verify oracle" and the `drive-run` and `status` skills run it with
no `--require`. **Status:** OPEN.
**Sites:** `modules/workspace_census.py:189-217` (the four stage-tree names,
fixed strings), `:292-294`, `:331-333`, `:418-420` (an unseen tree is
"pending"); `modules/verify.py:491-492` (default `required` = every stage
that is not pending), `:192-193` (no aligned zones: nothing to check, no
finding), `:515-520` (the verdict).

The 2026-09-30 reorganisation of the dive folders renamed the stage trees:

| the code looks for | the dives now hold |
|---|---|
| `batched_images_by_zone` | `images_batched_by_zone` |
| `aligned_components` | `realityscan_align_zones` |
| `exports` | `exports_models`, `exports_models_v2`, `exports_las_v2` |
| `preprocessed_images` | `images_preprocessed` |

None is found, flat or one level down. Every stage from batch on is
therefore "pending"; the default requirement is "finish what you started",
so only extract and georeference are required, and both are done. There are
no aligned zones, so the provenance, frame, nav and scale checks have
nothing to run on and raise nothing. Verdict `ok`, exit 0.

### Measured, 2026-10-01 — `python -m modules.verify --workspace <dive>\proc --json` (it only reads)

| workspace | exit | verdict | required | zones_aligned | components | what is on disk (counted separately) |
|---|---|---|---|---|---|---|
| `Desktop\NA165_H2060\proc` | 0 | ok | extract, georeference | 0 | 0 | 9 zone folders, 130 `.rsalign`, 9 `align_inputs.json` in `realityscan_align_zones`; 9 zones in `images_batched_by_zone` |
| `Desktop\NA168_H2082\proc` | 0 | ok | extract, georeference | 0 | 0 | 2 zone folders, 13 `.rsalign`, 2 `align_inputs.json` |
| `Desktop\NA168_H2077\proc` | 0 | ok | extract, georeference | 0 | 0 | 1 batched zone, model exports, a published package |
| `Desktop\NA168_H2080\proc` | 0 | ok | extract, georeference | 0 | 0 | `images_preprocessed`, RealityScan projects |
| `Desktop\NA165_H2063\proc` | 2 | blocked | extract, georeference, merge | 0 | 19 | blocked on two out-of-band scales read from `deliverable_records\merge_report.json`; still 0 zones seen |

`provenance.layout` is `absent` for all four trees in all five workspaces
and `provenance.nav.method` is `no_aligned_zones`. With `--require align`
H2060 reads `incomplete`, exit 1 ("no aligned_components/") — wrong the
other way, but not a false pass. On H2060 the georeference stage also
reports `flight_log_u_alt01_ori180_2L_UTM.txt`, from
`agent_workspace\prior_test\logs\`: the alphabetically first
`flight_log*_UTM.txt` anywhere under the root (`workspace_census.py:93`,
`:255-260`), a prior-accuracy test variant, not `nav\`'s master.

So the nav-provenance ladder of `315de32` has never run on a dive as it is
laid out today (which is also why B23 cannot currently be reached there),
and four of five dives return the oracle's best verdict with nothing
verified.

### The fix (proposed)

Two parts; the first matters more.

1. **A census that located nothing past georeference must not say `ok`
   when the root plainly holds work.** A bounded look for stage evidence
   under names the census does not know — any `*.rsalign`,
   `align_inputs.json`, `batch_inputs.json` or `*.rsproj` within two or
   three levels — and, where there is some while the matching tree is
   `absent`, a BLOCKING finding: "stage artifacts exist under folders this
   census does not recognise (`realityscan_align_zones\zone_1\...`);
   nothing past georeference was verified". A genuinely fresh dive has none
   and still reads `ok`.
2. Teach the locator the layout as DATA rather than a second list of magic
   names: a `workspace_layout.json` at the results root naming each stage
   tree's folder (the reorganisation's `move_log.jsonl` holds the
   information), read by `_locate` before the built-in names. `exports`
   needs care — three candidate folders is the "refuse rather than pick"
   case.

Until then: a verify "ok" on a Desktop dive is evidence of nothing past
georeference. Read `counts.zones_aligned` and `provenance.layout` first.

---

## B25 — publish_cesium deletes whatever `--staging` names, before the `--dry-run` gate

**Kind:** unguarded destructive default. **Severity:** high — one mistyped
argument deletes a source export, or a dive, that may exist nowhere else,
on the very invocation whose purpose is to change nothing. **Status:** OPEN.
**Sites:** `publish_cesium.py:207-209` (`stage()`:
`if staging.exists(): shutil.rmtree(staging)`), `:537` (default staging
`<dir>/_cesium_local`), `:538` (the call), `:550-556` (the dry-run gate,
AFTER it), `:472-474` (`--staging`); `publish_batch.py:151-153` (passes no
`--staging`).

`stage()` writes the local-frame copy of the mesh that gets uploaded. It
begins by removing the staging directory if one exists, with no test of
what that directory is. `main()` calls it at `:538`; `--dry-run` returns at
`:556`. The help for `--dry-run` says "plan and stage ... upload nothing",
so staging on a dry run is intended. Deleting an arbitrary existing
directory is mentioned nowhere.

### Measured, 2026-10-01 (synthetic export in scratch, `--dry-run --no-geoid`)

| invocation | before | after | exit |
|---|---|---|---|
| default staging, `<dir>\_cesium_local\note_from_last_week.txt` already there | the note, `m.obj`, its sidecar | the note is gone; `_cesium_local\m.obj` written inside the export folder | 0 |
| `--staging <dir>` (equal to `--dir`) | `m.obj`, `m.mtl`, `m.obj.rsInfo`, `unrelated_deliverable.las` | **folder empty** | 1, `FileNotFoundError` traceback |
| `--staging <dive>` (a parent of `--dir`) | `exports\c10\obj\{m.obj, m.obj.rsInfo}`, `nav\flight_log.txt` | **folder empty** — the sibling `nav\` went too | 1, `FileNotFoundError` traceback |

In the last two rows the vertices are already in memory, so the placement
is planned and logged first; the crash comes when `rewrite_obj_local`
reopens a source that no longer exists.

The default is a milder form of the same fault: it writes into the export
folder, i.e. into the deliverable tree (a default-staging run would put a
1.2 GB copy beside H2060 C10 and a 10.8 GB copy inside the H2077 package;
the review's dry runs avoided that only by passing `--staging` to a scratch
folder), and `publish_batch.py` does so for every component.

### The fix (proposed)

- Refuse a staging path that, after `resolve()`, is the source directory or
  an ancestor of it.
- Only ever remove a directory this tool made: `stage()` drops a marker
  file and removes an existing directory only when the marker is there or
  the directory is empty; anything else is a refusal naming the path.
- Move the default out of the export folder (a sibling, or a temp
  directory).
- One test per row above, on `tmp_path`.

Until then: always pass `--staging <a folder you can lose>`, never an export
or package folder.

---

## B26 — A geoid grid that cannot be fetched comes back as `inf`, and nothing checks it

**Kind:** fail-open — the guard built against a silent ZERO does not cover
a silent INFINITY. **Severity:** medium. A live run dies at request
encoding before any asset exists, which is an accident of the JSON encoder
and not a guard; a `--dry-run` exits 0 and prints `Infinity` as the height.
**Status:** OPEN.
**Sites:** `modules/cesium_placement.py:475-479` (`geoid_separation`: a
NaN-only guard), `:501-502` (`msl_to_ellipsoidal`), `:724-727` and
`:771-774` (`plan_placement`, both branches; `:721-723` checks the ECEF
conversion, not the height that leaves), `publish_cesium.py:502-503` (PROJ
network enabled unless `--no-geoid` or `--no-proj-network`).

`geoid_separation` builds its transformer with `allow_ballpark=False`, so
with PROJ network OFF a missing grid raises instead of returning 0. With
network ON the transformer builds — the grid is expected from the CDN —
and the failure moves to `transform()`, which does not raise: it returns
`inf`. The guard at `:476` is `separation is None or separation !=
separation`, a NaN test. `inf` passes it.

### Measured, 2026-10-01 (PROJ user directory redirected to an empty scratch folder; `PROJ_NETWORK_ENDPOINT=http://127.0.0.1:9`, a closed local port)

    grid hidden, network OFF   PlacementError: no EGM2008 geoid transformation is available ...
    grid hidden, network ON    geoid_separation returned inf
                               msl_to_ellipsoidal(-650.0, ...) -> (inf, inf)

`publish_cesium.py --dry-run` with DEFAULT flags on a synthetic projected
export, same environment — exit 0:

    INFO anchor lon=-169.046249 lat=-14.210270  depth -650.00 m + geoid N +inf m = ellipsoidal h inf m
    "position": [ -169.0462491714334, -14.21027017872663, Infinity ]

A live run would hand that body to `requests` (`publish_cesium.py:285`,
`json=body`), whose encoder refuses it: `InvalidJSONError: Out of range
float values are not JSON compliant` (encoder exercised offline, nothing
sent). So no asset is created — by luck. The failure is an uncaught
traceback after the whole staging pass, not a `PlacementError`; and
`--plan-json` (`:533-535`) writes `Infinity` to disk through the standard
`json` module without complaint.

This machine has the grid installed for both interpreters in use, so it
does not bite here today. It bites on a fresh machine, another interpreter,
or a ship with no route to cdn.proj.org — which is where this pipeline
runs.

Pinned, not fixed: `test_a_non_finite_geoid_never_becomes_a_finite_placement`
(projected), `test_geocentric_non_finite_geoid_never_becomes_a_finite_placement`
and `test_a_failed_grid_lookup_never_returns_a_finite_separation` accept a
refusal and otherwise require the bad value to stay visible. None of them
enshrines the `inf`; the last also pins the NaN guard that does exist.
`validate_cesium_assets.py` has its own guard (a non-finite N stops the
audit).

### The fix (proposed)

- `geoid_separation`: refuse anything not finite
  (`separation is None or not math.isfinite(separation)`), with the
  missing-grid remedy text plus "PROJ network is on but the grid could not
  be fetched".
- `plan_placement`: check the final height is finite on both branches
  before returning a plan — a second net, since a future geoid source can
  bypass the first.
- Then tighten the three tests to `pytest.raises(PlacementError)`.
- `publish_batch.py:151-153` passes no `--no-proj-network`; once the grid
  is a declared prerequisite it should. Until then pass it by hand.

---

## B27 — Two guards the publisher describes but does not have: the flight log is not consulted, and a shifted export is not noticed

**Kind:** missing guard — the check is documented, wired to an argument,
and never reached. **Severity:** medium, latent: no OBJ on this machine
triggers it, and when one does the asset lands kilometres to megametres
away with `--verify` confirming it (verify compares ion against the plan,
and the plan is what is wrong). **Status:** OPEN.
**Sites:** `modules/cesium_placement.py:357-366` (`resolve_to_global`
returns before `nav_envelope` is first used at `:386-387`), `:704-761` (the
geocentric branch; `isfinite` at `:721-723` is its only check), `:171-218`
(`parse_rsinfo` reads `<Model>` only), `:74-83` (`RSInfo` has no field for
the export settings); `publish_cesium.py:452-455`, `:508-515`;
`wildscan/session.py:709-719`.

**1. `--flight-log` is a no-op on every export with no matrix to
interpret.** Its help calls the nav envelope "a second, independent check
on the transformToModel reading", and that is all it is: `resolve_to_global`
returns the vertices untouched when the sidecar has no `transformToModel`
(`:357-360`) or an identity one (`:362-366`), and the envelope is only ever
compared inside the candidate-scoring loop further down. That covers every
geocentric export (identity) and every `georef_v2.py` product (no matrix)
— everything this campaign publishes. Measured, geoid stubbed: an
H2077-site ECEF mesh and an H2060-site UTM mesh, each planned with a nav
envelope from another ocean (E 500000-500100, N 100000-100100, alt -10..0),
are both accepted without a word. The wildscan planner pins `--flight-log`
"as the INDEPENDENT nav check" (`session.py:709-719`); on these exports it
checks nothing.

**2. A shifted or scaled export is not noticed.** RealityScan records an
export's anchor, rotation and scale in the sidecar's `<ModelExport
settingsAnchor=... settingsRotation=... settingsScale=...>`; `parse_rsinfo`
reads only `<Model>`. Sidecar census of this machine, 2026-10-01 (389
files under the Desktop dives' export and package folders, read-only): all
241 OBJ and 128 FBX sidecars carry anchor `0 0 0` and scale `1 1 1`, or —
the 16 written by `georef_v2.py` — no `<ModelExport>` at all; but **19 PLY
sidecars carry `settingsAnchor="6070869 1174903 1555610"`**, the H2060
dense-PLY preset's float32 shift. Shifted exports therefore exist in the
same trees, and are off the Cesium route only because `select_objs` takes
`*.obj`. `test_export_preset_applies_no_hidden_shift_or_scale` pins the
three stock presets at zero shift; nothing pins what a sidecar actually
says. Measured: a type-3 OBJ whose vertices are the mesh minus its ECEF
anchor, with a sidecar saying so (`settingsAnchor` = that anchor,
`settingsScale="0.5 0.5 0.5"`). `parse_rsinfo` keeps neither value and the
plan is accepted at lat 90.0000, ellipsoidal height -6,356,727 m — the
centre of the Earth — for a mesh whose site is 132.8053 E 7.5525 N at
-1,048 m.

### The fix (proposed)

- Run the nav check on the RESOLVED points whatever the transform was: for
  a projected export, the fraction of vertices inside the envelope
  (`_nav_score` exists) with a stated margin; for a geocentric one, project
  the anchor into the flight log's zone (its EPSG is in the filename, as
  `validate_cesium_assets.utm_epsg` reads it) and compare. A flight log
  that was passed and could not be used is an error, not silence.
- Give the geocentric branch a plausibility test of its own for runs with
  no log: height within about 12 km of the ellipsoid, anchor inside the
  declared project CRS's area of use.
- Parse `<ModelExport>` and refuse anything but anchor `0 0 0`, rotation
  `0 0 0`, scale `1 1 1`. Refusing is right; applying them would be a
  guess, for the same reason the `transformToModel` candidates are scored
  rather than assumed.
