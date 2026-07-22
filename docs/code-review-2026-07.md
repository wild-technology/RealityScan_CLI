# Code review & first-machine validation — July 2026

What changed in the RealityScan CLI layer, why each change was made, and
what the evidence was. Covers commits `d360002` through `724814a`
(2026-07-21/22).

Companion docs: `HANDOFF.md` (current state + checklist outcomes),
`CLAUDE.md` (the hard rules this work is bound by), `README.md`
(architecture).

---

## Why this review happened

The July 2026 overhaul rewrote the RealityScan execution layer — unified
`RealityScanCLI`, the shared `:run` delegate/wait pattern, per-instance
marker files, the RealityCapture → RealityScan rename. It was reviewed
adversarially and the findings were fixed. But it was written and
reviewed on Linux, and RealityScan is Windows-only, so **not one line of
the batch layer had ever executed against a real RealityScan install.**

`HANDOFF.md` said so explicitly and listed seven things to verify on
first run. This pass executed that checklist on the dual-5090 Windows
box using the repo's own harness (`testing/run_zone9_tests.py`), against
the zone_9 dataset.

The headline result: **the code was correct on paper and wrong in
practice in five distinct ways.** Every one of them was invisible to
static review, because each depended on either the runtime environment
or on RealityScan's actual (undocumented) behavior.

---

## Part 1 — Defects found by execution

### 1. Workflow scripts could not be launched at all

**Symptom.** The first smoke run died after two seconds with
`'AlignImagesFromFolder.bat' is not recognized as an internal or
external command`.

**Cause.** `RealityScanCLI.run_batch_script()` spawned
`['cmd', '/c', script_name]` with `cwd=SCRIPTS_DIR`, relying on cmd
resolving a bare script name from the working directory. Windows
disables exactly that when `NoDefaultCurrentDirectoryInExePath=1`, which
Git Bash sets. From a plain `cmd.exe` prompt the old code worked; from
any POSIX-style shell it could never work.

Switching to an absolute path exposed a second, worse bug: from a
checkout path containing spaces the run failed with `'C:\Users\jonat\RS'
is not recognized`. `cmd /c "C:\path with spaces\script.bat"` strips the
outer quotes under cmd's parsing rules — the exact failure mode
`HANDOFF.md` had predicted for the process trigger, in a different place.

**Fix.** Invoke the `.bat` by absolute path with no `cmd /c` wrapper at
all and let Python's `subprocess` do the quoting, which it does
correctly for batch files.

