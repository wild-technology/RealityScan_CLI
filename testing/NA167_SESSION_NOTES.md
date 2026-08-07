# RealityScan 2.2 CLI — revised documentation & bug findings

Compiled from empirical testing on NA167_H2075 (2026-07-22/23) and
ON2026 (2026-08-04/07). Three sections: (1) the official documentation
for every command/setting we used, **revised** to say what actually
happens; (2) bug findings for CLI processing; (3) a consolidated
reference of operation ids, error codes and exit codes — kept here
because RealityScan truncates its own log on every instance boot, so
this document is the only durable record of them. Narrative/test matrix: `MERGE_TEST_PLAN.md`; repo state:
`HANDOFF.md`; raw results: `D:\na167_h2075\rs_test\merge_test\strategy_results.json`.

---

## Section 1 — Revised command & settings documentation

Format: **official** = what the local Help says; **revised** = what our
runs verified, including everything the Help leaves out.

### Instance & session control

**`-setInstanceName <name>` / `-delegateTo <name>|* <cmd>`**
- Official: named instances; delegate commands to a running instance.
- Revised: delegated commands are **queued FIFO** and the delegating
  process returns at hand-over, not completion. Instant commands
  (`-set`) can be fired without completion waits because FIFO guarantees
  ordering before the next queued operation.
- Revised (2026-08-04): the instance argument accepts **`*`**, meaning
  "the first available instance". This holds for `-delegateTo`,
  `-waitCompleted`, `-getStatus`, `-pauseInstance`, `-unpauseInstance`
  and `-abortInstance`. **Consequence: a RealityScan started from the
  GUI / Epic Games Launcher — which carries no `-setInstanceName` — is
  still fully drivable from the CLI via `*`.** Verified against a live
  GUI session: `-getStatus RS1` → exit 5, `-getStatus *` → exit 0.
  Caveat: `*` means *first available*, so it is ambiguous the moment two
  instances run. Use explicit names for multi-GPU work and reserve `*`
  for attaching to a single interactive session.

**`-waitCompleted <name>|*`**
- Official: block until the current process finishes.
- Revised: returns **prematurely** when issued before the instance picks
  up a queued command. Always: grace delay → wait → grace → wait
  (the `:run` pattern). Never infer completion any other way.

**`-getStatus <name>|*`**
- Official: errorlevel 0 iff the instance exists.
- Revised: correct for existence, but "gone" precedes process teardown
  by several seconds — **file handles (progress marker) are released
  after** getStatus already reports the instance dead. Retry
  marker-file deletion for up to ~60 s before concluding an instance is
  still alive.
- Revised (2026-08-04): it also **prints a live progress line to
  stdout**, which the Help does not mention:
  `id:0x5051 progress:11.1% runtime:575.04sec endEstimation:4579.16sec rev:93 lastError:0`
  (operation id, percent, elapsed, estimated remaining, revision, last
  error code). Capture it by redirecting stdout — RealityScan is a
  GUI-subsystem binary and does not reliably attach to a parent console.
  This is the **only error channel available for a GUI-launched
  instance**, which has no `ErrorWriter.bat` hook and therefore no
  `errors_<instance>.txt`. `ModelToFinal.bat` gates on `lastError:`
  for exactly this reason. Unverified: whether `lastError` is sticky
  across operations — do not read a non-zero code on the first gated
  command as proof that *that* command failed.

**`-headless -stdConsole -silent <dir> -writeProgress <file> <secs>`**
- Official: headless operation, crash-dump path, progress reporting.
- Revised: progress lines are `id frac elapsed remaining #tag`. The
  `#tag` matters: `#timeout` means the operation is internally stalled —
  elapsed keeps ticking and `remaining` becomes garbage. **`#timeout`
  lines are not progress**; treat them as stall evidence.

**`-quit`**
- Official: quit the instance.
- Revised: verify shutdown via `-getStatus` polling; closing large
  scenes takes time and the process outlives its getStatus visibility
  (see above).

### Project & image input

**`-newScene`** — as documented.

**`-addFolder <dir>`**
- Official: "Add all images to the specified folder. To include
  subdirectories, use `-set "appIncSubdirs=true"`."
- Revised: in our 2.2 build subfolders were included **without** setting
  the key (zone_13: wca/ + zeuss/ both imported). Set it explicitly
  anyway — the default is undocumented.

**`-add <file|list.imagelist>`**
- Official: import images from a path or an image list (text file,
  `.imagelist` extension, full paths one per line).
