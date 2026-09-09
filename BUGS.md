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
