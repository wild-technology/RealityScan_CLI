# Findings log — append-only, one entry per finding

Format: **finding** → *how it was discovered*. Newest at the bottom.
Companion docs: `NA167_SESSION_NOTES.md` (revised CLI docs + bug list),
`MERGE_TEST_PLAN.md` (matrix), `strategy_results.json` (raw numbers).

---

1. **Extracted frames were timestamped one output interval early (60 s
   at 1 fpm), shifting every georeference by a minute of ROV travel.**
   → Code review of `__extract_video_cv2`: the frame seek (`next_frame_number`)
   and the timestamp source (`current_frame_number`) used different frame
   indices. Confirmed by a synthetic 30 fps video with per-frame gray
   levels: extracted frame content matched the *corrected* timestamps.

2. **The pipeline's stage chaining had never worked end-to-end.**
   → Cross-reading producers vs consumers: batcher writes
   `batched_images_by_zone/` + `flight_log<suffix>_UTM.txt`; alignment
   read `batched_images/` + `flight_log.txt`. No run log ever showed it —
   the alignment module silently aligned without a trajectory when the
   log wasn't found.

3. **XMP calibration priors were never loaded in any historical run.**
   → Arithmetic anomaly: after aligning zone_13, 871 "new" .xmp appeared
   in a folder that already had 904 — exports (`stem.xmp`) hadn't
   overwritten the priors (`name.jpg.xmp`). RealityScan only reads
   `stem.xmp`.

4. **The prior content itself hurts registration (96.3% → 89.6% on
   Zeuss).** → A/B on zone_13: run 1 with priors effectively absent
   (naming bug), run 2 after promoting priors to `stem.xmp` and deleting
   run-1 poses. Same images, same settings.

5. **`-addFolder` imports camera subfolders into one scene; basename
   flight logs match images in subfolders.** → zone_13 live run: 34 wca
   + 904 zeuss images in subfolders, bare-filename log, 93.4%
   registered, no err:18002.

6. **UTM zone must be derived per cruise, never hand-edited.** →
   HANDOFF already warned (NA173 was 57S while the template said 4N);
   NA167 computed to 53N from `utm.from_latlon` and verified round-trip
   through the generated FlightLogParams (EPSG:32653).

7. **Full-file image verification is untenable at this scale.** → The
   first georeference run sat at ~180 s CPU with hours projected: PIL
   `.verify()` walks every byte for CRCs ≈ 720 GB of reads over 18k
   39 MB stills. Header-probe cut the whole stage to ~5 min.

8. **geoall's "binary search" was O(N) per lookup anyway.** → Review:
   `times = [row["TIME"] for row in data_rows]` was rebuilt inside every
   call before `bisect`.

9. **Multiple nav CSVs per dive collide into one dict key.** → NA167's
   root has nine `NA167_H2075_*.csv`; `find_rov_datafiles` kept
   whichever globbed last. Now prefers `*final_datatable.csv`.

10. **cmd/stdin encoding breaks scripted prompts.** → Batch driver died
    at the accept prompt: PowerShell native piping prepends a BOM and
    delivers CRLF, so `input()` returned `"a\r"` ≠ `"a"`. Discovered by
    reproducing the pipe in isolation; fixed with `.strip()` everywhere
    and scripted `input()` in drivers.