- Revised: works as documented; CRLF line endings fine. This is the
  mechanism for **shared-path components** (same image path appearing in
  multiple scenes' components), which merging by camera identity needs.
- Revised: adding images **auto-imports `<stem>.xmp` sidecars found next
  to them** — poses in leftover sidecars become priors silently. Clean
  exported sidecars before any re-run that must be independent.

**`-importFlightLog <log> <params.xml>`**
- Official: import a flight log with the given import parameters.
- Revised: rows referencing images **not in the scene** make the import
  report a failed process (err:18002, 0x820000FF) even though present
  rows import fine — filter logs to the scene's images. Name matching
  is by **basename** and finds images in subfolders (verified: bare
  filenames matched images living in `wca/` and `zeuss/`). The params
  XML's `CoordinateSystemFlightLog(Type)` keys must match the log's UTM
  zone — a wrong zone imports silently and misplaces everything;
  generate the XML from the flight-log filename's zone tag
  (`modules/flight_logs.write_flight_log_params`).

### Alignment & components

**`-align`**
- Official: align images.
- Revised: takes **no parameters** in 2.x (a params xml argument is
  silently ignored — apply `sfm*`/`lis*` keys via `-set` beforehand).
  With components already in the scene, `-align` is align/**update**:
  it adds new images to existing components and can fuse components.
  Runtime varies ~3× with scene character at equal image counts
  (zone_6 62–98 min vs zone_4 21–24 min, both ~1.5k frames, same GPU).
  Registration is independent of how images were added (folder vs
  imagelist: 95.2% vs 95.3% / 90.1% vs 91.0% on identical zones).

**`-setMinComponentSize <n>`**
- Official: threshold for component operations.
- Revised: also gates XMP export (default 5 silently skips small
  components). Set to 1 before exports.

**`-selectMaximalComponent` / `-renameSelectedComponent <name>`** — as
documented; the reliable selection primitive (see Section 2 on
`-selectAllComponents`).

**`-exportSelectedComponentDir <dir>`**
- Official: export selected component to a directory.
- Revised: file is named after the **component** (`Merged.rsalign`),
  not the scene — snapshot the directory before/after to identify new
  exports, or rename the component first.

**`-exportXMPForSelectedComponent`**
- Official: export camera metadata of the selected component as XMP.
- Revised: sidecars are written **next to the images** (wherever they
  live), named `<stem>.xmp`. `xcr:Position` is in a **grid-anchored
  local frame, not UTM** (fit local→UTM with `poses2flightlog.py`).
  Only registered cameras get pose entries — counting pose-bearing
  sidecars is a reliable registration census. Beware: these exports are
  auto-imported as priors by any later `-add` of the same images.

**`-importComponent <file.rsalign>`**
- Official: "Import a component from the component.rsalign file."
- Revised: **only import from the component's original export
  location.** A relocated copy imports into a permanent `#timeout`
  stall (≥6 h observed, no error, no dump). Component files are large
  (~0.7 GB per ~1.5k cameras, opaque `TBSM` binary — no readable
  camera list; use the XMP census for counts).

**`-mergeComponents`**
- Official: "Merge already created components. No new images are added."
- Revised (fully verified): operates on the scene's components (no
  "select all" command exists). **Fuses ONLY through cameras shared by
  identity** — same image path present in more than one component
  (D6: two half-zone components sharing 390 images → 56 min merge
  reconstruction → "Finalizing 1 component"). With zero shared cameras
  it exits SUCCESS and silently leaves components separate, under every
  flag combination — verify merges by camera count, never exit status.
  `sfmMergeGeoreferencedComponents=true` did NOT enable overlap-free
  merging headless (neither via -mergeComponents nor via -align), at
  least for flight-log-prior components. A working merge takes real
  time (~1 h for 1–4k-camera pairs), not seconds.

### Settings keys (`-set "key=value"`)

- Official table gives type/default only; prose scattered in
  alignsettings.htm.
- `sfmMergeGeoreferencedComponents` (false): merge georeferenced
  components "even without visual overlap". THE flag for flight-log
  pipelines; test results in matrix cells D1/D2.
- `sfmForceComponentRematch` (false): realign images/cameras using
  existing poses to find better connections.
- `sfmImagesOverlap` (Low/Medium/High): pair-search breadth.
- `lisPreferImagesAsFeatureSource` (false): laser-scan oriented feature
  source toggle; the GUI's per-input "Merge using overlaps / component
  features / all image features" trio has **no documented CLI key**.
- App keys verified in production use: `appQuitOnError`,
  `appAutoSaveMode`, `appProcessAction=ExecuteProgram`,
  `appProcessActionTime=0`, `appProcessExecCmd` (quote the exe path!),
  `appIncSubdirs`.
- Process-trigger result codes: 0 and 1 are both routine success
  (whitelist), 0x820000FF warning-class (e.g. err:18002),
  0x82000060 unknown/invalid command, 0x8000FFFF generic failure
  (see Section 2), 3 = crash with minidump at the `-silent` path.

---

## Section 2 — Bug findings: CLI processing

Numbered; RS = RealityScan-side behavior, INT = integration-side
(cmd/subprocess/orchestration). Each includes the mitigation now baked
into the repo.

**B1 (RS) — Relocated component import hangs forever.**
`-importComponent` on a `.rsalign` copied away from its export directory
enters `#timeout` and never returns/errors (observed 6 h+; watchdog
required). Mitigation: import in place; `MergeZoneComponents.bat` takes
a `.complist` of original paths; test drivers watchdog merge-class ops
(45 min) — alignment ops stay unbounded per repo rule.

**B2 (RS) — `-selectAllComponents` does not exist.**
Fails as unknown/invalid (0x82000060) despite appearing in older repo
scripts; Help lists only `selectComponent`/`selectMaximalComponent`.
All workflows now use the maximal-component pattern. (Legacy
`AlignZonesSequentially.bat` carried this dead command — fixed.)

**B3 (RS) — getStatus/teardown race.** Instance reports gone while its
process still holds `progress_<inst>.txt` for several seconds → next
workflow's marker clearing raced it. Mitigation:
`RealityScanCLI._clear_markers` retries for 60 s.

**B4 (RS) — `#timeout` progress defeats stall detection.** The stalled
state ticks its elapsed counter, so line-change–based activity detection
saw a "live" instance for 6 h. Mitigation: `_monitor_until_exit` treats
`#timeout`-suffixed lines as stall evidence; the 2 h stall warning now
names the hung-operation case.

**B5 (INT) — cmd splits unquoted `;` `,` `=` into separate .bat
arguments, and Python `subprocess` quotes only on whitespace/quotes.**
Consequences observed: a semicolon-joined component list arrived as two
arguments (merge cell failed "found 1"); `key=value` settings arrived as
two arguments → RS err:7155 ("Parsing setting key=value failed") →
**flags silently never applied** → and the parse failures hit the errors
marker, aborting the workflow. Mitigation: lists cross the boundary as
`.complist` files; settings cross as `key:value` and the bat converts
the colon. Rule: never pass delimited data as bat arguments.

**B6 (RS) — `0x8000FFFF` is generic; the app log is truncated per
boot.** Broken `-set` args and the zone_14 align failure report the
same code; the actual reason line exists only in
`%LOCALAPPDATA%\Temp\RealityScan.log`, which the next instance boot
destroys. Mitigation: snapshot the log immediately after any failure
(wave 1f drivers do per cell).

**B7 (RS) — XMP sidecar conventions.** RS reads/writes `<stem>.xmp`
only; `image.jpg.xmp` files are ignored silently (a batcher bug wrote
priors that way — no historical run ever loaded its priors). Exports
land beside images and are auto-imported as exact-pose priors on later
adds — cross-run contamination unless cleaned. Priors themselves are
not automatically beneficial: zone_13 A/B measured 96.3% (no priors) →
89.6% (priors on), so prior content must be validated per rig
(`batch_xmp_priors` now defaults off).

**B8 (RS, PARTIALLY RESOLVED) — zone_14 standalone align fails with
0x8000FFFF.** 2/2 reproduction at different elapsed times and path
forms. Input data formally exonerated (full decode, zero hash
duplicates, zero black/featureless frames, clean nav, normal motion
profile). **Localized 2026-07-23: B_sequential aligned the same 1,476
images successfully inside the growing 3-zone scene (94.6% overall,
single component) — the failure is specific to solving zone_14 as a
standalone scene, not to its data.** Practical workaround: grow a
failing zone from an already-aligned neighbor instead of aligning it
solo. Remaining open: the internal reason line (solo retry + app-log
snapshot still queued).

**B10 (INT) — LF-only .bat files break `call :label` nondeterministically.**
cmd's label search is byte-offset sensitive; with LF endings the same
`call :run` resolved ten times then failed ("The system cannot find the
batch label specified - run") at a later callsite. All workflow .bat
files must be CRLF; `.gitattributes` now pins `*.bat text eol=crlf`.

**B11 (RS) — observed during the first valid merge cell:** in-place
`-importComponent` takes ~2 s per 0.7 GB component (relocation was the
entire hang story); `-setMinComponentSize` is officially deprecated
("will be removed in the next release" warning); `-mergeComponents` on
two zero-overlap components logged "Finalizing 9 components" (fragment
behavior under analysis in the matrix cells).

**B10 (RS) — XMP export of an imported-component scene writes ORDINAL
sidecars.** `-exportXMPForSelectedComponent` on a component built from
`-importComponent`-ed .rsalign files writes `00000.xmp`, `00001.xmp`, ...
next to the images instead of `<stem>.xmp` (observed NA156 smoke merge,
2026-07-23). Count remains a valid registration census; per-camera
identity is only available when exporting from the original aligned
scene. Ordinal sidecars are inert as priors (no image has an ordinal
stem); `camera_registry.sanitize_and_census` deletes them quietly.

**B11 (RS) — the merge feature-source trio IS CLI-accessible.** Contrary
to the earlier "GUI-only" conclusion, `-setFeatureSource 0|1|2` (0=merge
using overlaps, 1=component features, 2=all image features) exists under
"Commands for Selected Images" and composes with `-selectImage
<imagePath|regexp> [set|union|sub|intersect|toggle]` /
`-selectAllImages` — per-camera merge-mode experiments are scriptable
(e.g. `-selectImage "P231C.*"` then `-setFeatureSource 2`). Also found:
`-exportLatestComponents <dir>` exports ALL components of the last
alignment (gated by `-setMinComponentSize`), and
`-selectComponentWithLeastReprojectionError` /
`-deleteComponent <idx>` / `-deleteAllComponents` exist.

**B9 (INT) — piped stdin quirks.** PowerShell native piping prepends a
BOM (first prompt answer corrupted) and CRLF endings reach `input()` as
trailing `\r`. Mitigation: all interactive prompts `.strip()` before
comparison; automated drivers answer prompts via a scripted `input`
instead of stdin pipes.

---

## Section 3 — Operation ids, error codes & exit codes

Consolidated because these were previously scattered across `FINDINGS.md`,
`CLAUDE.md` and `HANDOFF.md`, and because **the app log is not a durable
record of them** (see 3.5). Everything here is empirical, from
RealityScan **2.2.0.119430**. Epic documents none of it.

### 3.1 `-getStatus` `id:` field — operation ids

The `id:` in `id:<op> progress:<pct> ... lastError:<code>` identifies the
*running operation*, not an error. Mapping derived by pairing the id with
the command that was delegated and the app-log completion line.

| id | Operation | How it was pinned |
|----|-----------|-------------------|
| `0xffffffff` | **idle — nothing running** | always with `progress:0.0%` + `endEstimation:0.00sec` |
| `0x6` | `-exportSelectedModel` | metric OBJ export; log "Exporting Textured and Colored Mesh completed" |
| `0x7` | `-calculateTexture` | seen immediately after the workflow echoed "Texturing model" |
| `0x5034` | **UNCONFIRMED** | observed once at 37.2% immediately before a save; adjacent to `0x5035` but never isolated. Do not rely on it. |
| `0x5035` | `-save` (project) | checkpoint save; log "Saving Project completed in 169.264 seconds" |
| `0x5051` | Normal Detail reconstruction (`-calculateNormalModel`) | twice on ON2026: 3,499 s / 24 parts and 24,933 s / 163 parts, each ending "Reconstruction in Normal Detail completed" |

A GUI click produces the same id as the equivalent CLI command — these are
process ids, not CLI-specific. Treat them as build-specific.

### 3.2 Error codes

| Code | Meaning | Notes |
|------|---------|-------|
| `0x5076` | Envelope for `Processing failed: Operation aborted.` **and** `Operation warning.` | **Not specific.** Emitted for aborted reconstruction, aborted feature detection, aborted Correcting Image Colors, and the flight-log warning alike. Always printed twice in a row. Never diagnose from this alone. |
| `err:18002` (+ `0x820000FF`) | Flight log references images not in the scene | "The file contains 1350 images which are not in the current scene." The trajectory still imports fine. Warning-class. |
| `err:7185` (+ `CPP\0x5555`, `CPP\0x5555\0x557a`) | "Provided arguments don't match any overload for command '\<cmd\>'" | In practice this means **a path with spaces got split into several arguments** — not that the command is wrong. See the `[ON2026]` entries in the repo-root `FINDINGS.md`. |
| `err:7155` | "Parsing setting key=value '\<key\>' failed" | Settings passed as `key=value` through .bat args; use `key:value`. Finding 15. |
| `err:5605` | Rename failed — component selection was cleared | `-mergeComponents` async re-reconstruction races the next command. |
| `0x82000060` | Command does not exist | `-selectAllComponents` is not a 2.2 command. Finding 13. |
| `0x8000FFFF` | Generic "unexpected program state" | Covers both malformed `-set` args and genuine solve failures. Finding 16/17. |
| `0x80070057` | `E_INVALIDARG` | |
| `0x82010061` | Value left in `lastError` after a failed `-save` | Reported as `lastError:-2113863583`; see 3.3. |

### 3.3 `lastError` encoding and lifetime

- Printed as a **signed 32-bit decimal**. To read as hex, add 2³² when
  negative: `-2113863583 + 4294967296 = 2181103713 = 0x82010061`.
- `0` means "no error recorded for the most recent operation".
- **Sticky while idle, cleared when the next operation starts** — four
  consecutive idle polls kept a dead error, which vanished the instant the
  retried save began. Gate on `lastError != 0` **AND** `rev:` advancing,
  never on `lastError` alone (see the `[ON2026]` CLI-behavior entries in
  the repo-root `FINDINGS.md`).

### 3.4 Exit codes

| Surface | Code | Meaning |
|---------|------|---------|
| `RealityScan.exe` process | `0` | success |
| | *error's decimal code* | with `appQuitOnError=true` |
| | `3` | crash (minidump at the `-silent` path) |
| `-getStatus <name>` | `0` | instance exists |
| | `5` | no such instance (verified: `-getStatus RS1` on a GUI instance) |
| `appProcessAction` trigger `$(processResult)` | `0`, `1` | both success — `1` is emitted by routine operations such as `-addFolder`; whitelist both |
| | `0x820000FF` | warning class |
| | `0x80070057` | `E_INVALIDARG` |

### 3.5 The app log is not a durable record

`%LOCALAPPDATA%\Temp\RealityScan.log` is **truncated when an instance
boots**. Observed again 2026-08-07: a log holding every code in 3.1/3.2
from a 14-hour session was reduced to two "Loading Project completed"
lines by the next boot. Copy the log immediately after any failure — and
put codes in this document, because nothing else keeps them.

## Resume state (2026-07-24 — merge investigation COMPLETE)

For a fresh session picking this up: **the merge-strategy investigation
is finished.** Read `FINDINGS.md` (31 entries with provenance) and
`MERGE_STRATEGY_REPORT.md` (headline numbers + production
recommendation). Nothing is running on the machine.

- **Answered**: three zones fuse into one component two proven ways —
  B sequential growth (94.6%, 444 min, ≤60 GB) and C joint align
  (94.5%, 169 min, ~165 GB — does not scale); align-then-merge
  CONFIRMED via D6 ("Finalizing 1 component" from two half-zone
  components sharing 390 images); shared cameras are the ONLY merge
  glue headless (georef flag inert); merges are silent no-ops without
  glue — always verify by camera count.
- **zone_14**: RealityScan solver bug `MSS_STR001` (4/4 deterministic,
  data fully exonerated; evidence `testing/results/z14_forensic_rslog.txt`)
  — report to Epic; grow-from-neighbor is the workaround.
- **Loose ends for the next session** (ranked):
  1. Batcher production change: canonical-pool zones (imagelists or
     hardlinks) instead of per-zone copies, so components can merge
     (report §recommendation 4). Then wire zone-align → chain-merge into
     the alignment module.
  2. Multi-GPU parallel zone aligns (RS2 on GPU 1) — still untested.
  3. One-off unexplained: `%RealityScan%` expanded empty once after a
     56-min blocked waitCompleted (finding 31 parenthetical) — watch
     for recurrence; re-run the D6 merge if the fused .rsalign artifact
     is wanted (the verdict itself is solid from the app log).
  4. Optional wave-3 cells (`MERGE_TEST_PLAN.md` §4): overlap-breadth
     key, refine-then-merge with poses2flightlog.
- **Artifacts on D:**: `D:\na167_h2075\rs_test\merge_test\` — all
  components, per-cell logs + RS-log snapshots, `strategy_results.json`
  (every cell's raw record). The 18 zones and georeferenced flight log
  remain under `rs_test\`.
- Machine notes: RS1 on GPU 0 (`rs_settings.json`); an unrelated user
  COLMAP python job may be running — leave it alone.