**Evidence.** Smoke test passes from both `...\RealityScan_CLI` and a
deliberately hostile `C:\Users\jonat\RS CLI space test\` copy.

### 2. `find` resolved to GNU find and scanned the disk

**Symptom.** After fix 1, the workflow hung. Twenty minutes in, the
process tree showed `cmd /c type ... | find` burning 820 seconds of CPU,
and the captured log was full of
`find: '/c/ProgramData/...': Permission denied`.

**Cause.** The `:run` subroutine counted lines in the results log with
`type "%ResultsLog%" | find /c /v ""`. Launched from Git Bash, `PATH`
puts `/usr/bin/find` (GNU findutils) ahead of `C:\Windows\System32\find.exe`.
GNU find given those arguments walks the entire filesystem instead of
counting lines — on every wait iteration.

**Fix.** Fully qualify `%SystemRoot%\System32\find.exe` in both workflow
scripts.

**Why it matters beyond this bug.** This is the second
environment-dependent defect in a row, and both were invisible to review
because review assumes a canonical environment. The pipeline is launched
from Python, which may be launched from anything.

### 3. Completion detection was fundamentally unsound

This is the most important finding, and the one with the widest blast
radius.

**Symptom.** Intermittent, non-deterministic failures. Commands appeared
to execute out of order; `-renameSelectedComponent` failed with
`No component selected [err:5605]`; sometimes the same script succeeded.

**Cause.** The `:run` subroutine treated **growth of
`results_<instance>.log` as proof that the delegated command had
finished**. That log is written by RealityScan's own
`appProcessAction=ExecuteProgram` trigger, and the design assumed one
line per delegated operation.

That assumption is false. RealityScan 2.2 fires the same trigger for
periodic internal processes. The results log from a single smoke run:

```
8:55:27.87 process 41063 finished with result code 0 in 0 seconds
8:55:28.01 process 41061 finished with result code 0 in 0 seconds
8:55:28.04 process 41064 finished with result code 0 in 0 seconds
8:55:47.16 process 20598 finished with result code 2181038335 in 17 seconds
8:55:47.34 process 41063 finished with result code 0 in 0 seconds
8:55:47.47 process 41064 finished with result code 0 in 0 seconds
```

PIDs 41061/41063/41064 recur constantly at zero duration — heartbeats,
not our work. So the wait loop exited as soon as *any* process
completed, typically a heartbeat within milliseconds, and the script
raced ahead while `-align` was still running.

**Fix.** Remove the log-growth gate entirely. `:run` is now
delegate → 2 s grace → `-waitCompleted` → 1 s grace → `-waitCompleted`,
then check the errors file. The double wait handles the documented
pickup race (`-waitCompleted` returns prematurely if the instance has
not yet dequeued the command); the grace periods make the first wait
land after pickup.

**The lesson.** The log-growth mechanism was *introduced by the previous
adversarial review* as a fix for the pickup race. It was a reasonable
inference from the documentation and it was wrong, because it depended
on an undocumented property of a third-party binary. Code review cannot
validate a contract with a closed-source executable; only execution can.
`CLAUDE.md` hard rule 2 already said "never infer completion from
process names" — the deeper rule is **never infer completion from an
event you cannot attribute to your own command.**

### 4. `-mergeComponents` cleared the component selection

**Symptom.** Even after fix 3, `-renameSelectedComponent "Merged"` still
failed with `No component selected [err:5605]`.

**Cause.** With a single component, `-mergeComponents` is a no-op — but
it still triggers an asynchronous re-reconstruction and leaves nothing
selected. The workflow assumed it would leave the merged component
selected.

**Fix.** Drop `-mergeComponents` and use `-selectMaximalComponent`
(documented, takes no parameters) before the rename.

### 5. XMP export silently wrote nothing — the metric was lying

**Symptom.** The workflow reported success, exported a component, saved
the project — and registered **0 of 32** images. Zero `.xmp` sidecars
existed. A direct CLI probe (`-load project -selectMaximalComponent
-exportXMP -quit`) exited **0** and wrote nothing.

**Cause.** Per the local Help (`allcommands.htm`), `-exportXMP` exports
"camera metadata of components created in the last alignment" and
respects `setMinComponentSize`, whose **default is 5** — and it is not
scoped to the selected component.

**Fix.** `-setMinComponentSize 1` + `-exportXMPForSelectedComponent`,
placed *after* component selection rather than immediately after
`-align`.

**Why this one is dangerous.** It was a **measurement** bug wearing the
costume of a reconstruction failure. Registration read 0%, which looks
exactly like "alignment doesn't work on this imagery." Had it not been
chased down, the obvious next move would have been to start tuning
alignment parameters against a metric that was structurally incapable of
reporting success. Any run whose success metric reads zero should be
treated as instrumentation-suspect until the instrument is verified.

### 6. `-align` was silently ignoring all custom alignment settings

**Symptom.** None — latent. `HANDOFF.md` flagged it as unverified.

**Finding.** `AlignZonesSequentially.bat` called
`-align "%AlignmentParams%"`, inherited from older code. **`-align`
accepts no parameters in RealityScan 2.x** (confirmed in the installed
Help and Epic's online docs; commands that do take a params XML —
`exportXMP`, `exportRegistration`, `loadBundler` — document it
explicitly). So all 28 tuned settings in `AlignmentParams.xml` were
being discarded: camera-prior enablement and weights, `Ultra` detector
sensitivity, the `Division` distortion model, feature caps.

**Fix.** Parse the `sfm*`/`lis*` keys out of the XML and apply each via a
delegated `-set` before a plain `-align`. Delegated commands queue FIFO
on the instance, so ordering is guaranteed and the sets need no
completion wait.

**Impact.** Zone alignments were running on stock settings. This is the
change most likely to alter real-world output quality.

### 7. Flight log: wrong CRS, and a false-failure on import

Two separate defects, both found while debugging the import step.

**Wrong coordinate system.** `FlightLogParams.xml` declared
`+proj=utm +zone=4 +datum=WGS84` / EPSG:32604 — UTM zone **4N**, stale
from an earlier project. NA173_H2103a is UTM **57S**. Corrected to
EPSG:32757 (`+proj=utm +zone=57 +south`). Georeferenced output would
otherwise have landed in the wrong zone *and* the wrong hemisphere.
**Check this per cruise.**

**False failure on import.** `-importFlightLog` reported a failed
process (`2181038335` = `0x820000FF`) and aborted the workflow, while
the application log said `Trajectory imported successfully.` The
underlying condition was `err:18002` — "The file contains 2624 images
which are not in the current scene" — a warning-class result raised
because the log covered the whole zone while the run used a subset. The
test runner now writes a flight log filtered to the images actually
staged. (Production runs are unaffected: `BatchDirectory` already writes
per-zone logs.)

### 8. Test harness defects

Not product code, but they blocked validation:

- `list_images()` only read the dataset root, while zone_9 ships as
  `camlower/ cammid/ camupper/ zeuss/` subfolders — so the harness saw
  zero images.
- The smoke subset used every-Nth stratified sampling, which produces 32
  frames with no mutual overlap. Alignment then depends on borderline
  component formation, making the smoke test a coin flip. Replaced with a
  contiguous block per camera; smoke went from 2/32 to 17/32 registered.

### 9. Flight-log discovery gap (pre-existing, `7e51210`)

With `Extract Images` active, `GeoreferenceImages` writes
`flight_log_*_UTM.txt` into `<output>/raw_images`, but `BatchDirectory`'s
fallback search only globbed `<output>` itself and would find nothing.
Now searches `raw_images` first, then the output root.

---

## Observed RealityScan 2.2 process result codes

Empirically collected during this pass — the app documents none of them.

| Code | Hex | Meaning as observed |
|---|---|---|
| 0 | — | Success |
| 1 | — | Benign. Emitted by routine successful operations (e.g. `-addFolder`). The `ErrorWriter.bat` whitelist of 0/1 is correct — checklist item 4 resolved. |
| 2181038335 | `0x820000FF` | Warning-class failure. Seen for `err:18002` (flight log references images not in the scene). |
| 2147942487 | `0x80070057` | `E_INVALIDARG`. Seen for `err:5605` (no component selected). |
| 3 | — | Crash; minidump written to the `-silent` path. |

---

## Part 2 — Changes enabled by the validation

Once the pipeline could actually run and *measure*, three things followed.

### Preprocessing, measured then baked in (`2b5e0c1`)

With a trustworthy registration metric, the harness ran the A/B it was
built for on 400-image subsets:

| variant | registered | rate |
|---|---|---|
| **clahe_c2_t8** | **239/400** | **59.8%** |
| clahe_c1_t8 | 214/400 | 53.5% |
| clahe_c3_t8 | 184/400 | 46.0% |
| clahe_c2_t16 | 167/400 | 41.8% |
| wb_clahe_c2_t8 | 135/400 | 33.8% |
| clahe_c4_t8 | 134/400 | 33.5% |
| clahe_c2_t4 | 124/400 | 31.0% |
| **baseline** | **0/400** | **failed to form any component** |

Preprocessing is not a marginal gain on this imagery — untouched frames
produced no component at all. CLAHE clip 2.0 / 8×8 tiles on the LAB L
channel is a sharp optimum, and gray-world white balance actively hurts.

This became `modules/preprocess_images/`, wired into `main.py` between
Georeference and Batch. It writes processed copies to
`<output>/preprocessed_images`, mirroring folder structure and
preserving filenames (flight-log matching is by filename); originals are
untouched so texturing can still use them. `BatchDirectory` prefers the
preprocessed folder when present. `testing/preprocess_variants.py` now
imports the transforms from the module rather than keeping a second
copy, per `CLAUDE.md` hard rule 6.

### `poses2flightlog.py` (`d4759d0`)

The USBL/DVL flight logs are position *estimates*; after alignment the
bundle-adjusted poses are better relative geometry. The XMP sidecars
hold those poses — but in a grid-anchored **local** frame, not UTM
(verified: `xcr:Position` values are small and local, and the XMP
`latitude`/`longitude` attributes are invalid, e.g. `179.98N`).

The tool fits the rigid local→UTM transform (Umeyama) against the
flight-log priors and rewrites the log in the same 13-column format,
plus a per-image residual CSV. On the zone_9 subset the residuals imply
a navigation error of **4.3 m median, 10 m p95** — comfortably inside
the 10 m accuracy the log claims for itself.

### Test coverage (`724814a`)

`testing/test_preprocess_module.py` asserts the properties the pipeline
depends on: mirrored folders, preserved filenames, **byte parity with
the canonical transform** (so the harness and the pipeline cannot
silently diverge), idempotent rerun, and that CLAHE actually altered
pixels.

---

## Part 3 — Deliberate non-changes

Things that look like omissions but are choices:

- **Orientations are not rewritten by `poses2flightlog.py`.** Six
  rotation-convention candidates were tested against the flight-log
  yaw/pitch/roll; none matched (best mean error ~77°). Writing
  orientations in an unverified convention would poison future priors,
  which carry weight 10. Positions only, until the convention is
  established by a controlled test.
- **Scale is locked at 1 in the pose fit.** The priors already pin scale
  during alignment, and fitting scale against noise-dominated navigation
  data collapses it (0.50 observed on zone_9). `--allow-scale` exists for
  diagnostics only.
- **Result code 1 stays whitelisted** in `ErrorWriter.bat`. It was
  inherited from the Epic sample and flagged for verification; observation
  shows routine successful operations emit it.
- **The repo layout was not restructured.** Flat root, documented in
  `README.md`; changing it would break documented paths for no benefit.

---

## Part 4 — Still unverified

Carried forward; do not assume these work:

1. **`AlignZonesSequentially.bat` has not been run end to end.** All
   validation used `AlignImagesFromFolder.bat`. The `-set`-based
   alignment-parameter fix was verified only by testing the XML parse
   (all 28 keys extracted correctly), not by a full zone run.
2. **Shutdown timing on large scenes.** Verified on small scenes only;
   the 15-minute bound on very large scenes remains untested.
3. **Multi-GPU parallel instances.** Single-instance GPU pinning via
   `rs_settings.json` was exercised; two instances on separate GPUs were
   not.
4. **Full-zone (2,656 image) run.** Phase 3 has not been executed;
   preprocessing results are from 400-image subsets.
5. **XMP rotation convention** (see Part 3).

---

## Generalizable lessons

1. **Review cannot validate a contract with a third-party binary.** The
   most serious defect was introduced *by* a careful review as a fix for a
   real race, and was falsifiable only by running it.
2. **Attribute your events.** An event-driven completion signal is only
   valid if you can prove the event belongs to your operation.
3. **A zero metric is an instrumentation bug until proven otherwise.**
   Registration read 0% because export was misconfigured, not because
   alignment failed.
4. **Environment-dependent defects need hostile environments.** Two bugs
   only appeared because the pipeline was launched from Git Bash, and one
   only from a path containing spaces. Both are now part of the test
   routine.
5. **Stale configuration outlives the project it came from.** The UTM 4N
   coordinate system rode along silently from a previous dataset.

---

## Commit index

| Commit | Change |
|---|---|
| `d360002` | CLI execution layer fixes (defects 1–8) + `HANDOFF.md` outcomes |
| `2b5e0c1` | `modules/preprocess_images/`, wired into `main.py`; transforms deduplicated |
| `24c0894` | Untrack a `__pycache__` directory |
| `7e51210` | Flight-log discovery in `raw_images` (defect 9) |
| `d4759d0` | `poses2flightlog.py` |
| `724814a` | Preprocessing module test; dataset seeds moved to `M:` |