11. **`-importComponent` of a relocated .rsalign hangs forever
    (#timeout state, no error).** → A1 merge stage sat 6 h; workflow log
    stopped at the first import; progress marker ticked `#timeout` with
    garbage ETA. In-place imports later measured at ~2 s per 0.7 GB.

12. **`#timeout` progress lines defeat line-change stall detection.** →
    The same 6 h hang produced zero stall warnings: every tick differed
    from the last line, so it counted as activity. Detector now treats
    `#timeout` as stall evidence.

13. **`-selectAllComponents` does not exist in RealityScan 2.2.** → A2
    align failed at the export block with 0x82000060; grep of
    `allcommands.htm` lists only `selectComponent` /
    `selectMaximalComponent`. The dead command had lived unnoticed in
    `AlignZonesSequentially.bat`.

14. **`-getStatus` says "gone" before the process releases marker-file
    handles.** → Next workflow's marker clear raised "held open" seconds
    after shutdown verification passed. 60 s retry added.

15. **cmd splits unquoted `;` `,` `=` into separate .bat arguments, and
    Python subprocess only quotes on whitespace.** → Twice: a
    semicolon-joined component list arrived as two args ("found 1");
    then `key=value` settings arrived split — RealityScan.log showed
    `Parsing setting key=value 'sfmMergeGeoreferencedComponents' failed
    [err:7155]` and `'false' failed`, meaning **no flag cell had ever
    applied its flags** and the parse errors aborted the workflows via
    the errors marker. Lists now cross as files, settings as
    `key:value`.

16. **`0x8000FFFF` is generic ("unexpected program state"), and
    RealityScan.log is truncated on every instance boot.** → Broken
    `-set` args and the zone_14 align failure emitted the identical
    code; a post-failure log snapshot lost the race to the next boot
    (91-byte capture). Log copies now happen inside the driver
    immediately after the failing call returns.

17. **zone_14 fails standalone alignment deterministically (3/3,
    0x8000FFFF) with fully clean data.** → Reproduced across duplicate-
    path and shared-path forms at different elapsed times. Data
    exonerated by: full-pixel decode of all 1,476 frames, zero MD5
    duplicates, zero near-black/featureless frames (Laplacian), zero
    nav duplicates/gaps, motion profile bracketed by its two healthy
    neighbors.

18. **zone_14's images align fine inside a larger scene.** →
    B_sequential grew z6→z14→z4 into ONE component, 3,906/4,131 posed
    (94.6%) — including zone_14's frames. The failure is scene-solve
    specific, not data. Production workaround: grow stubborn zones from
    an aligned neighbor.

19. **Sequential growth and joint alignment give identical quality;
    they differ 2.6× in time and 2.7× in memory (opposite winners).** →
    B: 94.6%, 444 min, ≤60 GB. C: 94.5%, 169 min, ~165 GB peak (27 GB
    commit headroom on a 192 GB box). Joint alignment extrapolates to
    ~700 GB for a full 19k-image dive — not viable; chunking is not
    optional at production scale.

20. **Alignment runtime varies ~3× with scene character at equal image
    count.** → zone_6 61.6/97.8 min vs zone_4 24.3/20.8 min, both
    ~1.5k frames, same GPU, both run twice.

21. **LF-only .bat files break `call :label` nondeterministically.** →
    The first valid merge cell died with "cannot find the batch label -
    run" after ten successful `call :run`s; the new bats had been
    written with LF endings. CRLF conversion fixed it;
    `.gitattributes` pins `*.bat eol=crlf`.

22. **`-setMinComponentSize` is deprecated** ("will be removed in the
    next release"). → Warning line in the per-cell RealityScan.log
    snapshot during the first valid merge cell.

23. **`-mergeComponents` is SILENT when it cannot merge.** → Zero-
    overlap control cells (z6+z4, flags off, both path forms): workflow
    exits success, single exported "merged" component is exactly
    zone_6's (1,533/1,534 cameras). Merge success must be verified by
    camera count (pose-bearing XMP census), never by exit status.

24. **`sfmMergeGeoreferencedComponents=true` does NOT change
    `-mergeComponents` behavior.** → D1: identical zero-overlap pair,
    flag on, still 1,533 cameras (zone_6 alone). Working hypothesis: the
    key is an *alignment* setting and only modulates merging performed
    by `-align` — under test in D2 (align mode + georef + rematch).

25. **Georeference-based merging did not manifest via headless CLI in
    ANY form we could drive.** → D2: `-align` over the imported pair
    with georef=true + forceRematch=true — still 1,533 (zone_6 alone).
    Caveat recorded rather than "docs wrong": components built from
    flight-log **priors** may not count as "georeferenced" in the sense
    the flag requires (RS distinguishes prior-weighted from
    ground-control-locked georeferencing; our exports' lat/long XMP
    attrs are garbage per poses2flightlog analysis). Practical
    conclusion for production: do NOT rely on georef merging — plan
    image overlap between zones; shared cameras are the only merge
    mechanism verified to work headless (D5 pending as the positive
    proof).

26. **The zero-overlap non-merge is universal across mechanism × flag ×
    path form.** → Full 1f sweep on the z6+z4 pair: `-mergeComponents`
    flags-off (A1/A2 controls), `-mergeComponents` + georef (D1),
    `-align` + georef + rematch (D2), `-align` flags-off shared paths
    (D3) — every cell exits success with the maximal component exactly
    zone_6 (1,533/1,534 cameras). ~17–21 min per cell, dominated by
    boot/import/export overhead, not merging.

27. **zone_14's failure is RealityScan internal error `MSS_STR001` in
    the reconstruction phase.** → 4th deterministic reproduction with
    in-driver log capture (`merge_test/z14_forensic_rslog.txt`): all
    1,476 features detect fine, "Reconstruction failed after 1449 s,
    Processing failed: Unexpected program state, [Internal error
    MSS_STR001]" plus an internal trace. A solver bug triggered by this
    scene's structure — reportable to Epic with the captured log; the
    grow-from-neighbor workaround (finding 18) stands as the production
    mitigation.

28. **`#timeout` progress does NOT always mean hung** — heavy align
    phases legitimately freeze the progress fraction for 20+ minutes
    while deep compute proceeds. → Calibrated by grepping B_sequential's
    successful run: 40 `#timeout` lines, streaks frozen at one fraction,
    final result 94.6%. The pathological signature is `#timeout` from
    fraction 0.00 with an ever-growing ETA (the import hang). Policy:
    stall-warn on `#timeout` (2 h), never auto-kill an align on it.

29. **Incremental growth is state-sensitive and can DEGRADE existing
    structure.** → D5 step 1 (grow z6 → add z14 → align): both aligns
    finalized 4 components and the final maximal held only 870 cameras —
    less than zone_6's solo 1,533 — while B's three-stage grow through
    the same first two stages ended at 3,906 in one component. Adding a
    pathological zone (z14, see finding 27) to a two-zone solve broke it;
    the three-zone context held. Incremental growth outcomes are not
    order/subset-invariant — verify camera counts after every grow step.

30. **`-mergeComponents` performs a real reconstruction pass when
    components share cameras.** → D5-alt (grown_b 3,906 + a2_zone_4
    1,453, massive camera identity): 56 min of merge reconstruction,
    "Finalizing 11 components", maximal exported at the full 3,906 with
    no loss — versus instant silent no-ops on every zero-overlap pair.
    Count-ambiguous (z4 added ≈0 new cameras by construction), so the
    decisive fixture is the split-zone test (two z6 halves sharing ~390
    images: fused ≈1,533 vs unfused ≈1,000) — running as D6.

31. **CONFIRMED: `-mergeComponents` FUSES components through shared
    cameras.** → D6 split-zone fixture: zone_6 divided into two
    1,000-image halves sharing 390 images, each aligned solo (749 and
    342 cameras), imported into a fresh scene, `-mergeComponents` with
    both flags pinned false → RealityScan app log: 56 min of merge
    reconstruction ending in **"Finalizing 1 component"** — two in, one
    out. This is the positive proof that align-zones-then-merge works
    headless, requiring only image overlap between zones at shared
    paths. (The workflow's EXPORT step then died on a one-off cmd
    anomaly — `%RealityScan%` expanded empty after the 56-min block,
    "'-delegateTo' is not recognized" — so no .rsalign artifact was
    exported; single occurrence across ~10 identical merge workflows,
    unexplained, re-run if the artifact is needed.)

32. **`*` is a valid instance name meaning "the first available
    instance" — so a GUI-launched RealityScan with no
    `-setInstanceName` IS reachable from the CLI.** → 2026-08-04, live
    ON2026 session. A RealityScan started by the Epic Games Launcher
    (no instance name on its command line) answered `-getStatus RS1`
    with exit 5, which looked like "unreachable, CLI is useless here".
    The local Help settled it: `getStatus instanceName|*`,
    `delegateTo instanceName|*`, `waitCompleted instanceName|*`,
    `pauseInstance|abortInstance instanceName|*` all accept `*`.
    Verified: `-getStatus *` → **exit 0** against that same GUI
    instance. This removes the assumption that only CLI-booted
    instances can be driven.

33. **`-getStatus` prints a live progress line on stdout, not just an
    errorlevel — it is a usable error and progress oracle for an
    instance that has no ErrorWriter hook.** → Same session: capturing
    stdout gave
    `id:0x5051 progress:11.1% runtime:575.04sec endEstimation:4579.16sec rev:93 lastError:0`.
    Fields: operation id, percent, elapsed, estimated remaining,
    revision, last error code. A GUI-launched instance never ran
    `startRealityScan.bat`, so `errors_<instance>.txt` does not exist
    for it and the `:run` marker-file gate is blind; parsing
    `lastError:` covers that gap. Parser verified against a known-good
    (`lastError:0` → pass), a known-bad (`lastError:20501` → fail) and
    an empty status (→ pass, nothing running). NOT yet verified: whether
    `lastError` is sticky across operations, i.e. whether a code left by
    a previously aborted operation would trip the gate on the next
    command. Treat a non-zero `lastError` on the FIRST gated command as
    "inspect the app log", not "this command failed".

34. **`startRealityScan.bat` is unsafe to call against a scene you want
    to keep: it issues `-newScene -deleteAutosave` whenever
    `-getStatus` finds the instance already running.** → Code read
    while planning how to attach to the live ON2026 session. With `*`
    resolving to a GUI instance holding hours of finished
    reconstruction, calling any existing workflow script would have
    silently wiped it, because every workflow starts by calling
    `startRealityScan.bat`. Mitigation: `ModelToFinal.bat` attaches via
    a bare `-getStatus` guard and never calls that script.

35. **`err:7185` "Provided arguments don't match any overload for
    command 'save'" is the signature of a path that got split on
    spaces, not of a bad command.** -> 2026-08-04: a checkpoint
    `-save "M:\ON2026 COLMAP processing\rs\final\...rsproj"` issued via
    PowerShell `Start-Process -ArgumentList @('-delegateTo','*','-save',$path)`
    failed instantly. The **array** form of `-ArgumentList` does not
    quote elements containing spaces for this binary, so RealityScan saw
    three arguments. The directory was writable (write-test passed);
    nothing was wrong with the path. Fix: pass `-ArgumentList` as a
    single **string** with the path explicitly quoted. Same class of bug
    as CLAUDE.md hard rule 8, arriving through PowerShell rather than
    through .bat argument splitting.

36. **`lastError` from `-getStatus` is sticky while the instance is
    idle, but clears when the next operation starts.** -> Same session,
    resolving the open question in finding 33. After the failed save,
    four consecutive polls at `id:0xffffffff` all reported
    `lastError:-2113863583` (0x82010061). The moment the retried save
    began, the field read `lastError:0` again at `id:0x5035`. So a naive
    "fail if lastError != 0" gate would blame the *next* command for the
    *previous* command's error. `ModelToFinal.bat` therefore captures
    `rev:` before delegating and only treats a non-zero `lastError` as a
    failure **if `rev` also advanced** - rev increments once per
    completed operation. When rev is unchanged it warns and continues.

37. **The unwrap preset, not the texture preset, decides the final
    model's UV layout when simplification is on.** -> 2026-08-04 ON2026
    run: texturing was asked for at 4x8192, but the exported model is
    the *simplified* one, which gets unwrapped fresh from
    `Unwrapping_Simplified.xml` - that file says
    `unwrapMaximalTexCount=1` at `16384`, which would have silently
    produced one 16k page instead of four 8k pages (identical texel
    budget, but 16k exceeds the max texture size many engines accept).
    Added `Unwrapping_Simplified_4x8k.xml` and made `ModelToFinal.bat`
    pick the unwrap preset to match the texture preset. Verified in the
    artifact: four `*_diffuse.jpg`, each exactly 8192x8192.
