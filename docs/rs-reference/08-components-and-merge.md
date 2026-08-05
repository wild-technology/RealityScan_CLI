# Components: model, selection, export/import, and merge semantics

This document covers the RealityScan 2.2 **component** — what it is, every CLI command that
creates, selects, renames, deletes, exports or imports one, the `.rsalign` component file and
the `.complist` input file, and the full empirical record of **merge semantics**: what actually
fuses two components, what silently does not, how to verify a merge, and how to drive merging at
8,000+ camera scale. It does **not** cover alignment settings themselves (see
`03-settings-keys.md` for every `sfm*` key and `07-alignment.md` for align behavior,
registration rates and growth), XMP sidecar format and naming rules (see
`05-metadata-xmp-and-sidecars.md`), flight-log import / CRS / metric scale (see
`06-georeferencing-flightlogs-and-scale.md`), the XML parameter-file mechanism (see
`09-xml-parameter-files.md`), model generation from a merged component (see
`10-reconstruction-texturing-export.md`), or the delegation/`:run` execution layer and marker
files (see `01-cli-fundamentals.md`, `11-automation-patterns.md` and
`12-failure-modes-and-race-conditions.md`).

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

---

## Contents

1. [The component model](#1-the-component-model)
2. [Command reference — every component command](#2-command-reference--every-component-command)
3. [The `.rsalign` component file](#3-the-rsalign-component-file)
4. [The `.complist` input file](#4-the-complist-input-file)
5. [Merge semantics](#5-merge-semantics)
6. [Verification protocol — never trust exit status](#6-verification-protocol--never-trust-exit-status)
7. [Merge strategy at scale](#7-merge-strategy-at-scale)
8. [Runnable recipes](#8-runnable-recipes)
9. [Failure catalogue](#9-failure-catalogue)
10. [Open questions](#open-questions)

---

## 1. The component model

### 1.1 What a component is

A component is a group of images aligned together — one connected registration solution.
One alignment can produce many components; the Help lists the causes as: the photo collection
contains more than one disjoint object, weak texture, too few images, too large a change in
perspective, or too little overlap for automatic pairing
[OFFICIAL: appbasics/components, tutorials/mergecomponents].

A component is portable: "The RealityScan alignment component is, in fact, a small scene file.
It holds image lists, image properties, camera poses and so on." A project may hold any number of
imported components, and "Components can also contain duplicate images or points"
[OFFICIAL: appbasics/components].

Epic's stated purpose for the framework: split a large reconstruction into pieces, solve each,
merge later — "only the information which is relevant to connection of components is maintained,
rather than all input data" — and correct a faulty scene by exporting the bad part, fixing it in
a spare scene, reimporting, and re-aligning, at which point "RealityScan engine will apply fixes
from the corrected component" [OFFICIAL: appbasics/components]. That round trip is the sanctioned
rollback pattern and this repo adopts it as such [OFFICIAL: appbasics/components] +
[VERIFIED-as-adopted-policy: FINDINGS 2026-07-23, cells U15/U16 — see §3.5].

**Governing production intent recorded here:** a multi-component terminal state is a *correct*
outcome, not a failure. An underwater dive can contain two discrete physical features (e.g. bow +
main hull) that share zero imagery; no mechanism can or should fuse them. "As big as it can get"
is judged **per feature**, and no deletion/export/success logic may be size-based — only
containment-based deletion is legal [VERIFIED-as-owner-intent: FINDINGS 2026-07-24].

### 1.2 Component naming, and why names are not identity

| Fact | Tag |
|---|---|
| New components created by an alignment are named `Component N`. `N` is **unstable** across runs — values 5, 9, 0, 3, 4 were observed across two zones. | [VERIFIED: FINDINGS 2026-07-24] |
| `-importComponent X.rsalign` names the in-scene component `X` — the **file stem**. Two attempt directories that export the same stem therefore put two identically-named components into one assembly. | [VERIFIED: FINDINGS 2026-07-28] |
| `-selectComponent <name>` **does** resolve names in an assembled project whose components were renamed before export. It silently no-ops in zone scenes that were saved *before* the rename. | [VERIFIED: FINDINGS 2026-07-26] |
| Whether `-align` UPDATES an existing component in place (keeping its name) when it only grows is **not established**. | [OPEN: hardening cell U6, never run] |

**Consequence for automation:** rename deterministically *before* every export
(`<zone>_c<K>`, `<tag>_a<attempt>_c<K>`), and correlate a manifest to a scene component by
**image set**, never by name [VERIFIED-as-design: docs/MERGE_REWORK_RECOMMENDATIONS Q6].

### 1.3 Alignment fragmentation is nondeterministic

zone_1 (4,540 images, identical settings, identical sidecars, identical inputs) aligned to
**2 components / 4,391 cameras** in one run and **9 components / 4,392** in another. Total
registration is stable; component *structure* is not. **Component structure cannot be relied on
across runs — only manifest-tracked image sets can** [VERIFIED: FINDINGS 2026-07-24].

### 1.4 Small components

The GUI groups components below a threshold into one expandable "Small components" entity in the
1Ds view, configurable by three controls: *Include smaller than* (default **3** cameras),
*Exclude bigger than*, and *As small as a percentage of inputs*. A hover action deletes all small
components at once (undoable) [OFFICIAL: appbasics/smallcomponents].

This is a **1Ds-view display/bulk-delete feature and is separate from `-setMinComponentSize`**,
which is the *export/selection* gate with a default of **5**
[OFFICIAL: appbasics/allcommands vs appbasics/smallcomponents].
No CLI command for the small-components thresholds or for "delete all small components" appears in
`appbasics/allcommands` [VERIFIED-by-inspection of the master command table].
[OPEN: whether the small-components thresholds are exposed as `-set` keys — cheapest probe: change
each of the three controls in the GUI, then diff the app config, or type the likely key prefixes in
the console view and read the error.]

### 1.5 What the CLI cannot ask about a component (the blindness list)

These are hard limits of the 2.2 CLI, all established here. Every one of them shapes the
verification protocol in §6.

| Question | Answerable from the CLI? | Tag |
|---|---|---|
| How many components are in the scene? | **No.** There is no component-count query. The peel loop infers exhaustion from a tolerated `-renameSelectedComponent` failure on an emptied scene. | [UNDOCUMENTED / VERIFIED: FINDINGS 2026-07-24] |
| Which images are in component X? | **No.** `.rsalign` is opaque binary; membership must be reconstructed from XMP sidecar harvests. The **GUI** answers it directly — expand the component node in the 1Ds view and read the *Camera poses* tree node — so this is a CLI-only blindness, not a product limitation. | [VERIFIED: NA167_SESSION_NOTES §1] + [OFFICIAL: tutorials/mergecomponents] |
| What is component X's mean reprojection error? | Only indirectly, via `-selectComponentWithLeastReprojectionError` (which selects, it does not report). `-exportReport` may emit it but has never been driven headless here. | [INFERRED: from the command's presence in `appbasics/allcommands`] + [OPEN: hardening cells U7/U14] |
| Did the last `-mergeComponents` fuse anything? | **No.** Exit status is SUCCESS either way. | [VERIFIED: NA167 #23–26] |
| Is a component georeferenced / correctly scaled? | **No CLI query.** Verified in the GUI, or externally by fitting exported poses against nav. | [OPEN: hardening cell U7] |

---

## 2. Command reference — every component command

All names are literal and case-sensitive as typed. Official descriptions are compressed from
`appbasics/allcommands` (group "Alignment") [OFFICIAL: appbasics/allcommands]. On the command line every name takes a
leading `-`; inside the Help's table the names appear bare (`mergeComponents`, not
`-mergeComponents`) [OFFICIAL: appbasics/allcommands].

**Process IDs** in the "Verified delta" column are the values `-writeProgress`'s `algId` parameter
reports for the running operation, and come from the Help's table, not from measurement here
[OFFICIAL: tutorials/processids].

| Command | Params | Official description | Verified delta |
|---|---|---|---|
| `-selectMaximalComponent` | — | Select the largest component for further processing. | **Silently no-ops on an empty scene** (no errors marker). The reliable selection primitive. [VERIFIED: FINDINGS 2026-07-23] |
| `-selectComponent` | `componentName` | Select a component with the specified name (`componentName`) for further processing. | Resolves manifest names in an *assembled* project (components renamed before export); silently no-ops on names a scene does not carry. [VERIFIED: FINDINGS 2026-07-26] Process ID `21857 CLI_SELECT_COMPONENT` [OFFICIAL: tutorials/processids]. |
| `-selectComponentWithLeastReprojectionError` | — | Select the component with the smallest Mean error [pixels]. | Exists in this build. Not used by this repo (component choice is by camera count). [VERIFIED: NA167 B11] |
| `-renameSelectedComponent` | `newComponentName` | Rename the currently selected component. | On an **emptied** scene it fails `E_INVALIDARG 0x80070057` (decimal `2147942487`) "in 0 seconds" — that failure **is** the peel-loop exhaustion signal. An earlier observation recorded it silently no-opping instead; both terminals are handled — see §2.3. [VERIFIED: FINDINGS 2026-07-24] Process ID `21859 CLI_RENAME_SELECTED_COMPONENT` [OFFICIAL: tutorials/processids]. |
| `-deleteSelectedComponent` | — | Delete the currently selected component. | Exists; silently no-ops on an empty scene. [VERIFIED: FINDINGS 2026-07-23] Process ID `21863 CLI_DELETE_SELECTED_COMPONENT` [OFFICIAL: tutorials/processids]. |
| `-deleteComponent` | `index` | Delete a component by index. Indices start at **0**. | Exists in this build. Never used here — indices are unstable, names and maximal-selection are preferred. [VERIFIED: FINDINGS 2026-07-23] |
| `-deleteAllComponents` | — | Delete all components. | Exists in this build. [VERIFIED: FINDINGS 2026-07-23] |
| `-setMinComponentSize` | `size` | Minimal component size for export via `exportLatestComponents` and `exportXMP`. Default **5**. | **DEPRECATED** — the app logs "will be removed in the next release" — but still **required**: without it, components under the default 5 are silently excluded from selection AND from XMP export. Set to `1` before any census export. [VERIFIED: NA167 B11, FINDINGS 2026-07-24] |
| `-exportSelectedComponentDir` | `folderName` | Export the selected component into a folder as a `.rsalign`. | **The file is named after the COMPONENT, not the scene.** Rename first, or snapshot the directory before/after. `-renameSelectedComponent X` → `X.rsalign`. [VERIFIED: NA167_SESSION_NOTES §1; cells U15/U16 2026-07-23] |
| `-exportSelectedComponentFile` | `fileName` | Export the selected component to a named `.rsalign` file. | Not used by this repo (the `Dir` form is). Untested here. [INFERRED: it is the naming-safe alternative to the Dir form; settled by one export.] |
| `-exportLatestComponents` | `folderName` | Export components created in the **last alignment** as `.rsalign` into a folder; gated by `setMinComponentSize`. | Exports **ALL** components of the last alignment, not just the maximal one — the older maximal-only export was unnecessary loss. [VERIFIED: allcommands sweep + production, 2026-07-23] |
| `-importComponent` | `component.rsalign` | Import a component from the `component.rsalign` file. | **Only from the ORIGINAL export directory** — see §3.3. In place: ~2 s per 0.7 GB. [VERIFIED: NA167 B1/B11] Process IDs `20594 IMPORT_COMPONENT`, `20597 IMPORT_COMPONENT_STRUCTURE` [OFFICIAL: tutorials/processids]. |
| `-mergeComponents` | — | Merge already created components. **No new images are added** to the existing components. | The centerpiece — see §5. Fuses only through image **content**; silent no-op otherwise; verify by census, never exit status. [VERIFIED: NA167 #23–26/#30/#31, FINDINGS 2026-07-24] |
| `-update` | — | Update all components and models by a **rigid transformation** to fit the actual constraints and control points. | A similarity/rigid fit applied *after* reconstruction. It can rotate or rescale a component; it cannot stiffen or repair geometry. This is the step that georeferences a freshly merged component. [VERIFIED: FINDINGS 2026-07-26] Process ID `65542 UPDATE_CONSTRAINTS` [OFFICIAL: tutorials/processids]. |
| `-setCamerasGravityDirection` | `componentID` (optional) | If images' XMP carries `xcr:Gravity`, rotate the component so `-z` follows gravity. Sparse cloud only, not the mesh. | Never exercised here. [OPEN: no ROV imagery in this repo carries `xcr:Gravity`; probe = add the tag to one sidecar and re-align.] |
| `-exportXMP` | `params.xml` (optional) | Export camera metadata of components created in the **last alignment** as XMP; components must satisfy `setMinComponentSize`. | Writes **stem-named** `<stem>.xmp` beside the images, in every observed context. This is the only identity-preserving census. [VERIFIED: FINDINGS 2026-07-23, B10 final form] |
| `-exportXMPForSelectedComponent` | — | Export camera metadata of the **selected** component as XMP using current settings. | Writes **ordinal** sidecars `00000.xmp`, `00001.xmp`, … in every observed context. Count is a valid census; identity is lost. [VERIFIED: NA167 B10, four consistent datapoints] The Help documents only the *location* — "XMP files are stored in the same folder as the respective images" — and gives **no naming rule at all** for either XMP command, so ordinal-vs-stem is [UNDOCUMENTED]. [OFFICIAL: appbasics/allcommands] |

### 2.1 `-selectAllComponents` DOES NOT EXIST

`-selectAllComponents` fails as an unknown/invalid command, result code `0x82000060`. It had
lived unnoticed in `archive/legacy_scripts/AlignZonesSequentially.bat`
[VERIFIED: NA167 #13 / B2, FINDINGS 2026-07-23]. The Help's master command table lists exactly
three component-selection commands: `selectComponent`, `selectMaximalComponent`,
`selectComponentWithLeastReprojectionError` [OFFICIAL: appbasics/allcommands].

**What to use instead:**

| Intent | Correct CLI |
|---|---|
| Operate on every component | Nothing — `-mergeComponents` and `-align` already act on **all** components in the scene. No pre-selection exists or is needed. [VERIFIED: MergeZoneComponents.bat, in production] |
| Export every component | `-setMinComponentSize 1` then `-exportLatestComponents <dir>` (align-produced components only) |
| Enumerate every component | The destructive **peel loop**: `-selectMaximalComponent` → rename → export → census → `-deleteSelectedComponent`, repeat (§6.3) |
| Delete every component | `-deleteAllComponents` |

### 2.2 Legacy / Help-prose-only spellings — do not use

| Spelling | Where it appears | Status |
|---|---|---|
| `-exportComponent` | `tutorials/commandline_1` examples only (`-selectMaximalComponent -exportComponent %MyPath%\max`) | Absent from the master table in `appbasics/allcommands`. [INFERRED: a stale pre-2.x name left in a tutorial example; never invoked here, so its non-existence is not proven] Use `-exportLatestComponents` / `-exportSelectedComponentDir` / `-exportSelectedComponentFile`. |
| `-minComponentSize` | one `tutorials/commandline_1` example | Master-table name is `-setMinComponentSize`. [INFERRED: same stale-example hypothesis; untested] |
| `-selectAllComponents` | older third-party/legacy scripts | Proven not to exist (`0x82000060`). [VERIFIED: NA167 #13 / B2] |

### 2.3 Empty-scene behavior and the peel terminal

`-selectMaximalComponent` **silently no-ops on an empty scene and writes no errors marker**
[VERIFIED: FINDINGS 2026-07-23]. Loop terminals must therefore never be built on "did an error
appear?" alone.

**[CONTRADICTED — two in-repo observations disagree about `-renameSelectedComponent` on an
emptied scene, and both are retained because production depends on handling both]:**

| Date | Observation |
|---|---|
| 2026-07-23 | "selectMaximalComponent / renameSelectedComponent / deleteSelectedComponent silently no-op on an empty scene (no errors marker) — loop terminals must be file-existence checks, not error checks" [VERIFIED: FINDINGS 2026-07-23] |
| 2026-07-24 | With the scene emptied, `-selectMaximalComponent` no-ops and the *following* `-renameSelectedComponent` **fails** `E_INVALIDARG 0x80070057` (`2147942487`) "in 0 seconds", observed on the smoke E2E [VERIFIED: FINDINGS 2026-07-24] |

Neither has been re-run to settle which condition produces which — a *fresh* empty scene and a
scene *emptied by deletion* may not behave the same
[OPEN: O-14 — cheapest probe is `-newScene`, then `-selectMaximalComponent` +
`-renameSelectedComponent x`, then read the errors marker. ~1 min].

Because there is no component-count query, **the tolerated rename failure IS the exhaustion
signal** when it fires. This repo's `MergeZoneComponents.bat` is written to terminate on **either**
behaviour, which is why the peel loop is robust:

- `:run_peelrename` exits `2` when the errors marker is non-empty **and** contains `2147942487`,
  moving the marker to `expected_peelend_<instance>.txt` as evidence; any other error content is a
  hard failure (exit `1`) [VERIFIED-by-inspection: MergeZoneComponents.bat lines 262–289].
- If the marker is empty instead (the 2026-07-23 behaviour), `:run_peelrename` returns `0` and the
  next line — `if not exist "%output_dir%\%merged_name%_c%peel_index%.rsalign" goto :after_export`
  — is the file-existence terminal [VERIFIED-by-inspection: MergeZoneComponents.bat line 244].

`AlignZone.bat`'s identity loop uses only the file-existence form (an empty harvest directory, then
a missing `.rsalign`) and tolerates no error at all
[VERIFIED-by-inspection: AlignZone.bat lines 138–143].

### 2.4 Adjacent commands that are component-scoped but documented elsewhere

| Command | Scope note | Tag |
|---|---|---|
| `-correctColors` `layerName` | "Run color correction for all layers or a specified layer (`layerName`) **in the selected component**." Component selection therefore gates it. Never driven here. | [OFFICIAL: appbasics/allcommands] |
| `-selectLargestModelComponent` | **Model** topology, not alignment components — selects triangles of the largest connected mesh component. It is what makes a rigid-glue container dangerous downstream (§5.7). | [OFFICIAL: appbasics/allcommands] |
| `-exportRegistration` | Exports registration in a chosen format (the GUI dialog whose first save-as type is the `.rsalign` component). **Blocks forever headless without a params XML.** | [VERIFIED: FINDINGS 2026-07-21] |
| `-setFeatureSource` `0\|1\|2` | Per-*image-selection* control of which features a later align uses when integrating components — see §5.3. | [OFFICIAL: appbasics/allcommands] + [VERIFIED: NA167 B11] |

Other component-related process IDs in the Help's table, none of which map to a documented CLI
command: `21025 EXPAND_CONNECTED_COMPONENTS_SELECTION`, `21026 CALCULATE_COMPONENTS_METADA` (sic),
`21030 SELECT_MAX_CONNECTED_COMPONENTS`, `41062 EXPORT_REGISTRATION_COMPONENT`
[OFFICIAL: tutorials/processids]. There is **no process ID for a merge operation** in the table
[VERIFIED-by-inspection of the full processids table].

---

## 3. The `.rsalign` component file

### 3.1 Format, size, opacity

| Property | Value | Tag |
|---|---|---|
| Extension | `.rsalign` — the Help calls the format "RealityScan Alignment Component" | [OFFICIAL: appbasics/allcommands] |
| Legacy extension | `.rcalign` is carried in this repo's discovery list (`COMPONENT_EXTENSIONS = ('.rsalign', '.rcalign')`, merge_zones.py line 74) and CLAUDE.md documents it as still readable, but **no `.rcalign` has ever been imported here** and the 2.2 Help never mentions it | [INFERRED: repo policy + code, not an observation] |
| Content | A small scene file: image lists, image properties, camera poses; control points placed on the component are exported with it | [OFFICIAL: appbasics/components] |
| Encoding | Opaque binary, magic `TBSM` — **no readable camera list** | [VERIFIED: NA167_SESSION_NOTES §1] |
| Size scaling | **~0.7 GB per ~1,500 cameras** | [VERIFIED: NA167_SESSION_NOTES §1] |
| Membership recovery | Impossible from the file. Must come from the XMP census captured at align time (§6) | [VERIFIED: NA167 B10] |

The GUI equivalent of the export is ALIGNMENT ▸ Export ▸ **Registration**, choosing the first
save-as type ("RealityScan alignment component"), which is the only type that "preserves all
features of the application" [OFFICIAL: appbasics/components].

Selection semantics, stated exactly as the Help states them, because they are the trap
[OFFICIAL: appbasics/components]:

- "Any subset of aligned cameras can be exported as a component."
- "To export **all** components, leave this selection empty."
- "A complete component is exported if the current selection is empty **or** it is a single camera
  selection."
- "If there are control points placed on the component, they will also be exported with the
  component."

So a **stray active image selection silently narrows or empties the export**, and under `-silent`
the confirming dialog is auto-answered: an XMP export completed in **0.057 s instead of 20.5 s**
after a flight-log import left its matched images selected
[VERIFIED: FINDINGS 2026-07-23] [UNDOCUMENTED: the Help nowhere warns that `-importFlightLog`
leaves a selection behind].
**Always `-deselectAllImages` before any component or XMP export.**

### 3.2 Export names the file after the COMPONENT, not the scene

`-exportSelectedComponentDir <dir>` writes `<componentName>.rsalign` into `<dir>`. The scene name
is irrelevant. Rename first, or snapshot the directory before/after to identify the new file
[VERIFIED: NA167_SESSION_NOTES §1; U15/U16 PASS 2026-07-23].

```bat
:: Deterministic export: rename, then export.
call :run -deselectAllImages         || goto :fail
call :run -setMinComponentSize 1     || goto :fail
call :run -selectMaximalComponent    || goto :fail
call :run -renameSelectedComponent "zone_1_c0"                         || goto :fail
call :run -exportSelectedComponentDir "F:\na156_h2024_v2\aligned_components\zone_1" || goto :fail
:: -> F:\na156_h2024_v2\aligned_components\zone_1\zone_1_c0.rsalign
```

### 3.3 Import: the hard rule about location

> **`-importComponent` works only from the component's ORIGINAL export directory.**

A `.rsalign` copied or moved elsewhere imports into a **permanent `#timeout` stall**: no error, no
minidump, no completion. Observed ≥ 6 hours. The stall is invisible to line-change stall detection
because `#timeout` progress lines keep ticking their elapsed counter
[VERIFIED: NA167 #11/#12 / B1/B4, FINDINGS 2026-07-23; CLAUDE.md hard rule 7].
This is the highest-severity trap in the component API and it is **entirely undocumented**
[UNDOCUMENTED: no Help coverage of relocation].

In place, import is cheap: **~2 s per 0.7 GB component** [VERIFIED: NA167 B11, 2026-07-23].

Mitigations in force here:
- Workflows take a `.complist` of **original** paths rather than scanning a staging folder (§4).
- `merge_zones.load_inputs` accepts complist entries that live outside `--components_root`
  precisely so a hull from an earlier run can stay at its original export location
  [VERIFIED-by-inspection: merge_zones.py lines 130–156].
- Merge-class operations are watchdogged at 45 min in test drivers; alignment operations stay
  unbounded per repo rule [VERIFIED: NA167 B1 mitigation].

`appCopyImportedComponentsToCache` (bool, default `false`) is the one setting that plausibly
interacts with this behavior [OFFICIAL: tutorials/setkeyvaluetable]; it has **never been swept**
here [OPEN: §Open questions].

### 3.4 Import names the component after the file stem

`-importComponent X.rsalign` creates an in-scene component named `X`. (The GUI equivalents are
WORKFLOW ▸ Import Metadata ▸ **Component**, or dragging the file into the 1Ds view; an imported
component carries a small star icon there. A control point arriving with an imported component
whose name collides with an existing one but whose placement differs "will be imported with the
imported component's name as a suffix" [OFFICIAL: appbasics/components].)

Two attempt directories
exporting the same stem therefore place two identically-named components into one assembly, and
name-resolved later steps (`-selectComponent`, model naming, `-reprojectTexture`) then cross
components with a clean exit status [VERIFIED: FINDINGS 2026-07-28 and 2026-07-25].

This is why `merge_zones.fused_export_name()` embeds the attempt number:

```python
def fused_export_name(tag: str, attempt_no: int) -> str:
    return f'{tag}_a{attempt_no}'          # -> cluster_0_a2_c0.rsalign
```

`peel_index` restarts at 0 every attempt, so without the attempt number two accepted fusions in
one cluster both claim `<tag>_m_c0`: the manifest validator raised "duplicate component identity"
and killed one H2024 run, and the second silently clobbered the first's lineage
[VERIFIED: FINDINGS/merge_zones.py comment, 2026-07-28].

### 3.5 The component round trip is a sanctioned rollback

Export the faulty part → import it into an empty scene → fix it (control points, more images,
constraints) → import it back into the original scene → `-align`, which "will apply fixes from the
corrected component" [OFFICIAL: appbasics/components]. Adopted here as the rollback pattern; the
`.rsproj` bundle is **byte-stable across load/delete/export cycles when the session quits without
saving** (hash-verified twice), which is what makes the destructive in-session peel safe
[VERIFIED: cells U15/U16, FINDINGS 2026-07-23].

---

## 4. The `.complist` input file

### 4.1 Format

A plain-text file, one **absolute** `.rsalign` path per line, extension `.complist`:

```
F:\na156_h2024_v2\aligned_components\zone_2\zone_2_c0.rsalign
F:\na156_h2024_v2\aligned_components\zone_3\zone_3_c0.rsalign
F:\na156_h2024_v2\aligned_components\zone_5\zone_5_c0.rsalign
```

Rules established here [VERIFIED-by-inspection: MergeZoneComponents.bat lines 68–81;
merge_zones.py lines 817–821]:

| Rule | Detail |
|---|---|
| Detection | `MergeZoneComponents.bat` switches to list mode iff `%1` ends in `.complist` (`if /i "%components_dir:~-9%" == ".complist"`); otherwise `%1` is treated as a folder and every `*.rsalign` in it is imported. |
| Line endings | Written CRLF (`newline='\r\n'`) by the driver; `for /f "usebackq delims="` reads either. |
| Encoding | UTF-8 **without BOM**. |
| Existence | Every entry is existence-checked before the instance boots; a missing file aborts with exit 1 via `goto :argfail`. |
| Count guard | `merge` and `align` modes require ≥ 2 components; `assemble` mode requires ≥ 1 (a fully-converged single-feature dive must still be able to produce its assembly project). |
| Paths | Must be the components' **original export locations** (§3.3). This is the entire reason the file exists. |

**BOM hazard:** `Set-Content -Encoding utf8` in Windows PowerShell 5.1 writes a BOM, and a BOM on
line 1 of a `.complist` silently invalidates the first entry — `merge_zones` read
`\ufeffF:\...\zone_1_c6.rsalign`, found no manifest for it, and aborted with "complist entries
without manifests". Python's `encoding='utf-8'` writes no BOM. From PowerShell use
`[System.IO.File]::WriteAllLines($p,$lines,(New-Object System.Text.UTF8Encoding($false)))`.
Verified by reading the first three bytes (239, 187, 191)
[VERIFIED: FINDINGS 2026-07-27].

### 4.2 Why lists must cross the `.bat` boundary as files

`cmd` splits unquoted `;` `,` `=` into separate batch arguments, and Python's `subprocess` quotes
only on whitespace. Two production consequences were observed:

1. A semicolon-joined component list arrived as **two** arguments — the merge cell aborted with
   "found 1".
2. `key=value` settings arrived as two arguments; RealityScan logged
   `Parsing setting key=value 'sfmMergeGeoreferencedComponents' failed [err:7155]` and
   `'false' failed`, meaning **no flag cell before wave 1f had ever applied its flags** — and the
   parse errors landed in the errors marker, spuriously aborting the workflows that carried them.

[VERIFIED: NA167 #15 / B5, FINDINGS 2026-07-23; CLAUDE.md hard rule 8]

**The rule:** lists cross as files (`.complist`, `.imagelist`); settings cross as `key:value` and
the `.bat` converts the colon back to `=` immediately before `-set`:

```bat
:applySet
set "kv=%~1"
set "kv=%kv::==%"
%RealityScan% -delegateTo %RS_INSTANCE% -set "%kv%"
exit /b 0
```

---

## 5. Merge semantics

The Help's list of merge mechanisms is correct as far as it goes. Two things it does not give you:
the **actual fusion criterion** — image *content* overlap — appears nowhere in it (§5.2), and one
capability it explicitly promises, `sfmMergeGeoreferencedComponents`, has never been reproduced
headless here (§5.3). Everything below is what the CLI does, measured.

### 5.1 The mechanisms the Help offers

[OFFICIAL: tutorials/mergecomponents] lists five ways to connect a split scene:

| Mechanism | Help statement | CLI form | Status here |
|---|---|---|---|
| Run alignment again | "RealityScan will first use special algorithms designed for merging components." | `-align` (with components present) | **Works** — align/update: adds new images to existing components AND can fuse them [VERIFIED: NA167_SESSION_NOTES §1] |
| Merge Components tool | "no new images are added to the existing components" | `-mergeComponents` | **Works, conditionally** — see §5.2 |
| Control Points | ≥ 4 CPs each assigned to more than one image in every component; "Connect two components with any 6 control points" | `-importControlPointsMeasurements`, `-editControlPointSelection`, then `-align` | **Never exercised headless here** [OPEN: O-10] |
| Ground Control Points | ≥ 3 GCPs assigned to images in different components, ≥ 5 assignments; georeferences components to a common space, then align "will automatically try to improve accuracy by finding additional tie points" | `-importGroundControlPoints`, then `-align` | **Never exercised headless here** [OPEN: O-10] |
| Adding More Images | "one of the faster options" | `-add` / `-addFolder`, then `-align` | **Works** — the sequential-growth strategy (§7.1) |

[OFFICIAL: tutorials/mergecomponents_cp, tutorials/mergecomponents_images] for the CP/GCP counts
and the add-images path.

**Why the CP/GCP rows are `[OPEN]` and not simply "unused":** the CLI has no command that *places*
a control point on an image — the interactive act the tutorials describe. The only headless routes
into a scene's control points are `-importControlPointsMeasurements cpmFileName [params.xml]`,
`-importGroundControlPoints gcpFileName [params.xml]`, and `-detectMarkers [params.xml]`
(automatic marker detection), each of which needs a settings XML exported once from the matching
GUI dialog. `-editControlPointSelection "key=value"`, `-selectControlPoint`, `-renameControlPoint`,
`-deleteControlPoint index` and `-defineDistance` then manipulate what exists
[OFFICIAL: appbasics/allcommands]. Nothing in that chain has been exercised in this repo
[OPEN: O-10].

### 5.2 The governing rule: **fusion is CONTENT-driven**

> **Content overlap ⇒ fusable by either mechanism, with or without scene georeferencing
> constraints. Zero content overlap ⇒ silent no-fuse, regardless of flags, mechanism or path
> form.**
> [VERIFIED: D7 probe wave, `testing/probe_d7.py`, FINDINGS "D7 RESOLVED", 2026-07-24]

The evidence, in the order it was obtained:

**(a) Zero shared cameras never fuse — universal and silent.** NA167 D-cells isolated
mechanism × flag × path form on the `zone_6` + `zone_4` pair (which never see the same seafloor):

| Cell | Mechanism | Flags | Result |
|---|---|---|---|
| A1_merge (wave 1f) | `-mergeComponents` | defaults | No fuse — maximal component = zone_6 exactly, 1,533 cams |
| D1_geo_merge | `-mergeComponents` | `sfmMergeGeoreferencedComponents:true` | No fuse — 1,533 |
| D2_geo_rematch_align | `-align` | georef `true` + `sfmForceComponentRematch:true` | No fuse — 1,533 |
| D3_align_sharedpath | `-align`, shared-path components | both flags pinned `false` | No fuse — 1,534 |

Every cell exited **SUCCESS**; each took ~17–21 min dominated by boot/import/export overhead
[VERIFIED: NA167 #26, MERGE_TEST_PLAN wave 2, 2026-07-24].

**(b) Shared cameras DO fuse — the positive proof.** Cell D6: `zone_6` split into two 1,000-image
halves sharing **390 images**, aligned solo to 749 and 342 cameras, imported into a fresh scene,
`-mergeComponents` with both flags pinned `false` → **56 minutes of merge reconstruction ending in
"Finalizing 1 component"** [VERIFIED: NA167 #31 / D6, 2026-07-24].

**(c) Path identity is sufficient but NOT necessary.** The D7 probe used `zone_c` (78 cams) and
`zone_d_c0` (42 cams) built from disjoint image sets — **zero shared basenames, zero shared
paths** — that nonetheless view the same wreck strip:

| Cell | Pair | Mechanism | Union log + `-update`? | Result |
|---|---|---|---|---|
| D7b | zone_c + zone_d_c0 | `-mergeComponents`, georef `true`, prior `true` | **NO** | **FUSED**, census 120 = 78+42 exact, "Finalizing 1 component", 70 s |
| D7a | same | same | YES | FUSED, 120, 57 s |
| Q9a | mini_a_c0 (118) + mini_b_c2 (62) | `-align`, `sfmForceComponentRematch:true` | NO | FUSED, 180, 68 s |
| D7c | same | `-mergeComponents`, georef `true`, prior `true` | YES | FUSED, 180, 93 s |

[VERIFIED: MERGE_TEST_PLAN "D7 probe wave", FINDINGS 2026-07-24]

**(d) The reconciliation.** D1–D3 never fused because those pairs had zero *content* overlap.
They are consistent with the rule, not contradictory
[VERIFIED: D7 probe wave, testing/probe_d7.py, FINDINGS "D7 RESOLVED" 2026-07-24]. The union flight log remains **required to georeference the merged
result** but plays no role in fusion — the earlier "union log + `-update` is what enabled the
duplicate-path merges" hypothesis is **refuted**
[SUPERSEDED: candidate discriminator recorded 2026-07-24 morning, refuted the same day].

**(e) Two earlier statements now carry SUPERSEDED status but are retained**, because they were the
correct reading of the NA167 evidence and because the shared-camera path is still the only one
`-mergeComponents` can use *deterministically*:

- "Shared cameras are the ONLY merge mechanism verified to work headless" — **sufficient, not
  necessary** [SUPERSEDED: by D7, 2026-07-24].
- "Camera identity is path identity" — **sufficient, not necessary** [SUPERSEDED: same].

The merge-rung admission gate in `merge_zones.py` still requires the shared-image graph to
**span** the subset (§7.4), for a different reason: a merge rung glues *everything* in the scene
indiscriminately, so identity connectivity is the safety property, not the fusion mechanism
[VERIFIED-as-design: FINDINGS 2026-07-28].

### 5.3 `sfmMergeGeoreferencedComponents` — documented capability never observed headless

| | |
|---|---|
| **Docs claim** | "When multiple components are created and each is georeferenced, enabling this setting allows them to be merged even without visual overlap." Type `bool`, default `false`. [OFFICIAL: appbasics/alignsettings; tutorials/setkeyvaluetable] |
| **Observed** | With `sfmMergeGeoreferencedComponents=true`, **neither** `-mergeComponents` nor `-align` produced an overlap-free merge for flight-log-prior components. Cells D1 (merge, flag on, zero-overlap pair) → no fuse, 1,533 = zone_6 alone. D2 (align, georef true + rematch true) → no fuse. [CONTRADICTED: NA167 wave-1f/D1/D2, 2026-07-24] |
| **How observed** | Pose-XMP camera census of the resulting maximal component, per cell, with the swept keys pinned in every cell (values persist across instance restarts) and pose sidecars deleted between cells. [VERIFIED: MERGE_TEST_PLAN §3] |
| **Caveat that keeps this open** | Those cells fed the flag components georeferenced from **position-only priors at 10 m claimed accuracy**. The feature's documented premise ("each is georeferenced") was arguably never met — RealityScan may distinguish prior-weighted from ground-control-locked georeferencing. **Do not treat D1/D2 as final.** [SUPERSEDED-RISK: FINDINGS 2026-07-25 RECON] |
| **Aggravating observation** | Three accepted `merge_georef` attempts on H2024 `cluster_1` scored as exact-sum fusions with zero camera loss while RealityScan's own log reported "Finalizing 3", then "7", then "8" components — a container holding eight disjoint objects. Zero loss on a zero-shared-imagery "fusion" is the signature of **co-location, not registration**. [VERIFIED: FINDINGS 2026-07-28] |

Related keys, for completeness (full inventory in `03-settings-keys.md`):

| Key | Type / default | Official prose | Use here |
|---|---|---|---|
| `sfmMergeGeoreferencedComponents` | bool / `false` | merge georeferenced components without visual overlap | `false` in pass-1 zone aligns (auto-fusing disjoint pockets by georeference would freeze bad geometry invisibly); `true` on every merge-ladder rung [VERIFIED-as-decision: docs/settings-evaluation-2026-07.md §4] |
| `sfmForceComponentRematch` | bool / `false` | "the application realigns images and cameras to find better connections. It uses existing camera poses to search for new matches" | `false` in pass-1 zone aligns (a merge-stage tool, wasted per zone); `true` on the align-mode merge rungs [OFFICIAL: appbasics/alignsettings] + [VERIFIED-as-policy: docs/settings-evaluation-2026-07.md §4; merge_zones.LADDERS] |
| `sfmImagesOverlap` | Low/Medium/High | "Defines how many common features are expected between images" | `Medium` in production. **`High` as a merge-ladder rung is not defensible** — it only widens candidate-pair search, so it can help only where components share content the matcher skipped; zero-overlap components never fuse under any rung, and the hull fused on every rung, so matching was never the constraint [VERIFIED: FINDINGS 2026-07-27] |
| `sfmEnableCameraPrior` | bool | "prior positions for the images are used in the alignment process and for georeferencing the scene" | `true` throughout; it is what makes components georeferenced in the first place. Composes with the merge flag: (a) is per-camera during alignment, (b) is per-component post-solve; (b) without (a) is inert [INFERRED from Help prose + design reasoning; never isolated by a cell] |
| `aligFeaturesMode` / `-setFeatureSource 0\|1\|2` | 0 = merge using overlaps, 1 = use component features, 2 = use all image features | Help ties these to "a new alignment of components", set per selected input: `0` uses solely images/points common to all components and "extremely speeds up the reconstruction process, as well as reduces computer memory consumption"; `1` is "the most common and fastest type"; `2` is "the slowest process of all these, recommended for a small number of camera poses" [OFFICIAL: appbasics/components] | **CLI-accessible** (`-setFeatureSource`, composed with `-selectImage` / `-selectAllImages`) — the earlier "GUI-only" conclusion is [SUPERSEDED: NA167 B11, 2026-07-23]. **Consumed by ALIGN, not by Merge Components** [INFERRED from the Help's "a new alignment of components" wording; never A/B'd here]. Mode `0`'s "images/points which are in common (the same in all components)" means **shared-PATH images, not duplicate copies of the same picture** — per-zone copies are different images to RealityScan's identity check [VERIFIED-as-reading: FINDINGS 2026-07-23, caveat added at the 2026-07-24 RECON]. Note `-selectImage` matches **literal full paths only** in this build (the Help documents a regexp dialect that selects nothing), so composing a per-camera selection is a per-image loop — see `02-command-reference.md` |

### 5.4 Timing signature — and its scale dependence

- **A working merge takes real time.** ~1 hour for 1–4k-camera pairs (D6: 56 min; D5-alt: 56 min).
  At production scale, **instant completion is the no-fuse signature**
  [VERIFIED: NA167 #23/#30, MERGE_STRATEGY_REPORT].
- **But the heuristic is scale-dependent and must not be applied blindly.** On the 120-camera D7
  fixture a *genuine* fusion completed in **57–93 s**, and the zero-overlap D-cells took
  **17–21 min** each (dominated by boot, import and export overhead) — i.e. the no-fuse case took
  an order of magnitude *longer* than the small-fixture fuse
  [VERIFIED: MERGE_TEST_PLAN D7 wave + NA167 #26]. Timing is a smell, never a verdict. The verdict
  is the census (§6).

### 5.5 `-mergeComponents` RETAINS its input components

A merge or align leaves the **source components in the scene alongside the fused one**.

| Case | Peel result | Reading |
|---|---|---|
| D7 smoke fusion of 78 + 42 | `[120, 78, 42]` | fusion **plus** both originals |
| Controlled peel of a 3-input attempt | `[267, 116, 94, 57]` | fusion plus all three unconsumed parents |
| H2023 hull 2-input merge | `[3737, 3026, 714]` | fusion plus both parents |

[VERIFIED: FINDINGS 2026-07-24 and 2026-07-27]

The H2023 hull's fused entry is recorded as **3,737 in one place and 3,738 in another** across the
findings log (`peel 3,738 or 3,737 matches no subset sum of {3026, 714}`); both are within the
1–3-camera loss band of §5.9 and neither has been re-measured
[VERIFIED-as-recorded-inconsistency: FINDINGS 2026-07-27] [OPEN: O-4].

Two consequences:

1. **Any all-components export of a merge scene contains residual source copies.** Consumers must
   **attribute**, not enumerate.
2. **Component COUNT in a merge scene is not "how many features".** Never use it directly.

`merge_zones.attribute_result()` implements the attribution: peel entries are matched
largest-first against the remaining input manifests by camera-count arithmetic; an entry that
matches no remaining subset but equals an already-consumed input's count is that input's
**residual source component** — expected, recorded, never adopted
[VERIFIED-by-inspection: merge_zones.py lines 434–538].

### 5.6 "Finalizing N component(s)" — how to read it

RealityScan writes `Finalizing N component(s)` into `%LOCALAPPDATA%\Temp\RealityScan.log` during
merge/align reconstruction. Observed values and contexts:

| Observation | Context | Reading |
|---|---|---|
| "Finalizing 1 component" | D6 split-zone (390 shared images), 56 min | real fusion |
| "Finalizing 1 component" | D7a/D7b, 120 cams | real fusion |
| "Finalizing 9 components" | `-mergeComponents` on two zero-overlap components | fragment behavior; nothing fused |
| "Finalizing 11 components" | D5-alt, full 3,906 retained | behaviorally positive, count-ambiguous |
| "Finalizing 3", then "7", then "8" | merged5 `cluster_1`, three accepted `merge_georef` attempts | **the rigid-glue tell** — RS reports many components while the arithmetic scores one fused container |

[VERIFIED: NA167 B11, MERGE_TEST_PLAN, FINDINGS 2026-07-28]

**The exact semantics of `Finalizing N` are NOT ESTABLISHED** — new components? scene total?
components in the finalize phase? The value is recorded per attempt (`rs_finalizing` in
`merge_report.json`) as a **cross-check and never as a gate**
[OPEN: queued probe — two tiny imports, one merge, count the result; never run].

**Reading the log at all requires a validity check.** `RealityScan.log` is truncated on every
instance boot, so a snapshot can be a *splice* of two runs: one H2023 attempt's snapshot recorded
`importComponent` of eleven H2024 components because two merge drivers overlapped. A snapshot must
be validated against a run-unique token — the attempt's own complist paths — before any number is
read out of it [VERIFIED: FINDINGS 2026-07-27]. The implementation:

```python
def rs_finalizing_counts(rslog_path, expected_rsaligns):
    out = {'valid': False, 'counts': []}
    with open(rslog_path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    imported = set(re.findall(r"importComponent' with parameter '([^']+)'", text))
    expected = {os.path.normcase(p) for p in expected_rsaligns}
    seen = {os.path.normcase(p) for p in imported}
    out['valid'] = expected <= seen          # every complist path present => this attempt's log
    out['counts'] = [int(n) for n in re.findall(r'Finalizing (\d+) component', text)]
    return out
```

The two literal patterns matter: RealityScan writes
`… 'importComponent' with parameter '<path>'` and `Finalizing <N> component(s)` into
`%LOCALAPPDATA%\Temp\RealityScan.log` [VERIFIED-by-inspection: merge_zones.py lines 611–637,
regexes pinned against real snapshots].

### 5.7 The rigid-glue failure signature, and how to detect it

**The failure:** `merge_georef` on a set of components that share no imagery produces a single
container holding several disjoint physical objects, placed side by side by nav rather than
jointly solved. The container passes every camera-count check.

**The case of record.** merged5's `cluster_1_a3_c0` (3,615 cameras) packed **eight disjoint
objects** into one component. Of cluster_1's 28 component pairs, exactly **one**
(`zone_1_c2` ↔ `zone_4_c1`, 343 shared basenames) shared any imagery; the other seven related only
through transitive bbox adjacency under the old 10 m-margin border gate. All three accepted
attempts were `merge_georef`; RealityScan logged "Finalizing 3", "7", "8" while the arithmetic
scored each as an exact-sum fusion with **zero loss**
[VERIFIED: FINDINGS 2026-07-28, owner challenge + manifest forensics].

**The contrast that defines the signature.** The hull in the same run fused by `align`, logged
"Finalizing 1", and **LOST 5 cameras** — real joint solving. Zero loss on a zero-shared-imagery
"fusion" is the signature of co-location, not registration.

**Why it matters downstream:** `GenerateModel`'s keep-largest-connected-component step
(`-selectLargestModelComponent` → `-invertTrianglesSelection` → `-removeSelectedTriangles`) would
have deleted every smaller object from a model of that container
[VERIFIED: FINDINGS 2026-07-28; see `10-reconstruction-texturing-export.md`].

**Detection checklist** — flag a fusion as suspected rigid glue when **all** of these hold:

| # | Test | Data source |
|---|---|---|
| 1 | Mechanism was `-mergeComponents` with `sfmMergeGeoreferencedComponents=true` | attempt record |
| 2 | The subset's **shared-image graph does not span** it | manifests (`shared_image_count` over basenames) |
| 3 | Camera loss is exactly **zero** (result count = exact input sum) | peel counts vs manifest sums |
| 4 | RealityScan's own `Finalizing N` reports **N > 1** while the attribution scores one fused container | validated `rslog.txt` snapshot |
| 5 | The inputs' UTM bboxes do not truly overlap (only margin-adjacency relates them) | manifest `bbox_utm` |

**Caution on test 3 in isolation:** an exact sum is the *expected* result of any lossless fusion
between components that share no duplicate images, so exact-sum alone proves nothing. Test 4 is
the strongest discriminator available today, and its semantics are [OPEN] (§5.6).

**The D7b tension, stated rather than smoothed over.** D7b satisfies tests 1, 2, 3 and 5 (zero
shared basenames, exact 120 = 78+42, merge_georef) yet was read as a *content* fusion. What saves
it: it logged **"Finalizing 1 component"** (fails test 4), and its merge scene had **no flight log
at all**, so there were no scene constraints to co-locate by. What is not settled: whether the
imported components carried their own georeferencing from their zone solves into that scene.
[OPEN — see §Open questions.]

### 5.8 What merge can never do

| Claim | Status |
|---|---|
| "no new images are added to the existing components" | [OFFICIAL: appbasics/allcommands, tutorials/mergecomponents] — **true and load-bearing**. Orphans can never be picked up by a merge; only `-align` can add images. `MergeZoneComponents.bat` has no `-addFolder` at all, so a merge scene structurally cannot contain an orphan today. [VERIFIED-as-consequence: FINDINGS 2026-07-27] |
| Merge cannot shrink the *image set* (it can drop a handful of *registered cameras* — see §5.9) and cannot register orphans | [VERIFIED: FINDINGS RECON 2026-07-24 "What stands: merge cannot shrink and cannot register orphans"] |
| "Merge Components is rigid best-fit — no re-optimization, no repositioning" | **[CONTRADICTED-in-part.]** The Epic staff claim (forums.unrealengine.com/t/712116, OndrejTrhan, 2021-09) predates the rename and falls outside the 4-year trust window. Empirically, with shared cameras `-mergeComponents` runs ~56 min of visible merge reconstruction and can finalize different component counts; and H2023 zone_1's final census read **+37 cameras** against the manifest baseline when a rigid-merge consolidation was the only accepted mutation (attribution unresolved — merge effect vs a sub-`setMinComponentSize` census-mapping artifact). What stands: no new images, no shrink of the image set. What is **UNVERIFIED**: "no re-optimization" in the current build. Note the "no new images added" half **is** corroborated by current 2.2 Help wording, so only the re-optimization half rests on the stale citation. [AUDIT FLAG on the citation; FINDINGS RECON 2026-07-24; ALIGN_MERGE_HARDENING_PLAN audit flag] |
| `-mergeComponents` with a single component | No-op, and its async re-reconstruction can clear the selection. Replaced by `-selectMaximalComponent` in the smoke workflow. [VERIFIED: HANDOFF 2026-07-21] |
| Merge as a **consolidation** pass | Real: zone_1 went **9 components → 4** in a 38-min accepted growth pass with the same 4,392-image union. [VERIFIED: FINDINGS 2026-07-24] |

### 5.9 Fusion arithmetic and camera loss

Fusion can drop a small number of cameras, and the loss is real but not a fixed set:

Rows are labelled by **run**, because the same inputs give different losses on different runs —
that variability is itself the evidence that the loss is a solver effect and not deterministic
bookkeeping.

| Run | Case | Inputs | Result | Loss |
|---|---|---|---|---|
| H2023 fresh `merged` | hull, `merge` rung | 3,026 + 714 = 3,740 | 3,738 | −2 |
| H2023 fresh `merged` | hull, align rung 1 | same | 3,739 | −1 |
| H2023 fresh `merged` | hull, align rung 2 | same | 3,739 | −1 |
| H2024, post-junction-fix (pre-bounded-loss) | cluster_0 hull, rung 1 | 1,407 + 1,217 + 2,241 = 4,865 | 4,860 | −5 (0.10 %) |
| H2024, post-junction-fix (pre-bounded-loss) | cluster_0 hull, rungs 2–3 | same | 4,851 + a stray 5 | −14 counting only the fused entry, −9 if the stray fragment counts |
| H2024 `merged4` | cluster_0 hull, fused 3 → 1 | same | 4,859 | −6 (inside the 12-camera budget) |
| H2024 `merged5` | cluster_0 hull, rung 1 `merge_georef` | same | 4,854 + a stray 5 | −11 (inside budget, but the stray fragment made attribution `ambiguous` → rejected on the **attribution** term, not the loss term) |
| H2024 `merged5` | cluster_0 hull, rung 2 `align_rematch` | same | 4,860 | −5, `exact`, **ACCEPTED** |
| H2024 `merged4` | cluster_1, two accepted fusions | 1,634+69+64; 576+358+345+177 | 1,767; 1,456 | 0 (both exact) |
| H2024 `merged5` | cluster_1, three progressive fusions (3→1, 5→1, 2→1) | — | 1,767; 3,039; 3,615 | 0 (all exact) |
| H2024, new-gate non-hull re-run | `{zone_1_c2, zone_4_c1, zone_4_c2}`, align-only | 345+358+177 = 880 | 880 | 0 |
| H2024, new-gate non-hull re-run | `{zone_1_c4, zone_1_c5}`, align-only | 69+64 = 133 | 133 | 0 |
| H2024, junction-fix confirmation | `{zone_1_c1, zone_1_c4, zone_1_c5}`, merge | 392+69+64 = 525 | 525 | 0, fused 3 → 1, accepted |

[VERIFIED: FINDINGS 2026-07-25 (which explicitly CORRECTS an earlier "3,738 on all three rungs" —
the peel counts are `[3738]`/`[3739]`/`[3739]`), 2026-07-27, 2026-07-28]

**The `merged5` cluster_1 zero-loss rows are exactly the rows §5.7 indicts.** Only **one** of
cluster_1's 28 component pairs shared any imagery, so most of that consolidation was co-location
under `merge_georef`, not joint solving. They are listed here as arithmetic, not as evidence of
registration. The new-gate re-run rows below them are the contrast: same zero loss, but produced by
**align** over subsets whose relation was proved by content [VERIFIED: FINDINGS 2026-07-28].

Two caveats that must travel with these numbers:

1. **ICP follow-up over the peel poses:** merge-mode's confirmed drop is `C231C1034` (no fused
   pose within 2 m); the second is **masked by a ~0.55 m median non-rigid deformation** of the
   merged solution versus zone_1's own solve — itself a direct measurement of under-constraint and
   a seam/residual expectation [VERIFIED: FINDINGS 2026-07-25].
2. **The missing cameras are still not cleanly distinguishable from a harvest artifact.** For real
   loss: the deficit varies by mechanism, and a free re-align already drops 1–2 marginal cameras
   normally. Against: the peel harvest is a single PowerShell
   `Get-ChildItem -Recurse | Move-Item -Force` line, PowerShell 5.1 exits 0 on non-terminating
   pipeline errors (two locked sidecars are a silent −2), and a flat `-Force` move collapses
   same-stem ordinal sidecars from different folders. The ICP check matched identity by nearest
   position over those same peel poses, so it is **not independent evidence**
   [OPEN: §Open questions].

**The 5-camera loss that hid an entire fusion.** On the H2024 run made immediately after the
junction fix and **before** bounded-loss acceptance existed, cluster_0 peeled
`[4860, 2241, 1407, 1217]` on rung 1 and `[4851, 2241, 1407, 1217, 5]` on rungs 2–3 — i.e.
RealityScan fused essentially the whole hull every time — and the driver **rejected all three
attempts**, because 4,860 is not an exact subset sum of {2,241, 1,407, 1,217} = 4,865:
`attribute_result` returned `ambiguous`, no adopted entry had ≥ 2 inputs, so `fused` evaluated
False and `accept` never fired. The three parents each attributed to themselves exactly, so the
attempt still recorded `adopted=3, delta=0` — **a rejection that reads as a clean no-op in
`merge_report.json`**. A 0.10 % loss is enough to make a real fusion invisible
[VERIFIED: FINDINGS 2026-07-28]. This is why bounded-loss acceptance exists (§7.6).

### 5.10 Georeferencing the merged result

A merged component is a **NEW** component and is **not georeferenced by inheritance** — the input
components' own georeferencing does not carry over
[VERIFIED-as-observed: NA156 H2023, 2026-07-23; MergeZoneComponents.bat header].

The merge scene must therefore carry its own constraints:

1. `-importFlightLog <union_log> <FlightLogParams.xml>` **before** the merge (so the solve has
   priors to fit). Rows referencing images absent from the scene make the import report
   warning-class `0x820000FF` / `err:18002` while the trajectory imports fine for every present
   image — tolerated by the `:run_geoimport` subroutine, which matches the numeric code and moves
   the marker to `expected_18002_<instance>.txt` [VERIFIED: FINDINGS 2026-07-21/23].
2. `-update` **after** the merge — the rigid/similarity fit to those constraints is what actually
   georeferences the merged component [VERIFIED: MergeZoneComponents.bat lines 174–177].

Details of union-log construction, CRS/EPSG derivation and the metric-scale oracle live in
`06-georeferencing-flightlogs-and-scale.md`.

---

## 6. Verification protocol — never trust exit status

> **VERIFY EVERY MERGE BY POSE-XMP CAMERA CENSUS, NEVER BY EXIT STATUS.**
> The single most repeated operational rule in this repository
> [VERIFIED: NA167 #23; restated in CLAUDE.md, HANDOFF, MERGE_STRATEGY_REPORT].

A `-mergeComponents` that fuses nothing exits SUCCESS, writes no errors marker, and leaves an
export that is simply the largest input.

### 6.1 Census methods and their limits

| Method | How | Yields | Limits |
|---|---|---|---|
| **Stem-named XMP census** (`-exportXMP`) | `-deselectAllImages` → `-setMinComponentSize 1` → `-exportXMP`; count `.xmp` files containing `xcr:Position` | Camera count **and identity** (basenames) | Covers only "the last alignment" and silently skips components below `setMinComponentSize` [OFFICIAL: appbasics/allcommands]; only registered cameras get pose entries, which is what makes the count a registration census [VERIFIED: NA167_SESSION_NOTES §1] |
| **Ordinal XMP census** (`-exportXMPForSelectedComponent`) | select a component, export, count files | Camera count of **that one component** | Sidecars are `00000.xmp`, `00001.xmp`, … — **identity is lost**. Valid as a count only. Ordinal sidecars are inert as priors (no image has an ordinal stem) and are deleted by `camera_registry.sanitize_and_census` [VERIFIED: NA167 B10] |
| **Successive difference** | Per lap: `-exportXMP` (all remaining components) → harvest stems → export + delete the maximal component → repeat. `members(c_K) = stems(r_K) − stems(r_{K+1})` | Per-component **membership** | Only works in the ORIGINAL aligning scene. Destructive in memory; requires a prior `-save` and a `-quit` without saving [VERIFIED: AlignZone.bat identity loop] |
| **Count-based peel** | Per lap: select maximal → rename → export `.rsalign` → `-exportXMPForSelectedComponent` → harvest → delete | Per-component **camera counts**, maximal-first | Identity lost (ordinal); membership must come from attribution against input manifests [VERIFIED: MergeZoneComponents.bat `:harvest`] |
| **Manifest sum** | Sum `camera_count` over the manifests of the components in the assembly | The assembly's camera total | It is the **inputs'** total, not an observation of the assembled project. Assemble mode exports no XMPs, so nothing observes the assembly itself — in particular its metric scale is unmeasured. Tag it as a manifest sum, always [VERIFIED-as-caveat: merge_zones.py EVALUATION_READY text] |
| **`Finalizing N` from `RealityScan.log`** | Regex over a snapshot validated against the attempt's complist | A cross-check only | Semantics not established; log is truncated per boot and can be a splice [OPEN + VERIFIED: FINDINGS 2026-07-27] |
| **Exit status / errors marker** | — | **Nothing about fusion** | A silent no-fuse exits SUCCESS and writes no errors marker [VERIFIED: NA167 #23/#26] |

### 6.2 The identity loop (AlignZone) — membership by successive difference

`AlignZone.bat` runs this **after** saving the project, so it is destructive in memory only, and
quits **without** saving:

```bat
echo Capturing per-component identity (destructive in-memory loop)
set /a comp_index=0
:identityLoop
if %comp_index% GEQ 20 goto :identityDone
if not exist "%output_dir%\identity_r%comp_index%" mkdir "%output_dir%\identity_r%comp_index%"
call :run -deselectAllImages || goto :fail
call :run -exportXMP         || goto :fail
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%input_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force"
set "have_poses="
for %%F in ("%output_dir%\identity_r%comp_index%\*.xmp") do set have_poses=1
if not defined have_poses goto :identityDone
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "%scene_name%_c%comp_index%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
if not exist "%output_dir%\%scene_name%_c%comp_index%.rsalign" goto :identityDone
call :run -deleteSelectedComponent || goto :fail
set /a comp_index+=1
goto :identityLoop
:identityDone
```

Notes [VERIFIED-by-inspection: AlignZone.bat lines 115–152]:
- **The loop inherits the zone's `-setMinComponentSize %min_component_size%`** (issued once at
  line 99, production value **50**), NOT `1`. The merge peel in §6.3 re-issues
  `-setMinComponentSize 1` inside every lap; the align identity loop deliberately does not. So a
  zone's sub-50 pockets are invisible to this census by design, and any camera arithmetic derived
  from it is arithmetic over components ≥ the floor, never over the scene
  [VERIFIED-by-inspection: AlignZone.bat line 99 vs MergeZoneComponents.bat line 238].
- Lap cap **20**; the empty harvest is the exhaustion terminal (it also fires when only sub-min
  components remain).
- `-exportXMP` writes stems for **all remaining components**, so `identity_r<K>` is a cumulative
  snapshot; membership is the successive difference, computed by the Python orchestrator.
- The exports are `<scene>_c0.rsalign`, `<scene>_c1.rsalign`, … in **maximal-first** order.

**Known defect (fixed).** The harvest *moves* every pose-bearing `.xmp` out of the image tree, so
the last-peeled component's sidecars are never re-exported: measured on a fresh zone_1, **796 of
4,540 images (17.5 %) were left with no sidecar** — the entire bow component (665/665), 123 of c0,
8 unregistered. Any re-align of an already-harvested zone then silently runs with a partially
ungrouped camera set (which confounded cells PD-4 and PD-4a). Fixed by
`camera_registry.ensure_calibration_sidecars()` [VERIFIED: FINDINGS 2026-07-25]. See
`05-metadata-xmp-and-sidecars.md`.

### 6.3 The peel loop (merge scenes) — counts only

In a merge scene, stems are unavailable (B10), so the peel exports the **selected** component's
sidecars each lap and the per-lap **file count** is that component's exact camera count:

```bat
:harvest
set /a peel_index=0
:peelLoop
if %peel_index% GEQ 40 goto :after_export
if not exist "%output_dir%\identity_r%peel_index%" mkdir "%output_dir%\identity_r%peel_index%"
call :run -deselectAllImages   || goto :fail
call :run -setMinComponentSize 1 || goto :fail
call :run -selectMaximalComponent || goto :fail
call :run_peelrename -renameSelectedComponent "%merged_name%_c%peel_index%"
if errorlevel 2 goto :after_export
if errorlevel 1 goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
if not exist "%output_dir%\%merged_name%_c%peel_index%.rsalign" goto :after_export
call :run -exportXMPForSelectedComponent || goto :fail
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%RS_MERGE_IMAGES_ROOT%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%peel_index%' -Force"
if errorlevel 1 ( echo ERROR: harvest move failed & goto :fail )
call :run -deleteSelectedComponent || goto :fail
set /a peel_index+=1
goto :peelLoop
```

Lap cap **40**; terminal is the tolerated `E_INVALIDARG` rename (§2.3)
[VERIFIED-by-inspection: MergeZoneComponents.bat lines 224–250].

Reader side:

```python
def peel_counts_from(out_dir):
    sizes, k = [], 0
    while True:
        d = os.path.join(out_dir, f'identity_r{k}')
        if not os.path.isdir(d): break
        n = len([f for f in os.listdir(d) if f.lower().endswith('.xmp')])
        if n == 0: break
        sizes.append(n); k += 1
    return sizes                     # maximal-first, matches <name>_c<K>.rsalign
```

### 6.4 Instrument invariants — a broken measurement channel is not a result

Two failure shapes silently destroyed hours of correct GPU work here; both are now mechanical
checks.

**(a) Empty peel beside a non-empty export ⇒ ABORT.**

```python
first_export = os.path.join(adir, f'{export_name}_c0.rsalign')
if result.success and not sizes and os.path.isfile(first_export):
    raise RuntimeError('peel harvest returned EMPTY but the export exists - '
                       'the measurement channel is broken. Aborting instead of mis-scoring.')
```

This exact shape discarded **5 h 12 m** across two runs [VERIFIED: FINDINGS 2026-07-27/28;
merge_zones.py lines 836–845].

**(b) The cause it was protecting against: reparse points.** RealityScan writes **NO XMP sidecars
when a scene's images resolve through a directory junction, and reports success.** Four baseline
components on real paths harvested `identity_r0` = 267 files (= 116+94+57, exact); the same
workflow on junction-rooted components harvested **zero**, silently, across 18 attempts
[VERIFIED: FINDINGS 2026-07-27] [UNDOCUMENTED: no Epic coverage].
Compounding it, PowerShell 5.1 `Get-ChildItem -Recurse` does **not** descend into junction
*children* (0 vs 9,835 `.xmp` on the same tree via its real path) while Python's `os.walk` does.
The ALIGN harvest survived because it is handed the zone folder itself (the junction is the
enumeration root); the MERGE harvest died because it is handed the parent
[VERIFIED: FINDINGS 2026-07-27].
**Fix verified:** replace per-zone junctions with real directories of **hardlinked** `.jpg`
(9,835 files, 35.8 GB logical, 0.05 GB actual) plus **copied** `.xmp` and flight logs — sidecars
deliberately not hardlinked so a v2 write cannot corrupt the baseline's. No re-align was needed —
the components were never the problem, only the paths baked into them
[VERIFIED: FINDINGS 2026-07-28].

**(c) A merge-scene `-exportXMPForSelectedComponent` can complete and write nothing.** The log
said "Exporting Registration completed in 8.758 seconds", yet a sweep of the whole drive found
zero `.xmp` written. Ruled out: "an imported component carries no images" (the merge scene
reported `Added 1407 images` / `1217` / `2241`). Root cause was the reparse-point write path above
[VERIFIED: FINDINGS 2026-07-27].

**(d) A truncated peel is currently indistinguishable from a complete one** — the terminal
subroutine's evidence file `expected_peelend_<instance>.txt` is written and never read
[VERIFIED: FINDINGS 2026-07-27 adversarial review] [OPEN: §Open questions].

**(e) The peel count is its own only witness, and a stale sidecar can cancel a real loss.**
The per-lap file count is simultaneously the evidence for membership, for `camera_count` and for
the acceptance arithmetic, and nothing sanitizes the image tree *before* an attempt —
`sanitize_and_census` runs after the workflow, so attempt 1 of a run inherits whatever the tree
held. `census_leftover` is recorded in `merge_report.json` and never checked (and reads ~0 by
construction, because the harvest already moved the sidecars out). Consequence: an inflation of
`+N` stale sidecars can exactly cancel a real solver loss of `−N`, producing
`confidence == "exact"`, `lost == 0` and a **false accept** whose manifest names basenames the
component does not contain [VERIFIED: FINDINGS 2026-07-27 adversarial review]
[OPEN: no mechanical check exists; the cheap fix is to assert a clean tree before each attempt and
to gate on `census_leftover == 0`].

### 6.5 The acceptance decision (pure, testable)

```python
def acceptance_verdict(workflow_success, adopted_count, fused, confidence, lost, tol):
    accept = bool(workflow_success and adopted_count and fused
                  and confidence == 'exact'
                  and lost is not None and lost <= tol)
    rejection = None
    if workflow_success and adopted_count and lost and lost > tol:
        rejection = 'shrink'
    if workflow_success and fused and confidence != 'exact':
        rejection = 'ambiguous_attribution'
    return accept, rejection
```

Kept pure so the test suite drives the **real** decision rather than a re-implementation
[VERIFIED-by-inspection: merge_zones.py lines 296–313].

Two historical defects worth carrying forward:

- **The "never-shrink" invariant was dead code and never fired.** Every adopted entry's
  `camera_count` equals its matched subset's sum, each input pops exactly once, and
  `confidence == "exact"` requires the remaining set to be empty — therefore
  `adopted_cams == input_cams` identically and `lost == 0` always. The clause could never reject,
  and could not see a camera **gain** either, which is precisely what `sfmForceComponentRematch`
  and `sfmImagesOverlap:High` exist to produce. Every earlier statement attributing the hull
  rejection to never-shrink is **wrong**; the real gate was exact subset-sum attribution
  [SUPERSEDED: all prior never-shrink attributions; VERIFIED: FINDINGS 2026-07-27, 35 confirmed /
  11 refuted findings across 9 review agents].
- **`fused` is inferred from the same arithmetic that fails on a lossy fusion**, so a fusion is
  only *visible* when its count is an exact input-subset sum. No code path in the driver could
  assert that two components fused. The dominant rejection shape records **no reason**:
  `workflow_success: true, attribution: "ambiguous", adopted_count: 0, camera_delta: null`
  [VERIFIED: FINDINGS 2026-07-27].

---

## 7. Merge strategy at scale

### 7.1 The three strategies, measured

Fixture: `zone_6 ←312 shared→ zone_14 ←239 shared→ zone_4`, 4,131 unique images, **zero** direct
6↔4 overlap, so a single final component requires transitive stitching. Dual-5090 / 192 GB box,
GPU 0, instance RS1 [VERIFIED: MERGE_STRATEGY_REPORT, NA167 #19, 2026-07-22…24].

| Strategy | CLI shape | Single component? | Registered | Wall time | Peak RAM |
|---|---|---|---|---|---|
| **B — sequential growth** | per zone: `-add <list>` → `-importFlightLog` → `-align`, one scene | **YES** | 3,906/4,131 (94.6 %) | 444 min | ≤ ~60 GB |
| **C — joint align** | one `-add union.imagelist` → one `-align` | **YES** | 3,904/4,131 (94.5 %) | 169 min | ~165 GB |
| **A — align-then-merge** | per-zone `-align` → `-importComponent`×N → `-mergeComponents` | conditional (§5.2) | 90–95 % per zone | 21–98 min/zone, **parallelizable** | ≤ ~60 GB/zone |

**Quality is strategy-independent** (94.5 % vs 94.6 % is noise). The choice is resource-shaped:
C is 2.6× faster than B but 2.7× hungrier, and joint alignment extrapolates to **~700 GB for a
19k-image dive** — **chunking is mandatory at production scale**
[VERIFIED: NA167 #19, 2026-07-24].

Production recommendation on record:
1. Align zones independently (embarrassingly parallel across GPUs via `RS_INSTANCE` /
   `RS_GPU_DEVICES`).
2. Merge chains of components over shared content, pairwise/progressively (~1 h per merge),
   verifying every merge by census.
3. Rescue a zone that fails standalone alignment by **growing it from an aligned neighbour**, not
   by retrying solo (the `MSS_STR001` workaround — see `07-alignment.md` and
   `12-failure-modes-and-race-conditions.md`).
4. Batcher change this implies: zones must reference a canonical image pool (hardlinks or
   imagelists) rather than per-zone copies.
[VERIFIED-as-recommendation: MERGE_STRATEGY_REPORT, 2026-07-24]

**Caveat on (3):** incremental growth is **state-sensitive and can degrade existing structure** —
a z6→z14 two-zone grow fragmented to an 870-camera maximal (below z6's solo 1,533), while the
three-zone grow through the same stages held 3,906. Growth outcomes are not order- or
subset-invariant; verify camera counts after every grow step
[VERIFIED: NA167 #29, 2026-07-24].

### 7.2 Feature geography — clusters, and why a fraction target is wrong

Running `component_analysis.merge_plan` over the twelve H2023 zone manifests — **pure analysis, no
RealityScan** — resolves three spatially disjoint UTM clusters:

| cluster | components | unique images | UTM extent |
|---|---|---|---|
| hull | zone_1 c0/c1/c3/c4/c5/c6/c7/c8 + zone_2 c1 | 3,720 | E 594693–594719 / N 2345096–2345160 |
| bow | zone_2 c0 (keeper) + zone_1 c2 (twin, discarded) | 686 | E 594653–594668 / N 2345217–2345251 |
| west pocket | zone_2 c2 | 102 | E 594599–594607 / N 2345248–2345256 |

**Hull ∩ bow = zero shared basenames**, so no mechanism can ever fuse them. The ceiling on the
maximal component is **3,720/4,600 = 80.9 %**, below both `--target` values ever used (0.85, 0.83):
a maximal-fraction gate was **unreachable by construction** and would have burned the full
three-attempt ladder (~1.7 h measured) and exited 1 on a *correct* result
[VERIFIED: FINDINGS 2026-07-24; docs/MERGE_REWORK_RECOMMENDATIONS].

Consequently `--target` in `merge_zones.py` is **informational only, never a gate**, and
convergence (a full ladder cycle with no fusion) is the terminal condition.

**Do not cite `D:\na156_h2023\merged`'s 83.9 %** as evidence about merge mechanism: five ordinal
`Component N.rsalign` exports, empty twin plan, predates manifests; read with the clusters above,
its 3,860 is a hull-cluster maximal, not a shortfall
[SUPERSEDED: FINDINGS 2026-07-24].

### 7.3 The pair gate — which components belong in one merge scene

**Owner uniqueness criterion (2026-07-28):** two components belong in one merge scene **only when
they share imagery or their bboxes truly overlap.**

```python
def pair_related(a, b):
    shared = shared_image_count(a, b)          # lowercased basename intersection
    if shared:
        return True, f'{shared} shared images'
    ba, bb = a.get('bbox_utm'), b.get('bbox_utm')
    if not ba or not bb:
        return True, 'null bbox - conservative'
    dx = min(ba[2], bb[2]) - max(ba[0], bb[0])
    dy = min(ba[3], bb[3]) - max(ba[1], bb[1])
    if dx > 0 and dy > 0:
        return True, f'true bbox overlap {dx:.1f} x {dy:.1f} m'
    return False, 'no shared imagery, no spatial overlap'
```

`--pair_gate overlap` is the default; `--pair_gate border` retains the pre-2026-07-28 behavior
(`component_analysis.find_borders`, `DEFAULT_BORDER_MARGIN_M = 10.0`) so the two can be compared
rather than assumed [VERIFIED-by-inspection: merge_zones.py lines 257–279, 344–365].

**The margin is applied to BOTH bboxes**, so a 10 m margin treats components up to **20 m** apart
as bordering. Every description of it as a "10 m-expanded bbox", including several in the findings
log, understates the reach by 2× [VERIFIED: FINDINGS 2026-07-27, pinned by
`testing/test_merge_scope.py`].

**Measured effect of the gate rework:** under the new gate the 8 non-hull H2024 components
partition into **5 clusters** (versus **ONE** under the border gate), and both resulting fusions
were content-driven and exact:

| subset | shared-image graph | rungs run | peel | verdict |
|---|---|---|---|---|
| `{zone_1_c2, zone_4_c1, zone_4_c2}` | does not span | align-only | `[880, 358, 345, 177]`, 880 = 345+358+177 | fused all three, zero loss — content proved what the bbox suggested |
| `{zone_1_c4, zone_1_c5}` | zero shared imagery, true bbox overlap | align-only | `[133, 69, 64]` | fused, exact |

[VERIFIED: FINDINGS 2026-07-28]

**Scope — which of the related components actually enter one merge scene.** The pair gate says
which components are *related*; `--merge_scope` says how many of them are handed to RealityScan at
once [VERIFIED-by-inspection: merge_zones.py lines 740–797]:

| `--merge_scope` | Behaviour | Why |
|---|---|---|
| `neighbour` (default) | Walk targets **largest-first** (`growth_order`); each attempt's scene is that target plus every component related to it (`neighbour_subset`). A target relating to nothing is marked exhausted, no attempt run. | An all-at-once scene names no pair when it fails: H2024 `cluster_1` put **12 components in one scene**, and `cluster_0` ran all three rungs with a 0.236-scale component present every time, so it was never learned whether its two sound siblings would fuse alone. |
| `cluster` | The whole cluster in one scene, the pre-2026-07-27 behaviour. | Retained so the two can be **compared** rather than assumed. |

A `attempted: set[frozenset]` of subset signatures prevents a symmetric pair costing six attempts
instead of three (target A yields `{A,B}`; target B yields the identical set)
[VERIFIED-by-inspection: merge_zones.py lines 751–785]. An `origin_map` resolves synthetic fused
keys back to original input keys transitively, because a second-round fusion's attribution names
first-round synthetic keys and the scale gate is keyed by originals — without it every merged
component reads `unmeasured` and the gate blocks the very thing the ladder produced
[VERIFIED-by-inspection: merge_zones.py lines 756–762].

### 7.4 The spanning requirement for `-mergeComponents` rungs

`-mergeComponents` rungs are admitted **only when the shared-image graph SPANS the whole subset.**
Any-pair sharing is not enough: a merge rung glues every component in the scene indiscriminately,
which is exactly how merged5's eight-object container was produced (§5.7).

```python
def effective_ladder_for(subset, ladder):
    if shared_graph_spans(subset):
        return ladder
    align_only = [s for s in ladder if s['mode'] == 'align']
    return align_only or ladder
```

`shared_graph_spans` is a flood fill over `shared_image_count` edges: True iff every member is
reachable from every other [VERIFIED-by-inspection: merge_zones.py lines 316–341].

**Rationale, stated precisely:** merge fuses through camera identity; align fuses through content.
So an identity-connected subset is the only one a merge rung can act on soundly; anything else
gets align-only rungs and lets content decide
[VERIFIED-as-design + measured outcome: FINDINGS 2026-07-28].

### 7.5 The escalation ladder

One variable per rung, largest-anchor first, judged by census and peel, never by exit status
[VERIFIED-by-inspection: merge_zones.py `LADDERS`]:

```python
LADDERS = {
    'merge_first': [                                   # default
        {'label': 'merge_georef', 'mode': 'merge',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true']},
        {'label': 'align_rematch', 'mode': 'align',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true',
                      'sfmForceComponentRematch:true']},
        {'label': 'align_rematch_high_overlap', 'mode': 'align',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true',
                      'sfmForceComponentRematch:true',
                      'sfmImagesOverlap:High']},
    ],
    'content_first': [ ... align_rematch, align_rematch_high_overlap, merge_georef ],
}
```

Notes:
- `merge_first` is mechanistically sound for duplicate-path zones and was ~25 % faster than align
  mode in the D7 probe; the D7 verdict made ladder inversion unnecessary
  [VERIFIED: FINDINGS 2026-07-24].
- Rung 3 (`sfmImagesOverlap:High`) is retained but **is not defensible on the evidence** — see
  §5.3.
- **An accepted rung short-circuits the rest of the ladder** and is worth half the wall clock
  (merged5 68.3 min vs merged4 121.8 min) [VERIFIED: FINDINGS 2026-07-28].
- A rung that fuses **restarts** the ladder on the new state; convergence is a full cycle with no
  fusion.

### 7.6 Bounded-loss acceptance

**Owner decision in force (2026-07-28): bounded loss at 0.25 % of input cameras.** The default
remains **0** (exact subset sums only); the 0.25 % is passed explicitly by the driver
(`--loss_tolerance 0.0025`), warned at startup, and recorded per attempt and in
`EVALUATION_READY.txt` [VERIFIED-as-decision: HANDOFF "DECISION IN FORCE (owner, 2026-07-28)"].

```python
def loss_budget(input_cams, loss_tolerance_frac):
    return int(input_cams * loss_tolerance_frac)
```

Inside `attribute_result`, a *lossy* subset (whose camera sum exceeds the peel count by ≤ budget)
is considered **only when no exact subset exists**; ties break by smallest loss, then largest
subset, so a genuine fusion beats a lone input that happens to sit within tolerance. Every adopted
result carries the `loss` it was accepted with [VERIFIED-by-inspection: merge_zones.py lines
434–538].

This exists because acceptance semantics on a deliverable are an owner decision, not a silent
default — and because without it, H2024's real 4,860-of-4,865 hull fusion was rejected three times
(§5.9).

### 7.7 Twin components

The 20 % batcher overlap band duplicates images into adjacent zones, and the same strip solved
independently can fragment into near-identical twins whose residual quality differs with solve
context.

Policy [VERIFIED: FINDINGS 2026-07-23; `modules/component_analysis.py`, 31-test suite]:

| Rule | Implementation |
|---|---|
| A twin pair exists when ≥ `DEFAULT_CONTAINMENT_THRESHOLD` (**0.95**) of the contained component's images appear in the container | `find_twins`, classified `full` (containment 1.0) or `partial` |
| A component with **no unique images** is discardable | `choose_keeper` |
| A component with **any unique images** must NEVER be dropped | enforced per member |
| Coverage is checked against the **union of the members still being kept**, evaluated **worst-first** | guarantees every basename survives in at least one kept component |
| Keeper preference | higher `camera_count` → lower `quality.mean_reproj_px` (missing quality loses the tie-break) → larger zone network → component key for determinism |

`--assemble_only` deliberately **bypasses** twin resolution and relatedness gating: carried as-is
means as-is, because routing a hand-built complist through `partition_clusters` silently discarded
containment twins [VERIFIED-as-fix: merge_zones.py lines 1137–1142].

### 7.8 The bookkeeping layer — component manifests (schema v1)

RealityScan's CLI cannot enumerate a component's images, so membership is captured at zone-align
time — the only moment per-camera XMP identity still exists — and persisted as
`<rsalign>.manifest.json` beside the exported `.rsalign`:

```json
{
  "schema": 1,
  "zone": "zone_1",
  "component": "zone_1_c0",
  "rsalign": "F:\\na156_h2024_v2\\aligned_components\\zone_1\\zone_1_c0.rsalign",
  "images": ["P231C0003_20231104_edt.jpg", "..."],
  "camera_count": 123,
  "bbox_utm": [594693.0, 2345096.0, 594719.0, 2345160.0],
  "quality": {"mean_reproj_px": null},
  "created": "2026-07-28T04:11:07+00:00",
  "history": [{"event": "zone_align_identity_export", "at": "2026-07-28T04:11:07+00:00"}]
}
```

| Field | Source | Tag |
|---|---|---|
| `images` | pose-bearing stem sidecars between two sanitize passes (successive difference) | [VERIFIED: component_manifest.py] |
| `bbox_utm` | the **zone flight log** rows of the member images (`name;X;Y;Alt;…`), matched by basename **and** stem, case-insensitively | [VERIFIED-by-inspection: component_manifest.py module docstring + `bbox_from_flight_log`] |
| **Not** `bbox_utm` | exported XMP `xcr:Position` — those are **grid-anchored local-frame** values, not UTM | [VERIFIED: B10 context, 2026-07-23] |
| `history` | audit trail for every accept/rollback/twin-drop | [VERIFIED-by-inspection: component_manifest.py `append_history`] |

`component_analysis._validate` refuses duplicate component identities (`zone/component`), which is
what caught the two-fusions-in-one-cluster naming collision
[VERIFIED-by-inspection: component_analysis.py lines 49–65].

### 7.9 Terminal state and the evaluation gate

One assembly project holding **every** surviving component (fused or single) at its own maximum,
georeferenced via union flight log + `-update`, saved plus a dated copy, then an
`EVALUATION_READY.txt` report for the owner gate. `--auto_model` optionally runs `GenerateModel`
per surviving component ≥ `--min_size` instead of stopping at the gate
[VERIFIED-by-inspection: merge_zones.py lines 1196–1329].

Merge results of record:

| run | result |
|---|---|
| H2023 `merged` (**superseded**) | 3,860 / 3,855 / 3,855 cameras across 3 attempts, 31 min for the first |
| H2023 fresh `merged` | hull pair fused 3,740 → **3,738 (merge rung) / 3,739 / 3,739 (both align rungs)**, **auto-rejected** on exact-subset-sum attribution; 4 components delivered (hull 3,026 + hull strip 714 + bow 665 + west pocket 102), 4,507/4,598 (98.0 %) |
| H2023 `merged_pd6` | 3 singleton clusters, **zero** merge attempts, 1.5 min solve time, 3 components, 4,496/4,600 (97.7 %) |
| H2024 `merged4` | 121.8 min, 4 components, 8,474 cams; hull fused 3 → 1 at 4,859 (6-camera loss inside budget) |
| H2024 `merged5` | 68.3 min, 2 components, 8,475 cams; `cluster_0_a2_c0` 4,860 via `align_rematch`; `cluster_1_a3_c0` 3,615 — **later confirmed a rigid glue of 8 objects** |
| H2024 `final_assembly` | 6 components, 8,475 cams, all modelled and all metrically measured |

[VERIFIED: FINDINGS/HANDOFF 2026-07-24 … 2026-07-29]

The `final_assembly` terminal state, in full, is the concrete shape of "as big as it can get, per
feature" — note that two of the six are fused results from the new-gate re-run (§7.3) and four are
zone components that were correctly left alone:

| component | cameras | metric scale | model wall time |
|---|---:|---:|---:|
| `cluster_0_a2_c0` — the HULL | 4,860 | 0.997 | 338.3 min |
| `zone_1_c0` | 1,634 | 1.084 | 249.3 min |
| `cluster_1_a1_c0` | 880 | 1.000 | 122.8 min |
| `zone_4_c0` | 576 | 0.947 | 106.1 min |
| `zone_1_c1` | 392 | 1.023 | 97.4 min |
| `cluster_4_a1_c0` | 133 | 0.980 | 40.1 min |

Project `F:\na156_h2024_v2\final_assembly\assembly\H2024_Final_Assembly.rsproj`; dated copy
`F:\na156_h2024_v2\RC_projects\NA156_H2024_V2_merged_20260729` (95.2 GB)
[VERIFIED: FINDINGS 2026-07-29; HANDOFF "THE DELIVERABLE"].

---

## 8. Runnable recipes

All examples assume the repo's execution layer: an instance named `RS1` already booted by
`startRealityScan.bat`, `%RealityScan%` = `C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe`,
and the `:run` subroutine (delegate → 3 s grace → `-waitCompleted` → 2 s grace → `-waitCompleted`
→ abort if the errors marker is non-empty). See `01-cli-fundamentals.md` and
`11-automation-patterns.md`.

### 8.1 Minimal raw-CLI merge of two components (no repo scaffolding)

The instance must already be booted and named `RS1` (`-setInstanceName RS1`, see
`01-cli-fundamentals.md`). `RS` here plays the role of the repo's `%RealityScan%`.

**Every `-waitCompleted` in this recipe is single, which is exactly what the repo's `:run`
subroutine refuses to do**: `-waitCompleted` can return prematurely when it is issued before the
instance has picked the queued command up, so production code always does
delegate → ~3 s grace → `-waitCompleted` → ~2 s grace → `-waitCompleted`
[VERIFIED: FINDINGS 2026-07-21]. The single waits below keep the example readable; do not copy that
part into anything unattended.

```bat
set RS="C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"

%RS% -delegateTo RS1 -newScene
%RS% -waitCompleted RS1

:: Import IN PLACE - original export directories only.
%RS% -delegateTo RS1 -importComponent "D:\na167_h2075\rs_test\merge_test\z6\zone_6_c0.rsalign"
%RS% -waitCompleted RS1
%RS% -delegateTo RS1 -importComponent "D:\na167_h2075\rs_test\merge_test\z14\zone_14_c0.rsalign"
%RS% -waitCompleted RS1

:: Flags cross as key=value, ALWAYS quoted as one argument.
%RS% -delegateTo RS1 -set "sfmMergeGeoreferencedComponents=true"
%RS% -delegateTo RS1 -set "sfmEnableCameraPrior=true"

:: Constraints BEFORE the merge so the solve has priors to fit.
%RS% -delegateTo RS1 -importFlightLog "D:\na167_h2075\rs_test\merge_test\flight_log_53N_UTM.txt" ^
                                      "D:\na167_h2075\rs_test\merge_test\FlightLogParams_53N.xml"
%RS% -waitCompleted RS1

%RS% -delegateTo RS1 -mergeComponents
%RS% -waitCompleted RS1
%RS% -waitCompleted RS1

:: -update is what georeferences the NEW merged component.
%RS% -delegateTo RS1 -update
%RS% -waitCompleted RS1

:: Deterministic export + census. deselect FIRST (flight-log import left a selection).
%RS% -delegateTo RS1 -deselectAllImages
%RS% -delegateTo RS1 -setMinComponentSize 1
%RS% -delegateTo RS1 -selectMaximalComponent
%RS% -delegateTo RS1 -renameSelectedComponent "z6_z14_merged"
%RS% -delegateTo RS1 -exportSelectedComponentDir "D:\na167_h2075\rs_test\merge_test\out"
%RS% -delegateTo RS1 -exportXMPForSelectedComponent
%RS% -waitCompleted RS1
%RS% -waitCompleted RS1
:: -> out\z6_z14_merged.rsalign  +  00000.xmp, 00001.xmp, ... beside the images
%RS% -delegateTo RS1 -quit
```

Then **verify**: count `.xmp` files carrying `xcr:Position` under the image root. If the count
equals the larger input's camera count, **nothing fused** — regardless of exit status.

### 8.2 The repo workflow

```
MergeZoneComponents.bat  %1 complist|folder  %2 out_dir  %3 name
                         %4 merge|align|assemble  %5 min_component_size
                         %6..%9 "key:value" settings
```

```bat
:: One ladder rung: merge mode, georef flag on, min size 1, peel harvest enabled.
set "RS_MERGE_FLIGHT_LOG=F:\na156_h2024_v2\merged5\cluster_0\flight_log_cluster_0_57S_UTM.txt"
set "RS_MERGE_FLIGHT_LOG_PARAMS=F:\na156_h2024_v2\merged5\cluster_0\FlightLogParams_57S.xml"
set "RS_MERGE_HARVEST=1"
set "RS_MERGE_IMAGES_ROOT=F:\na156_h2024_v2\batched_images_by_zone"

call MergeZoneComponents.bat ^
  "F:\na156_h2024_v2\merged5\cluster_0\attempt_1_merge_georef\cluster.complist" ^
  "F:\na156_h2024_v2\merged5\cluster_0\attempt_1_merge_georef" ^
  "cluster_0_a1" merge 1 ^
  "sfmMergeGeoreferencedComponents:true" "sfmEnableCameraPrior:true"
```

Produces, in the attempt directory: `cluster_0_a1_c0.rsalign`, `cluster_0_a1_c1.rsalign`, …
(maximal-first), `identity_r0/`, `identity_r1/`, … (per-component ordinal sidecars), the saved
`.rsproj`, and — written by the Python driver — `rslog.txt`.

### 8.3 The driver

```bat
python merge_zones.py ^
  --components_root "F:\na156_h2024_v2\aligned_components" ^
  --images_root     "F:\na156_h2024_v2\batched_images_by_zone" ^
  --output          "F:\na156_h2024_v2\merged5" ^
  --name            "H2024_V2_Assembly" ^
  --project_label   "NA156_H2024_V2" ^
  --min_size 50 --pair_gate overlap --merge_scope neighbour ^
  --ladder merge_first --loss_tolerance 0.0025 ^
  --scale_gate true --auto_model false
```

Outputs: `merge_report.json` (schema 2 — per-attempt peel sizes, attribution, confidence,
`cameras_lost`, `loss_tolerance`, `rs_finalizing`, durations), `EVALUATION_READY.txt`, and
`assembly/<name>.rsproj`.

Assembly-only staging (no ladder, every input carried as-is):

```bat
python merge_zones.py --complist "F:\na156_h2024_v2\final.complist" --assemble_only true ^
  --components_root "F:\na156_h2024_v2\aligned_components" ^
  --images_root "F:\na156_h2024_v2\batched_images_by_zone" ^
  --output "F:\na156_h2024_v2\final_assembly" --name "H2024_Final"
```

---

## 9. Failure catalogue

| # | Symptom | Cause | Mitigation | Tag |
|---|---|---|---|---|
| 1 | `-importComponent` never returns; `#timeout` progress lines tick for hours; no error, no minidump | The `.rsalign` was copied/moved away from its original export directory | Import in place; drive from a `.complist` of original paths; watchdog merge-class ops at 45 min | [VERIFIED: NA167 B1] |
| 2 | Merge exits SUCCESS, "merged" export is just the biggest input | Zero content overlap between the components | Census every merge; gate candidates on shared imagery or true bbox overlap | [VERIFIED: NA167 #23–26] |
| 3 | `-selectAllComponents` fails `0x82000060` | The command does not exist in 2.2 | Use `-selectMaximalComponent` / no pre-selection at all | [VERIFIED: NA167 B2] |
| 4 | Flags appear applied but nothing changed; `err:7155 Parsing setting … failed` in the app log; workflow aborts on the errors marker | `key=value` split by cmd into two `.bat` arguments | Cross the boundary as `key:value`; convert inside the workflow; always quote the pair at `-set` | [VERIFIED: NA167 B5] |
| 5 | Component/XMP export completes in ~0.06 s and writes nothing | Flight-log import left images actively selected; under `-silent` the "Export Selection" dialog is auto-answered | `-deselectAllImages` before **every** export | [VERIFIED: FINDINGS 2026-07-23] |
| 6 | Small components missing from exports and from the census | `-setMinComponentSize` default 5 silently excludes them | `-setMinComponentSize 1` before census exports (the command is deprecated but still required) | [VERIFIED: NA167 B11] |
| 7 | Peel harvest returns `[]` while `<name>_c0.rsalign` exists | Images resolve through a directory junction, so RS writes no sidecars (silently); or PowerShell 5.1 will not descend into junction children | Real directories with hardlinked images; the empty-peel invariant aborts the run | [VERIFIED: FINDINGS 2026-07-27/28] |
| 8 | Two accepted fusions in one cluster collide on the name `<tag>_m_c0`; "duplicate component identity" | `peel_index` restarts every attempt | Embed the attempt number: `<tag>_a<N>_c<K>` | [VERIFIED: FINDINGS 2026-07-28] |
| 9 | `merge_zones` aborts with "complist entries without manifests" for a file that exists | UTF-8 **BOM** on line 1 written by PowerShell 5.1 `Set-Content -Encoding utf8` | Write with `UTF8Encoding($false)` or from Python | [VERIFIED: FINDINGS 2026-07-27] |
| 10 | A completely successful ladder that fused 3 → 1 then aborts with "need at least 2 components" | The `component_count LSS 2` guard was applied to `assemble` mode too | Assemble mode now requires ≥ 1; every other mode still requires ≥ 2 | [VERIFIED-as-fixed: FINDINGS 2026-07-28] |
| 11 | Report shows `workflow_success: true, attribution: "ambiguous", adopted_count: 0, camera_delta: null` and no rejection reason — looks like a clean no-op | A real but *lossy* fusion is invisible to exact subset-sum attribution | Bounded-loss tolerance (`--loss_tolerance`), explicitly passed | [VERIFIED: FINDINGS 2026-07-27/28] |
| 12 | Attempts that re-import a previously fused component harvest nothing (`identity_r0: 0`) | Not explained | Do not build on it without a probe | [OPEN: FINDINGS 2026-07-28] |

---

## Open questions

Every `[OPEN]` in this document, with the cheapest probe that would close it.

| # | Question | Cheapest probe | Origin |
|---|---|---|---|
| O-1 | What exactly does `Finalizing N component(s)` count — newly created components, scene total, or components entering the finalize phase? It is the strongest available rigid-glue discriminator and its semantics are unknown. | Two tiny imports (e.g. the 78- and 42-camera D7 components), one `-mergeComponents`, then peel and compare the peel length against the logged `N`. ~5 min on the smoke fixture. | FINDINGS 2026-07-28; NA167 B11 ("Finalizing 9 components" on a zero-overlap pair, "fragment behavior under analysis") |
| O-2 | Was D7b a genuine content fusion or a rigid glue? It satisfies four of the five rigid-glue tests (zero shared basenames, exact 120 = 78+42, `merge_georef`) and is exonerated only by "Finalizing 1" and the absence of a flight log in the merge scene. Do imported components carry their own georeferencing into a new scene? | Re-run D7b with input components aligned **without any flight log** (so they cannot be georeferenced at all). If it still fuses, content fusion is proven independent of georeferencing. ~15 min on the smoke fixture. | This document, §5.7 |
| O-3 | Does `sfmMergeGeoreferencedComponents=true` work when the components are georeferenced by **ground control**, rather than by 10 m-accuracy position priors? The D1/D2 cells arguably never met the feature's documented premise. | Re-test the georef-flag path with priors-v2 components (tight accuracies), or with ≥ 3 GCPs assigned across the two components, on a zero-content-overlap pair. Queued as a PD follow-on cell, never run. | SUPERSEDED-RISK flag, FINDINGS 2026-07-25 |
| O-4 | Are the 2 (or 3, or 5) "lost" cameras in a fusion a real solver drop or a harvest artifact? The peel harvest is a single PowerShell `Move-Item -Force` line that exits 0 on non-terminating errors, and the ICP check reused those same poses. | Settle it from artifacts already on disk: re-import `cluster_*_m_c0.rsalign` **from its original export location** into a spare instance and census it. 3,740 ⇒ accounting artifact; 3,738 ⇒ real loss. (Reading RealityScan's own count from `rslog.txt` is not trustworthy on these artifacts because of the log-splice finding.) | FINDINGS 2026-07-27 |
| O-5 | A **truncated** peel is currently indistinguishable from a complete one — `expected_peelend_<instance>.txt` is written and never read. | Have the driver require that evidence file (or a rename failure record) before treating a peel as complete; assert `peel_index` reached the terminal rather than the 40-lap cap. Code change plus one smoke run. | FINDINGS 2026-07-27 adversarial review |
| O-6 | Why do attempts that re-import a previously fused component harvest nothing (`identity_r0: 0`)? cluster_1 attempts 2–4 recorded zero while attempts 1 and 5 harvested normally; it did not recur in merged5. | Import one previously fused `.rsalign` from its original location into a fresh scene beside one un-fused component, run the peel, and compare against the same pair with the fused input replaced by its parents. ~20 min. | FINDINGS 2026-07-28 |
| O-7 | Does `-exportLatestComponents` produce anything after a plain `-mergeComponents` (which is not an "alignment", so "the last alignment" may be empty)? The repo restricts the call to align mode on the assumption that it does not. | Run merge mode on the smoke fixture, then `-setMinComponentSize 1` + `-exportLatestComponents <dir>` and count the files. ~5 min. | Hardening cell U9 |
| O-8 | Does `-align` UPDATE an existing component **in place**, keeping its name, when it only grows — or does it always create a new `Component N`? | Align a scene, rename the maximal component to a distinctive string, add a handful of images, re-align, then `-selectComponent <that string>` and check whether it resolves. ~10 min. | Hardening cell U6 |
| O-9 | Does `appCopyImportedComponentsToCache` (bool, default `false`) change the relocated-import hang? It is the one setting that plausibly interacts with hard rule 7. | Set it `true`, then `-importComponent` a **deliberately relocated** copy of a small component with a 10-minute watchdog. If it imports, the hang has a supported workaround. | SURVEY_settings; CLAUDE.md hard rule 7 |
| O-10 | Do the merge-by-**control-point** and merge-by-**ground-control-point** paths work headless? Both are documented (≥ 4 CPs each on more than one image per component / ≥ 3 GCPs with ≥ 5 assignments) and neither has ever been driven through this CLI. | On the smoke fixture, place 6 CPs across the mini_a/mini_b pair via `-importControlPointsMeasurements` + `-editControlPointSelection`, then `-align`; census. The prerequisite params XML must be exported from the GUI dialog once. | tutorials/mergecomponents_cp; never exercised here |
| O-11 | Which feature-source mode (`-setFeatureSource 0\|1\|2`) is actually consumed by which operation, and does `0` ("merge using overlaps") measurably speed up or improve a merge on duplicated overlap bands? The Help ties the trio to "a new alignment of components", implying align-only, but this has never been A/B'd here. | On the D6 split-zone fixture (390 shared images), run `-selectAllImages -setFeatureSource 0` then `-align`, versus the same with mode `1`, and compare runtime, peak RAM and fused camera count. ~2 h. | [INFERRED] from appbasics/components; NA167 B11 |
| O-12 | Are the "Small Components" thresholds (*Include smaller than* default 3, *Exclude bigger than*, *As small as a percentage of inputs*) and "Delete all small components" reachable from the CLI at all? | Type likely key prefixes into the GUI console view with TAB completion, or change each control and diff the app config. ~5 min with the GUI. | appbasics/smallcomponents; absent from allcommands |
| O-13 | Is `-exportSelectedComponentFile <fileName>` a naming-safe alternative to `-exportSelectedComponentDir` (which names the file after the component)? Untested here. | One export of a known component to an explicit filename; check the resulting name. ~2 min. | appbasics/allcommands; unused by this repo |
| O-14 | Does `-renameSelectedComponent` on an empty scene **fail** `0x80070057` or **silently no-op**? Two in-repo observations disagree (2026-07-23 vs 2026-07-24, §2.3), and the peel terminal depends on it — the workflow currently handles both, but a truncated peel is only detectable if the failure form is guaranteed (see O-5). | `-newScene`, then `-selectMaximalComponent`, then `-renameSelectedComponent x`; read `errors_<instance>.txt`. Repeat once after a delete-to-empty rather than a fresh scene, since those may differ. ~1 min. | FINDINGS 2026-07-23 vs 2026-07-24 |
