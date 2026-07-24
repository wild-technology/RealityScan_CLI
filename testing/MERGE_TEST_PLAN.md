# Component-Merge Test Plan — RealityScan 2.2, NA167 zones 6/14/4

Goal: determine, empirically, how zone components produced by this
pipeline are best merged into one complete georeferenced component —
which mechanism, which flags, and which zone-growth pattern scale to a
full dive (18+ zones).

Status legend: `RUNNING` / `QUEUED` (scripted, waiting on instance) /
`PLANNED` / `DONE(result)`. Update this file as cells complete; raw
metrics land in `D:\na167_h2075\rs_test\merge_test\strategy_results.json`
(wave 1) and `flag_results.json` (wave 2).

## 1. What the documentation actually says

All quotes from the local help (`C:\Program Files\Epic Games\
RealityScan_2.2\Help\en-US\`), which is authoritative for this build.

### Commands (`appbasics/allcommands.htm`)

| Command | Doc statement | Implication |
|---|---|---|
| `-mergeComponents` | "Merge already created components. When using this command, **no new images are added** to the existing components." | Pure fuse of existing components. Contrast with `-align`, which both merges and adds. |
| `-importComponent c.rsalign` | "Import a component from the component.rsalign file." | Components are portable across scenes/instances. |
| `-align` | (tutorials) align/update semantics: aligns new images **and** extends/merges existing components. | The implicit second merge path. |
| `-add list.imagelist` | "Import one or more images from a specified file path or from an image list… full paths… each" | Enables shared-path components across zone scenes. |
| `-addFolder` | "To include subdirectories, use `-set "appIncSubdirs=true"`." | Observed to recurse in our env without the key; set it explicitly anyway. |
| `-exportXMPForSelectedComponent` | "XMP files are stored in the same folder as the respective images." | Our registration ground truth; also why test images must live in a disposable pool. |

### Settings keys (`tutorials/setkeyvaluetable.htm` + `appbasics/alignsettings.htm`)

| Key | Type/default | Doc prose | Hypothesis for our data |
|---|---|---|---|
| `sfmMergeGeoreferencedComponents` | bool / false | "When multiple components are created and each is georeferenced, enabling this setting allows them to be **merged even without visual overlap**." | The big lever: every zone component is UTM-georeferenced by flight log, so merges should succeed even where camera identity is broken (duplicated overlap copies). |
| `sfmForceComponentRematch` | bool / false | "realigns images and cameras to find better connections. It uses existing camera poses to search for new matches." | Improves merge quality / rescues weak overlap at extra runtime. |
| `sfmImagesOverlap` | Low/Medium/High (repo params: Low) | (pairing breadth hint) | Higher = broader pair search; may matter for cross-zone seams in joint/sequential aligns. |
| `lisPreferImagesAsFeatureSource` | bool / false | "import .zfprj mosaic images and use them as feature source… help to register the unregistered scans or automatically find the same features when merging" | Laser-scan oriented; low priority probe. |
| `appCopyImportedComponentsToCache` | bool | (undocumented prose) | Operational only; not swept. |

### GUI-only feature-source modes (`appbasics/components.htm`) — no documented CLI key

> "**Merge using overlaps** — the software will use solely the
> components' images/points which are in common (the same in all
> components)… extremely speeds up… reduces memory."
> "**Use component features** — most common and fastest… only the points
> used in the alignment of the imported component… important to create
> components which have more points in common."
> "**Use all image features** — slowest… recommended for a small number
> of camera poses."

CLI cells therefore run whatever RealityScan's headless default
feature-source is; this is a documented **limitation**, not a testable
axis. If merge quality ever hinges on it, the fallback is saving a GUI
project with the mode set and driving it via CLI.

### Ambiguities the matrix resolves empirically

1. Does `-mergeComponents` require shared cameras **by path identity**,
   or does duplicate pixel content suffice? (A1 vs A2)
2. Does `sfmMergeGeoreferencedComponents=true` let `-mergeComponents`
   fuse georeferenced components with zero shared identity? (D1)
3. Is `-align`-with-components equivalent to `-mergeComponents`, better,
   or worse? (D2, D3 vs A1/A2 merges)
4. Does incremental `add→log→align` growth chain a single component
   without any merge step? (B)
5. What does chunk+merge cost vs one joint align? (A2/B vs C)
6. Does pairwise progressive merging (M1=6+14, M2=M1+4) preserve
   quality, i.e. does the pattern scale to 18 zones? (D4 vs A2)

## 2. Fixtures

- Chain: `zone_6 ←312 shared→ zone_14 ←239 shared→ zone_4`, **zero**
  direct 6↔4 overlap → a single final component proves transitive
  stitching.
- Pool: `rs_test\merge_test\pool` — 4,131 unique Zeuss-dominant images
  at stable paths; per-zone `.imagelist` (full), `_new.imagelist`
  (incremental), `union.imagelist`, per-zone + union flight logs,
  auto-generated `FlightLogParams_53N.xml`.
- Workflows (all `:run`-pattern, in `RS_CLI/Scripts/`):
  `AlignImagesFromFolder.bat`, `AlignImageList.bat`,
  `SequentialAlignGrow.bat`,
  `MergeZoneComponents.bat <comps> <out> <name> [merge|align] [k=v ×5]`.

## 3. Metrics & contamination controls

Per cell: **cameras in final component** = exported stem `.xmp` files
containing `<xcr:Position>` (census across the dirs the component's
images live in); **component files** exported (count = did it fuse);
**runtime**; **errors marker** content; RealityScan's own
`%LOCALAPPDATA%\Temp\RealityScan.log` harvested for merge/registration
lines (no timestamps — bookmark by byte offset per cell).

Controls:
- Pose-bearing XMPs deleted between cells (RealityScan auto-imports
  sidecars on add → a leftover export = exact-pose priors leak).
- Swept `-set` keys are **pinned in every cell** (values persist across
  instance restarts).
- Legacy `*.jpg.xmp` prior files are inert (wrong naming) and ignored
  by the census.
- One instance (RS1, GPU 0), sequential cells, verified shutdown between.

## 4. Test matrix

### Wave 1 — mechanism baselines (RUNNING)

| Cell | Inputs | Mechanism | Flags | Hypothesis |
|---|---|---|---|---|
| A1_align_z6/z14/z4 | zone folders (duplicated overlap paths) | per-zone `-align` | defaults | ≥90% registration each (zone_13 precedent) — z6 DONE(95.2%, 1533/1610, 1 comp, 61.6 min); z14 **FAILED** (0x8000FFFF @54.6 min, no dump → transient theory; wave-1b retry queued); z4 DONE(90.1%, 1438/1596, 1 comp, 24.3 min) |
| A1_merge_full (wave 1b) | retried z14 + z6 + z4 | `-mergeComponents` | defaults | replaces A1_merge if z14 retry recovers; without z14 the wave-1 A1_merge cell degrades to a zero-overlap negative control (z6+z4 share no images) |
| A1_merge | 3 components, duplicate paths | `-mergeComponents` | defaults | **fails or partial** — no shared camera identity. RESULT (wave 1f, z6+z4 zero-overlap control): workflow exits SUCCESS but **nothing fuses** — maximal component = zone_6 exactly (1,533 cameras). `-mergeComponents` is **silent** when it cannot merge; verify by camera count, never exit status. (Earlier attempts: relocated-import hang B1; `=`-split voids B5.) In-place imports: ~2 s per 0.7 GB component |
| A2_align_z6/z14/z4 | pool imagelists (shared paths) | per-zone `-align` | defaults | same registration as A1 — z6 DONE(95.3%, 1534 posed, 1 comp, 97.8 min; registration identical to A1's 95.2%, so path form doesn't affect alignment); z14 **FAILED again** (0x8000FFFF @30.8 min — 2/2 across path forms → scene-specific internal RS failure, NOT transient, NOT data corruption: all 1,476 images deep-decode clean, log has no degeneracies, motion profile normal vs neighbors). Localization comes from the retry + whether B/C survive z14's images; z4 DONE(91.0%, 1453 posed, 1 comp, 20.8 min — matches A1's 90.1%) |
| A2_merge | 3 components, shared paths | `-mergeComponents` | defaults | **single component ≈ sum of zones** via 312/239 shared cameras |
| B_sequential | incremental lists, one scene | `add→log→align` ×3 | defaults | one component grows without merge step — **DONE: SUCCESS. Single component, 3,906/4,131 posed (94.6%), 444 min.** Transitive 6→14→4 stitching proven; zone_14's images registered fine inside the grown scene (B8 is a standalone-scene solver failure, not bad data). Runtime premium ~3.5× vs separate zone aligns |
| C_joint | union list | single `-align` | defaults | ceiling registration; longest single-op runtime — **DONE: single component, 3,904/4,131 (94.5%), 168.8 min, peak memory ~165 GB (27 GB commit headroom left on a 192 GB box)**. Registration identical to B (94.6%); 2.6× faster than B but 2.7× the memory. Joint alignment does NOT scale to a full dive (~19k images ⇒ ~700 GB extrapolated) |

### Wave 2 — flag variants + growth pattern (ALL DONE 2026-07-24)

| Cell | Inputs | Mechanism | Flags | RESULT |
|---|---|---|---|---|
| D1_geo_merge | duplicate-path comps (z6+z4, zero overlap) | `-mergeComponents` | georef=**true**, rematch=false | **No fuse** — 1,533 = zone_6 alone; the flag does not change `-mergeComponents` |
| D2_geo_rematch_align | duplicate-path comps | `-align` | georef=**true**, rematch=**true** | **No fuse** — 1,533; georef merging never manifested headless (finding 25 caveat: prior-weighted vs GCP-locked georeferencing) |
| D3_align_sharedpath | shared-path comps (z6+z4, zero overlap) | `-align` | both pinned false | **No fuse** — 1,534; align-as-merge needs shared cameras too |
| D4 | — | — | — | Skipped (zone_14 solo comp unproducible, B8); superseded by D5/D5-alt/D6 |
| D5_step1 grow z6+z14 | incremental lists | `add→log→align` ×2 | defaults | **Fragmented**: maximal 870 < z6's solo 1,533 (finding 29 — growth is state-sensitive); step 2 merge therefore inconclusive (1,453 = z4 alone) |
| D5-alt | grown_b (3,906) + z4 comp (1,453), massive identity | `-mergeComponents` | pinned false | 56-min real merge reconstruction, "Finalizing 11 components", full 3,906 retained — behaviorally positive, count-ambiguous |
| **D6 split-zone (decisive)** | two z6 halves (749 + 342 cams, 390 shared images) | `-mergeComponents` | pinned false | **FUSED: "Finalizing 1 component"** after 56 min (app log; workflow export step then hit a one-off cmd anomaly, so no .rsalign artifact — verdict stands on the log). **Positive proof of align-then-merge.** |

### D5 — rebuilt positive merge test (PLANNED; zone_14 solo comp is unproducible)

Grow z6+z14 sequentially (proven to digest zone_14), export the two-zone
component, then `-mergeComponents` it with zone_4's solo shared-path
component — 239 shared pool images provide camera identity across the
two components. This is the align-then-merge production pattern under
test despite B8.

### Wave 3 — conditional follow-ups (PLANNED, gated on waves 1–2)

| Cell | Trigger | Test |
|---|---|---|
| E1 overlap-breadth | B or C misses cross-zone seams | re-run with `sfmImagesOverlap=Medium/High` |
| E2 georef-assist on shared paths | A2_merge partial | A2 comps + georef=true |
| E3 feature-source probe | any merge quality-limited | `lisPreferImagesAsFeatureSource=true` variant (long shot; laser-scan oriented) |
| E4 refine-then-merge | seam misalignment in merged output | poses2flightlog per zone → re-align with 1 m refined priors → merge |

## 5. Empirical findings about the CLI itself (2026-07-23)

Discovered by the matrix runs, all now fixed in the repo:

1. **`-importComponent` hangs forever on a relocated `.rsalign`** — a
   component file copied away from its export directory imports into a
   `#timeout` state that never errors (observed 6 h+). Import components
   from their original export paths; `MergeZoneComponents.bat` takes a
   `.complist` file of paths for exactly this reason.
2. **`-selectAllComponents` does not exist in RealityScan 2.2** despite
   appearing in older scripts — it fails with 0x82000060
   (verified against `allcommands.htm`: only `selectComponent` and
   `selectMaximalComponent` exist). `AlignZonesSequentially.bat` carried
   this bug since it was written; fixed.
3. **`-getStatus` reports an instance gone seconds before its process
   releases file handles** — the next workflow's marker clear raced the
   teardown. `RealityScanCLI._clear_markers` now retries for 60 s.
4. **`#timeout`-tagged progress lines tick like activity** — they muted
   the stall detector during the import hang. The detector now treats
   them as stall evidence, not progress.
5. `cmd` splits unquoted `;` `,` `=` into separate batch arguments, and
   Python's `subprocess` only quotes on space/tab/quote — pass lists to
   .bat workflows via files, never delimited arguments.
6. `0x8000FFFF` (2147549183) is RealityScan's **generic** "unexpected
   program state" process result — broken `-set` arguments and the
   zone_14 align failure both report it. The code alone identifies
   nothing; the reason line lives only in `%LOCALAPPDATA%\Temp\
   RealityScan.log`, which each instance boot truncates — snapshot it
   immediately after a failure.
7. The same `=`-splitting hit `key=value` **settings arguments**: RS
   received key and value as separate `-set` parameters (err:7155,
   "Parsing setting key=value failed"), so no flag cell before wave 1f
   ever applied its flags — and the parse failures landed in the errors
   marker, spuriously aborting the merge workflows that carried them.
   Settings now cross the python→bat boundary as `key:value` and the
   workflow converts the colon. Wave 1e's merge-cell "results" are void;
   wave 1f re-runs them and snapshots `RealityScan.log` per cell (each
   instance boot truncates it).

## 6. Decision rules

- If **D1** works: today's batcher output (duplicated overlap copies)
  merges as-is → no pipeline change needed for merging; keep folders.
- Else if **A2/B** work: batcher gains an imagelist/hardlink mode so zone
  scenes share image paths; alignment module grows or merges from there.
- **B vs A2**: B needs no component juggling and no second pass — prefer
  it if quality matches; A2/D4 remain the recovery path when a zone must
  be re-run in isolation.
- **C** sets the quality bar: chunked strategies within ~2–3% of C's
  registration with materially better peak memory/runtime win.
