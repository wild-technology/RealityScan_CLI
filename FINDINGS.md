# FINDINGS — consolidated running log

One entry per established fact, WITH how it was discovered. Append new
findings at the bottom of the relevant section with a date. Refuted
hypotheses stay, marked SUPERSEDED.

CONSOLIDATION NOTE (2026-07-24, extended 2026-08-07): this file merges
THREE research lines:

- **[H2023]** — NA156 H2023 production line (this machine): settings
  evaluation, camera registry, zone aligns, within-zone growth,
  hardening cells U1–U20. Deep docs: `docs/settings-evaluation-2026-07.md`,
  `docs/merge-growth-strategy-2026-07.md`, `testing/ALIGN_MERGE_HARDENING_PLAN.md`.
- **[NA167 #n]** — NA167 H2075 merge-strategy matrix (Honeybadger box):
  strategies A/B/C, D-cell merge-mechanism isolation, findings #1–31.
  Deep docs: `testing/FINDINGS.md` (frozen numbered log, do not append),
  `testing/MERGE_STRATEGY_REPORT.md`, `testing/MERGE_TEST_PLAN.md`,
  `testing/NA167_SESSION_NOTES.md`.
- **[ON2026]** — ON2026 RH0042/RH0043 Voyis stereo line (2026-08-04/07):
  attaching to a GUI-launched instance, the model-to-final half, and the
  nav/orientation groundwork for a re-run. Deep docs:
  `testing/NA167_SESSION_NOTES.md` §3 (operation ids, error codes, exit
  codes). Cross-line: this line's priors are COLMAP-derived and its
  accuracy matrix lives in the external `colmap_studio` fact base
  (cells C-20260730-05/09, C-20260803-01), which upstream code already
  cites — read it before proposing any orientation cell here.

Entries below carry their source tag. Cross-line reconciliations are
tagged **[RECON]** and dated 2026-07-24. `testing/FINDINGS.md` is
frozen as the NA167 raw log; all new findings go HERE.

## [NA168] 2026-08-14 - exports were stamped with the WRONG coordinate system

**H2077 exported with
`globalCoordinateSystemName="epsg:32757 - WGS 84 / UTM zone 57S"`.** H2077
is 53N. 32757 is the placeholder zone sitting in `FlightLogParams.xml`.

SCOPE - the GEOMETRY was never wrong. `ModelExportParamsOBJ_NiraParts`
sets `exportCoordinateSystemType=3`, i.e. geocentric ECEF, and the
exported vertices check out against H2077's own nav to within ~1 km
(computed ECEF -4294961/4638621/833425 vs exported
-4295946/4638342/832605, the residual being the survey patch's offset
from the dive's on-bottom fix). The vertices are absolute, so they do not
depend on a UTM zone at all. What was wrong is the METADATA LABEL - and
that is what a GIS import, a Cesium tiler or a Nira upload reads to place
the asset. Re-exporting changed the label and left the geometry
byte-identical, which is the expected result and the proof of both
claims.

Cause: nothing in the pipeline ever set an output coordinate system, so
the export inherits whatever the application last held.
`write_flight_log_params()` rewrites the CRS of the flight log being
**imported** - it has no bearing on what is **exported**. The two are
separate settings and only the first was managed.

RealityScan 2.2 has `-setProjectCoordinateSystem authority:id` and
`-setOutputCoordinateSystem authority:id`; neither was called anywhere.
`ExportDeliverables.bat` now issues both when `RS_OUTPUT_CRS` is set, and
`export_deliverables.py` derives it from the flight log's own zone tag
(`--flight-log`, via the existing `crs_for_flight_log`) or takes `--crs`
directly. With neither, it now WARNS instead of silently inheriting.

Note this is separate from the publish path, which already resolved a CRS
per asset (`publish_batch.py`) - so the exports on disk were wrong while
the upload was right, and nothing compared them.

## [NA168] 2026-08-14 - the stillcam DNGs declare white_level 255 over 12-bit data

**This silently produced 340 blank white frames and a 0-camera align.**
`raw/still_cam/**.DNG` reports `white_level = 255` while the sensor data is
12-bit (`raw_image` max 4095, median ~331, p99.9 ~1030). rawpy honours the
declared level, so a plain `postprocess()` clips EVERY pixel to white:
converted frames measured mean 255.0 / std 0.1, RealityScan detected no
features, and the align exited **result code 0** with zero components.
Nothing in the pipeline flagged it - a successful-looking run end to end.

`raw.white_level` is read-only, but `raw.raw_image` is writable, so
`tools/convert_dng.py` rescales the plane into the declared range before
demosaic (fixed factor 0.2372, mapping p99.9 to ~245). The factor is
FIXED, never per-image: a per-frame stretch gives overlapping frames
different tone curves and works against the matcher.

Camera WB also renders this imagery heavily magenta (RGB means
229/122/223). The converter now applies a fixed `user_wb` of
[2.1331, 1.3822, 1.2840] - the daylight WB times an averaged gray-world
correction sampled over 8 frames, which agreed within a few percent. Note
this is NOT the gray-world that hurt registration in the zone_9 A/B: that
was correcting already-correct colour; this is fixing a real cast at
conversion time.

LESSON: verify converted imagery has actual content (a luminance std of
0.1 is not an image) before spending a RealityScan run on it. Both failing
aligns here reported success at every stage.

## [NA168] 2026-08-16 - The flight-log FORMAT must be installed, or columns vanish silently

`Metadata/FlightLogParams.xml` names its parser by GUID
(`gpsLogFileFormat`). RealityScan resolves that GUID against
`flightlogs.xml` **in its own installation directory**, never the repo
copy. When the GUID is absent there the import does NOT fail: it falls
back and DROPS the columns that format defined, exit code 0.

Measured 2026-08-16: `grep -c B438A617 "<install>/flightlogs.xml"` = **0**.
Our first ten columns coincide with stock `{97F08A22}`, so position and raw
yaw/pitch/roll still landed and nothing looked wrong, while **columns
10-12 (YawAccuracy, PitchAccuracy, RollAccuracy) were discarded on every
import**, leaving `ifUseOriAcc=true` with nothing to consume. Every H2077 /
H2082 / H2080 align to date ran on unweighted orientation priors.

This is the SECOND occurrence. testing/PRIORS_DISTORTION_TEST_PLAN.md item
1 records the same defect, hand-patched, with the note "verify it survives
app updates". It did not - a RealityScan update reverted the file. A
hand-run repair step is a fix with a half-life.

FIXED, permanently: `modules/flightlog_format.py` asserts the configured
GUID is registered in the INSTALL **before every import**, and SELF-HEALS
by merging the repo's formats when it is not. Verified by reverting the
install to stock and watching the guard detect, install and re-verify.
Checking after an import cannot detect this, so it is checked before.

RELATED FACT, and it retires the sidecars: the CSV flight-log reader's
variable vocabulary is far wider than its shipped example formats suggest.
Per `Help/en-US/tools/defineimportformat.htm` it also accepts
**FocalLength, PrincipalU, PrincipalV, Skew, AspectRatio,
RadialDistortion1-4, TangentialDistortion1-2** - i.e. a full per-image
PRIOR CALIBRATION. New 14-column format `{D1F2A3B4-...}` adds FocalLength
at index 13, sourced per camera from cameras.json. There is no CLI command
that sets focal length (only `-setPriorCalibrationGroup` and
`-setPriorLensGroup` exist), and the WCA units publish no EXIF focal tag,
so before this the focal prior reached RealityScan by NO route at all once
sidecars were removed.

Registration EXPORT is customisable the same way (`calibration.xml`,
`Help/.../defineexportformat.htm`). `-exportRegistration` runs against the
SELECTED component, so `$ExportCameras` enumerates that component's members
in one non-destructive pass, written to the OUTPUT tree - which is what
finally makes the XMP identity harvest unnecessary.

Two traps found while implementing:
- `&tab;` is not a predefined XML entity, so a strict parser rejects both
  files. The first draft SWALLOWED that ParseError and returned an empty
  set, which reports a correctly installed format as missing.
- An ElementTree round-trip reindents the whole stock file and rewrites
  `&tab;` as `&#9;`. The installer splices at TEXT level instead.

## [NA168] 2026-08-15 - Settings contract: the params XML is authoritative for what it names

RealityScan serializes part of its own Alignment Settings dialog under
OBFUSCATED numeric ids - `s235l`, `s236l`, `s237l`, `s251l`-`s254l` -
instead of readable `sfm*` names. AlignZone's applier filtered on
`findstr /b /c:"sfm" /c:"lis"`, so those 7 were silently skipped: **28 of
35 entries applied**, the other 7 inheriting whatever the instance held,
while the file header promised settings "never from instance defaults".

Owner contract (2026-08-15): **settings named in the XML take priority and
are ALL applied; settings it does not name are explicitly UNDEFINED** and
inherit the instance. The old promise was never achievable anyway - the
file names 35 settings, not RealityScan's whole namespace.

Two traps found while implementing it:

- **Never gate on token 1.** The obvious fix is to check that a line is an
  `entry` line, but token 1 is `  (entry key=` and cmd reads that angle
  bracket as a REDIRECTION operator: every `echo %%P| findstr` becomes a
  hunt for a file named `entry`. Measured result: "The system cannot find
  the file specified" x35 and TOTAL=0 - all 35 settings lost, worse than
  the bug being fixed. Gate on the KEY (token 2) instead, requiring it to
  start with a letter: that admits every real setting and rejects the
  `(Configuration id="{GUID}")` header, whose quoted token is brace-led.
- **Angle brackets in `echo` inside .bat** break the same way in error
  messages - an `echo` describing the XML entry format silently redirected.

`app*` keys now FAIL CLOSED (`:appGlobalKey`) rather than being skipped:
they are application-wide, persist into the user's own GUI session, and
need per-instance approval. `appIncSubdirs` is set deliberately in the
workflow, not through the params file. Verified by running the parse
standalone against the real XML: 35 of 35, GUID rejected. 484 tests pass.

## [NA168] 2026-08-14 - RETRACTED: "Division registers ZERO on rectilinear imagery"

**This entry previously reported a controlled A/B showing Division at 0
cameras against Brown3 at 1,925. THE TEST WAS CONFOUNDED. Do not cite it.**

The Division run was given a COPY of a batch tree taken AFTER a full
align + identity-harvest cycle, so it carried 7,694 inherited calibration
sidecars the Brown3 run had left behind, plus whatever else that cycle
wrote. The distortion model was not the only variable, so the comparison
establishes nothing about Division.

Two further reasons the same measurement was unsound: the image set at the
time was ~50% thumbnails (see the thumbnail entry below), and nothing
verified sidecar currency before either run.

Owner position, 2026-08-14: **Division is universal**; Brown3 is somewhat
better for rectilinear, but Division is what the shipped
`AlignmentParams.xml` uses and what the pipeline should run. Follow the
code's logic. A clean A/B - fresh batch, no inherited sidecars, no
thumbnails - has not been done; until it is, there is NO evidence here
either way.

What DOES survive from that work: H2082's registration ceiling is set by
its transect geometry, not by the distortion model (see the transect
entry), and the components that do form are metrically sound.

## [NA168] 2026-08-14 - Division is the wrong global distortion model for rectilinear rigs

`Metadata/AlignmentParams.xml` carries `sfmDistortionModel = Division`,
commented as a global fallback because "the real distortion model is
per-camera via XMP sidecars". But `batch_xmp_priors` DEFAULTS TO FALSE, so
on a normal run no sidecar states a model and every camera aligns as
FISHEYE. For NA168 both photogrammetry cameras are rectilinear (cinema and
the Sony are brown3), so the H2077/H2082 aligns ran fisheye-on-rectilinear.
Worked around per-run with `RS_ALIGN_PARAMS` pointing at a Brown3 variant
rather than editing the canonical file, which the WCA fisheye line still
depends on. The real fix is for the global to follow the rig actually
present - open.

## [NA168] 2026-08-14 - the survey imagery is H2077's, not H2082's

NA168's only photogrammetry-grade stills are
`raw/still_cam/survey_stills`: 340 cinemacam DNG at a **2 s median gap
(p90 also 2 s)**, spanning 2024-11-11 22:16 - 11-12 05:34. That interval
sits inside **H2077** (launch 11-11T19:17, recovery 11-12T10:54), not
H2082. The folder is flat and undived, which is why it reads as generic.

H2082's own stills are documentation, not survey: `still_cam/H2082` is
103 frames at a 35 s median and **616 s p90** gap, and `still_cam_sony/
H2082` is 306 frames across a 21 h dive. A first alignment attempt on
H2082 (93 dualHD highlights + 306 Sony, CLAHE 2.0/8x8, loose 10/1/15
priors) registered **0 cameras and produced 0 components** - consecutive
frames are ~29 m apart at p90 over a 1254 x 2511 m box, so they share no
visual field. That is a property of the imagery, not a pipeline fault.

`processed/capture_highlights` (94 frames for H2082) is a curated subset
of `processed/capture_pngs` (3,616 in-window frames, burst cadence);
neither is usable here anyway - the dualHD grab is Unreal-only material
by owner direction (2026-08-14), and its cam1/cam2 channels share one
1920x1080 footprint, so they could not be separated by sensor size.

Naming that matters: `still_cam` IS the cinemacam - its
`C007C6418_<UTC14>.DNG` names already match the `^c\d+c` family pattern
and resolve to calibration group 3 with no registry change. The Sony is a
separate body, ILCE-7M3 with an `E 20mm F2.8 F050`; focal 20.0 mm is read
from the EXIF sub-IFD rather than assumed.

## [NA168] 2026-08-14 - capture_pngs carries a thumbnails/ subdir under the SAME filenames

`processed/capture_pngs/<date>/` has a `thumbnails/` subdirectory holding a
**350x197 copy of every frame under an identical filename**. Any recursive
glob (`**/*.png`) therefore returns TWO files per timestamp, and half the
staged set is 30x too small to match features against full-size imagery.

Measured on H2082: 3,506 staged "frames" were **1,991 thumbnails + 1,753
real**, and the zeuss camera registered at **4.4%** as a direct result.
Nothing downstream notices - they are valid PNGs, with valid parseable
timestamps, that resolve to the correct camera family. The only tell is
image dimensions.

Same trap applies to `dive_reports/<DIVE>/images/thumbnails` and
`samples/<id>/vidcaps/thumbnails`. ALWAYS exclude a `thumbnails` path
component when staging, and assert a single image dimension per camera
afterwards - a dimension census is the cheap check that catches this.

CAUTION: this invalidates any registration-rate comparison made against
H2082 before 2026-08-14, including the "dropping the low-res camera hurt"
entry below, which was measured on the contaminated set.

## [NA168] 2026-08-14 - frames must be gated to ON BOTTOM, not launch-recovery

Video-derived frames outside `[On Bottom Time, Off Bottom Time]` are
descent and ascent - open water, no seafloor, nothing to match, and they
pull the zone clustering toward a track that has no imagery worth aligning.

Use the dive summary's On/Off Bottom columns, the SAME window and source
`ROVDataConcat/processors/process_dat.filter_vfr_data` uses to gate DVL
positions, so imagery and nav agree on what counts as the dive. For H2082
that is 20:00:32 -> 16:33:34 against a 19:04:56 -> 17:24:44
launch-recovery: ~56 min of descent and ~51 min of ascent trimmed.

Gate at the VIDEO level first, not just the frame level: 6 of H2082's 90
ProRes files fall entirely outside the window, and skipping them avoids
~220 GB of copying and ~40 min of extraction before a single frame is
written.

## [NA168] 2026-08-14 - the RealityScan cache reached 1.2 TB and nearly stopped the box

`%LOCALAPPDATA%\Temp\RealityScan` grew to **1,227 GB across 133,804 files,
flat in one directory** - no per-session subfolders, so age is the only way
to tell live cache from dead. Free space had fallen to 182 GB with a 39 GB
ProRes staging pipeline and an alignment both writing.

Deleting entries older than 24 h freed **562 GB with 0 files in use**, so
the running align was untouched. The project must be SAVED before clearing
cache younger than that. Bucket by `LastWriteTime` before deleting anything
- a wholesale clear during a live align destroys it.

## [NA168] 2026-08-14 - dropping the low-res camera HURT registration (negative result)

Intuition said the 1920x1080 dualHD H.264 grabs were polluting a solve
built on 5760x3240 stills. Measured, they were not - they were bridging.

H2082, same imagery, same settings, only the camera set differs:

| run | cinema registered | of | rate |
|---|---|---|---|
| cinema + zeuss + sony (6,656 imgs) | 1,759 | 2,844 | **61.8%** |
| cinema ONLY (2,844 imgs)           | 1,613 | 2,844 | **56.7%** |

The zeuss frames themselves registered at only 4.4% (154/3,506) and sony
at 3.9% (12/306) - so by their own numbers they look like dead weight -
yet REMOVING them cost the cinema camera 5 points. They supply
intermediate views between the high-res bursts. Do not prune a camera on
its own registration rate alone.

## [NA168] 2026-08-14 - H2082 is a TRANSECT; it cannot yield one model

H2082's survey is 3 s bursts strung along a line, not an area block. The
component structure says so directly: 15 components over roughly
100 x 350 m, each only 5-35 m wide, and merge_zones partitions those 15
into **13 spatial clusters** - i.e. almost nothing overlaps anything.
merge_zones' own words on the one cluster with neighbours: "shared-image
graph does not span the subset - align-only rungs; a merge rung could
only rigid-glue here".

The metric-scale oracle agrees: **10 of 13 components FAIL** the
0.90-1.10 gate (observed 0.79-1.17, and one component at 0.000). Weak
geometry, not a settings problem.

Consequence: H2082 yields a SET of disjoint patches, largest 409 cameras.
Reprocessing will not change that; only a different survey pattern would.
Compare H2077, an actual area survey: 92.4% into ONE 284-camera
component.

BUT the fragmentation is NOT the same as bad geometry, and the scale
oracle separates the two cleanly. The three largest components PASS:
zone_2_c0 409 cams at **scale 0.991, IQR width 0.040** (excellent),
c2 163 cams at 1.033, c3 144 cams at 0.965 - 716 cameras of metrically
sound reconstruction. The 10 failures are the small scattered fragments
(0.485-1.166, one degenerate at 0.000), which is exactly the expected
shape. So H2082's deliverable is three sound patches, not one site model
and not a write-off. Do not read "13 clusters" as "the dive is unusable".

## [NA168] 2026-08-14 - there is NO CLI command for a per-camera distortion model

Searched the complete `set*` command list in Epic's own CLI reference. The
only per-selection calibration commands are:

    setPriorCalibrationGroup    setPriorLensGroup
    setConstantCalibrationGroups    setCalibrationGroupByExif

All four set GROUPING. `sfmDistortionModel` (Division | Brown3 | Brown4 |
Brown3WithTangential2 | Brown4WithTangential2 | KplusBrown3WithTangential2
| KplusBrown4WithTangential2) is a GLOBAL `sfm*` alignment key - one value
for the whole scene.

Consequence, and it NARROWS the supersession entry below: the CLI replaces
sidecars for SEPARATING cameras, but **not** for stating a per-camera
distortion model. On a MIXED rig - NA168 H2080 has fisheye upper
(division) firing alongside rectilinear cinema and zeuss (brown3) - one
global model is wrong for one of them, and the XMP `Camera:DistortionModel`
entry remains the only mechanism that can say otherwise.

Options for a mixed rig, none free: keep sidecars for the model only;
align fisheye and rectilinear as separate zones and merge; or accept one
global model and let the mismatched cameras self-calibrate within their
own lens group. Unresolved - do not assume the sidecar-free path covers
this case.

## [NA168] 2026-08-14 - the 45 deg down-look was on the WRONG camera

Owner, 2026-08-14: "upper is 45 degrees down, cinema and mid are pointed
directly forward ... it's how they were loaded on this cruise and NA165."

The registry had `wca_cinema` at **pitch 45** and `wca_starboard` (the
upper) at **mount=None, never measured** - the tilt recorded against the
camera that does not have it, and absent from the one that does.
`camera_registry`'s own docstring repeated the error ("the same Cinema
unit sits ... 45 deg under WCA names").

Fixed: `wca_cinema` -> pitch 0, new `wca_upper` family (`^u\d+c`, the
`U###C` WCA still prefix) -> starboard camera at pitch 45. `wca_port`
(mid) already read 0 and was right. Lever arms untouched - those are the
VALIDATED figures and were not in question.

BLAST RADIUS: the NA156 H2023/H2024 WCA line was solved with cinema at 45.
The owner vouched for NA168 and NA165 only. If that line is reprocessed,
give it a cruise-scoped family rather than moving the row back.

## [NA168] 2026-08-14 - flight log must be imported AFTER the sfm settings

Owner sequence: load images -> select by camera pattern -> set
priors/params -> load flight log for geo data. AlignZone.bat had
`-importFlightLog` BEFORE the AlignmentParams `-set` loop, so the
georeferencing priors were taken in while `sfmEnableCameraPrior`,
`sfmCameraPriorWeight` and `sfmCameraPriorAccuracy*` still held whatever
the instance last had - the very keys governing how those priors are
weighted. Reordered.

## [NA168] 2026-08-14 - XMP sidecars are NOT the only way to group cameras

**SUPERSEDES** the line below reading "XMP calibration sidecars are the
ONLY way to separate EXIF-identical cameras". RealityScan 2.2 ships
`-setPriorCalibrationGroup <n>` and `-setPriorLensGroup <n>`, which set
exactly the two groups the sidecar carried, against whatever
`-selectImage <regexp>` has selected - and the registry already stores a
per-family filename regex. Also present: `-setConstantCalibrationGroups`,
`-removeCalibrationGroups`, `-setCalibrationGroupByExif`. Discovered by
reading Epic's own "List of All CLI Commands" page while scoping the
sidecar removal; the claim had never been re-checked against 2.2 docs.
Implemented in `modules/prior_groups.py`. NOT yet verified against a live
instance - the H2082 production run below still used the legacy path.

## [NA168] 2026-08-14 - component identity without the destructive harvest

`-exportLatestComponents <dir>` writes every component >= the
`setMinComponentSize` gate as its own `.rsalign`, so the component SET is
knowable without deleting anything; `-selectComponent` +
`-exportRegistration` then reads each component's membership directly
instead of inferring it by successive difference of XMP stem harvests.
This removes the mechanism that stripped 796 of 4,540 zone_1 images
(17.5%) of their calibration priors. Implemented in `AlignZone.bat`
behind the default path, old harvest kept at `RS_LEGACY_XMP_IDENTITY=1`.
CAVEAT: `build_component_manifests` still reads `identity_r<K>`, so the
legacy flag remains REQUIRED for a full run until that is ported. Also
open: `-exportRegistration`'s params XML is not hand-authorable - it must
be exported once from RealityScan's own "Export Registration" dialog.

## [NA168] 2026-08-14 - H2082 Sony stillcam clock runs on Palau local time

The Sony ILCE-7M3 stills in `raw/still_cam_sony/H2082` carry EXIF
`DateTime` on **UTC+9**, not UTC. Correcting by **-9 h** is what makes
them georeferenceable at all; geoall reads time from the FILENAME, so the
staging step bakes the corrected stamp in. Established three ways, because
the dive-window test alone could not discriminate (offsets -6 h through
-10 h all put 306/306 frames inside launch-recovery):
1. cross-correlation against the UTC-named dualHD frames peaks at -9 h
   (100 Sony frames within +/-120 s of a dualHD frame; next best 87);
2. -9 h aligns the two cameras' FIRST frames to 41 s - every other offset
   is out by an hour or more;
3. NA168 sits at ~130.8 E, and Palau is UTC+9.
Discovered when 260/306 frames fell inside the dive window and 46 did
not - a partial fit, which is the signature of a clock offset rather than
a data problem. A naive as-is import would have silently georeferenced
those 46 frames against the wrong nav.

## [NA168] 2026-08-14 - H2082 is UTM zone 52N, not 53N

H2082 works at 4.68 N, 130.77 E - **zone 52N, EPSG:32652** - and the whole
79,457-row track stays in one zone (no crossings). Worth recording because
the neighbouring H2077 site is at 7.56 N, 132.80 E, which IS zone 53N:
taking "the NA168 zone" from another dive's summary puts the whole model
~350 km east. geoall derives the zone from the nav itself and tags the
flight-log filename, which is the only thing downstream reads.

## [ON2026] 2026-08-08 - calibration-sidecar hygiene collision (test cell)

Per-eye APPROXIMATE calibration sidecars (manufacturer resized-corrected
values; groups L=0/R=1) on a zone_1 copy collapsed registration to 44.8%
(1,623/3,626) with meter-scale prior residuals - but NOT because
calibration priors are wrong: camera_registry's sidecar hygiene
(sanitize/harvest + ensure_calibration_sidecars) assumes it owns every
image-adjacent .xmp, swept the hand-placed calibration files into the
identity harvest, and could not regenerate them (VOYIS is not a registry
family): '1623 image(s) of unknown camera type left without a
calibration sidecar'. While engaged, the priors steered solved focals to
within 0.005-0.013 of the manufacturer 24.2345 (closer than
self-calibration). Discovered by the owner-directed parallel test cell;
verdict + numbers in M:\ON2026_run2\_agent\calib_verdict.json.
FOLLOW-UP: register the VOYIS family (calibration content from
modules/cameras.json on2026_voyis) so hygiene regenerates rather than
destroys, then re-test on a quiet instance. Production run2 stays
sidecar-free (95-99% registration, consistent).

## RealityScan 2.2 CLI behavior

- **addFolder does NOT recurse by default in this build** — zone_1/zone_2
  aligns added "0 layer images" and every flight-log row then failed
  err:18002. Discovered: live H2023 run failed in 25 s; RealityScan.log
  snapshot showed `Added 0 layer images`. Fix: `appIncSubdirs=true`
  before every addFolder. [H2023] (2026-07-23)
  - Nuance: an earlier NA167 zone_13 run DID import camera subfolders
    into one scene via -addFolder [NA167 #5] — that run had
    appIncSubdirs set by the fixed workflow; the flag, not the build,
    is the variable.
- **-align on instance defaults is a real hazard** — AlignImagesFromFolder
  never applied AlignmentParams.xml; only AlignZonesSequentially did.
  Discovered: code reading during settings evaluation. Fix: every
  workflow applies the sfm*/lis* keys; policy "never align on instance
  defaults". [H2023] (2026-07-23)
- **cmd splits unquoted `;` `,` `=` into separate .bat arguments**, and
  Python subprocess only quotes on whitespace — `key=value` settings
  arrived split, RealityScan.log showed `Parsing setting key=value ...
  failed [err:7155]`, meaning **no flag cell had applied its flags** and
  the parse errors aborted workflows via the errors marker. Lists now
  cross as files, settings as `key:value`. [NA167 #15] (2026-07-23)
- **-align takes no parameters in 2.x** — `-align "%AlignmentParams%"`
  is not supported (allcommands.htm + online docs); settings must be
  applied via delegated `-set` commands before a plain `-align`.
  [H2023, first-machine validation] (2026-07-21)
- **-selectAllComponents does not exist in RealityScan 2.2** — fails
  0x82000060; only selectComponent / selectMaximalComponent (+
  selectComponentWithLeastReprojectionError) exist. The dead command
  had lived unnoticed in AlignZonesSequentially.bat. [NA167 #13]
  (2026-07-23)
- **exportLatestComponents exports ALL components of the last alignment**
  (gated by setMinComponentSize) — the old maximal-only export was
  unnecessary loss. Discovered: allcommands.htm sweep. [H2023] (2026-07-23)
- **-setMinComponentSize is deprecated in 2.2** ("will be removed in the
  next release") but still required — without it components under the
  default threshold 5 are silently excluded from selection/export.
  Discovered: warning line in a per-cell RealityScan.log snapshot.
  [NA167 #22] (2026-07-24)
- **-setFeatureSource 0|1|2 and -selectImage ARE CLI** — the
  merge feature-source trio was wrongly believed GUI-only. Discovered:
  allcommands.htm "Commands for Selected Images" section. [H2023]
  (2026-07-23)
- **selectImage matches LITERAL FULL PATHS ONLY in this build** — bare
  regexp, dot-star-wrapped, glob, and regexp with explicit 'set'
  modifier ALL silently select nothing; a literal full path selects
  exactly its image. Selection composition = per-image literal
  selectImage union loop (~0.1–0.3 s per image — budget minutes for
  thousand-image sets). The Help's "imagePath|regexp" wording does not
  match observed 2.2 behavior — forum-mining follow-up open.
  Discovered: bisection probes U-SEL2 through U-SEL8. [H2023, U1/U19/U2]
  (2026-07-23)
- **-editInputSelection is the master per-image CLI control** (local
  Help tutorials/editselectioncommand.htm): on the current image
  selection it sets enable-alignment (inpEnabled), features source
  (aligFeaturesMode 0|1|2), enable meshing/texturing, texture weight,
  masking mode, per-image PRIOR POSE (inpPose 0–3, translation/rotation,
  accuracies, locked-pose groups) AND full calibration/lens priors
  (inpCalibrationGroup, inpCalibration Unknown/Approximate/Fixed,
  inpFocal, principal point, inpDistortionModel 0–5, coefficients).
  `"inpEnabled=false"` works as a single quoted key=value arg, and
  -align honors enable/disable exactly. [H2023] (2026-07-23)
- **XMP export naming: the COMMAND determines it, not the scene** —
  `-exportXMP` writes STEM-named sidecars; `-exportXMPForSelectedComponent`
  writes ORDINAL sidecars (00000.xmp, …) in every observed context.
  Four consistent datapoints; an earlier session-based hypothesis was
  WRONG and is SUPERSEDED. Consequence: per-component membership is
  derived by SUCCESSIVE DIFFERENCE of `-exportXMP` stem harvests as
  components are deleted (AlignZone.bat identity loop). [H2023, B10
  final form] (2026-07-23)
- **Flight-log import leaves the matched images ACTIVELY SELECTED**, and
  selection-driven exports under -silent then export nothing
  ("Export Selection" dialog auto-answered; XMP export completed in
  0.057 s vs 20.5 s). Fix: -deselectAllImages before exports. [H2023]
  (2026-07-23)
- **-importFlightLog reports a failed process (err:18002, 0x820000FF)
  when the log references images not in the scene** — the trajectory
  itself imports fine. Filter the flight log to images present when
  aligning subsets. [H2023, first-machine validation] (2026-07-21)
- **-importComponent of a relocated .rsalign hangs forever** (#timeout
  state, no error; observed 6 h). In-place imports: ~2 s per 0.7 GB.
  Import components from their original export paths — `.complist`
  workflow input exists for exactly this. [NA167 #11] (2026-07-23)
- **The errors marker carries only ErrorWriter's numeric result code**,
  never the err:NNNN text (that is only in %LOCALAPPDATA%\Temp\
  RealityScan.log, truncated each boot). Tolerant handlers must match
  codes (2181038335 = 0x820000FF warning-class; 0x80070057 E_INVALIDARG
  from emptied-scene select paths). [H2023] (2026-07-23)
- **0x8000FFFF is generic ("unexpected program state")** — broken -set
  args and the zone_14 align failure emitted the identical code; and
  RealityScan.log is truncated on every instance boot, so post-failure
  snapshots lose the race to the next boot. Log copies must happen
  inside the driver immediately after the failing call returns.
  [NA167 #16] (2026-07-23)
- **-getStatus says "gone" before the process releases marker-file
  handles** — the next workflow's marker clear raced the teardown;
  60 s per-file retry added. [NA167 #14] (2026-07-23)
- **Process result code 1 is benign in practice** — routine successful
  operations (e.g. -addFolder) report result 1 through the trigger;
  real failures report distinct codes. Whitelist of 0/1 kept. [H2023,
  first-machine validation] (2026-07-21)
- **RealityScan 2.2 emits periodic internal heartbeat processes through
  the same appProcessExecCmd trigger** — "the results log grew" does not
  mean "our command finished"; completion = delegate → grace → double
  -waitCompleted. [H2023, first-machine validation] (2026-07-21)
- **Check Integrity / Check Topology have no CLI commands** — their fix
  action maps to -cleanModel + -closeHoles. [H2023] (2026-07-23)
- **-removeSelectedTriangles removes the SELECTED set** (= Filter
  Selection tool); -selectLargeTrianglesRel threshold is multiples of
  average edge length, not pixels. [H2023] (2026-07-23)
- **-deleteSelectedComponent, -deleteComponent <idx>, and
  -deleteAllComponents all exist** in this build (allcommands.htm sweep).
  [H2023] (2026-07-23)
- **selectMaximalComponent / renameSelectedComponent /
  deleteSelectedComponent silently no-op on an empty scene** (no errors
  marker) — loop terminals must be file-existence checks, not error
  checks. [H2023] (2026-07-23)
- **quit-without-save leaves the .rsproj bundle byte-stable** across
  load/delete/export cycles (hash-verified twice); rename →
  exportSelectedComponentDir writes <newname>.rsalign. [H2023, U15/U16]
  (2026-07-23)
- **-exportRegistration without a params XML blocks forever headless** —
  avoid until a params file saved from the GUI dialog exists. [H2023]
  (2026-07-21)
- **#timeout progress lines defeat line-change stall detection** (every
  tick differs, so a hang counts as activity) — AND #timeout does NOT
  always mean hung: heavy align phases legitimately freeze the progress
  fraction 20+ min (40 #timeout lines in a successful 94.6% run). The
  pathological signature is #timeout from fraction 0.00 with ever-growing
  ETA. Policy: stall-warn on #timeout (2 h), never auto-kill an align on
  it. [NA167 #12, #28] (2026-07-23/24)

## Alignment behavior & settings

- **Settings for the WCA rig class** (full rationale:
  docs/settings-evaluation-2026-07.md §4): sfmEnableCameraPrior=true
  (IS the GUI "use camera priors for georeferencing"), prior weight
  10.0, sfmDistortionModel Brown3 global fallback with REAL models per
  camera via XMP (fisheye=division, rectilinear=brown3, post-merge
  upgrade path Brown4WithTangential2), sfmDetectorSensitivity Ultra,
  sfmImagesOverlap Low→Medium, sfmForceComponentRematch=false and
  sfmMergeGeoreferencedComponents=false for pass-1 zone aligns,
  appIncSubdirs=true always. [H2023] (2026-07-23)
- **SUPERSEDED (2026-08-14, see the [NA168] entry at the top): XMP
  calibration sidecars are the ONLY way to separate EXIF-identical
  cameras** — the PREMISE holds (WCA rendered JPGs are EXIF-identical
  across cameras: Z CAM E2-F6, no focal tag, one calibration/lens group
  per PHYSICAL camera), but "only way" does not: RealityScan 2.2's
  `-setPriorCalibrationGroup` / `-setPriorLensGroup` set the same groups
  in-session, with no file written beside the images.
  Old batcher values (camlower "12 mm fisheye"; actually rectilinear
  17 mm) were wrong and plausibly explain NA167's "priors hurt" A/B.
  [H2023] (2026-07-23)
- **XMP calibration priors were never loaded in any historical run** —
  written as `image.jpg.xmp`; RealityScan only reads `image.xmp`.
  Discovered by an arithmetic anomaly in sidecar counts after aligning
  zone_13. [NA167 #3] (2026-07-22)
- **The old prior CONTENT itself hurt registration (96.3% → 89.6% on
  Zeuss)** — A/B on zone_13 with priors absent vs promoted. Generation
  is opt-in until corrected per-camera values are re-validated per rig.
  [NA167 #4] (2026-07-22)
- **Extracted frames were timestamped one output interval early** (60 s
  at 1 fpm) — frame seek and timestamp source used different frame
  indices; confirmed with a synthetic per-frame-gray video. Any dataset
  extracted with the old __extract_video_cv2 carries the offset.
  [NA167 #1] (2026-07-22)
- **UTM zone must be derived per cruise, never hand-edited** —
  FlightLogParams.xml is auto-generated from the zone tag in the
  flight-log filename (NA173 was 57S while the template said 4N; NA167
  computed 53N and round-tripped). [NA167 #6 + H2023] (2026-07-22)
- **Alignment fragmentation is strongly nondeterministic; total
  registration is not** — zone_1 (4,540 images, identical settings,
  sidecars, inputs) aligned to 2 components/4,391 cameras in one run and
  9 components/4,392 in another. Component structure cannot be relied on
  across runs — only manifest-tracked image sets can — and within-zone
  growth/merge is MANDATORY machinery. [H2023] (2026-07-24)
- **Alignment runtime varies ~3× with scene character at equal image
  count** (zone_6 61.6/97.8 min vs zone_4 24.3/20.8 min, both ~1.5k
  frames, same GPU, both run twice) — budget by zone, not image count.
  [NA167 #20] (2026-07-23)
- **zone_14 fails standalone alignment deterministically (4/4) with
  fully clean data** — RealityScan internal error MSS_STR001 in the
  reconstruction phase (forensic log: testing/results/z14_forensic_rslog.txt);
  data exonerated by full-pixel decode, MD5, Laplacian, nav checks.
  Its images align FINE inside a larger scene (B grew through it at
  94.6%). Production rule: when a zone fails alignment solo, grow it
  from an aligned neighbor — don't retry solo. Reportable to Epic with
  the captured log. [NA167 #17, #18, #27] (2026-07-23/24)
- **Align output is never pose-stable** — a free re-align moved ALL 118
  cameras of a solved smoke scene and can drop 1–2 marginal ones.
  [H2023, U18 bonus] (2026-07-23)
- **Pose-locking is unusable as a growth anchor** — editInputSelection
  inpPose=3 takes effect but -align then refuses: "prior set to 'Exact'
  mode must be all aligned in a single run. Incremental adding is not
  supported." Checkpoint/rollback stays the primary never-shrink
  mechanism. [H2023, U18 FAIL] (2026-07-23)

## Merge & component growth

### Mechanism (reconciled 2026-07-24)

- **[RECON] Shared cameras are the ONLY merge mechanism verified to work
  headless.** NA167 D-cell isolation: zero-shared-camera pairs NEVER
  fuse — under -mergeComponents or -align-as-merge, georef flag on or
  off, rematch on or off, duplicate-path or shared-path form — and the
  non-merge is always SILENT (workflow exits success; the "merged"
  export is just the biggest input). With shared cameras,
  -mergeComponents FUSES: D6 split-zone fixture (two zone_6 halves
  sharing 390 images, aligned solo to 749 + 342 cams) merged in 56 min
  of real reconstruction ending "Finalizing 1 component". Verify EVERY
  merge by pose-XMP camera census, never exit status. [NA167 #23–26,
  #30, #31] (2026-07-24)
- **[RECON] Camera identity is (at minimum) path identity** — zones
  built as per-zone COPIES of overlap images (different paths) provide
  no shared-camera identity for merging; zones must reference a common
  image pool (imagelists or same on-disk paths). This makes the
  batcher's duplicate-copy output a production defect for the merge
  stage (change queued). [NA167, MERGE_STRATEGY_REPORT] (2026-07-24)
- **[RECON] OPEN CONTRADICTION (test cell D7, testing/MERGE_TEST_PLAN.md):
  the H2023/NA156 line observed apparent fusion WITHOUT path identity,
  twice** — smoke: mini_a (118) + mini_b (62), 40 overlap images
  duplicated at different paths, merge_zones.py produced one 180-camera
  component in 66 s; production H2023: 5 duplicate-path components
  fused to a 3,860-camera maximal in 31 min. NA167 D1/D2 say the georef
  flag never does this. Candidate discriminator: merge_zones.py imports
  the union flight log + CRS into the merge scene and runs `-update` —
  the D-cells never gave the merge scene its own constraints. Suspicion:
  180 = 118 + 62 exactly (no dedup of the 40 duplicated images), which
  is consistent with rigid side-by-side PLACEMENT rather than identity
  fusion — seam quality unverified. Until D7 runs, treat georef-based
  merging as UNPROVEN and duplicate-path "fusions" as suspect placements.
  (2026-07-24)
- **[RECON] "Merge Components is rigid best-fit" needs qualification.**
  The Epic staff claim (2021, pre-rename, outside the 4-year trust
  window) says no re-optimization / no repositioning / no new images.
  Empirically: with shared cameras -mergeComponents runs ~56 min of
  visible "merge reconstruction" and can finalize different component
  counts [NA167 #30–31]; and H2023 zone_1's final census read +37
  cameras vs the manifest baseline after a rigid-merge stage was the
  only accepted mutation (attribution unresolved — merge effect vs
  census-mapping nuance). What stands: merge cannot shrink and cannot
  register orphans. What is UNVERIFIED: "no re-optimization" in the
  current build. (2026-07-24)
- **featureSource is consumed by ALIGN, not Merge Components**: 0 =
  merge using overlaps (images COMMON to components — NOTE per the
  identity finding this means shared-PATH images, not duplicate
  copies), 1 = component features (existing tie points only), 2 = all
  image features (slow, small counts). Discovered: components.htm
  "Features source" prose. [H2023, caveat added at RECON] (2026-07-23)
- **Align is the actual merge/growth engine**: re-runs use "special
  algorithms designed for merging components", are cheap (cached
  features), "try a different strategy" on repetition; after
  georeferencing, align hunts additional cross-component tie points.
  Discovered: mergecomponents*.htm tutorials + staff answer. — BUT
  align-as-merge ALSO requires shared cameras across components
  [NA167 D3]. [H2023 + RECON caveat] (2026-07-23/24)
- **Align can SHRINK components** (re-optimization drops marginal
  cameras) — "grow, never shrink" must be enforced by checkpoint/
  rollback, not assumed. Observed: H2023 3,860 → 3,855; zone_1 c7 pass
  lost 51 previously-registered images. [H2023] (2026-07-23/24)
- **A merged component is NOT georeferenced unless the merge scene holds
  constraints** — imported components' own georeferencing does not carry
  into the new component. Fix: union flight log + CRS params into the
  merge scene, then `-update`. Discovered: owner GUI inspection
  ("showstopper") + allcommands.htm + live re-run. [H2023] (2026-07-23)
- **Component reimport does NOT carry non-member images** — orphans are
  absent from a components-only project and carry no trajectory until
  the flight log is imported. Checkpoint/rollback must use .rsproj file
  copies, not component reimport. [H2023] (2026-07-23)
- **Official fix-and-reimport round trip**: export faulty part →
  fix in spare scene → reimport → align "applies fixes". Components
  tolerate duplicate images by design. [H2023, components.htm] (2026-07-23)

### Strategy results (NA167 zones 6/14/4 matrix + H2023 production)

- **Sequential growth (B) and joint align (C) give identical quality;
  they differ 2.6× in time and 2.7× in memory, opposite winners** —
  B: one component, 3,906/4,131 (94.6%), 444 min, ≤60 GB. C: one
  component, 3,904 (94.5%), 169 min, ~165 GB peak. Joint alignment
  extrapolates to ~700 GB for a 19k-image dive — chunking is mandatory
  at production scale. [NA167 #19] (2026-07-24)
- **Incremental growth is state-sensitive and can DEGRADE existing
  structure** — z6→z14 two-zone grow fragmented to an 870-camera
  maximal (< z6's solo 1,533) while the three-zone B grow through the
  same stages held 3,906. Growth outcomes are not order/subset-
  invariant — verify camera counts after every grow step. [NA167 #29]
  (2026-07-24)
- **Empirical H2023 registration**: zone_1 96.7% (4,391/4,540) first
  run, 4,392 re-run; zone_2 94.3–95.1% (920–928/976); cross-zone merge
  produced a 3,860-camera maximal (83.9% of unique) in 31 min (see
  OPEN CONTRADICTION for mechanism). Registration ceiling is
  unregistrable imagery, not merge mechanics. [H2023] (2026-07-23)
- **Twin components across zones**: the 20% batcher overlap duplicates
  images into both zones; the same strip solved independently can
  fragment into near-identical twins whose residual quality differs
  with solve context. Post--update residuals expose the weak twin. A
  twin with no unique images is discardable by the "never discard
  unique images" rule. Detection/automation: modules/component_analysis.py
  (containment scan, keeper choice, border gating, orphan tracking,
  merge planning; 31-test pytest suite passing). Coverage is checked
  against the UNION of still-kept group members, worst-first. [H2023]
  (2026-07-23)
- **Georef-only rigid fusion** (sfmMergeGeoreferencedComponents +
  merge/-update) was DESIGNED as the last resort placing components
  purely by nav (~1–2 m real accuracy, bakes nav error into seams) —
  but see the OPEN CONTRADICTION: it has never been PROVEN to act
  headless at all. [H2023 design + NA167 negative results] (2026-07-23/24)
- **Growth passes are align-UPDATES that refresh EVERY component** — a
  census after an "isolated" component pass covers the whole zone;
  per-component before/after accounting produced phantom gains. The
  zone-level baseline census drives the invariant, gain, and orphan
  derivation. [H2023] (2026-07-24)
- **Zone_2 growth ground truth**: 928/976 (95.1%), ZERO real gains —
  the 48 orphans are genuinely unregistrable; honest convergence after
  one sweep. Three components remain by design (northern strip has no
  visual ties). [H2023] (2026-07-24)
- **Zone_1 growth ground truth: EVERY re-solve pass shrinks a
  weakly-connected fragment set** — global re-align + all 8 component
  passes rejected and rolled back (c7's pass lost 51 images); final
  4,429/4,540 (97.6%), 148 orphans. The +37 delta vs the 4,392 manifest
  baseline is an OPEN question (rigid merge was the only accepted
  mutation). Implication: for fragmentation like zone_1's, visual
  growth is exhausted immediately; the cross-zone stage is the
  productive path. [H2023] (2026-07-24)
- **Checkpoint/rollback validated in anger** — a growth run killed
  mid-pass was fully recovered by copying the "initial" .rsproj bundle
  checkpoint back over the scene. [H2023] (2026-07-24)
- **In-session successive-difference identity capture VALIDATED end to
  end** (smoke mini_a): align → saves → destructive harvest loop →
  quit-no-save produced .rsalign + manifest (118 members by real
  basename, UTM bbox), census from manifests == original registration,
  zero pose sidecars left beside images. [H2023] (2026-07-23)
- **H2023's feature geography is IN the manifests, and it makes the
  maximal-fraction merge target mathematically unreachable.** Running
  `component_analysis.merge_plan` over the 12 zone manifests
  (`aligned_components`, pure analysis, no RealityScan) resolves three
  spatially disjoint UTM clusters:
  - hull — zone_1 c0/c1/c3/c4/c5/c6/c7/c8 + zone_2 c1, bbox band
    E 594693–594719 / N 2345096–2345160, **3,720 unique images**;
  - bow — zone_2 c0 (686) and its twin zone_1 c2 (672), identical bbox
    E 594653–594668 / N 2345217–2345251, ~60 m NW, **686 images**;
  - west pocket — zone_2 c2, E 594599–594607 / N 2345248–2345256,
    another ~50 m west, **102 images**.
  Hull ∩ bow = **0 shared basenames**, so no merge mechanism (shared
  cameras or content rematch) can ever fuse them. Ceiling on the
  maximal component is therefore 3,720/4,600 = **80.9%**, below both
  `--target` values ever used (0.85 in the `merged` run, 0.83 in
  rs_settings). merge_zones.py must run the full three-attempt ladder
  (~1.7 h) and exit 1 on a CORRECT result. Discovered: manifest
  analysis during 2026-07-24 onboarding; confirms the owner's bow/hull
  statement from the data independently, and quantifies HANDOFF's
  size-based-hazard #2. [H2023] (2026-07-24)
- **The `merged/` run is superseded, not a baseline** — its
  `components_in` are five ordinal `Component N.rsalign` exports with
  an EMPTY twin_plan (it predates manifests). Its three attempts read
  3,860 / 3,855 / 3,855 cameras (83.9%, 83.8%, 83.8%) and it exited
  "no attempt reached the 85% target". Read with the clusters above,
  3,860 is a hull-cluster maximal component, not a shortfall. Do not
  cite it as evidence about merge mechanism. [H2023] (2026-07-24)
- **`-mergeComponents` as a rigid consolidation pass really does
  consolidate: zone_1 went 9 components → 4** (growth pass `merge`,
  38 min, accepted). Discovered: `growth/zone_1/final_components`
  holds four ordinal `Component N (1).rsalign` files against the nine
  manifested pre-growth exports, same 4,392-image union. Supports
  HANDOFF queue item 7 (a zero-camera-gain pass that reduces component
  count still serves the merge stage). [H2023] (2026-07-24)
- **The zone_1 growth +37 census delta most likely = cameras below the
  50-camera export floor, absorbed by the rigid merge** (HYPOTHESIS,
  not yet proven). Both the identity harvest and every census export
  run under `setMinComponentSize 50`, so members of sub-50 components
  are invisible to the census; the only accepted mutation before the
  +37 appeared was the 9→4 consolidation. Cannot be closed from the
  report alone — `try_build_manifests` produced ZERO manifests for the
  post-growth exports (B10 ordinal rule: identity is unharvestable
  outside the original aligning scene), so post-growth membership does
  not exist to diff. Test: re-census the zone_1 scene at
  `setMinComponentSize 1`. [H2023] (2026-07-24)
- **The GrowZone disabled-images bug did NOT reach the zone_1
  authoritative artifact — because every component pass was rolled
  back.** GrowZone.bat component mode disables all images, enables a
  subset, aligns, and falls through to `:save_quit` with no
  re-enable, so each of the eight passes saved a crippled scene; the
  driver then restored the checkpoint each time. Timestamp evidence:
  `zone_1.rsproj` mtime 03:31:57 == the `merge` pass's save; all
  component passes ran 03:31→03:54 and were rolled back; the surviving
  checkpoints are `initial` and `grow_s1_zone_1_c7` (taken before the
  last pass, i.e. the post-merge all-enabled state). The code bug
  stands (HANDOFF queue item 5) — a single ACCEPTED component pass
  would persist it. Confirm in the GUI before trusting the scene.
  [H2023] (2026-07-24)

- **D7 RESOLVED: RealityScan 2.2 fuses components via image CONTENT;
  path identity is NOT required; georef constraints are NOT what
  enabled the NA156 duplicate-path merges.** Probe (testing/probe_d7.py,
  smoke fixture, 2026-07-24): zone_c (78 cams, mini_a-only images) +
  zone_d_c0 (42 cams, mini_b-only images) share ZERO basenames and ZERO
  paths but view the same wreck strip. `-mergeComponents` fused them to
  one 120-camera component (78+42 exact) BOTH without any flight log in
  the merge scene (D7b) AND with union log + -update (D7a) — "Finalizing
  1 component" in both. `-align` + rematch on the 118+62 overlap pair
  fused to 180 without a log (Q9a); the original 66 s merge replicated
  at 180 (D7c). Reconciliation with NA167 D1–D3 (never fused): those
  pairs had zero CONTENT overlap (z6+z4 never see the same seafloor).
  Every fusion observation to date is explained by one rule: **content
  overlap => fusable (either mechanism); no content overlap => no fuse,
  silently, regardless of flags/log**. Consequences: (a) the union-log
  candidate discriminator is refuted — the log is still REQUIRED for
  georeferencing the merged result, but plays no role in fusion;
  (b) queue #9's ladder inversion is unnecessary — merge_first is
  mechanistically sound for duplicate-path zones (and ~25% faster than
  align mode in the probe); (c) bbox border gating is the correct
  candidate filter, since content overlap requires spatial adjacency;
  (d) the H2023 3,860 merge was real content fusion, not co-location —
  seam quality still owner-inspected at the gate. Hook-chain liveness
  self-test PASSED in the same probe (results_RS1.log grew after the
  CRLF normalization). [H2023] (2026-07-24)

- **A merge/align leaves the SOURCE components in the scene alongside
  the fused component.** Smoke E2E of the reworked merge driver
  (2026-07-24): after fusing 78+42, the peel loop read components
  [120, 78, 42] — the fusion PLUS both originals. The legacy
  maximal-only export naturally picked the fused one, which is why
  this went unnoticed. Consequences: (a) any all-components export of
  a merge scene contains residual source copies — consumers must
  attribute, not enumerate (merge_zones.attribute_result: largest-first
  subset matching, residual = count equal to an already-consumed
  input); (b) component COUNT in a merge scene is not "how many
  features" — never use it directly. Discovered: peel harvest counts +
  exact 120=78+42 arithmetic. [H2023] (2026-07-24)
- **Peel-loop terminal state: -selectMaximalComponent on an EMPTY scene
  silently no-ops and the following -renameSelectedComponent fails
  E_INVALIDARG 0x80070057 (2147942487) "in 0 seconds"** — there is no
  CLI query for "how many components remain", so the tolerated rename
  failure IS the loop's exhaustion signal (:run_peelrename, marker
  moved to expected_peelend_<inst>.txt as evidence). Same pattern as
  the tolerated 18002 flight-log import. [H2023] (2026-07-24)

- **Calibration XMP sidecars at align time cut zone_1 fragmentation
  from 9 components to 3** at equal-or-better registration (fresh run
  4,405/4,540 = 97.0% vs production 4,392 = 96.7%; same imagery, same
  box). Discovered: 2026-07-24 fresh end-to-end run — the production
  zones were batched BEFORE the calibration-sidecar work, the fresh
  zones with it. Confirms the camera-registry design decision; details
  docs/FRESH_RUN_2026-07-24.md. [H2023] (2026-07-24)
- **Component fusion can DROP a small number of cameras: hull c0+c1
  (3,026+714=3,740) fused to 3,738 (merge mode) and 3,739 (both
  align-mode rungs)** — a −2/−1/−1 pattern, so the loss is real but
  not a fixed set. Exact-additivity attribution therefore cannot
  assume fusions conserve cameras; the driver's acceptance
  (never-shrink + exact membership) auto-rejected and carried the
  intact inputs forward. Bounded-loss acceptance is an OWNER decision,
  not a driver default. CORRECTED 2026-07-25: an earlier entry said
  "3,738 on all three rungs" — the peel counts are [3738]/[3739]/[3739].
  Follow-up (2026-07-25 ICP over peel poses): merge-mode's confirmed
  drop is C231C1034 (no fused pose within 2 m); the second is masked by
  a ~0.55 m MEDIAN non-rigid deformation of the merged solution vs
  zone_1's own solve — itself a notable fact for seam/residual
  expectations. [H2023] (2026-07-25)
- **Fresh-run end-to-end result (2026-07-24): 4,507/4,598 unique
  images (98.0%) across four feature components** (hull 3,026 + hull
  strip 714 + bow 665 + west pocket 102), assembled georeferenced in
  one project; zone_2 (852 imgs, 11.9% reg) is transit imagery whose
  only aligned part twins the west pocket (twin-dropped, zero loss).
  The feature-aware pipeline (cluster partition → ladder → convergence
  → assembly → evaluation gate) ran end to end unattended. [H2023]
  (2026-07-24)

- **[RECON 2026-07-25] GOVERNING REFRAME (owner-driven): the week's
  pathologies share one upstream cause — the rig's metrology never
  reached the solver.** Until 2026-07-25, every alignment ran with
  position-only priors at 10x-inflated claimed accuracy (10/10/1 m vs
  the rig's real DVL 1 m XY / Paro 0.1 m Z), no orientation priors
  (custom 13-column flight-log format never installed), and the
  fisheye solved through brown3. Re-read under that lens:
  fragmentation (9->3 components from calibration groups alone — a
  partial priors fix — with the residual c0/c1 hull split likely the
  same disease), the merge's 0.55 m median solve-to-solve deformation
  (a DIRECT measurement of under-constraint), the -2/-1 fusion camera
  drops (loose seam cameras), zone_2's 11.9% and the 91 "genuinely
  unregistrable" orphans (concluded under broken priors — transit
  imagery is exactly where nav priors should carry registration), and
  the high residuals the owner observed. Consequence for priorities:
  priors v2 (testing/PRIORS_DISTORTION_TEST_PLAN.md) is the MAIN
  LINE; merge-repair machinery (ladder, attribution, bounded-loss)
  re-evaluates as insurance after re-alignment under real priors.
  Verification-culture lesson recorded: every automated oracle
  measured QUANTITY (census counts, component counts) and none
  measured QUALITY (residuals, prior-vs-solved deviation,
  solve-to-solve deformation) — solve quality was an unnamed
  blindness; the GUI was its only detector. Residual extraction and
  deformation-vs-zone-solve checks are to become standing oracles
  alongside the census. (2026-07-25)
- **[RECON 2026-07-25] SUPERSEDED-RISK flag on NA167 D1/D2** ("georef
  merging never manifested headless"): those cells fed the flag
  components georeferenced from position-only priors with 10 m claimed
  accuracy — the feature's documented premise ("each is georeferenced")
  was arguably never met. Do not treat D1/D2 as final until re-tested
  with priors-v2 components (queued as a PD follow-on cell). The
  content-fusion rule (D7 RESOLVED) stands regardless — it explains
  every observed fusion; what is in doubt is only whether the
  georef-flag path ALSO works when georeferencing is real. (2026-07-25)

- **SUPERSEDED (2026-07-25): "zone_2 is transit imagery whose images
  are genuinely unregistrable."** PD-2b re-aligned the same 852 images
  under Division + orientation priors @15° + real accuracies (1/1/0.1):
  **812/852 registered (95.3%) vs 101/852 (11.9%)** under the old
  config — an 8x improvement from configuration alone, no data change.
  Components [621, 102, 57, 32]; the 621-camera corridor spans the
  hull->bow->pocket connecting extent. Zone_2 is the physical BRIDGE
  between the features, not filler. Every "unregistrable" verdict
  rendered under the pre-2026-07-25 config (including the 91-orphan
  pool and production zone_2's "48 genuinely unregistrable") is
  untrusted until re-tested. Discovered: PD-2b cell, 10.5 min.
  [H2023] (2026-07-25)

- **CRITICAL — THE FRESH-RUN HULL COMPONENTS ARE AT ~1/5 TRUE SCALE;
  THE DELIVERED ASSEMBLY IS METRICALLY INCOHERENT** (2026-07-25).
  Per-component solved-vs-nav pairwise-distance ratio (rotation- and
  translation-invariant), fresh zone_1: **c0 (hull main, 3,026 cams)
  = 0.175** (IQR 0.168–0.186), **c1 (hull strip, 714) = 0.220**,
  c2 (bow, 665) = 1.011. Fresh zone_2 = 0.902, zone_3 = 0.965–0.991.
  So two components holding 82% of the delivered assembly's cameras
  are ~5.7x and ~4.5x SMALLER than reality, while the rest are sound.
  Three independent confirmations:
  1. **Constant across scale bands** — the ratio holds at 0.197 / 0.181
     / 0.185 / 0.179 / 0.174 / 0.174 across 1-2, 2-4, 4-8, 8-16, 16-32,
     32-64 m nav-distance bins. A pure SIMILARITY (uniform scale) error,
     NOT drift, fold, or accumulating error.
  2. **Implied ROV speed** — hull solve says 0.01 m/s (implausible for
     a vehicle surveying a 64 m hull); nav says 0.08 m/s (plausible
     slow inspection). On the bow, solve 0.22 m/s == nav 0.21 m/s.
     Nav is right; the hull solve is wrong.
  3. **The rig as an independent ruler** — the fixed C-P baseline
     measures 1.11-1.21 m in metrically sound components but 0.22 m in
     hull c0, i.e. 0.20x. Agrees with the nav-derived 0.175x without
     using nav at all.
  Consequences, all previously mis-attributed: (a) the owner's "high
  residuals" — position priors in metres cannot be satisfied by a
  5.7x-shrunken solve; (b) the c0+c1 fusion camera drops (-2/-1) — the
  merge was asked to rigidly fuse two bodies whose scales differ by
  26% (0.175 vs 0.220), which is geometrically impossible without a
  similarity transform; the never-shrink gate rejecting it was RIGHT
  for a deeper reason than we knew; (c) the 0.55 m merge deformation.
  A uniform scale error is INVISIBLE in the viewer, which is why
  "all components look good" was true and still is - locally.
  NOT chronic: the older production run's zone_1 components measure
  0.77-1.01. Something about the fresh run's zone_1 solve specifically
  lost scale. Root cause NOT yet established. [H2023] (2026-07-25)
- **RIG GEOMETRY VALIDATED — the georef module's mount angles AND lever
  arms are CORRECT.** Measured on two INDEPENDENT metrically-sound
  solves (bow c2 from the zone_1 align; zone_2 from PD-2b): C-vs-P
  optical-axis angle **47.2°/46.8°** vs the code's 45.0°, and **C above
  P by +1.12 m / +1.03 m** vs the code's implied +1.00 m (P at 1 m
  forward + 1 m down, C at 1 m forward). |P-C| separation 1.21/1.11 m.
  Both mounts at 1 m forward is confirmed (residual relative forward
  offset ~0.15 m, negligible). **RETRACTION:** an earlier entry in this
  session claimed the Port lever arm was wrong by ~1 m. That was
  measured inside hull c0 - the 0.175-scale component - so both its
  separation (0.22 m) and its "vertical" component were meaningless.
  Only the ANGLE from that measurement was valid (angles are invariant
  under scale and rotation). Owner's recollection of "~0.5 m" spacing
  is ~half the measured value; the code's 1.0 m stands, corroborated
  twice. [H2023] (2026-07-25)
- SUPERSEDED (2026-07-25, see the two entries above): **RIG GEOMETRY
  MEASURED FROM THE SOLVE (2,169 near-simultaneous C/P pairs, zone_1
  fresh run). Mount angles CONFIRMED; the PORT LEVER ARM IS WRONG BY
  ~1 m.**
  - C-vs-P optical-axis angle: **47.2°** (IQR 47.0–47.4) vs the code's
    45.0° — owner's "C = 45° down, P = straight-on" CONFIRMED (2.2°
    residual is mount tolerance / solve bias, not a structural error).
  - |P − C| separation: **0.22 m** (IQR 0.21–0.28) vs the 1.00 m the
    code implies. Vertical component: **0.00 m** (IQR −0.09..+0.04) vs
    the code's "P sits 1 m below C". P is ~0.17 m *ahead* of C.
  - Method (immune to the absolute-frame weakness that spoiled the
    earlier mount derivation): both quantities are RIG-INTERNAL —
    relative axis angle and relative position between two cameras on
    one rigid vehicle — so they are observable in any solve regardless
    of how weakly the scene's absolute attitude is constrained. The
    positions used are ECEF (metric) from a georeferenced solve, and
    the 10 m-loose position priors of that run mean the VISUAL solution
    dominated: 0.22 m is what the imagery says, against a 1 m prior.
  - **Why this now matters more than it used to:** with position
    accuracies tightened to 1 m XY / 0.1 m Z (2026-07-25), a 1 m
    lever-arm error in Z is a ~10-sigma conflict on EVERY Port frame,
    where the old 10/10/1 accuracies absorbed it silently. Prime
    suspect for elevated residuals, and a candidate cause of the PD-4
    zone_1 collapse (dense interleaved P/C frames accumulate the
    conflict; sparse zone_2/zone_3 showed no harm from tight positions
    alone — PD-0a neutral). Owner confirmation of true rig offsets
    requested before overwriting `_get_camera_offsets`. [H2023]
    (2026-07-25)
- **`LensDistortionPrior="Approximate"` with NO coefficients supplied
  does NOT pin distortion to zero** — cinema has carried exactly that
  since the camera registry was written and still solved k1 = −0.0524
  over 2,204 cameras. An earlier caution in this session ("Approximate
  would assert approximately-zero distortion, wrong for a fisheye")
  was WRONG; `Unknown` merely withheld a hint. Port/Starboard moved to
  `Approximate` per owner directive. Supplying measured coefficients
  remains a further refinement (must be measured under Division — the
  single-parameter division model is not the brown3 k1). [H2023]
  (2026-07-25)

- **DEFECT (fixed): AlignZone's identity harvest PERMANENTLY STRIPS
  calibration sidecars from the image tree.** The harvest PowerShell
  MOVES every pose-bearing .xmp into identity_r<K>; the last-peeled
  component's sidecars are never re-exported, so those images end up
  with no calibration prior at all. Measured on fresh zone_1: **796 of
  4,540 images (17.5%) had no sidecar** - the ENTIRE bow component
  (665/665), 123 of c0, and 8 unregistered. Consequence: any re-align
  of an already-harvested zone silently runs with a partially
  ungrouped camera set (the WCA JPGs are EXIF-identical, so the XMP
  group is the ONLY thing separating Port from Cinema). **PD-4 and
  PD-4a both re-aligned zone_1 in this state, so their "collapse"
  results (669 and 782 of 4,540) are CONFOUNDED and cannot be read as
  evidence against Division or tight priors.** Fixed:
  `camera_registry.ensure_calibration_sidecars()` regenerates any
  missing sidecar from the registry, and the alignment module now
  calls it after every zone align. Discovered while building the bow
  fixture - 665 images copied, 0 sidecars came with them. [H2023]
  (2026-07-25)
- **A metric-scale oracle now exists** (`testing/scale_oracle.py`):
  median solved-vs-nav pairwise-distance ratio per component,
  invariant to translation and rotation. Self-test reproduces the
  hand-derived figures exactly (fresh zone_1 c0 0.175 / c1 0.221 /
  c2 1.009), i.e. validated against a known-bad AND a known-good case
  before use. This closes the "quantity-only oracle" blindness named
  in the 2026-07-25 reframe: every future align cell reports SCALE,
  not just registration count. [H2023] (2026-07-25)

- **Over-tight position priors FRAGMENT solves and worsen scale** — bow
  2x2 (665-image known-good component, clean sidecars, scale oracle):
  loose 10/10/1 gave ONE component at scale 1.049 (Brown3) / 0.989
  (Division); tight 1/1/0.1 split it into 2 and 3 components and pushed
  the maximal component's scale to 0.886 / 0.826. Registration barely
  moved (656-665 in every cell) - which is precisely why a
  camera-counting oracle never caught it, and why the zone_1 "collapse"
  was misread as a Division or memory problem. LESSON: the flight-log
  accuracy columns want END-TO-END per-image position uncertainty
  (timestamp matching + nav interpolation + lever arm + dive drift),
  NOT the instantaneous sensor spec. The owner's DVL 1 m / Paro 0.1 m
  are sensor figures; using them as prior accuracy over-constrains the
  solve. Reverted to 10/10/1; intermediate ladder queued. [H2023]
  (2026-07-25)

- **RESOLVED: the hull scale error is fixed by the corrected alignment
  configuration.** PD-6 re-aligned fresh zone_1 with Division + explicit
  loose 10/10/1 position priors + calibration sidecars intact:
  **c0 = 3,738 cams at scale 0.981** (IQR 0.949-1.027) and c1 = 656 at
  1.076, total 4,394/4,540 in 67.7 min. Against the baseline's
  4,405/4,540 in THREE components at hull scale 0.175/0.221. So:
  registration unchanged within noise (-11, 0.24%), components 3 -> 2,
  and metric validity restored. Note the hull now solves as ONE
  3,738-camera component natively - exactly the object the merge stage
  was straining to build by fusing c0+c1 (3,026+714=3,740, dropping 2
  cameras in the attempt). The within-zone hull split was itself an
  artifact of the broken configuration, not real geography.
  ATTRIBUTION: two things changed vs baseline - (a) Brown3 -> Division,
  and (b) the accuracy columns are now actually imported (baseline ran
  before the 13-column format was installed, so RS fell back to global
  prior defaults). Division is the physically motivated candidate: the
  Port fisheye forced through a 3-parameter radial model biases the
  focal estimate, and in this geometry focal error maps directly to
  reconstruction scale. A Brown3 + explicit-loose isolation cell on
  zone_1 (~70 min) would settle it; not run, since the corrected config
  is adopted either way. **Owner's instinct that Division was right for
  the fisheye was correct, and its real payoff was metric validity, not
  registration count.** [H2023] (2026-07-25)

- **DEFECT (fixed): AlignZone.bat does not write component manifests —
  only the alignment MODULE does, so any driver invoking the .bat
  directly produces exports the feature-aware merge refuses.** PD-6's
  components carried an identity harvest (identity_r0/r1) and two
  .rsalign exports but ZERO `.rsalign.manifest.json`, because
  `relaunch_pd6.py` calls `RealityScanCLI.run_batch_script` and skips
  the module's post-align manifest step. `merge_zones.load_inputs`
  refuses unmanifested components by design (no membership → no
  border-gating, twin resolution, or attribution), so the corrected
  zone_1 could not have fed the assembly at all. Discovered by
  directory listing while planning the assembly re-run, not by any
  failure — the align reported success. Fixed by making
  `RealityScanAlignment.capture_component_identities` public (ONE
  implementation, per the no-second-way rule) and calling it from
  `relaunch_pd6.py`; manifests rebuilt for the existing PD-6 exports
  from the on-disk harvest (3,738 / 656 cameras, matching the census).
  LESSON: the .bat/module split means "success" from a direct .bat
  driver is a weaker claim than success from the module — research
  cells that must feed production stages have to replay the module's
  post-processing. [H2023] (2026-07-25)

- **The corrected zone_1 leaves NOTHING for the merge ladder to do.**
  Dry-run of `merge_zones.partition_clusters` over the PD-6 exports +
  zone_3: three spatially disjoint singleton clusters — hull 3,738
  (bbox Y 2345096–2345160), bow 656 (Y 2345217–2345251), west pocket
  102 (Y 2345248–2345256) — zero discards, zero fusable pairs. The
  fresh run spent ~75 min on a hull ladder whose entire purpose was to
  fuse c0+c1 into the object the corrected config now solves natively.
  Confirms the GOVERNING INTENT reading from the data: this dive's end
  state is three feature components, and merge work on it is
  self-inflicted. Scale oracle over all fresh zones for the record:
  zone_2 c0 0.998 (101 cams), zone_3 c0 0.990 (102), PD-6 zone_1 c0
  0.982 (3,738) / c1 1.075 (656) — only the old zone_1 hull was ever
  metrically broken. [H2023] (2026-07-25)

- **The corrected assembly is built: 3 components, 4,496/4,600 (97.7%).**
  `merged_pd6` ran in 1.5 min of solve time — three singleton clusters,
  zero merge attempts, straight to assembly; project
  `D:\na156_h2023_fresh\merged_pd6\assembly\H2023_PD6_Assembly.rsproj`
  (sfm0/1/2 = 2,489/295/44 MB, proportional to 3,738/656/102 cameras).
  The run's ONE error line — `result code 2181038335` = **0x820000FF**,
  the documented err:18002 warning class — was verified benign by
  matching all 102 "not found in the current scene" images against every
  component manifest: **zero overlap**, i.e. they are exactly the
  unregistered remainder (4,598 union-log rows − 4,496 cameras = 102).
  `Trajectory imported successfully` and `update` both followed.
  Confirms the standing rule: importing a union log that covers
  unregistered images always raises this warning, and the census, not
  the exit status, is what settles a merge. [H2023] (2026-07-25)

- **DEFECT (fixed): `merge_report.json`'s `census_after_update` was
  structurally incapable of measuring the assembly, and reported 0 for a
  sound 4,496-camera result.** Assemble mode exports no XMPs by design
  (it imports components and georeferences them), so the
  `sanitize_and_census(images_root)` call after it scans pose sidecars
  that assembly never wrote — it reads leftovers from whichever stage
  ran last, and reads zero once a prior stage has sanitized the tree.
  Discovered by disbelieving a 0 next to `workflow_success: true`.
  Replaced with `cameras_from_manifests` (the manifest sum, the same
  number EVALUATION READY reports), tagged as coming from the inputs.
  LESSON per provenance: a number keeps the tag it had when produced, and
  a census that cannot see its subject must not be published under a name
  that claims it did. [H2023] (2026-07-25)

- **BLINDNESS (open): the metric-scale oracle cannot see the
  DELIVERABLE.** `scale_oracle.py` needs pose XMPs, which only an
  identity harvest produces; assemble mode saves and quits without
  exporting any. So scale is measured on the assembly's INPUTS while
  `-update` — a similarity fit to the nav constraints, and therefore
  exactly the step that can set scale — runs afterwards unobserved.
  The 0.982/1.075/0.990 figures for `merged_pd6` are pre-assembly.
  EVALUATION_READY.txt now says so in the report itself rather than
  leaving the reader to assume. Closing it means porting the
  successive-difference harvest to a dated COPY of the assembly project
  (already queued as workflow-evaluation item 3), which yields
  per-component membership and a measurable deliverable in one step.
  [H2023] (2026-07-25)

## Resource envelope & monitoring

- **Near-OOM, RealityScan slows to a crawl WITHOUT crashing and WITHOUT
  spilling to NVMe** — indistinguishable in the progress feed from a
  hang, making memory pressure the THIRD cause of persistent #timeout.
  Mitigation: RealityScanCLI samples available RAM (GlobalMemoryStatusEx),
  warns below 4 GB free, includes the RAM figure in stall warnings.
  MEASUREMENT CAVEAT (owner-caught): workflows run MULTIPLE
  RealityScan.exe processes (persistent instance + transient helpers) —
  identify the instance by largest working set or tracked PID before
  quoting memory numbers (a "2.2 GB during a 4,540-image align" misread
  was a 30 MB transient; the instance was ~11 GB + 4 GB VRAM).
  Processing box: 93.6 GB RAM. [H2023] (2026-07-24)
- **Memory bounds observed**: per-zone aligns ≤ ~60 GB (NA167 ~1.5k
  images/zone); joint 4,131-image align ~165 GB peak on a 192 GB box.
  [NA167 #19] (2026-07-24)

## Rig & data

- **H2023 contains TWO discrete physical features — the bow and the
  main hull of the wreck, surveyed as separate chunks in one dive**
  (owner-stated 2026-07-24). Zones are batched on image DENSITY, not
  features, so zone boundaries are blind to feature boundaries; a
  discrete feature's component may simply be smaller than the main
  hull's and can NEVER fuse with it visually. Consequences (owner
  intent, governs all component handling): a multi-component terminal
  state is a CORRECT outcome; "as big as it can get" is judged
  PER FEATURE, not per scene; no deletion/export/success logic may be
  size-based — only containment-based (no unique images) deletion is
  ever legal; a maximal-fraction success target misreads disjoint
  features as merge failure. Expect this pattern in other dives.
  [H2023, owner] (2026-07-24)
- **Four physical cameras** (owner-confirmed): Zeuss rect 23 mm; Port
  (aka cammid) fisheye 14 mm; Cinema (aka camlower) rect 17 mm;
  Starboard (aka camupper) fisheye 14 mm. NA156 mounts: Port 0 deg,
  1 m fwd + 1 m down; Cinema 45 deg down, 1 m fwd. S231C*.mov videos on
  D:\H2023 ARE Starboard (excluded for photogrammetry). [H2023] (2026-07-23)
- **ROVDataConcat**: georeferencers require stage-2 kalman columns
  (final_datatable.csv); H2023 nav covers 2023-11-03T19:44 to
  2023-11-04T05:48; H2023 has no geotiff (kalman_offset fails, harmless
  for photogrammetry). Multiple nav CSVs per dive collide into one dict
  key — find_rov_datafiles prefers *final_datatable.csv [NA167 #9].
  [H2023 + NA167] (2026-07-23)
- **Full-file image verification is untenable at scale** — PIL
  .verify() ≈ 720 GB of reads over 18k stills; header-probe cut the
  stage to ~5 min. [NA167 #7] (2026-07-22)
- **CLAHE preprocessing: scope is EMPIRICALLY CONTESTED** — zone_9
  (NA173): baseline aligns to NOTHING, CLAHE 2.0/8×8 rescues it
  (validated default-on here). LilyJean stereo pairs (COLMAP pipeline,
  3,607 pairs): both adaptive enhancement and fixed backscatter
  subtraction REDUCED registration ~30% vs originals. Both results are
  real; scope unresolved; reconciliation matrix Q-05 queued (zone_9 ×
  COLMAP, LilyJean × RealityScan, judged on REGISTRATION). If CLAHE
  ends up texture-only, RealityScan Image Layers
  (.geometry/.texture/.mask) are the official reconciling mechanism.
  See docs/COLMAP_CROSSOVER.md. [H2023 + LilyJean fact base via
  HANDOFF] (2026-07-23)
  - UPDATE 2026-07-24: full COLMAP fact base received from owner
    (frozen copy docs/COLMAP_FINDINGS_UNIFIED.md). Its candidate
    explanations for the conflict (F-20260723-33): ENGINE (RealityScan
    applies internal tone mapping pre-detection), DETECTOR, or IMAGERY
    REGIME (zone_9 baseline catastrophically flat vs LilyJean baseline
    that aligns well). Also externally corroborated on the COLMAP side
    (Summers & Jones, arXiv:2507.21715: enhancement generally degrades
    feature matching; raw preferred). Their standing policy — geometry
    on originals, color-correct only at texturing — is the opposite of
    this pipeline's default; Q-05's four cells decide the
    documentation-guide policy for both.
- **Cross-engine Zeuss-camera anomaly** — COLMAP zone_9: 710 zeuss
  frames REGISTERED but with ZERO triangulated points (contribute
  nothing downstream; C-20260721-15/Q-07 in the COLMAP fact base) —
  independently echoing this line's NA167 zone_13 A/B where XMP priors
  cost 6.7 points of registration specifically on Zeuss [NA167 #4].
  Two engines, two failure shapes, one physical camera family: treat
  Zeuss calibration/imagery as suspect and prioritize per-camera
  validation when Zeuss zones underperform. [RECON, via COLMAP fact
  base] (2026-07-24)

## Windows & automation traps

- **`Set-Content -Encoding utf8` in Windows PowerShell 5.1 writes a BOM**, and a
  BOM on line 1 of a `.complist` silently invalidates the first entry: merge_zones
  read `\ufeffF:\...\zone_1_c6.rsalign`, found no manifest for it, and aborted with
  "complist entries without manifests". Python writes these files with
  `encoding='utf-8'` (no BOM), so only hand-authored/PowerShell-authored lists are
  affected. Use `[System.IO.File]::WriteAllLines($p,$lines,(New-Object
  System.Text.UTF8Encoding($false)))`. Verified by reading the first three bytes
  (239,187,191 = BOM). (2026-07-27)

- **cmd: exit /b N inside a MULTI-STATEMENT parenthesized block returns
  0 to the caller**; the single-line `( echo msg & exit /b 1 )` form
  propagates correctly. Never put exit /b inside multi-line parens; use
  single-line chains or goto. [H2023] (2026-07-23)
  - **REFINED 2026-07-24 by direct measurement** (four probe .bats,
    `cmd //c`, before/after on MergeZoneComponents.bat). The code is
    lost in exactly ONE configuration: `exit /b` sitting inside an
    outer multi-line parenthesized block (an `if (...)` body or a
    `for ... do (...)` body) in the body of the script that IS the
    process entry point. Measured:
    - top-level `( echo … & exit /b 1 )` → **1** (correct);
    - top-level multi-line `if … (` … `exit /b 1` `)` → **1** (correct
      — the original review finding over-reached here);
    - `exit /b 1` in an `if`-block nested inside `if defined … (` → **0**;
    - `exit /b 1` in an `if`-block nested inside a `for /f … do (` → **0**;
    - the same nested shapes inside a `call :label` SUBROUTINE → **1**;
    - the same nested shape in a `call`ed CHILD .bat → **1**.
    Consequences, both verified rather than assumed: (a) the shared
    `:run` abort contract is **LIVE** — a probe replicating `:run` with
    a non-empty errors marker aborts (exit 1) and with an empty one
    continues, so `call :run … || goto :fail` does detect RealityScan
    errors in every workflow; (b) `startRealityScan.bat`'s nested
    boot-timeout `exit /b 1` propagates correctly through `call`, so
    the "timeout exit-code shape" review item is a NON-ISSUE; (c) the
    only genuinely broken sites were MergeZoneComponents.bat's
    top-level complist validations (missing complist, missing
    component) — both returned 0, i.e. an unreadable component list
    would have been reported and then IGNORED by the driver. Fixed by
    routing every validation to a top-level `:argfail` label.
    [H2023] (2026-07-24)
- **cmd label-search fails on LF-only line endings** — "cannot find the
  batch label" strikes intermittently at LF-only byte offsets, even
  after earlier `call :label` calls in the same file succeeded. All
  .bat/.vbs must be CRLF; .gitattributes pins *.bat and *.vbs eol=crlf;
  normalize after any scripted edit. [H2023 + NA167 #21, independently
  hit on BOTH machines] (2026-07-23)
- **Git Bash mangles cmd switches** — `cmd /c foo.bat` under MSYS
  converts /c to C:\ and launches an interactive cmd that exits 0
  silently. Use `cmd //c` or PowerShell for .bat invocation tests.
  [H2023] (2026-07-23)
- **VBS quote-escaping in string literals is a trap — compose with
  Chr(34)** — CRITICAL SELF-INFLICTED: malformed ErrorWriterLaunch.vbs
  quoting meant ErrorWriter.bat NEVER RAN and the errors-marker system
  was inert for ~a day of runs (caught by review; completed results
  remained trustworthy because they were validated by census/manifest
  data). Diagnostic: the hook fires for every completed process incl.
  heartbeats, so an active progress file WITHOUT a results log is proof
  the hook is dead. After ANY hook-chain change, verify
  results_<inst>.log grows during the next run. [H2023] (2026-07-24)
- **Unattended prompts must catch EOFError, not trust isatty()** —
  hidden consoles report isatty()=True with an EOF stdin. [H2023]
  (2026-07-24)
- **cmd/stdin encoding breaks scripted prompts** — PowerShell native
  piping prepends a BOM and delivers CRLF (`input()` returned "a\r").
  .strip() everywhere; scripted input() in drivers. [NA167 #10]
  (2026-07-22)
- **ASCII-only console output everywhere** (cp1252 crashes; hit twice).
  PYTHONIOENCODING=utf-8 when parsing UTF-8 sources. [both lines]
- **One-off cmd anomaly, unexplained**: after D6's 56-min merge block,
  `%RealityScan%` expanded empty ("'-delegateTo' is not recognized") —
  single occurrence across ~10 identical workflows; the export step
  died. Watch for recurrence. [NA167 #31 note] (2026-07-24)

## Process conventions

- RC_projects daily save schema: {expedition_dive}_{zone|merged}_YYYYMMDD
  .rsproj in RC_projects one level up from the zone image directory;
  saves after components / merge / texture / final model. (owner
  requirement 2026-07-23)
- **Final per-zone alignment projects are the AUTHORITATIVE artifacts;
  the cross-zone merged project is derived and never trusted over
  them** (owner rationale 2026-07-24). The saved zone project = the
  post-growth accepted state ("as big as the components got
  within-zone"), all images re-enabled, paired with its identity
  manifests as one recovery unit. Three reasons: (a) hand-evaluation
  fallback when the merged result looks wrong — it shows exactly what
  the merge stage was handed, per feature; (b) per-component identity
  is only harvestable from the original aligning scene (B10 ordinal
  rule) and re-alignment is nondeterministic, so a lost zone project
  means unrebuildable identity; (c) the merge stage is the
  least-proven link (D7 open, silent non-merge modes on record) —
  recovery from a bad merge must never require re-running the stage
  upstream of these saves. (2026-07-24)
- Model recipe (owner 2026-07-23): high → remove marginal → remove
  large(30) → largest component → closeHoles+clean → simplify(noise)
  → texture → 4× simplify(smooth 80%)+clean → unwrap → reproject.
  Keep: raw high, textured pre-simplify, textured post-simplify.
  Texture AFTER closeHoles so fill areas get blended image color;
  reprojection then maps manifold→manifold (no nodata).
- Never run RealityScan headless for owner-attended runs: RS_HEADLESS=0.
- Verify merges/grows by camera census, never exit status (multiple
  silent-failure modes are on record: silent non-merge, silent no-op
  selects, inert error hook).
- Forum-mining rules (owner directive 2026-07-23): staff replies
  outrank user lore; only posts ≤4 years old trusted; pre-rename
  (RealityCapture-era) posts get most suspicion; every adopted gem goes
  here with URL, author status, date, verification status.

## H2024 run + ROVDataConcat (2026-07-25 evening)

- **Hook-chain liveness PASSED — the standing self-test owed since the
  2026-07-24 CRLF normalization is now CLOSED.** `results_RS1.log` grew
  with fresh entries (22:17:02 → 22:17:12, six completions) during the
  H2023 model run, so `appProcessAction=ExecuteProgram` →
  `ErrorWriterLaunch.vbs` → `ErrorWriter.bat` still fires end to end
  after the .vbs/.bat line-ending changes. Discovered by reading the
  marker directory during a live run. [H2023] (2026-07-25)

- **ROVDataConcat: `main_kalman.py` exits 0 even when a module FAILS.**
  The H2024 stage-2 run printed `ERROR in kalman_offset: No GeoTIFF
  matching 'H2024_k2mapping_geotiff*.tif'`, then `Aborting:
  kalman_offset failed; downstream modules depend on its output`, and
  the run summary listed `kalman_offset FAILED` — yet the process
  returned exit code 0. Any caller gating on exit status treats a
  failed pipeline as success. Discovered by reading the log of a run
  whose exit code said success. Harmless for photogrammetry (the
  needed `*_final_datatable.csv` comes from `kalman_filter`, which
  succeeded; `kalman_offset` only produces the Unreal upload file),
  but it is a silent-failure channel in a tool this pipeline depends
  on. [H2024] (2026-07-25)

- **ROVDataConcat stage-1 resume detection is EXPEDITION-WIDE, not
  per-dive** — `STEP_OUTPUT_GLOBS` matches `*/[!.]*_<output>.csv` under
  `RUMI_processed`, so a step counts as done if ANY dive has its
  output. Consequence: a single new dive cannot be extracted by simply
  running the orchestrator (every step is skipped because older dives
  satisfy the glob), and `--force` is all-or-nothing across the whole
  expedition. This is why the first H2024 attempt "finished way too
  fast": stage 1 was skipped entirely and stage 2 consumed pre-existing
  2026-07-23 extracts. Discovered by reading `step_outputs_exist` after
  the owner flagged the runtime as implausible. Mitigation used:
  backed up `RUMI_processed` and ran `main.py --force` for the whole
  expedition. [H2024] (2026-07-25)

- **H2024 imagery is clean and rig-identical to H2023.** All 8,197 JPGs
  under `F:\H2024\Images\edited` fully DECODE (not merely verify) with
  zero corruption, and `camera_registry.identify` classifies every one:
  cinema 4,100 + port 4,097, zero unknown — confirming the owner's
  "camera locations are the same as H2023". ANOMALY: exactly one image,
  `C231C2370_20231104202628_edt.jpg`, is 3846x2163 while the other
  8,196 are 4244x2827. A different sensor footprint means different
  intrinsics, so RealityScan will group it separately from the rest of
  the cinema set regardless of its XMP calibration group. Discovered by
  a full-decode validation pass with a dimension census. [H2024]
  (2026-07-25)

- **The hull model CRASHED RealityScan at `closeHoles`/`cleanModel`** —
  minidump `RealityScanCrash-20260726-054742.dmp` written at 01:47:42
  local, and the workflow's next command could not be delegated at all
  (`ERROR: Failed to delegate command: -renameSelectedModel
  "pd6_zone_1_c0_Manifold"`), which is the signature of a dead instance
  rather than a rejected operation. Step [5/8] on the 3,738-camera hull
  is the largest mesh in the deliverable. `merge_zones` recorded
  `success: false` for `pd6_zone_1_c0` and correctly carried on to the
  next component, so bow and torpedo were unaffected. The crash itself
  is ESTABLISHED; its attribution is not - see the SUPERSEDED clause
  next. [H2023] (2026-07-26)
  - **SUPERSEDED (same night, by timeline evidence): "the crash was
    caused by contention from the H2024 CLAHE + zone copy."** The claim
    was that CLAHE at 12 workers and a 9,835-file copy ran concurrently
    with the hull "for the whole window". File mtimes refute it: CLAHE
    output spans 22:30:42-22:33:51 (THREE minutes) and the zone copy
    02:43:57-02:45:15 (78 seconds), while the crash was at 01:47:43 -
    neither was running. The only concurrent load was the batcher's
    zone-computation phase, a single Python process. Lesson: "was
    something else running?" is answerable from mtimes and should be
    checked before it is asserted as a prime suspect; the near-OOM
    precedent made a memory story feel plausible without evidence.
    Corrected reading at the time: the crash is most likely INTRINSIC to
    `closeHoles`/`cleanModel` at this mesh size, so a clean-box retry is
    a cheap discriminator rather than an expected fix. (2026-07-26)
  - **SUPERSEDED IN TURN (2026-07-26, by the retry's exit code): the cause
    was neither contention NOR intrinsic memory - it was the DISK.** The
    clean-box retry reached step [6/8] and failed with
    `0x80070070 ERROR_DISK_FULL` on a `D:` drive at 0 bytes free. See the
    ROOT CAUSE entry below. Both memory stories are retired as causes; the
    memory readings were real but incidental.

- **H2024 prep completed clean end to end.** Georeference 8,197/8,197
  (100% acceptance, all exact matches, zone 4Q), CLAHE 2.0/8x8 on
  8,197 with 0 failures, density batch into 5 zones (2,983 / 1,537 /
  1,279 / 1,413 / 2,623 = 9,835 with overlap bands, 8,197 unique).
  Every zone carries per-camera subfolders, a per-zone flight log, and
  a 1:1 calibration sidecar for every image (`b_xmp_priors true`
  verified by count). Reaching this took four attempts, each blocked by
  a separate real defect - see the four fixes committed 2026-07-25
  evening. [H2024] (2026-07-26)

- **The image batcher spends HOURS in zone computation and seconds
  copying.** On 8,197 H2024 images the run georeferenced in ~1 min and
  CLAHE'd in 3 min, then sat in the batcher's zone-analysis phase from
  ~22:34 to 02:43 - roughly **4 h 10 min** - before writing all five
  zones in **78 seconds** (02:43:57-02:45:15). So >99% of the batch
  stage's wall clock is analysis, not I/O, on a dataset of only 8k
  points. Discovered while reconstructing the hull-crash timeline from
  file mtimes. [H2024] (2026-07-26)
  - **SUPERSEDED (same session): the 4 h 10 min was NOT analysis - it was
    `plt.show()` waiting for someone to close a window.** The batcher
    called `plt.show()` unconditionally after saving each figure; on an
    interactive backend that BLOCKS until the window is dismissed, and the
    second figure cannot even appear until the first is closed
    (owner-observed independently). An identical re-run with the call gated
    on `stdin.isatty()` completed the whole stage in **28.9 min**. So the
    "> 99% of wall clock is analysis" claim is withdrawn, and there is no
    evidence of an O(N^2) path to hunt. LESSON: I inferred an algorithmic
    cost from one wall-clock measurement without asking what the process
    was actually doing - the same error as attributing the hull crash to
    contention. A blocking UI call is indistinguishable from slow compute
    if you only look at elapsed time. The real defect was worse than the
    imagined one: an unattended pipeline stage that stalls forever on a
    window nobody is there to close. Fixed, and the plots are still written
    as PNGs. (2026-07-26)
  - **RE-OPENED (2026-07-26, later): the retraction above was itself WRONG.
    The zone computation really is slow.** A third run, with `plt.show()`
    gated off and NO window in existence, wrote `kernel_density.png` at
    12:38:31 and `batch_zones.png` at **15:31:17** - **2 h 53 min** of
    genuine compute between the two saves, since everything between them is
    KMeans + zone split/merge + overlap scoring. So the ORIGINAL finding
    stands: the batch stage is dominated by analysis, not I/O, and an
    O(N^2)-ish path is worth hunting after all. What does NOT stand is my
    explanation for it. The 28.9 min run I retracted on is now the
    UNEXPLAINED outlier - it processed the same 8,197 images with the same
    parameters and cannot have done this work in that time; whatever it
    skipped is unidentified. LESSON: I used a single faster run as a control
    without establishing that it did equivalent work, which is the same
    error as reading elapsed time as compute in the first place. The
    `plt.show()` gate remains correct on its own merits - a blocking window
    in an unattended stage is a real hazard, owner-observed - it just was
    not the cause of the 4 h. (2026-07-26)

- **Zone copies happen only AFTER the accept gate, as designed** - the
  batcher prints its per-zone table, asks `Accept these batches?
  (a)ccept, (r)eject and set new params:`, and copies only once
  accepted. Under `RS_NO_INTERACTIVE` it logs `Non-interactive run:
  batches auto-accepted` and proceeds. Confirmed in the H2024 log plus
  mtimes showing every zone file written after that line. Worth keeping
  in mind: unattended runs therefore accept whatever zoning the KDE
  produced, with no human look at the table. [H2024] (2026-07-26)

- **CLAHE 2.0/8x8 visually verified on H2024 output, with its cost
  visible too.** Eight random frames compared against the pipeline's
  actual `preprocessed_images` artifacts (read from disk, not
  re-applied): hull plating goes from flat grey to legible painted
  characters and rivet lines (`C231C4652`), and encrustation texture
  emerges from near-uniform murk (`C231C5220`, `C231C2970`) - i.e. real
  local structure for feature detection. Cost: particulate is amplified
  with the signal, invisible marine snow becomes distinct speckle, and
  water-column haze lifts with it; `C231C3153` is a near-featureless
  frame that ends up merely brighter and noisier. Consistent with the
  staff caution about detectors manufacturing noise points on turbid
  imagery, and it sharpens Q-05 rather than settling it. NOTE the
  current pipeline order (Georeference -> Preprocess -> Batch -> Align)
  means CLAHE'd imagery is what gets BOTH aligned and textured;
  RealityScan Image Layers (`.geometry`/`.texture`) is the mechanism if
  geometry should come from originals and appearance from enhanced
  images. [H2024] (2026-07-26)

- **H2024 imagery spans 2023-11-04 ~20:26 to 2023-11-05 ~01:28**, not
  the 20:26-22:24 first stated - that figure came from sorting
  filenames rather than timestamps, and the two camera prefixes
  interleave in time. Well inside the nav window (17:27 11-04 to
  02:03 11-05), which the 100%-exact georeference match confirms
  independently. Lesson: for two-camera filename families, name order
  is not time order. [H2024] (2026-07-26)

- **DEFECT (fixed): `GenerateModel.bat` used FIXED model names while
  being run once per component against ONE shared project.** Every
  `-renameSelectedModel` wrote a constant name, so from the second
  component onward the scene held duplicates - and step [8/8] resolves
  its operands by name (`-reprojectTexture "HighPoly_Textured"
  "Simplified"`), so the bow's reprojection could map the HULL's texture
  onto the bow's mesh with a clean exit status. The intermediate-cleanup
  loop also deletes by name and could remove another component's models.
  All 19 references now carry a `%model_tag%` prefix taken from the
  component. Discovered by reading the workflow before the second
  component started, not by a failure; the run was stopped mid-hull and
  restarted rather than risk a silently wrong deliverable. [H2023]
  (2026-07-25)

- **`-selectComponent` DOES resolve manifest component names in an
  assembled project.** The standing worry (manifest names vs in-scene
  names never matching, because zone scenes were saved pre-rename) does
  NOT apply to the assembly: components are imported from `.rsalign`
  files that were renamed BEFORE export, so `-selectComponent
  "pd6_zone_1_c0"` and `"pd6_zone_1_c1"` both selected and modelled
  correctly. Discovered by running the real `--auto_model` path and
  reading the per-component workflow logs. Scope note: this says nothing
  about zone scenes, where the pre-rename save still applies. [H2023]
  (2026-07-26)

- **Three unattended-run defects in the orchestrator, all fixed.**
  Found by driving the documented `RS_MODULES` / `RS_NO_INTERACTIVE`
  entry point on a new dataset; each cost one failed attempt:
  - `main.py --help` crashed with `ValueError: unsupported format
    character '>'`. argparse %-expands help text at `print_help()` time
    and `batch_xmp_priors`' description contains `96.3% -> 89.6%`. This
    killed `--help` AND every argparse error path. Escaped at the
    argparse layer, so descriptions stay readable for prompts and no
    future percent can reintroduce it.
  - The inter-module `input("Press enter to continue...")` was
    unguarded, so an unattended chain died with `EOFError` BETWEEN two
    successful modules - georeference finished 8,197/8,197 and the
    pipeline stopped there. EOF now means continue. The codebase already
    guarded its other `input()` sites; this one was missed.
  - `preprocess_images.validate_parameters` raised `TypeError:
    _path_isdir: path should be string... not NoneType` when `-p_i` was
    absent, instead of naming the missing flag. Now reports which flag
    to pass.
  LESSON: the non-TTY path had not been exercised end to end on a fresh
  dataset since the overhaul, and all three failures were in the
  scaffolding around working modules, not the modules themselves.
  [H2024] (2026-07-25)

- **`sfmDistortionModel` is GLOBAL and all-or-nothing; the per-camera XMP
  `Camera:DistortionModel` hint does NOT switch models per camera.** The
  cinema sidecars declare `brown3`, yet every one of 2,558 cinema pose
  XMPs from PD-6 came back `xcr:DistortionModel="division"` - the same
  model as the 2,492 port records. Discovered by aggregating solved
  intrinsics out of the PD-6 identity harvest. This SETTLES the open
  decision rule in `testing/PRIORS_DISTORTION_TEST_PLAN.md` ("adopt
  division-for-P only if ... if the global key is all-or-nothing"): it
  is all-or-nothing, so a mixed-optics rig gets ONE distortion model and
  only the coefficients differ per calibration group. Consequence for
  PD-6's attribution: Division was not applied to the fisheye
  selectively - it was applied to everything, and the rectilinear camera
  tolerated it (k1 -0.038, tight IQR, hull scale 0.982). Supplying
  measured coefficients remains per-group and therefore still useful.
  [H2023] (2026-07-26)

- **Solved intrinsics under the corrected (PD-6) config, and the
  calibration groups are demonstrably working.** Over 5,050 harvest
  records (4,394 unique cameras; bow members appear in two laps by the
  successive-difference design):
  - cinema, 2,558 records: focal 35mm-eq **16.374** (IQR 16.302-16.476),
    division k1 **-0.0378** (IQR -0.0415..-0.0336), principal point
    (-0.0071, -0.0031), skew 0, aspect 1.
  - port, 2,492 records: focal 35mm-eq **15.499** (IQR 15.435-15.574),
    division k1 **-0.3875** (IQR -0.3933..-0.3832), principal point
    (+0.0027, +0.0056), skew 0, aspect 1.
  Both cameras were given the SAME 16.0 mm prior, and the solve
  separated them by 5.6% with IQRs of only about +/-0.5%. Because the
  WCA JPGs are EXIF-identical, the XMP calibration groups (3 cinema /
  2 port) are the only mechanism that could have separated them - so
  this is independent confirmation that the sidecar grouping works, not
  just that it is written. The order-of-magnitude k1 gap is the fisheye
  declaring itself. Discovered by parsing `xcr:` attributes from the
  PD-6 harvest XMPs. NOTE the exports also carry
  `xcr:CalibrationGroup="-1"`/`DistortionGroup="-1"` alongside
  `Camera:CalibrationGroup="3"`; the -1 is an export artifact, not a
  lost grouping. [H2023] (2026-07-26)

- **OWNER REPORT + DIAGNOSIS: the bow model sits ~45 deg off the true
  ground plane (site is a flat mud floor). The ALIGN is not the culprit;
  orientation priors are absent where they would constrain geometry and
  present only where they can merely rotate a finished component.**
  Measured from the PD-6 harvest: the bow's solved camera cloud matches
  nav to **0.8 deg** in best-fit-plane attitude (solved 8.1 deg off
  vertical vs nav 7.3 deg), with shape ratios agreeing to three decimals
  (mid/max 0.371 vs 0.370), and its optical axes are statistically
  identical to the hull's (median 148.1 vs 147.7 deg from local up, same
  ~50 deg spread). So there is no 45 deg rotation in the zone solve.
  WHERE YPR ACTUALLY ENTERS: the PD-6 align log is 7-column
  position-only, while the assembly's union log is 13-column carrying
  Yaw/Pitch/Roll at 3/5/3 accuracies - so the ONLY consumer of
  orientation was `-update` in the assembly, a rigid/similarity fit
  applied AFTER reconstruction, which can rotate a component but cannot
  stiffen or repair its geometry.
  RANKED CANDIDATES:
  1. `-update` rotated the bow to satisfy MIS-CONVERTED orientation
     priors. The Euler order / camera-mount convention for imported YPR
     is explicitly UNVERIFIED (the planned one-minute GUI check was
     never done). NOTE: an earlier version of this candidate also cited
     "Port lever arm off by ~1 m" as independent support - that claim was
     RETRACTED on 2026-07-25 (measured inside the 0.175-scale hull) and
     must not be used as evidence here; the validated lever arms are the
     code's originals. A 656-camera component spanning 9.3 m on a
     near-1D track is cheap to rotate about that track - the fit trades
     a small position penalty for the orientation term - whereas the
     hull (3,738 cams over 17.9 m) is far stiffer. Predicts a clean
     near-rigid tilt, which matches a crisp "45 degrees".
  2. Internal deformation of the bow: scale IQR width **0.444** vs the
     hull's 0.081 (5.5x wider), which by the oracle's own semantics means
     drift/fold, not a similarity error. Explains floor NON-FLATNESS but
     not a clean 45 deg plane.
  BLINDNESS NOW LOAD-BEARING (escalation condition): assemble mode
  exports no poses, so the assembled project - the artifact the owner
  actually looked at - cannot be measured. Hypotheses can only be ranked
  until poses are harvested from a copy of the assembly.
  CHEAP DECISIVE TEST: re-run the assembly `-update` with a
  POSITION-ONLY union log and re-measure the bow's attitude; the
  assembly stage costs ~2 min. If the tilt disappears, candidate 1 is
  confirmed and the remedy is to verify the YPR convention before
  importing orientation anywhere.
  OWNER POSITION (agreed, with a caveat): pitch/roll/yaw belong in the
  ALIGNMENT priors, not merely in the post-hoc georeferencing fit - that
  is where they would anchor absolute attitude AND stiffen a solve
  against exactly the drift measured in candidate 2. Caveat: they must be
  imported at 15 deg accuracy - PROVISIONAL, not validated, see the
  contamination flag - rather than the 3/5/3 in the zone logs (tight orientation at dense scale is already suspect
  from PD-4), and the convention must be verified first - importing
  wrong-convention YPR is itself a mechanism for this defect. [H2023]
  (2026-07-26)

- **RESOLVED BY FORUM MINING: the RealityScan YPR convention, and our
  flight log is 90 deg wrong for the Port camera.** Epic staff
  **OndrejTrhan** (2023-10-23, Epic Developer Community knowledge base
  "Registration export and camera orientations"): *"Yaw = 0, image is
  oriented to Y (upper side of image is oriented that way), Pitch = 0,
  image is looking down, Roll = 0, image is parallel with X axis."*
  Composition is intrinsic Roll -> Pitch -> Yaw; Yaw about Z, Pitch about
  Y, Roll about X. The Help's Trajectory Import page adds that imported
  **YPR is interpreted in NED** (OPK is the ENU variant), that "Euler
  angles order (YPR)" is a SETTING evaluated right-to-left, and that a
  **"Camera mount"** option exists whenever YPR is included.
  OUR PITCH CONVERSION IS CORRECT - verified against the written logs.
  `_convert_to_rc_orientation` already computes
  `rc_pitch = 90 + (pitch_vehicle - camera_offset)`, i.e. it already
  references pitch to nadir. Measured in `zone_1`'s flight log: **Port
  median 88.11 deg** (n=2,267; range 86.6-89.4) = essentially horizontal
  on a 90-deg-is-horizontal scale, and **Cinema median 43.11 deg**
  (n=2,273; range 41.5-44.3) = ~45 deg down from horizontal. Both match
  the rig as the owner describes it. Discovered by forum mining at owner
  instruction (owner recalled a staff post confirming the convention -
  correct, and it is OndrejTrhan's above). [H2023] (2026-07-26)
  - **SUPERSEDED (same session, within minutes, by reading the written
    logs): "we write pitch from horizontal, so Port is 90 deg wrong and
    Cinema is coincidentally right."** FALSE. I read
    `_get_camera_pitch_offset`'s "degrees down from vehicle forward axis"
    docstring and the flight-log writer, and asserted the defect WITHOUT
    checking the function between them or the actual column values. The
    +90 conversion was already there, and one `grep` of P231C rows
    (88.1 deg, not ~0 deg) refutes the claim outright. Lesson, and it is
    the same one as the earlier contention hypothesis this session: an
    output claim must be checked against the OUTPUT, not inferred from
    two ends of a call chain. Cost: a wrong diagnosis reported to the
    owner and committed. (2026-07-26)
  STILL OPEN after the correction - the import-side settings, which our
  `FlightLogParams.xml` does NOT pin, so both fall to defaults:
  1. **Euler angles order (YPR)** - a documented import setting evaluated
     right-to-left. Our angles assume intrinsic Roll -> Pitch -> Yaw per
     OndrejTrhan; if the default order differs, the composition is wrong
     even though each individual angle is right.
  2. **Camera mount** - offered whenever YPR is included. We already bake
     the camera mount into the angles (adding `camera_offset`), so a
     non-identity default here would DOUBLE-APPLY the mount.
  3. **Near-singular Port geometry**: Port's pitch sits at ~88 deg, within
     2 deg of the 90 deg degeneracy where roll and yaw axes collapse in
     this parameterisation. Small pitch noise then produces large
     attitude swings - a plausible contributor to a component that holds
     mostly Port frames.
  SCOPE — **CORRECTED, see the scope-correction entry below.** I first
  wrote "harmless to every align so far (production aligns ran
  POSITION-ONLY)". That is FALSE: the production params point at the
  13-column format with `ifUseOriAcc=true`, so the 2026-07-24 fresh-run
  aligns DID import orientation at 3/5/3. Only PD-6's cell was
  position-only. Orientation is consumed by BOTH the fresh-run aligns and
  the assembly's `-update`.

- **REVERTED 2026-07-26 (owner: "change lever"). The entry below is
  SUPERSEDED; the code is back to Port (1.0 fwd, 0.0 lat, 1.0 down) and
  Cinema (1.0, 0.0, 0.0), the values two metrically-sound solves validated.
  H2024's nav, flight log and zones are being regenerated from raw under
  the restored geometry.** Original flag follows:
  **DISPUTED — THIS CHANGE RESTS ON RETRACTED EVIDENCE AND SHOULD PROBABLY
  BE REVERTED (flagged 2026-07-26 by a contradiction audit).** The entry
  below cites "|P-C| separation 0.22 m, vertical component 0.00 m, P ~0.17 m
  ahead" as corroboration. Those figures were **already retracted on
  2026-07-25**: they were measured inside hull c0, the **0.175-scale**
  component, so both the separation and its vertical part are meaningless
  (0.22 x 5.7 ~= 1.25 m, which is what the sound solves actually report).
  The RETRACTION entry above validated the ORIGINAL code on two
  INDEPENDENT metrically-sound solves - bow c2 and zone_2 from PD-2b -
  finding **C above P by +1.12 m and +1.03 m** against the code's implied
  +1.00 m, separation 1.21/1.11 m, and concluded "the code's 1.0 m stands,
  corroborated twice".
  So the owner's 2026-07-26 instruction ("roughly the same distance
  forward, the Z in my notes may be wrong") conflicts with the measured
  evidence, and I implemented it while quoting numbers the log had already
  thrown out. CONSEQUENCE: H2024's flight log and its re-batched zones are
  currently built with Port 1 m too HIGH and 0.17 m too far forward. H2023
  is unaffected (it was not re-georeferenced). AWAITING OWNER DECISION;
  if reverted, H2024 needs its flight log and zones regenerated again.
  [H2023] (2026-07-26)

- **Rig lever arms corrected: Port and Cinema are level, not 1 m apart in
  Z.** Owner (2026-07-26): both cameras are roughly the same distance
  forward of the USBL, and the Z figure in the notes was the doubtful
  one. This matches the solve-derived rig-internal geometry already
  recorded - |P-C| separation 0.22 m (IQR 0.21-0.28), vertical component
  **0.00 m** (IQR -0.09..+0.04), P about 0.17 m ahead of C. Applied in
  `_get_camera_offsets`: Port 1.0 m forward / 1.0 m DOWN -> **1.17 m
  forward / 0.0 m down**, Cinema unchanged at 1.0 / 0.0. Removes a
  ~10-sigma-per-Port-frame conflict at the 0.1 m Z accuracy that was in
  force when the error was found. Rig-internal quantities are observable
  regardless of how weakly absolute attitude is constrained, which is why
  this derivation is trusted where the mount-ANGLE derivation was not.
  [H2023] (2026-07-26)

- **CONTAMINATION FLAG: every prior conclusion about whether ORIENTATION
  PRIORS help or hurt was measured through an unverified import path, and
  none of them isolates what was actually being tested.** The orientation
  work above establishes that (a) imported YPR is read in NED with a
  CONFIGURABLE Euler order evaluated right-to-left, (b) a **Camera mount**
  option applies whenever YPR is included, and (c) our
  `FlightLogParams.xml` pins NEITHER - so every orientation cell ran on
  whatever the import defaults are, composing angles in a possibly
  different order than the intrinsic Roll -> Pitch -> Yaw our numbers
  assume, and possibly double-applying a camera mount we already baked in.
  Additionally Port's pitch sits at ~88 deg, within 2 deg of the
  parameterisation's 90 deg degeneracy.
  CELLS AFFECTED (registration counts stand as measurements; the
  ATTRIBUTION to "orientation priors" does not):
  - **PD-0** (13-col + tight YPR 3-5 deg) - already a bad cell for
    changing two variables; now doubly so.
  - **PD-0b** ("orientation at HONEST 15 deg", 109/124, +7 vs baseline,
    "dose-response proven: 5 deg fragments, 15 deg gains"). The ACCURACY
    dose-response may well survive, since weighting is independent of
    composition order, but "orientation helps" really means "these
    particular numbers, composed by an unknown default order, helped".
  - **PD-1b** (Division + orientation@15, 112/124, "gains not additive").
  - **PD-4** (Division + orientation@15 + 1/1/0.1, COLLAPSED to
    669/4540) - already confounded by the sidecar-stripping defect AND by
    memory contention; the unpinned import is a third confound. Its
    reading that "orientation-at-scale is the poison" is not supported.
  - **M-DIV-ORI** (smoke + orientation@15, 118/120).
  - **Interim v2-config policy** "orientation@15 deg is validated on
    SPARSE zones (zone_2 8x, zone_3 +7)" - downgrade from validated to
    PROVISIONAL.
  - **Mount-angle derivation from solved scenes** (zone_3 C~58 deg down vs
    a zone_1 strip C~-42 deg, both with tight IQRs) - already recorded as
    unreliable because position-only georeferencing leaves absolute
    attitude weakly constrained; any re-derivation must pin the import
    settings FIRST or it will inherit the same ambiguity.
  NOT affected: **PD-6 only** among the production aligns (its cell params
  point at a 7-column position-only format), plus all scale-oracle results
  and the rig-INTERNAL geometry (relative axis angle, relative camera
  separation) that the lever-arm correction rests on - those are observable
  regardless of absolute attitude.
  **AFFECTED, corrected 2026-07-26: the 2026-07-24 FRESH RUN.** An earlier
  version of this line claimed the fresh run was position-only. It was not -
  production `FlightLogParams.xml` selects the 13-column YPR format with
  `ifUseOriAcc=true`, so zone_1/2/3 imported orientation at 3/5/3 under the
  same unpinned Euler order. See the scope-correction entry below.
  REQUIRED BEFORE ANY FURTHER ORIENTATION CELL: pin Euler order and camera
  mount explicitly in `FlightLogParams.xml`, then re-run one cheap sparse
  cell (Z3) to see whether the PD-0b gain survives a pinned import.
  [H2023] (2026-07-26)

- **CORRECTION to the contamination-flag scope, and a THIRD candidate for
  the PD-6 scale fix.** I wrote that "production aligns ran POSITION-ONLY,
  so the unpinned orientation import was harmless". That is FALSE for the
  fresh run. The params files differ by format GUID:
  - production `FlightLogParams.xml` -> `{B438A617-...}` = the 13-column
    format whose parser maps **Yaw/Pitch/Roll at indices 7/8/9**, with
    `ifUseOriAcc=true`. So the 2026-07-24 fresh-run aligns (zone_1/2/3)
    DID import orientation, at the then-current **3/5/3** accuracies.
  - PD-6's cell `FlightLogParams_4Q.xml` -> `{0E9850E2-...}`, a 7-column
    position-only format. PD-6 genuinely had no orientation.
  CONSEQUENCE: PD-6 vs the fresh run differs in THREE ways, not two -
  (a) Brown3 -> Division, (b) accuracy columns actually imported, and
  (c) **orientation priors REMOVED**. Since the fresh run is exactly the
  run whose hull solved at scale **0.175** and PD-6 the one that solved at
  **0.982**, "removing tight, possibly mis-composed orientation priors" is
  a live candidate for the scale repair and was never listed. It is also
  mechanically plausible: orientation priors composed under the wrong
  Euler order fight the visual solution on every frame, and this geometry
  maps attitude error into focal/scale error.
  DOES NOT change the bow diagnosis: the bow the owner inspected comes
  from PD-6 (position-only), so its tilt cannot have been caused by
  align-time orientation priors - the assembly's `-update` remains the
  leading suspect. Discovered while pinning the import settings, by
  reading the two params files instead of assuming they matched. [H2023]
  (2026-07-26)

- **OWNER DECISION (2026-07-26): apply orientation priors at alignment
  regardless of the outstanding discriminator test, staying conservative
  on the claimed accuracy.** Rationale given: validated data should not be
  thrown away. Concern raised and overruled, recorded per the working
  agreement: the Euler order and Camera-mount import settings are still
  unpinned, and the correction above makes "tight orientation priors" a
  live candidate for the fresh run's scale collapse - so orientation ON
  with an unverified composition carries a real scale risk. MITIGATIONS in
  force: accuracies are already the conservative **15 deg** for yaw, pitch
  and roll (`_get_camera_pitch_accuracy` returns 15 for P/C, `yaw_acc` and
  `roll_acc` are 15) rather than the fresh run's 3/5/3, and every H2024
  component will be measured with `testing/scale_oracle.py` before it is
  used, so a repeat of the 0.175 failure is caught by evidence rather than
  by eye. [H2024] (2026-07-26)

- **Import settings `ifKGrp` and `ifKmode` cannot be pinned by
  inspection - they are the only plausible carriers of Euler order and
  Camera mount, and their value mapping is undocumented.** The Help
  documents the SETTINGS ("Euler angles order (YPR)", "Camera mount",
  both present whenever YPR is imported) but not their config keys;
  `flightlogs.xml` defines only column mapping; and neither key string
  appears in any file under the RealityScan install, so both are compiled
  into the binary. Current values, unchanged since the template was
  written: `ifKGrp=2`, `ifKmode=0x0`. Guessing a value here would silently
  change orientation handling - the exact failure class under
  investigation - so nothing was changed. TWO WAYS TO SETTLE IT: (1) set
  the two dropdowns in the GUI import dialog, save the params, and diff
  against this template (one minute, needs the GUI); (2) a CLI probe -
  align the smoke fixture with orientation at several `ifKmode` values and
  read the resulting camera attitudes out of the pose XMPs, which is
  fully headless and about 2 min per cell. [H2023] (2026-07-26)

- **NEAR MISS (fixed): five H2024 zones were silently a BLEND of two
  zonings, and were about to be aligned.** After the lever-arm correction
  changed every Port position, a re-batch reused the existing
  `batched_images_by_zone` folder: the batcher's unattended overwrite path
  reuses on the stated premise that "zone recomputation is deterministic
  for the same log+parameters", which was true and never verified. The
  flight log HAD changed, so zone membership changed, and `__copy_files`
  skips files already present but has no way to remove a member the new
  zoning dropped. Result: **12,679 jpgs on disk against 9,834 reported**
  (zone_2 1,537 -> 3,497, zone_5 2,623 -> 3,497), i.e. ~2,845 stale
  images, with the module reporting `Success: True`. Discovered by
  counting files per zone instead of trusting the summary. Fixed by
  making the premise mechanical: `batch_inputs.json` records the flight
  log's sha256 plus the six zoning parameters, and reuse is REFUSED with
  the remedy named when they differ. Contaminated folder removed and
  rebuilt clean - 9,834 jpgs, 1:1 sidecars, totals matching the report.
  LESSON: a reuse/resume path needs an input fingerprint, not a comment
  asserting the inputs are unchanged; and "Success: True" from a stage
  whose output is a directory means nothing without counting the
  directory. [H2024] (2026-07-26)

- **Hull model memory profile, now measurable.** The retry's resource
  trace (`logs/resources_GenerateModel_*.csv`) shows `-calculateHighModel`
  on 3,738 cameras driving the box to its limit: available RAM fell from
  79.4 GB to **3.1 GB within 3 minutes**, commit charge went 19.6 -> 105 GB
  and Windows grew the commit limit from 99.5 GB to ~120 GB to absorb it,
  after which the run oscillated at 87-105 GB committed with 7-32 GB free
  for the next half hour. RealityScan's working set peaked at 62.5 GB.
  Confirmed still doing real work rather than hanging: 9.1 cores busy and
  33% GPU measured over a 20 s window. The bow (656 cams) and torpedo (102)
  completed comfortably; the hull is 5.7x the bow.
  **These figures stand as a MEMORY PROFILE and NOT as the cause of any
  failure.** An earlier version of this entry read them as "memory
  exhaustion INTRINSIC to this component's mesh" and inferred that High
  detail plus `closeHoles` "does not fit in 93.6 GB without paging". The
  retry then failed on `ERROR_DISK_FULL`, not memory, so that inference is
  withdrawn - see the ROOT CAUSE entry below. What survives: the hull does
  page heavily at High detail, which makes it SLOW (step [1/8] alone ran
  far longer than the bow's entire recipe), and the pagefile is only
  6.9 GB. Whether the recipe needs a lever for the hull is therefore still
  open, but it is a THROUGHPUT question, not the explanation for the two
  crashes. [H2023] (2026-07-26)

- **ROOT CAUSE of the hull model failures: the DISK, not memory.** The
  retry ran 143.5 min, got past `closeHoles` (step [5/8], which the first
  attempt died at) and failed at **[6/8] texture generation** with
  `result code 2147942512` = **0x80070070 = ERROR_DISK_FULL**. `D:` had
  reached **0 bytes free**; the driver's own log-snapshot then failed with
  `[Errno 28] No space left on device`, which is what made it unmissable.
  The memory readings were real but incidental: RAM did fall to 3.1 GB, the
  pagefile is only 6.9 GB, and the process was verified doing genuine work
  (9.1 cores, 33% GPU) throughout. Both earlier explanations - concurrent
  load, then intrinsic memory exhaustion - are therefore SUPERSEDED as
  causes of these failures. `:fail` quits WITHOUT saving, so the assembly
  survived intact (parses, no zero-byte files, bow + torpedo models
  present).
  METHOD LESSON, and the sharpest one of the session: I built a resource
  trace hours earlier and instrumented CPU and memory *because memory was
  my hypothesis*. It faithfully recorded RAM falling to 3.1 GB and was
  silent about the disk that actually killed the run. A monitor built
  around one hypothesis will confirm or refute that hypothesis and tell you
  nothing else. Free disk on the project drive is now a trace column with a
  peak-minimum in the summary line. [H2023] (2026-07-26)

- **H2023 workspace physically relocated to `F:` behind a directory
  junction at the old `D:` path.** Owner-approved cleanup deleted
  `RC_projects` (57.1 GB), the superseded `merged` assembly (31.9 GB) and
  `orphan_pickup`/`orphan_pickup2` (17.6 GB), then the remaining 90.6 GB /
  39,235 files moved to `F:\na156_h2023_fresh` in 3.2 min, with
  `D:\na156_h2023_fresh` recreated as a JUNCTION to it. WHY the junction
  rather than a plain move: the saved `.rsproj` stores ABSOLUTE image paths
  that texturing needs, and hard rule 7 says a relocated `.rsalign` hangs
  the instance forever on import - a bare move would have broken both. With
  the junction every historical absolute path still resolves (verified for
  the .rsproj, a component .rsalign, a zone flight log and a real image)
  while the bytes live on F:. Result: **D: 0 -> 197.3 GB free, F: 773.9 GB
  free**. FOR FUTURE SESSIONS: `D:\na156_h2023_fresh` is NOT a real
  directory - if it is ever deleted or recreated, the junction must be
  restored (`New-Item -ItemType Junction -Path D:\na156_h2023_fresh -Target
  F:\na156_h2023_fresh`) or every recorded path in this log breaks.
  [H2023] (2026-07-26)

- **TRUE ROOT CAUSE of all three hull-model failures: RealityScan's CACHE
  DISK, not the project disk.** The instance log - snapshotted for the
  first time thanks to the per-model snapshot added earlier - says it
  outright: `Processing failed: Out of disk space..` during
  `simplify` (step [6/8], after `closeHoles` 125 s and `cleanModel` 230 s
  had both SUCCEEDED). The cache lives at **`D:\rccache`, 1,089 GB**, and
  it refilled the 197 GB freed by the owner-approved cleanup within one
  run. Moving the PROJECT to F: did nothing, because the cache does not
  move with it. Epic's own "Out of Disk Space" page confirms the
  mechanism - "processing cannot continue without freeing up some space on
  it", the process is aborted and "the progress will be lost" - and warns
  **"don't delete the files from your cache folder since this may lead to
  some failures in the project"**, so hand-clearing `rccache` is NOT a
  legitimate remedy. Their sanctioned levers are freeing space on the cache
  disk or changing the cache disk.
  SETTINGS (from `tutorials/setkeyvaluetable.htm`): `appCacheLocation` =
  `SystemTemp` | `Custom`; `appCacheCustomLocation` = path (used when
  Custom); `appAutoClearCache` = retention in days, where 999999 = never
  clear, 0 = clear all, and 3/7/14/30/90 select an age cutoff. `-clearCache`
  is also a CLI command, and requires the project be saved first.
  APPLIED: `startRealityScan.bat` now honours an opt-in `RS_CACHE_DIR` -
  when set it boots with `appCacheLocation=Custom` +
  `appCacheCustomLocation`, and unset keeps RealityScan's default, so
  nothing changes silently. `appAutoClearCache` deliberately untouched:
  retention is owner policy.
  INSTRUMENTATION LESSON, the third variation of the same mistake: after
  the disk-full diagnosis I added a `disk_free_gb` column - and pointed it
  at the drive holding the trace, i.e. the PROJECT drive. It faithfully
  reported 773.9 GB free for the whole run while the CACHE drive went to
  zero. Watching the right RESOURCE is not enough; it has to be the right
  INSTANCE of that resource. [H2023] (2026-07-26)

- **ROVDataConcat is DETERMINISTIC end to end — verified, not assumed.** A
  full forced re-run for H2024 (stage 1 raw extraction over the whole
  expedition, then stage 2 kalman) reproduced **all nine output CSVs
  byte-identically** (sha256 over USBL Atalanta/Hercules, dvl_lat_long,
  octans, sealog_sensors_merged, filtered_datatable, kalman_filtered_data,
  final_datatable, kalman_assessment). Confirmed the work actually re-ran:
  every stage-1 step reported `done` rather than `skipped (resume)`. Worth
  having as a fact rather than a belief, because several "deterministic for
  the same inputs" assumptions failed elsewhere this session (the batcher's
  zone-reuse premise most notably). Also re-confirms that the camera lever
  arm lives entirely in THIS repo's georeference module - it has no effect
  on nav, so a lever-arm change never requires re-running ROVDataConcat.
  [H2024] (2026-07-26)

- **DEFECT (fixed): `main.py` exited 0 when a module REFUSED to run.** On
  `validate_parameters()` returning False the orchestrator logged the error
  and did a bare `return`, which exits 0 - while the module-FAILURE branch a
  few lines below has always used `sys.exit(1)`. So a refused run was
  indistinguishable from a successful one to any caller gating on exit
  status. Discovered because the batcher's new fingerprint guard correctly
  refused to reuse zones built from a different flight log, and the process
  still reported success. Fixed to `sys.exit(1)` and verified by re-running
  the same refusal: now exit 1. NOTE this is the second silent-failure exit
  code found this session, after ROVDataConcat's `main_kalman.py` returning
  0 with a FAILED module - worth checking any other orchestrator here for
  the same shape. [H2024] (2026-07-26)

- **The batcher's input fingerprint WORKS IN ANGER.** After the lever-arm
  revert changed every Port position, the re-batch was refused with
  `Existing batched zones were built from DIFFERENT inputs (changed:
  flight_log_sha256). Reusing them would mix two zonings...`. This is the
  exact near-miss it was written for hours earlier (12,679 images on disk
  against 9,834 reported), now caught mechanically instead of by manually
  counting files. [H2024] (2026-07-26)

- **H2023 HULL MODEL COMPLETE.** Attempt 4 succeeded: `success=True` in
  384.1 min, all eight recipe steps, no errors, project saved plus dated
  copy. The only variable changed from the three failures was the cache
  drive (`RS_CACHE_DIR=E:\rscache`), which closes the loop on the
  disk-not-memory diagnosis. Resource peaks are worth recording because
  they are extreme: **CPU 100%, commit used 142.3 GB, minimum available
  RAM 0.3 GB**, minimum free project disk 672.6 GB, minimum free CACHE
  disk 6,900.5 GB. So the hull DOES run the box to the edge of memory - it
  simply never failed there. All three H2023 components (hull 3,738 / bow
  656 / torpedo 102) now carry models. [H2023] (2026-07-26)

- **CRITICAL: the metric-scale failure REPRODUCED on H2024 zone_3 - 1,192
  cameras at scale 0.236 - on the first production run with ORIENTATION
  PRIORS ENABLED.** Full sweep (`testing/scale_oracle.py`, all 16
  components): zone_1 eight components 0.937-1.119; zone_2 1.086;
  **zone_3 c0 = 0.236 (IQR 0.217-0.253)**; zone_4 five components
  0.983-1.196; zone_5 1.023. Registration looked entirely healthy
  throughout - 8,709 cameras, 82-93% per zone, `Success: True` on every
  zone - which is exactly the blindness the oracle was built for: a
  camera-counting gate passes this dataset.
  This is the SAME failure mode as the fresh-run H2023 hull (0.175) and it
  is the risk that was explicitly raised and overruled when orientation
  priors were switched on ("apply the orientations regardless of test...
  we should not throw away validated data"), with the scale oracle named
  as the mitigation. The mitigation worked on its first outing.
  ATTRIBUTION NOT YET ESTABLISHED - and must not be assumed. This run
  differs from the sound PD-6 run in more than one way: different dataset,
  orientation priors ON at 15 deg, and the unpinned Euler order / camera
  mount. The narrow IQR (0.217-0.253) says it is a clean SIMILARITY error,
  i.e. a whole-component scale collapse rather than drift or a fold -
  consistent with a focal/attitude conflict rather than a bad solve.
  DISCRIMINATOR (cheap, decisive, ~20 min for 1,279 images): re-align
  zone_3 alone with a POSITION-ONLY flight log and the 7-column format
  GUID, exactly as PD-6 was configured, and re-measure. If scale returns to
  ~1.0 then orientation priors under an unpinned Euler order are the cause
  and the priors must come back out until the convention is verified.
  NOTE zone_4 c2 (1.196) and c4 (1.100) also sit outside a +/-10% band, so
  zone_3 may be the extreme of a spectrum rather than an isolated fault.
  [H2024] (2026-07-26)

## Merge acceptance logic — adversarial review (2026-07-27)

Full report: `F:/_copylogs/merge_logic_review.md` (35 confirmed / 11 refuted,
9 agents). The owner asked whether the "hull fused on the first rung with fewer
cameras, then split on later attempts" behaviour is sound. Verdict: the OUTCOME
was right, the STATED MECHANISM is not what executed.

- **THE NEVER-SHRINK INVARIANT IS DEAD CODE AND NEVER FIRED.** In
  `merge_zones.py` every adopted entry's `camera_count` equals its matched
  subset's sum, each input pops exactly once, and `confidence == "exact"`
  requires the remaining set to be empty — therefore `adopted_cams ==
  input_cams` identically and `lost == 0` always. `lost > 0` can only arise when
  attribution is NON-exact, which is already rejected on its own term. The
  clause is vacuous in both directions: it can never reject, and it cannot see a
  camera GAIN either — precisely what `sfmForceComponentRematch` and
  `sfmImagesOverlap:High` exist to produce. On the H2023 hull `adopted` was
  EMPTY (peel 3,738 or 3,737 matches no subset sum of {3026, 714}), so the
  attempt died on the `adopted` term and never reached never-shrink. Every
  earlier statement in this log attributing the hull rejection to never-shrink
  is WRONG; the real gate was exact subset-sum attribution. [H2023] (2026-07-27)

- **The dominant rejection shape records NO reason.** `entry["rejected"]` is
  written only when `adopted` is truthy with `lost > 0`, or when `fused` is
  truthy. The H2023 shape (adopted empty, fused False) sets neither, and
  `camera_delta` is None — so `merge_report.json` shows `workflow_success: true,
  attribution: "ambiguous", adopted_count: 0, camera_delta: null` and no
  rejected key. The 3,740-vs-3,738 deficit appears nowhere in the report. The
  exports-incomplete downgrade records nothing either, and the "ambiguous" label
  OVERWRITES "shrink" when both fire. [H2023] (2026-07-27)

- **`fused` is inferred from the same arithmetic that fails on a lossy fusion**,
  so a fusion is only VISIBLE when its count is an exact input-subset sum. All
  three H2023 rungs therefore reported "nothing fused" about a merge that
  demonstrably did fuse. No code path in the driver can currently assert that
  two components fused. [H2023] (2026-07-27)

- **The 2 (or 3) missing cameras are probably a real solver drop, but are NOT
  yet distinguishable from a harvest artifact — and the ICP follow-up that
  seemed to confirm loss is not independent evidence.** For real loss: the
  deficit VARIES by mechanism (-2 merge, -1/-1 align), and a free re-align is
  already recorded as dropping 1-2 marginal cameras normally; deterministic
  bookkeeping would give a constant deficit. Against: the peel harvest is a
  single PowerShell line doing `Get-ChildItem -Recurse | Move-Item -Force` over
  the ENTIRE images_root, and Windows PowerShell 5.1 exits 0 on non-terminating
  pipeline errors — so `if errorlevel 1` cannot see a partial move, and two
  locked sidecars are a silent -2. Because merged-scene sidecars are ORDINAL
  (B10), a flat `-Force` move also collapses same-stem sidecars arriving from
  different folders. The ICP check matched identity by NEAREST POSITION over
  those same peel poses, so a sidecar lost in the move and a camera dropped by
  the solver are indistinguishable to it.
  SETTLES IT WITHOUT RE-RUNNING A MERGE, from artifacts already on disk: read
  RealityScan's own registered count for the fused component out of the
  attempt's saved `rslog.txt`, or re-import `cluster_*_m_c0.rsalign` FROM ITS
  ORIGINAL EXPORT LOCATION (hard rule 7) into a spare instance and census it.
  3,740 means accounting artifact; 3,738 means real loss. [H2023] (2026-07-27)

- **The peel count is the sole evidence for membership, camera_count AND the
  invariant, and its instrument is never asserted.** Nothing sanitizes the image
  tree before an attempt, and `census_leftover` is recorded but never checked
  (and reads ~0 by construction, since the harvest already moved the sidecars
  out). An inflation of +N can exactly cancel a real loss of -N, yielding
  `confidence == "exact"`, `lost == 0`, and a FALSE ACCEPT whose manifest names
  basenames the component does not contain. [H2023] (2026-07-27)

- **DEFECT IN TONIGHT'S OWN NEIGHBOUR-SCOPING: it re-runs identical subsets and
  is quadratic. FIXED 2026-07-27 before session end.** `exhausted.clear()` after a fusion is
  unconditional, so every previously exhausted target is retried even when its
  neighbour set did not change; and a symmetric pair costs SIX attempts rather
  than three, because target A yields subset {A,B} and then target B yields the
  identical subset. Fix: memoise attempted `frozenset(subset_keys)` and skip
  repeats; on a fusion drop from `exhausted` only the targets that border the new
  component. [H2024] (2026-07-27)

- **DEFECT IN TONIGHT'S OWN SCALE GATE: it blocks exactly the components the
  ladder produced. FIXED 2026-07-27 before session end.** `final_components` never carries an
  `inputs` key, so `apply_scale_gate` falls back to the synthetic fused
  component key, finds no scale record and returns `unmeasured` — which blocks.
  Any merged component is therefore refused a model regardless of its real
  scale. Fix: carry the attributed input keys onto `final_components`, or measure
  the fused component directly. [H2024] (2026-07-27)

- **Two smaller confirmed defects.** (a) A TRUNCATED peel is indistinguishable
  from a complete one: the reader breaks on the first missing or empty
  `identity_r<K>` while the workflow creates that directory before knowing a
  component remains, and both the lap cap and a missing export fall through to
  `exit /b 0`; `expected_peelend_<inst>.txt` is written and never read. (b) The
  bbox tie-break the module docstring promises DOES NOT EXIST — the code takes
  `subsets[0]` and poisons the whole attempt as ambiguous, which with 12
  components makes subset-sum collisions likely and discards genuine fusions.
  [H2023] (2026-07-27)

- **`sfmImagesOverlap:High` as its own ladder rung is not defensible** (owner's
  instinct, corroborated). It only widens candidate-pair search, so it can help
  only where components share content the matcher skipped. Both observed cases
  fall outside that: zero-overlap components never fuse under ANY flag
  [NA167 D1-D3], and the hull DID fuse on every rung, so matching was never the
  constraint. Replacing rung 3 with ORPHAN INCLUSION is mechanically sound —
  orphans are the only thing that can CREATE overlap where none exists, and they
  need FULL image features (component-features and overlaps give an orphan
  nothing, since it belongs to no component). NOTE `-mergeComponents` never adds
  images, so orphans require an `-align` rung, and `MergeZoneComponents.bat`
  currently has NO `-addFolder` at all — the merge scene structurally cannot
  contain an orphan today. [H2024] (2026-07-27)

- **The border margin is applied to BOTH bboxes**, so
  `DEFAULT_BORDER_MARGIN_M = 10.0` treats components up to **20 m** apart as
  bordering. Every description of this as a "10 m-expanded bbox", including
  several in this log, understates the reach by 2x. Pinned by
  `testing/test_merge_scope.py`. [H2024] (2026-07-27)

- **H2024 merge, killed at owner request after cluster_0 exhausted all three
  rungs with no acceptance.** cluster_0 was `zone_2_c0` + `zone_3_c0` +
  `zone_5_c0` (4,975 cams) — and it contained the 0.236-scale `zone_3_c0` in
  every attempt, so the run cannot tell us whether the two sound siblings would
  have fused alone. That is the concrete cost of all-at-once scoping and the
  reason neighbour scoping was implemented. cluster_1 (12 components, 3,483
  cams, 7 of them zone_1 fragments) had just begun attempt 1; worst case was
  3 x 11 = 33 attempts. Partial output preserved at
  `F:/na156_h2024/merged`; `aligned_components` untouched (16 components).
  [H2024] (2026-07-27)

- **H2024 zone component counts, for the record** (the merge did NOT create
  components — all 16 came from the aligns): zone_1 **8** comps / 2,574 cams;
  zone_2 1 / 1,415; zone_3 1 / 1,192; zone_4 **5** / 1,160; zone_5 1 / 2,368.
  Twin-drop removed `zone_1_c3` (251 cams, no unique images) leaving 15
  survivors. The fragmentation was zone_1 and zone_4, NOT zone_5. [H2024]
  (2026-07-27)

## Per-attempt `rslog.txt` snapshots are NOT reliably the attempt's own log (2026-07-27)

NOT A NEW MECHANISM. The overwrite hazard is already known and commented in
`merge_zones.py` at the auto_model loop ("RealityScan overwrites
`Temp\RealityScan.log` when the next instance starts"), learned from the
2026-07-26 hull crash. What is new is that it has demonstrably corrupted a
MERGE ATTEMPT's snapshot, and which artifact.

- **A saved `rslog.txt` can be a DIFFERENT run's log.** Discovered by reading
  `F:/na156_h2023_fresh/merge_verify/cluster_0/attempt_1_merge_georef/` at the
  start of the 2026-07-27 review session: its `cluster.complist` names the two
  H2023 components `zone_1_c0` + `zone_1_c1`, and its identity harvest is
  unambiguously H2023 (`identity_r0` 3,737 files, `r1` 3,026, `r2` 714) — but
  the `rslog.txt` filed beside them records `importComponent` of ELEVEN H2024
  components (`zone_1_c0/c1/c2/c4/c5/c6/c7` + `zone_4_c0..c3`). The reciprocal
  case is in the same run: `F:/na156_h2024/merged/cluster_0/attempt_3_align_
  rematch_high_overlap/rslog.txt` contains NO `importComponent` line at all.
  MECHANISM (strongly indicated by timestamps, not directly instrumented):
  `snapshot_rs_log` copies RealityScan's global per-launch log AFTER the
  workflow returns, and two merge drivers overlapped — H2024 `cluster_0`
  attempt_3 ran 05:58:54–06:17:46 while the H2023 `merge_verify` complist was
  written at 06:14:11. RealityScan truncates that log at each launch, so the
  saved file is a SPLICE: `merge_verify`'s process wrote boot+imports, the
  H2024 `cluster_1` process launched at 06:17:47 and truncated the file, then
  `merge_verify` kept appending its saves and peel exports into it. Head and
  tail of one `rslog.txt` therefore belong to different runs.
  CONSEQUENCE: the first half of the open
  "settle the 2 missing cameras from artifacts on disk" plan — read
  RealityScan's own registered count out of the attempt's `rslog.txt` — is
  NOT trustworthy on these artifacts. Re-importing `cluster_*_m_c0.rsalign`
  from its original export location and censusing it remains valid.
  A snapshot must be validated against a run-unique token (the attempt's own
  complist paths) before any number is read out of it. [H2023][H2024]
  (2026-07-27) ESTABLISHED

- **The H2023 hull merge scene KEPT its source components alongside the fused
  one.** Same artifact: the peel harvest of the 2-input merge (3,026 + 714 =
  3,740) yielded THREE components — 3,737 / 3,026 / 714 — so
  `-mergeComponents` added a fused component without consuming its inputs.
  That is why `attribute_result` found exact subset sums for the two originals
  and none for 3,737, reported `fused: false`, and rejected. It also means the
  "-2 vs -3 varies by mechanism" evidence for a real solver drop is weaker than
  recorded: 3,737 here is the fused component's own size, measured while both
  parents were still in the scene. Still does not settle real-loss vs
  harvest-artifact — the re-import census does. [H2023] (2026-07-27) ESTABLISHED

## The peel harvest cannot cross a directory junction (2026-07-27)

- **PowerShell 5.1 `Get-ChildItem -Recurse` does NOT descend into junction
  CHILDREN, and the peel harvest is built on it.** Measured directly on the
  H2024 v2 run: `F:/na156_h2024_v2/batched_images_by_zone` (a real directory
  holding five per-zone junctions to the shared tree) returned **0** `.xmp`
  files under `-Recurse`; the same tree through its real path returned
  **9,835**. Consequence: all five `identity_r<K>` directories of every merge
  attempt were created and left EMPTY, `peel_counts_from` returned `[]`,
  `attribute_result` got nothing to attribute, and all 15 attempts recorded
  `attribution: ambiguous, adopted_count: 0, camera_delta: null` — the exact
  no-reason rejection shape already logged for H2023. 155 minutes of correct
  GPU work was discarded by a blind instrument. [H2024] (2026-07-27) ESTABLISHED

- **The ALIGN harvest survived the same layout; only the MERGE harvest died.**
  AlignZone.bat is handed the zone folder itself — the junction IS the
  enumeration root, and PowerShell resolves a junction it is pointed at
  directly — so every v2 align manifest is complete (members == camera_count,
  bbox present, 14/14 components). MergeZoneComponents.bat is handed the
  PARENT of the zone folders, so the junctions are children and are skipped.
  Same tree, same tool, opposite outcome depending on where enumeration
  starts. Python's `os.walk` crosses junctions in both cases, which is why
  `ensure_calibration_sidecars` reported correct coverage throughout and gave
  no warning. [H2024] (2026-07-27) ESTABLISHED

- **SUPERSEDED AS A CAUSE (2026-07-27, same day).** The junction fact above is
  TRUE and reproducible, but it is NOT why the peel was empty. The merge was
  re-run with the REAL image tree (`assert_harvestable` verified no
  reparse-point children) and produced the IDENTICAL result: `peel=[]` on all
  18 attempts (cluster_0 x3, cluster_1 x15), all `identity_r<K>` empty.
  NOTE the re-run only cleared the READ side: the v2 components were still
  exported from junction paths, so the merged scene's images still resolved
  through the junction and the WRITE side was never tested. 157 more minutes
  spent on a
  mechanism I confirmed but never linked to the symptom. The junction entry
  stays as a real Windows trap; it is not the explanation. [H2024]
  (2026-07-27) SUPERSEDED

- **MEASURED, the actual failure: `exportXMPForSelectedComponent` completes in
  a merge scene and writes NOTHING.** In `merged2` attempt 1 the log shows
  `exportXMPForSelectedComponent` -> "Exporting Registration completed in
  8.758 seconds", yet a sweep of the whole of `F:` found **zero** `.xmp`
  written after the run began, and the image tree holds 9,835 sidecars of
  which 0 carry `xcr:Position` - the exact string the harvest filters on. So
  the harvest is not failing to FIND pose sidecars; none are ever created.
  Ruled out by measurement: the merge scene DOES contain images
  (`Added 1407 images` / `1217` / `2241`), so "an imported component carries no
  images" is not the reason. [H2024] (2026-07-27) ESTABLISHED

- **The ALIGN harvest, by contrast, is exactly correct** - which is what made
  the merge failure invisible for so long. zone_1's laps are
  2619/985/593/248/133/64/0, whose successive differences are
  1634/392/345/115/69/64 - reproducing all six component sizes to the camera.
  Pose sidecars exist during an align because the align itself wrote them;
  the peel then moves every one of them out, leaving the tree pose-free.
  A later merge therefore starts with nothing to harvest. [H2024]
  (2026-07-27) ESTABLISHED

- **RESOLVED BY PROBE: the cause is the JUNCTION, on the WRITE side.** Four
  BASELINE components (real image paths) were merged through the unchanged
  workflow with the same image tree, same harvest root, and the same 9,835
  restored calibration sidecars in place. Result: `identity_r0` 267 files
  (= 116+94+57, the exact camera count), ordinal-named `00000.xmp`..., all
  pose-bearing; `r1` 116, `r2` 94, `r3` 57, `r4` 0; attribution EXACT;
  `cluster_0: fused 3 -> 1` ACCEPTED; assembly built. So the entire
  export -> harvest -> attribute -> accept chain is sound. The ONLY difference
  from the failed v2 runs is that v2's components were exported by aligns
  rooted at a junction path, baking `F:\na156_h2024_v2\batched_images_by_zone\
  zone_N\...` into every `.rsalign`; RealityScan writes no XMP sidecars when
  the scene's images resolve through a reparse point, and reports success.
  ELIMINATED by the same probe: the calibration-sidecar restoration is NOT the
  cause. NOTE the junction was never necessary - `--r_input` and `--output_dir`
  are independent, so aligning FROM the real tree INTO a separate output
  protects a baseline just as well. [H2024] (2026-07-27) ESTABLISHED

- **FIX VERIFIED: de-junctioning the v2 image tree restores the whole chain.**
  The five per-zone junctions were replaced with real directories - `.jpg`
  HARDLINKED (9,835 files, 35.8 GB, same volume, 0.05 GB actual cost), `.xmp`
  and flight logs COPIED (deliberately not hardlinked: a shared inode would let
  a v2 write corrupt the baseline tree's sidecar). Recursive enumeration through
  the v2 path went 0 -> 9,835 sidecars, and `fsutil hardlink list` confirms one
  inode per image. A confirmation merge over three UNCHANGED v2 components
  (zone_1 c1+c4+c5, 525 cams) then produced peel [525, 392, 69, 64] - exact
  camera count, exact subset sums - and `fused 3 -> 1` ACCEPTED. No re-align
  was needed; the v2 components were never the problem, only the paths baked
  into them. [H2024] (2026-07-28) ESTABLISHED

- **THE HULL DOES FUSE. It is the ACCEPTANCE ARITHMETIC that rejects it.**
  With the instrument finally working, cluster_0 (zone_2 1,407 + zone_3 1,217 +
  zone_5 2,241 = 4,865) produced peel [4860, 2241, 1407, 1217] on rung 1 and
  [4851, 2241, 1407, 1217, 5] on rungs 2-3. So RealityScan fused **4,860 of
  4,865 cameras into one component** every time. It was rejected because 4,860
  is not an exact subset sum of {2241, 1407, 1217} (= 4,865): `attribute_result`
  returned `ambiguous`, no adopted entry had >= 2 inputs, so `fused` evaluated
  False and `accept` never fired. The three parents each attributed to
  themselves exactly, which is why the attempt still recorded `adopted=3,
  delta=0` - a rejection that looks like a clean no-op in the report.
  This is precisely the defect the 2026-07-27 merge review recorded and which
  was never fixed: "`fused` is inferred from the same arithmetic that fails on
  a lossy fusion, so a fusion is only VISIBLE when its count is an exact
  input-subset sum." A 5-camera loss out of 4,865 (0.10%) is enough to hide it.
  CONTRAST cluster_1, where both fusions were exact and both were accepted:
  attempt 1 peel [1767, 1634, 69, 64] (1634+69+64 = 1767) and attempt 5 peel
  [1456, 576, 358, 345, 177] (576+358+345+177 = 1456). Exact fuses, lossy does
  not. FIX REQUIRED: a signed bounded-loss tolerance inside `attribute_result`
  (HANDOFF loose end #3 - "a bounded-loss flag is INERT without that"). This is
  an ACCEPTANCE-SEMANTICS change on a deliverable and needs an owner decision,
  not a silent default. [H2024] (2026-07-28) ESTABLISHED

- **OBSERVATION, not yet explained: attempts that re-import a previously fused
  component harvest NOTHING.** cluster_1 attempts 2-4, whose scenes contained
  `cluster_1_m_c0.rsalign` from attempt 1, all recorded `identity_r0: 0`, while
  attempts 1 and 5 - neither of which contained a previously fused export -
  harvested normally. Consistent with B10's rule that identity is only
  harvestable from the original aligning scene, but not established. Do not
  build on this without a probe. [H2024] (2026-07-28) OPEN

- **`MergeZoneComponents.bat` refuses to ASSEMBLE a single component.** The
  `component_count LSS 2` guard at lines 80-83 is applied to every mode,
  including `assemble`, where one component is a perfectly valid deliverable
  (import, georeference, save). The confirmation merge fused 3 -> 1, so the
  assembly stage aborted with `ERROR: need at least 2 components, found 1` and
  merge_zones.py exited 1 AFTER a completely successful ladder. Latent for a
  multi-cluster run (N clusters yield >= N final components, so 2 clusters can
  never trip it) but it means a fully-converged single-feature dive cannot
  produce its assembly project. Fix: exempt assemble mode from the >= 2 check.
  APPLIED 2026-07-28: assemble mode now requires >= 1, every other mode still
  requires >= 2. Verified three ways via `cmd /c` with nothing else running -
  1 component + assemble proceeds past validation and boots; 1 + merge exits 1
  with "need at least 2 components to merge, found 1"; 0 + assemble exits 1.
  Both reject paths return 1, not 0, because they use the existing top-level
  `goto :argfail` rather than an `exit /b` inside a parenthesised block (the
  cmd trap in section 8). File re-verified pure CRLF (342 CRLF, 0 bare LF), and
  every .bat/.vbs under RS_CLI re-checked. [H2024] (2026-07-28) ESTABLISHED

## H2024 v2 deliverable + the model-naming collision (2026-07-28)

- **FINAL H2024 DELIVERABLE: `merged5`, 68.3 min, exit 0.**
  `F:/na156_h2024_v2/merged5/assembly/H2024_V2_Assembly.rsproj` - TWO
  components, 8,475 cameras, georeferenced, uniquely named and therefore
  model-ready. Dated copy:
  `F:/na156_h2024_v2/RC_projects/NA156_H2024_V2_merged_20260728.rsproj`.
  | component | cameras | origin |
  |---|---|---|
  | `cluster_0_a2_c0` | 4,860 | the HULL - all three of zone_2+zone_3+zone_5 |
  | `cluster_1_a3_c0` | 3,615 | all eight zone_1+zone_4 fragments, zero loss |
  The ladder behaved exactly as designed. cluster_0 rung 1 (merge_georef)
  peeled [4854, 2241, 1407, 1217, 5] - an 11-camera loss INSIDE the 12-camera
  budget, but the stray 5-camera fragment made attribution `ambiguous`, so it
  was rejected on the attribution term rather than the loss term; rung 2
  (align_rematch) peeled [4860, 2241, 1407, 1217], `exact`, 5-camera loss,
  ACCEPTED. cluster_1 consolidated progressively across three accepted
  fusions - 3->1 (1,767), 5->1 (3,039), 2->1 (3,615) - every one exact with
  ZERO loss. Half the wall-clock of merged4 (68 vs 122 min) because an
  accepted rung short-circuits the rest of the ladder. [H2024] (2026-07-28)
  ESTABLISHED

- **SUPERSEDED by merged5: `merged4`, 121.8 min, exit 0.** Kept only as the
  record of the naming collision below; do NOT model from it.
  `F:/na156_h2024_v2/merged4/assembly/H2024_V2_Assembly.rsproj` holds FOUR
  components totalling 8,474 cameras - cluster_0 fused all three of its inputs
  into **one 4,859-camera component (the hull)** with a 6-camera loss inside
  the 12-camera budget; cluster_1 yielded `cluster_1_a1_c0` (1,767, fused),
  `cluster_1_a5_c0` (1,456, fused) and `zone_1_c1` (392, unfused). All 14 input
  components PASS the 0.90-1.10 scale band. This is the shape the owner
  predicted: one very large component plus several smaller surveyed parts.
  [H2024] (2026-07-28) ESTABLISHED

- **MODEL-HANDLING BUG: two accepted fusions in one cluster export files with
  the SAME stem, so the assembly holds two identically-named components.**
  `-importComponent X.rsalign` names the in-scene component `X`, and
  `GenerateModel.bat` selects its target with `-selectComponent <name>`.
  merged4's assembly imported
  `cluster_1/attempt_1_merge_georef/cluster_1_m_c0.rsalign` AND
  `cluster_1/attempt_5_merge_georef/cluster_1_m_c0.rsalign` - different
  directories, identical stem - so the saved project contains two components
  called `cluster_1_m_c0`. Camera counts are correct (4859+392+1767+1456 =
  8474); the defect is purely identity, and it would send a per-component model
  run at whichever component RealityScan resolves first, silently. FIX APPLIED
  AND VERIFIED: the workflow is now handed `<tag>_a<attempt>` as its export
  name, so the file stem, the manifest `component`, and the in-scene name are
  one unique string. merged5's assembly imports
  `cluster_0_a2_c0.rsalign` and `cluster_1_a3_c0.rsalign` - distinct stems, and
  its rslog confirms both loaded with the expected counts (4,860 and 3,615).
  merged4 predates the fix and is NOT model-ready. [H2024]
  (2026-07-28) ESTABLISHED

- **`-selectModel` matches on EXACT name - the prefix hazard is not real.**
  Checked because `GenerateModel.bat`'s cleanup loop deletes `<tag>_HighPoly`
  while `<tag>_HighPoly_Textured` must survive. en-US `allcommands.htm`:
  "selectModel modelName - Select a model with the specified name", and the
  H2023 PD6 deliverable confirms it empirically: its cleanup ran and all three
  kept models (`_HighPoly_Raw`, `_HighPoly_Textured`, `_Simplified_Textured`)
  survived. No change needed. [H2023] (2026-07-28) ESTABLISHED

- **Deprecation sweep (2026-07-28).** `process_h2023.py` is already gone.
  DEAD, zero callers anywhere in the repo: `scan_pose_sidecars`,
  `members_from_sidecars`, `_resolve_image_basename` and `_POSE_TAG` in
  `modules/component_manifest.py` (~80 lines) - the old HANDOFF nit said
  "verify before deleting"; now verified, left in place for an owner call.
  Zero code references but documented and intentional: `SequentialAlignGrow.bat`,
  `AlignImageList.bat`. Deprecated but still used by `run_zone9_tests.py`:
  `AlignImagesFromFolder.bat`. NOT dead, a documented compatibility shim:
  `testing/scale_oracle.py`. The two `RealityCapture` hits in code are
  historical comments, allowed by the naming rule. (2026-07-28)

- **`-mergeComponents` retains its input components alongside the fused one -
  now confirmed on a controlled case.** The probe's peel was
  [267, 116, 94, 57]: the fused component PLUS all three unconsumed parents.
  Attribution handles this correctly when peel data exists (267 is the exact
  subset sum of the three, so confidence is `exact` and the fusion is
  adopted). This independently reproduces the H2023 hull observation recorded
  above. [H2024] (2026-07-27) ESTABLISHED

- **SUPERSEDED HYPOTHESIS (resolved same day by the probe above).**
  `-exportXMPForSelectedComponent` may only cover images from the LAST
  IN-SESSION ALIGNMENT (the documented `-exportXMP` limitation), so a
  `-mergeComponents` scene exports zero and reports success. If true, it also
  means the H2023 `merge_verify` peel (3,737 / 3,026 / 714) was moving STALE
  pose sidecars left in the tree by an earlier operation, not that attempt's
  output - which would make every merge-mode peel count in this log an
  artifact. DECISIVE CHEAP TEST: import two small v2 components (zone_1_c4 69
  cams + zone_1_c5 64 cams), `-mergeComponents`, then
  `-exportXMPForSelectedComponent`, and watch the image tree for any file
  containing `xcr:Position`. ~10 minutes, no full merge required. [H2024]
  (2026-07-27) OPEN

- **The merge DID fuse; only the accounting failed.** `cluster_0`
  attempt 1 imported exactly the three components named in its own
  `cluster.complist` (zone_2_c0 + zone_3_c0 + zone_5_c0) and its `rslog.txt`
  records `-mergeComponents` followed by **"Finalizing 1 component"**. The log
  was validated against the complist first, per the run-unique-token rule
  above; nothing ran concurrently this time. So a three-way fusion of 4,865
  cameras was performed and then reported as three "unfused input"
  components. MITIGATION: pass merge_zones.py the REAL images root, never a
  path whose children are reparse points. STRUCTURAL FIX WORTH DOING: the
  harvest should assert it moved a non-zero number of sidecars when the
  component it just exported is non-empty — an empty peel is currently
  indistinguishable from a legitimately empty scene. [H2024]
  (2026-07-27) ESTABLISHED

- **H2024 v2 re-align closed the metric-scale crisis.** `zone_3_c0` went from
  **0.236 FAIL** to **0.969 PASS** (IQR 0.147); the other two baseline
  failures also cleared (`zone_1_c2` 1.127 -> 1.081, `zone_4_c2` 1.196 ->
  0.919). All 14 v2 components now pass the 0.90-1.10 band. CAUSE NOT
  ESTABLISHED — the re-align changed several things at once (restored
  calibration sidecars, fresh solve, the 61723e4 code changes), and align
  fragmentation is already on record as nondeterministic. Do not attribute it
  to any single change without a controlled cell. [H2024] (2026-07-27)
  ESTABLISHED

## merged5 cluster_1 was a rigid glue, and the gate that allowed it (2026-07-28)

- **merged5's `cluster_1_a3_c0` (3,615 cams) is NOT a content fusion - it
  packed eight disjoint objects into one container.** Owner challenge,
  verified by forensics over the manifests: of cluster_1's 28 component
  pairs, exactly ONE (`zone_1_c2` <-> `zone_4_c1`, 343 shared basenames)
  shares any imagery; the other seven components relate only through
  TRANSITIVE bbox adjacency under the 10 m-margin border gate (effective
  reach 20 m, both boxes expanded). All three accepted cluster_1 attempts
  were `merge_georef` (`-mergeComponents` + `sfmMergeGeoreferencedComponents`)
  and RealityScan's own log reported 'Finalizing 3', then '7', then '8'
  components while the arithmetic scored each attempt as an exact-sum
  fusion with zero loss. CONTRAST the hull: its accepted rung was `align`,
  'Finalizing 1', and it LOST 5 cameras - real joint solving. Zero loss on a
  zero-shared-imagery "fusion" is the signature of co-location, not
  registration. GenerateModel's keep-largest-connected-component step would
  have deleted every smaller object from a model of that container.
  CAVEAT: the exact semantics of 'Finalizing N' are NOT established -
  recorded per attempt now (`rs_finalizing`), probe queued. [H2024]
  (2026-07-28) ESTABLISHED

- **The gate rework (owner uniqueness criterion): components belong in one
  merge scene ONLY when they share imagery or their bboxes TRULY overlap.**
  `pair_gate=overlap` is the default; `border` retains the old 10 m-margin
  adjacency for comparison. Additionally, `-mergeComponents` rungs are only
  admitted when the SHARED-IMAGE graph spans the whole subset (merge fuses
  through camera identity; align fuses through content) - any-pair sharing is
  not enough, since a merge rung glues every component in the scene
  indiscriminately. Empty-peel invariant added: an empty peel beside a
  non-empty export now ABORTS the run as an instrument failure instead of
  being scored as "nothing fused" (the shape that silently discarded 5h12m
  across two junction-blinded runs). (2026-07-28)

- **Non-hull re-run under the new gate: both fusions were content-driven and
  exact.** The 8 components partition into 5 clusters (vs ONE under the
  border gate). `{zone_1_c2, zone_4_c1, zone_4_c2}` does not span on shared
  imagery, so it ran align-only - and align fused ALL THREE: peel
  [880, 358, 345, 177], 880 = 345+358+177 exact, zero loss. So `zone_4_c2`
  genuinely belongs to that object (content proved what the bbox suggested).
  `{zone_1_c4, zone_1_c5}` (zero shared imagery, true bbox overlap) also
  fused by align: peel [133, 69, 64], exact. Projected finals: 5 non-hull +
  hull = 6 total against the owner's nominal 7 - the difference is exactly
  z4_c2 fusing INTO the c2/z4_c1 object rather than standing alone. [H2024]
  (2026-07-28) ESTABLISHED

## Cross-session incident + exploration-session integration (2026-07-28)

- **`RS_INSTANCE` was never an input.** `realityscan_cli.py` resolved the
  instance from constructor arg -> rs_settings.json -> default and only ever
  WROTE the env var for the .bat layer, so every driver exporting
  `RS_INSTANCE` was decorative - it worked because rs_settings said RS1. An
  exploration session running the overlap probe FROM this checkout believed
  it was on RS2 and ran on RS1 (its own audit #19: it could have -quit a live
  production instance; no harm only because the machine was verified clear).
  FIX APPLIED: env var now resolves between constructor arg and settings.
  The same session overwrote rs_settings.json's `merge` section with probe
  paths (`G:\zone_probe\...`); restored from this session's known values.
  (2026-07-28) ESTABLISHED

- **The overlap-donation defect is CONFIRMED against the artifact, and fixed.**
  Verified directly from the on-disk per-zone flight logs (not the audit's
  log inversion): H2023 zone_1 holds 4,540 of 4,598 unique images - 98.7% of
  the dive - spanning ALL THREE co-visibility blocks, with 756 images
  structurally unable to match its own main block; 918 duplicate copies
  (20.0%) across the tree. Cause: `np.argsort(score)[:overlap_size]` sized
  by the RECEIVER with no cap against the donor pool. FIX: symmetric cap
  (at most overlap% of receiver AND of donor pool) plus an optional absolute
  distance ceiling (`batch_overlap_max_distance_m`, default 0 = off - the
  band width is deliberately unsettled pending the overlap probe). 5 tests
  drive the real zoning code on synthetic strips. [H2023] (2026-07-28)
  ESTABLISHED

- **The batcher's "~3 h zone computation" was a blocked plt.show() the whole
  time.** Actual compute measured at 1.35 s for 8,197 points. The isatty()
  gate added earlier did not close it because isatty() LIES under hidden
  consoles (this repo's own Windows-traps list) - which is why a "gated" run
  still spent 2 h 53 min between its two figure saves, and why the 28.9-min
  run looked like an unexplained outlier. plt.show() is now opt-in only
  (`RS_SHOW_PLOTS=1`); the figures were always saved as PNGs regardless.
  SUPERSEDES HANDOFF loose end #10's "worth hunting" framing - hunted, found,
  fixed. (2026-07-28) ESTABLISHED

- **Audit fixes applied from the exploration session's 27-finding audit**
  (report: `F:/_copylogs/code_audit_2026-07-28.md`; claims re-verified here
  before changing anything): #5 `--scale_min/--scale_max` never reached the
  verdict - every band was baked at 0.90/1.10 while EVALUATION_READY printed
  the operator's values (fixed; test pins the wiring end to end). #6 geoall
  pitch ACCURACY was a stale prefix chain contradicting MOUNTS - WCA got 10
  vs 15, Zeuss 10 vs 30, and PD-0 shows over-tight orientation accuracy
  fragments the solve (fixed; parity test extended). #7 a zone that RAISED
  vanished from the align tally - neither Succeeded nor Failed, so nine
  raising zones out of ten still reported exit 0 (fixed: a raise records a
  failed zone). #4 GenerateModel `:try_delete_model` used a single short
  wait, so a no-op select on a missing intermediate left the FINAL TEXTURED
  MODEL selected for the delete that followed; both its error moves also
  launder ALL codes and 12 iterations overwrote the evidence file (fixed:
  double-wait shape, save BEFORE the cleanup loop, per-model evidence names;
  whitelist redesign queued). (2026-07-28)

- **The scale gate cannot measure FUSED components - by construction - and it
  correctly blocked them, including the hull.** In the final-assembly run all
  three fused components came back UNMEASURED while every unfused original
  passed: a merge-scene `-exportXMPForSelectedComponent` writes ORDINAL
  sidecars (B10) with no image identity, so the stem-pairing oracle has
  nothing to join on. The gate did its job - silence is not evidence - but it
  would have left the hull unmodelled. [H2024] (2026-07-28) ESTABLISHED

- **Correspondence-free scale measurement for fused components (quantile
  ratio), validated both directions.** Under a similarity transform, sorted
  distances-from-centroid of the same camera multiset correspond
  rank-for-rank, so ratios of matching quantiles (5th-95th, trimmed) between
  the solved cloud (ordinal pose sidecars in the fused component's
  identity_r0 - LOCAL frame, irrelevant since distance ratios are
  rigid-invariant) and the nav cloud give median + IQR without any pairing.
  TWO TRAPS hit on the way: (a) Position is an ELEMENT
  (`<xcr:Position>x y z</xcr:Position>`) in current exports, attribute form
  only in older ones; (b) a fused manifest's `images` is the unique-basename
  UNION, but the scene holds one camera per input OCCURRENCE (880 cameras
  over 537 unique basenames on cluster_1), so the nav multiset must be the
  CONCATENATION of the attributed input manifests' members. VALIDATION:
  known-good zone_1_c1 measures 1.045 vs the stem oracle's 1.023 (same
  verdict, 2.2%); the hull's real clouds shrunk by 0.236 FAIL at 0.235.
  ALIGN-scene identity_rK dirs are CUMULATIVE (rK = laps K..end), unlike
  merge scenes where rK is component K alone - component K's own sidecars
  are the stem difference rK minus rK+1. [H2024] (2026-07-28) ESTABLISHED

- **THE FUSED DELIVERABLES ARE METRICALLY SOUND - measured directly, not
  inherited.** `cluster_0_a2_c0` (the hull, 4,860 cams) scale **0.997**,
  IQR width 0.014; `cluster_1_a1_c0` (880) **1.000**, IQR 0.029;
  `cluster_4_a1_c0` (133) **0.980**, IQR 0.077. This closes the
  EVALUATION_READY caveat that the assembled deliverable's scale was
  unmeasured - for fused components it now is. [H2024] (2026-07-28)
  ESTABLISHED

## Final review + owner notes applied (2026-07-29)

- **SUPERSEDED detail in the audit-#4 entry below/above:** the
  "save BEFORE the cleanup loop" belt-and-braces WAS applied, then REMOVED
  the same day at the owner's direction - saving with ~15 models live is the
  inordinate-save case (measured: zone_1_c0's saves cost ~81 GB with it).
  The deletion-race protection is the double-wait in `:try_delete_model`
  alone, which is sufficient. Dated RC_projects copies are DEFERRED to one
  end-of-project `SaveProjectCopy.bat` call; model workflows run with
  RS_PROJECTS_DIR unset. (2026-07-29)

- **Final adversarial review (4 dimensions, 24 agents): 20 confirmed, 0
  refuted; all applied.** Highest-value: (a) the new
  `batch_overlap_max_distance_m` parameter was MISSING from the reuse-guard
  fingerprint - a re-run with a new ceiling would have silently reused zones
  built without one, the exact fail-open the guard closes; (b) two of this
  session's own regression tests re-implemented driver logic instead of
  driving it (the audit-#17 shape recurring) - the accept decision, loss
  budget, export naming and mechanism filter are now pure functions
  (`acceptance_verdict`, `loss_budget`, `fused_export_name`,
  `effective_ladder_for`) called by merge_cluster and exercised directly;
  (c) drivers left ask()-backed merge options unpinned - on a console the
  child's input() blocked forever on an invisible prompt, detached it
  silently inherited another session's rs_settings values; every option is
  now pinned and every driver subprocess gets stdin=DEVNULL; (d) the
  phase-skip in run_h2024_final treated a PARTIAL merge_report.json as
  terminal (merge_zones flushes per cluster) - now requires the assembly
  section; (e) assemble_only routed inputs through twin-drop, contradicting
  carried-as-is - it now bypasses partitioning entirely; (f) the harvest
  guard only checked TOP-LEVEL children for reparse points - now recursive;
  (g) ExportDeliverables dropped delayed expansion ('!'-path corruption),
  sweeps Model 1-9, and names evidence files per model. (2026-07-29)

## Export probe facts (2026-07-29)

- **`<comp>_HighPoly_Raw` does NOT survive the model recipe - the docstring's
  "models kept" list has been wrong since 2026-07-23.** Probed on the real
  assembly: `-selectModel cluster_4_a1_c0_HighPoly_Raw` -> err:5601 'not
  found'. Mechanism: step [2/8] RENAMES the selected model to `_Cleanup1`
  when the marginal filter fires, so the raw NAME leaves the project; the
  same rename chain is why `-selectModel <tag>_HighPoly` missed in every
  component's cleanup loop (it had become `_HighPoly_Textured` at [6/8]).
  The models that actually persist per component: `_HighPoly_Textured`,
  `_Simplified_Textured`, plus one default-named residual. QUEUED recipe fix
  if raw retention is wanted: duplicate the model after [1/8]
  (`-duplicateSelectedModel` exists) before the filter chain touches it.
  Export consequence: the dense PLY falls back to `_HighPoly_Textured`, the
  densest model guaranteed to exist. [H2024] (2026-07-29) ESTABLISHED

- **A load can fail on a stale `<name>.rsproj.new`** - an interrupted GUI
  save leaves the temp beside the project and the next headless `-load`
  reports warning-class 0x82000017 while still completing; the error channel
  then aborts the workflow. Setting the temp aside (rename, reversible)
  cleans the load. The owner's 12:44 GUI save was the source; the main
  .rsproj (08:01, post-models) was intact. [H2024] (2026-07-29) ESTABLISHED

- **By-parts exports verified on the real assembly**: OBJ 4 parts + per-part
  MTL + u1_v1 textures + .rsInfo (exactly Nira's expected layout), FBX 4
  parts + textures; ~35-38 s each on the 133-cam component. Exactly ONE
  default-named residual existed in the whole six-component project
  ('Model 1' - swept and saved), not one per component as hypothesised.
  [H2024] (2026-07-29) ESTABLISHED

## H2024 MODELS COMPLETE (2026-07-29)

- **All six components modelled from one assembly project.** Times and
  directly-measured scale:

  | component | cams | scale | model time |
  |---|---:|---:|---:|
  | `cluster_0_a2_c0` (HULL) | 4,860 | 0.997 | 338.3 min |
  | `zone_1_c0` | 1,634 | 1.084 | 249.3 min |
  | `cluster_1_a1_c0` | 880 | 1.000 | 122.8 min |
  | `zone_4_c0` | 576 | 0.947 | 106.1 min |
  | `zone_1_c1` | 392 | 1.023 | 97.4 min |
  | `cluster_4_a1_c0` | 133 | 0.980 | 40.1 min |

  Three kept models each (`_HighPoly_Raw`, `_HighPoly_Textured`,
  `_Simplified_Textured`). Project:
  `F:/na156_h2024_v2/final_assembly/assembly/H2024_Final_Assembly.rsproj`;
  dated copy `RC_projects/NA156_H2024_V2_merged_20260729` (95.2 GB).
  [H2024] (2026-07-29) ESTABLISHED

- **The ~5,000-camera model envelope, measured: it does NOT plateau.** Peak
  commit / minimum available RAM by component size: 133 -> 96.2 GB / 25.9 GB;
  392 -> 107.1 / 3.5; 576 -> 116.8 / 3.0; 880 -> 138.6 / 2.8; 1,634 -> 139.9 /
  2.0; **4,860 -> 148.7 / 0.9**. The apparent plateau at ~140 GB across 392-1,634
  cameras was an artifact of that range; the hull pushed ~9 GB past it and ran
  with under a gigabyte of headroom on a 93.6 GB box. It completed, but a
  materially larger component on this hardware should be treated as at risk,
  not as covered by the plateau. Cache on E: absorbed the working set
  (6.1 TB free throughout). [H2024] (2026-07-29) ESTABLISHED

- **Deferring the dated copy is worth ~10x on save cost.** `GenerateModel.bat`
  takes TWO `RC_projects` copies per component, one of them MID-RECIPE with
  every intermediate model still live. With them enabled, `zone_1_c0`'s saves
  consumed ~81 GB of F:. With `RS_PROJECTS_DIR` left unset (which skips both,
  no .bat change needed) `cluster_4_a1_c0` cost 6.8 GB end to end, and ONE
  dated copy of the finished six-component project took 13.1 min / 95.2 GB via
  the new `SaveProjectCopy.bat`. Owner-directed 2026-07-28; the per-component
  scene save must stay, since the workflow loads/models/quits per component.
  [H2024] (2026-07-29) ESTABLISHED

- **Benign, recurring: `-selectModel <tag>_HighPoly` reports result code
  2147942487 in every component's cleanup loop.** Whitelisted empty-selection
  code, evidence filed per model as
  `expected_select_RS1_<component>_HighPoly.txt`, the delete is skipped and the
  recipe continues. Seen on all six components. Consequence is a leftover
  `_HighPoly` intermediate, cosmetic. Cause not investigated - it is the one
  intermediate that is both renamed and immediately re-textured, so the name
  may be consumed by the texture step. [H2024] (2026-07-29) OPEN

- **Queued RealityScan probes - NOT run; no live probing until modeling
  completes (owner instruction), and each needs an instance name it controls
  (possible now that RS_INSTANCE is real):** (a) 'Finalizing N component'
  semantics - two tiny imports, one merge, count; (b) census of merged5's
  `cluster_1_a3_c0.rsalign` by re-import from its original location -
  container of 8 or single component; (c) rigid-glue reproduction - two
  zero-shared components + merge_georef, expect glue, pins the mechanism;
  (d) the overlap probe's unfinished arms
  (`F:/_copylogs/zoning_scripts/run_overlap_probe.py --arms arm_r2,arm_r6`) -
  the 6 m band is NOT settled, only its control arm ran; (e) GenerateModel
  error-whitelist redesign, needs the benign select-miss code from (a)-style
  probing. (2026-07-28)

## ON2026 model-to-final + nav prep (2026-08-04/07)

Model half of ON2026 (RH0042/RH0043 Voyis stereo, 38,948 images) driven to
final deliverables against a GUI-launched instance, plus the groundwork for
a re-run with updated nav. Source tag **[ON2026]**.

### CLI behavior

- **`*` is a valid instance argument meaning "first available instance",
  so a GUI/Epic-Launcher RealityScan with no `-setInstanceName` IS
  CLI-drivable.** Accepted by `-delegateTo`, `-waitCompleted`, `-getStatus`,
  `-pauseInstance`, `-unpauseInstance`, `-abortInstance` (local Help,
  `appbasics/allcommands.htm`). Verified against a live GUI session:
  `-getStatus RS1` -> exit 5, `-getStatus *` -> exit 0, same process.
  Ambiguous the moment two instances run, so use explicit names for
  multi-GPU and reserve `*` for attaching to one interactive session.
  [ON2026] (2026-08-04) ESTABLISHED

- **`-getStatus` prints an undocumented progress line on stdout, and it is
  the ONLY error channel for an instance the pipeline did not boot.**
  `id:0x5051 progress:11.1% runtime:575.04sec endEstimation:4579.16sec rev:93 lastError:0`
  Capture by redirecting (RealityScan is a GUI-subsystem binary and does not
  reliably attach to a parent console); both `for /f` pipe capture and file
  redirection work from cmd. An instance not booted by `startRealityScan.bat`
  never ran the ErrorWriter hook, so `errors_<instance>.txt` does not exist
  for it and the usual `:run` marker gate is blind. Operation ids observed:
  `0xffffffff` idle, `0x6` exportSelectedModel, `0x7` calculateTexture,
  `0x5035` save, `0x5051` Normal Detail reconstruction. Full table in
  `testing/NA167_SESSION_NOTES.md` Section 3. [ON2026] (2026-08-04) ESTABLISHED

- **`lastError` is a SIGNED 32-bit decimal, and it is STICKY while the
  instance is idle.** Add 2^32 to read as hex: `-2113863583` -> `0x82010061`.
  After a failed `-save`, four consecutive idle polls at `id:0xffffffff` all
  reported the dead code; it cleared the instant the retried save started.
  A gate on `lastError != 0` alone therefore blames the NEXT command for the
  PREVIOUS command's error. The stickiness itself is ESTABLISHED and
  unchanged; the GATE DESIGN described in the original version of this
  entry ("captures `rev:` before delegating and treats non-zero
  `lastError` as failure only if `rev` also advanced, rev incrementing
  once per completed operation") is **SUPERSEDED (2026-08-07 battery)**:
  rev tracks scene MUTATIONS, not operations, so a failed non-mutating
  command leaves rev unchanged and that gate continued past real
  failures. The shipped gate baselines `lastError` BEFORE delegating -
  see the battery entry below.
  [ON2026] (2026-08-04) ESTABLISHED (gate half superseded 2026-08-07)

- **`err:7185` "Provided arguments don't match any overload for command
  '<cmd>'" means a path got split on spaces, not that the command is
  wrong.** A `-save "M:\ON2026 COLMAP processing\...\x.rsproj"` issued via
  PowerShell `Start-Process -ArgumentList @(...)` (ARRAY form) failed
  instantly; the array form does not quote elements containing spaces for
  this binary, so RealityScan saw three arguments. Target directory was
  writable (write-test passed). Fix: pass `-ArgumentList` as a single STRING
  with the path explicitly quoted. Same class as the cmd/.bat splitting trap,
  arriving through PowerShell. [ON2026] (2026-08-04) ESTABLISHED

- **`startRealityScan.bat` destroys a live scene if called against one:
  line 20 issues `-newScene -deleteAutosave` whenever `-getStatus` finds an
  instance already running.** Still true on `origin/main`. Every other
  workflow script opens by calling it, including `GenerateModel.bat` and
  `ExportDeliverables.bat`, so there was no existing safe path to finish a
  mesh reconstructed interactively in the GUI. `ModelToFinal.bat` exists for
  exactly that case: it attaches via a bare `-getStatus` guard and never
  calls that script. Corollary: do NOT route it through
  `RealityScanCLI.run_batch_script`, which shuts down any running instance
  before launching. [ON2026] (2026-08-04) ESTABLISHED

- **With simplification on, the UNWRAP preset - not the texture preset -
  decides the exported model's UV layout.** The exported model is the
  simplified one and is unwrapped fresh, so a caller asking for 4 x 8192
  silently got one 16384 page from `Unwrapping_Simplified.xml`
  (`unwrapMaximalTexCount=1`, `unwrapMaxTexResolution=16384`). Equal texel
  budget, but 16k exceeds the maximum texture size many engines accept.
  Verified in the artifact after pairing the presets: four `*_diffuse.jpg`,
  each exactly 8192x8192. [ON2026] (2026-08-04) ESTABLISHED

- **The app log is not a durable record: `%LOCALAPPDATA%\Temp\RealityScan.log`
  is truncated when an instance boots.** Watched it happen mid-session - a
  log carrying every operation id and error code from a 14-hour run was
  reduced to two "Loading Project completed" lines by the next boot.
  Independently re-confirms [NA167 #16]. Copy the log immediately after any
  failure, and keep codes in `testing/NA167_SESSION_NOTES.md` Section 3.
  [ON2026] (2026-08-07) ESTABLISHED

### Nav / orientation priors

- **Every ON2026 flight-log variant carries yaw/pitch/roll accuracy of
  exactly 90.0 deg on all 38,948 rows.** Column statistics over five logs
  (`flight_log_zones.pre_rollfix.txt`, `rs_rollfix/`, `rs_zup/`,
  `roll0_backup`, current): min = median = max = 90.0 in all three
  orientation-accuracy columns, while the angle VALUES differ substantially
  (yaw medians 101/101/167/101/161; pitch 93/93/105/93/75; roll
  0/-50/2/-50/-176; the current log's altitude median is -0.505 against
  +0.54 for the four earlier ones). EXPLAINED, not accidental: the generator
  is `colmap_studio/pipeline/export_rs_flightlog.py`, `--ori-acc` default
  90.0. Do NOT extend this into "the roll-fix and Z-up experiments are
  therefore void" - that rider is refuted: the roll fix was settled by an
  independent oracle (colmap_studio C-20260803-01, fabricated roll=0.00 was
  wrong by ~93 deg), not by an alignment A/B. [ON2026] (2026-08-07) ESTABLISHED

- **OPEN / OWNER DECISION - the ON2026 pitch column has two incompatible
  readings and they disagree about where the degeneracy sits.** This entry
  records the conflict deliberately rather than picking a side.
  (a) RealityScan's own convention is staff-confirmed above (OndrejTrhan:
  "Pitch = 0, image is looking down"), i.e. 0 = nadir, 90 = horizontal,
  intrinsic Roll -> Pitch -> Yaw, YPR interpreted in NED.
  (b) The exporter that WROTE the column implements the same 0 = nadir
  scale (docstring lines 192-194) and was validated to 0.4 deg median
  against RealityScan's solved rotations on 2,260 images
  (colmap_studio C-20260803-01); it places the singularity at NEAR-VERTICAL
  and measures exposure as **1.3%** of ON2026 within 5 deg of vertical.
  (c) Measuring the same column for proximity to |pitch| = 90 instead gives
  **24.9%** (9,697/38,948 rows; median 75.34, p05 55.18, p95 107.59), and
  roll additionally wraps the branch cut, holding both -180.000 and
  +180.000.
  Same dataset, two bands. An earlier version of this entry asserted the
  24.9% reading as established on the assumption of aerospace YPR; that
  assumption is contradicted by (a). SUPERSEDED same day by the
  reconciliation below.
  RECONCILED (2026-08-07, owner question prompted the re-read): the two
  figures measure DIFFERENT degeneracies at opposite ends of the pitch
  range, and are not competing readings of one singularity.
  - **1.3% (near-vertical)** is the EXPORTER-side degeneracy: its yaw is
    "heading of the view direction" and its roll is referenced to
    horizontal, so both definitions collapse for a straight-down view.
    The exporter already mitigates it - `ypr_acc = min(180, max(ori_acc,
    MEASURED/sin_p))` widens the accuracy on exactly those rows.
  - **24.9% (near pitch 90 = horizontal)** is the candidate IMPORT-side
    degeneracy in RealityScan's OWN parameterisation: staff-confirmed
    composition is intrinsic Roll -> Pitch -> Yaw with pitch the middle
    rotation, and any such sequence is singular at middle = +/-90 - which
    in the 0-=-nadir scale is a HORIZONTAL view. This is the same
    degeneracy the [H2023] line already flags ("Port's pitch sits at
    ~88 deg, within 2 deg of the 90 deg degeneracy where roll and yaw
    axes collapse in this parameterisation"). A wall-inspecting ROV
    lives there: 24.9% of ON2026 rows within 5 deg of pitch 90.
  The import-side reading stays CONTINGENT on the unpinned Euler-order
  import settings (`ifKGrp`/`ifKmode`, established entry above) - the
  standing gate applies: pin Euler order and camera mount in
  `FlightLogParams.xml` before any further orientation cell. If the pin
  confirms the staff composition, the practical consequence is the
  mirror-image of the exporter's mitigation: orientation priors for
  near-HORIZONTAL frames deserve the 1/|cos(pitch-90)|-style widening on
  import, or simply the conservative 90-deg floor already in force.
  [ON2026] (2026-08-07) OPEN - narrowed to the Euler-order pin

- **The 0.020 position accuracy in the ON2026 logs is a constant CLI
  default, not measured per-sample sigma** (`--pos-acc` default 0.02 in
  `export_rs_flightlog.py`). Constant on all 38,948 rows across x/y/alt.
  Do NOT infer "real per-sample sigma would be an improvement": 0.02 m
  validated at 6.3 mm median prior residual and WON the accuracy matrix
  (colmap_studio C-20260730-05/09, 2,262 images: 0.02 m / 90 deg is the
  production winner; tight 10 deg orientation priors were actively worse).
  Scope matters - ON2026 priors are COLMAP-derived, the NA156 line's are
  nav-derived, and `PRIORS_DISTORTION_TEST_PLAN.md` records tight position
  priors FRAGMENTING components on that line. [ON2026] (2026-08-07) ESTABLISHED

- **`modules/flight_logs.py` cannot express a local-Euclidean frame - it
  only ever emits UTM - and the shared `FlightLogParams.xml` now carries a
  local-frame value, so one template serves two mutually exclusive campaign
  frames with no guard.** `write_flight_log_params` rewrites only
  `CoordinateSystemFlightLog` / `CoordinateSystemFlightLogType`, always as
  `+proj=utm +zone=N[ +south]` / `epsg:326xx|327xx` (byte-identical
  base -> origin/main). Provenance: `M:\ON2026 COLMAP processing\rs\FlightLogParamsLocal.xml`
  is byte-identical to `origin/main:.../Metadata/FlightLogParams.xml` - the
  hand-made local file was promoted into git in `902fcf7` (2026-08-03).
  Meanwhile `testing/ab_orientation_priors.py:115` calls
  `write_flight_log_params` on that same geocent template and converts it
  BACK to UTM. The function also leaves every accuracy-governing key
  untouched (`ifUsePosAcc`, `ifUseOriAcc`, `ifCSopt`, `ifuuInh`,
  `ifuuInhEn`); for `ifKGrp`/`ifKmode` see the established entry above.
  [ON2026] (2026-08-07) RESOLVED same day (commit 177a81a): frame
  parameter + second template + ensure_frame_match guard; the cited
  ab_orientation_priors.py now lives in archive/campaign_drivers/.
  The accuracy-governing keys remain unpinned (tracked with C1/C6).

### Defect in this session's own work

- **`ModelExportParamsObj_Metric.xml` shipped as dead config.** The metric
  (scale 1.0) OBJ export that fixed the 100x Unreal-preset scale was
  performed as a MANUAL one-off `-exportSelectedModel` invocation; the code
  path was never changed. `ModelToFinal.bat` hardcodes
  `ModelExportParamsObj.xml` (scale 100.0) for `export_format=obj` and its
  parser accepts only `obj|fbx|glb|none`, so no invocation could reach the
  metric file and the next automated obj run would reproduce the defect.
  Caught by adversarial review of the rebase, not by the run. Wired as
  `objmetric` in the follow-up commit. Lesson: a fix demonstrated by hand
  is not a fix until a code path reaches it. [ON2026] (2026-08-07) ESTABLISHED

### Live battery on the smoke scene (2026-08-07, clean slate)

- **`rev` tracks scene MUTATIONS, not operations - a failed command can
  complete without advancing it.** Probe on a freshly loaded 8-camera
  smoke scene: `-selectModel "NoSuchModel"` -> rev 11 -> 11, lastError
  -2147024809 (0x80070057 E_INVALIDARG, the known benign select-miss
  code), AND the ErrorWriter trigger logged a process completion for it.
  Refutes the earlier working assumption "rev increments once per
  completed operation" and with it the original ModelToFinal gate design:
  a genuinely failed non-mutating command was indistinguishable from a
  stale carried-over error and the workflow would have CONTINUED past it.
  Gate rebuilt same day: lastError baselined BEFORE delegating; a change
  to non-zero is a fresh failure regardless of rev; the stale-warn path
  needs the identical pre-existing code AND an unchanged rev.
  [ON2026] (2026-08-07) ESTABLISHED

- **ModelToFinal.bat verified live end-to-end in attach mode, including
  both stale-marker gate arms and the owner's new defaults.** Battery on
  the zone_9 smoke scene, own instance RS1: (4a) stale non-empty
  errors_RS1.txt + RS_TARGET==RS_INSTANCE -> first :run aborted exit 1
  (gate fires); (4b) same stale marker + attach via `*` -> gate skipped
  (foreign-marker fix), full chain ran in 143 s: texture at the 4x8k
  DEFAULT (empty preset argument), 80% simplify chain, unwrap, reproject,
  `objmetric` export - artifact .rsInfo reads `settingsScale="1 1 1"` -
  and save to RS_SAVE_PATH; verified shutdown. The sticky C5 error code
  did NOT false-abort 4b: lastError cleared when the next operation
  started, as established. [ON2026] (2026-08-07) ESTABLISHED

- **Windows trap (registry-worthy): a `start`-launched GUI child inherits
  captured stdout/stderr pipes - subprocess capture on the BOOT SCRIPT
  deadlocks even after timeout-kill.** startRealityScan.bat launches the
  instance via `start ""`; with subprocess.run(capture_output=True) the
  pipe never reaches EOF while the instance lives, and Python's
  communicate() blocks forever after the timeout kills only the .bat.
  Observed as a silent 10-minute hang with the instance idling at 0.3 GB.
  Boot invocations must run with stdout/stderr detached to files or
  DEVNULL, never pipes. [ON2026] (2026-08-07) ESTABLISHED

- **Three small CLI facts from the Euler-pin P0 probe (no-align scene,
  32 images, flight log imported).** (1) `-exportXMP` with no alignment
  in the scene is a SILENT NO-OP SUCCESS - rc 0, nothing written - the
  same do-nothing-quietly family as `-mergeComponents` with nothing to
  merge [NA167 #23]. (2) `-exportXMPForSelectedComponent` with no
  component sets lastError -2147467259 (0x80004005 E_FAIL) - new error-
  table entry: "no component to export". (3) `rev` increments on
  `-addFolder` (0 -> 1) and `-importFlightLog` (1 -> 2) - consistent with
  rev counting scene mutations. [ON2026] (2026-08-07) ESTABLISHED

- **Under fresh-boot settings, orientation priors do not influence
  alignment on the smoke fixture - a yaw/roll-scrambled log at 0.5 deg
  accuracy registered the same as the correct one (8/32 vs 6/32).**
  Scope limit, stated deliberately: the cells delegated a plain `-align`
  WITHOUT applying AlignmentParams' `-set` block, so which prior-weight
  settings were in force is UNKNOWN (the persisted-settings question).
  What this establishes is narrower but real: importing a 13-column log
  with tight orientation accuracies does not BY ITSELF make orientation
  priors act on the solve - the sfm* prior settings decide, and any
  orientation experiment that does not pin them explicitly is not
  measuring what it thinks it is. This retroactively weakens any
  historical cell that imported orientations without pinning the block.
  [ON2026] (2026-08-07) ESTABLISHED (narrow scope)

- **`-load` restores a scene with NO model selected - and the attach
  drivers' whole scenario is finishing a loaded scene.** Live gate B9,
  four attempts, one variable each: `-calculateTexture` against a
  freshly loaded scene fails 0x80004005 E_FAIL in 0 s (new error-table
  row: "texture with nothing selected"); passing the model name through
  ModelToFinal's %9 fixes it (finish_model.py --source-model). Second
  attempt proved the OWN-instance marker gate fires on a previous run's
  ErrorWriter entries - correct behaviour, but it means attach-to-own-
  instance needs pre-run marker clearing (queued as backlog B11); third
  attempt established that `progress_<inst>.txt` is HELD OPEN by the
  live instance (-writeProgress) and only the ErrorWriter-appended
  errors/results files are clearable while it runs. Final run: exit 0,
  147 s, full chain, artifacts verified. The attach monitor also
  surfaces STALE marker lines as if current - diagnose attach failures
  from the workflow log, not the relayed marker text.
  [ON2026] (2026-08-07) ESTABLISHED

- **The rerouted export path verified live: ExportDeliverables.bat via
  modules/export_deliverables.py -> run_batch_script produced all three
  deliverable legs (OBJ-by-parts, FBX, dense colored PLY - 13 files) in
  56 s on the smoke component, cleared a deliberately planted stale
  errors_RS1.txt pre-run, wrote the resource CSV, and shut down
  verified.** The wildscan portal now has zero paths around the
  execution layer. [ON2026] (2026-08-07) ESTABLISHED

## Cross-line import: [MAGIC] — ItsMagicISwear Apple-silicon engine line (2026-08-13)

A sibling project (`ItsMagicISwear`, local repo on the owner's Mac: a native Apple-silicon
photogrammetry engine) ran a research pass + same-day benchmarks on NA173 zone_4 that produce
facts directly relevant to THIS pipeline's future. Source fact base: that repo's `FINDINGS.md`
(M-20260812-15..22) and `docs/TECHNIQUE_SELECTION.md`. Entries below carry [MAGIC]; numbers
were measured on an M5 MacBook Pro (no CUDA) unless stated.

- **The COLMAP research line's fact base is a generation stale: COLMAP 4.1.1 absorbed
  GLOMAP as `colmap global_mapper` and ships a learned frontend built in** (ALIKED
  extraction + LightGlue matching via bundled ONNX, `--FeatureExtraction.type ALIKED_N16ROT`,
  `--FeatureMatching.type ALIKED_LIGHTGLUE`), plus `pose_prior_mapper` accepting per-image
  position priors with full 3x3 covariance. Standalone GLOMAP was archived 2026-03-09 with
  its prior path broken end-to-end (glomap issue #142) — "COLMAP vs GLOMAP" is no longer a
  meaningful comparison; the unified 4.1 binary is the thing to re-baseline against on
  HONEYBADGER before trusting any C-2026072x-derived comparison. Discovered: brew install
  colmap 4.1.1 + `-h` dumps + adversarially-verified research pass. [MAGIC] (2026-08-12)
  ESTABLISHED

- **First COLMAP-x-CLAHE datum, and it flips the expected sign for the COLMAP side of Q-05:
  CLAHE (2.0, 8x8, LAB-L — the exact Stage-0.5 recipe) HELPED COLMAP on NA173 ROV imagery.**
  200 contiguous zone_4 camlower frames, SIMPLE_RADIAL single camera, sequential-15 matching,
  registration by full reconstruction (per the F-20260723-03 metric lesson): SIFT raw 90/200
  (45%) -> SIFT+CLAHE 126/200 (63%) with global_mapper. Note the LilyJean cells that
  established "enhancement hurts COLMAP" tested adaptive enhancement and fixed backscatter
  subtraction, NOT plain CLAHE — so Q-05's reconciliation matrix gains a cell rather than a
  contradiction: preprocessing sign depends on the (imagery, exact enhancer, stack) triple,
  and CLAHE-on-ROV-video-frames helps COLMAP too, not only RealityScan. [MAGIC] (2026-08-12)
  ESTABLISHED

- **CLAHE's benefit extends to the learned stack on this imagery — and the learned stack
  raw beats classical+CLAHE.** Same 200-frame cell, global_mapper registration:
  ALIKED+LightGlue raw 127/200 (63.5%); ALIKED+LightGlue+CLAHE **149/200 (74.5%)** — best in
  matrix, with ALIKED at its default 2,048-feature budget vs SIFT's 8,192. Incremental mapper
  stayed flat at 88–94 in every variant: on 1 fps ROV imagery the global mapper is uniformly
  better, consistent with F-20260723-07. If the COLMAP line is revived on HONEYBADGER, the
  first cell to run is ALIKED+LightGlue+CLAHE+global_mapper. Caveat for that run: on the Mac
  build the bundled ONNX matcher ran ~7x slower than SIFT matching (1,111 s vs 161 s for the
  same pairs; likely CPU execution provider) — verify which ONNX EP the Windows CUDA build
  uses before timing conclusions. [MAGIC] (2026-08-12) ESTABLISHED

- **Nav-derived pair gating removes ~97–98% of matching work at 1 fps — the flight log alone
  is a sufficient retrieval stage.** zone_4 full log (1,912 images, median inter-frame
  spacing 0.285 m): exhaustive 1,826,916 pairs; sequential window 15 = 28,560 (1.56%);
  3 m XY radius = 60,947 (3.34%); their union ~3–4% while covering forward overlap and
  cross-track loop closures. Relevant wherever vocab-tree matching has been a cost or
  stability problem (cf. C-20260721-11/12): position-based gating from the 13-column log
  needs no vocab tree at all. Caveat: gating depends on RELATIVE nav error between nearby
  frames (smooth Kalman drift), not the 10 m absolute column — validate radius per cruise.
  [MAGIC] (2026-08-12) ESTABLISHED

- **Working recipe for injecting 13-column-log pose priors into a COLMAP 4.1.1 database**
  (the schema is the new rig/frame one): SQLite insert into `pose_priors` with
  corr_data_id=image_id, corr_sensor_type=0 (CAMERA), coordinate_system=1 (CARTESIAN),
  position as 3xfloat64 blob, position_covariance as 9xfloat64 blob (diag from the accuracy
  columns), gravity NULL. Positions MUST be local-frame (centroid-subtracted UTM) — the
  C-20260721-01 float32-UTM poisoning applies. `pose_prior_mapper` consumed them and ran;
  registration was unchanged vs plain incremental (88/200 both) — position priors anchor
  georeferencing but do not rescue correspondence-starved registration, matching this
  pipeline's own experience that the match layer, not the prior layer, is the binding
  constraint. COLMAP still has no attitude-prior input; the 13-column log's orientation
  columns remain unconsumed there. [MAGIC] (2026-08-12) ESTABLISHED

- **Context pointer: a learned-first engine is viable on Apple silicon.** VGGT-1B (feed-
  forward multi-view transformer) ran zero-shot on an M5/32 GB via torch-MPS: 128 frames per
  pass at 518 px in 20.6 GB, poses within 0.22 m mean of nav on raw turbid zone_4 imagery.
  The sibling project's v1 stack (ALIKED+LightGlue, MapAnything chunks, prior-native global
  solver, COLMAP 4.x interop) is recorded in its `docs/TECHNIQUE_SELECTION.md`; this
  pipeline's FINDINGS conventions and its RS pain points (component membership opacity, no
  incremental-against-locked-poses, census-not-exit-codes) are that engine's requirements
  spec via `docs/RS_CLI_DIGEST.md`. [MAGIC] (2026-08-12) ESTABLISHED

## H2080 per-component model+export campaign (2026-08-31)

Driving 64 named components of a GUI-built `NA168_H2080.rsproj` through
GenerateModel → ExportDeliverables, on an agent-owned COPY with a named
headless instance while the operator's GUI stayed open. Findings below are all
from that run.

- **`-exportModel <name>` resolves a model name GLOBALLY, but `-selectModel
  <name>` resolves it only within the ACTIVE component.** Established by
  controlled comparison, not inference: `ExportDeliverables.bat` wrote
  `NA168_H2080_c44`'s OBJ (2.1 GB, 15 files) and FBX (763 MB, 13 files) via
  `-exportModel`, then failed on `-selectModel "NA168_H2080_c44_HighPoly_Raw"`
  with **2147942487** (0x80070057) for a model verified present in the saved
  scene. Failed twice under the stock workflow; succeeded on the first attempt
  with a single `call :run -selectComponent "%comp%"` added ahead of the model
  lookups. Operation id **21856 = selectModel** (same id/code appears in the
  tolerated `expected_select_*Model N*` files from the residual sweep).
  CONSEQUENCE: **`ExportDeliverables.bat` cannot export more than one
  component per run** despite taking a multi-component name list — it has only
  ever worked because observed runs exported the component the preceding
  `GenerateModel` left active. The dense-PLY step is where it bites, being the
  only step needing a model other than `<comp>_Simplified_Textured`.
  Fix is a one-line `-selectComponent` in `:export_component`. [NA168]
  (2026-08-31) ESTABLISHED

- **The same scoping makes any TOLERANT model-delete silently no-op, and it
  reports success.** `:try_delete_model` is deliberately forgiving of a failed
  `-selectModel` (correctly — that is what lets the "Model 1".."Model 9" sweep
  skip absent names). For a non-active component the select fails with the same
  not-found code, the helper moves the marker to `expected_select_*` and
  returns 0 WITHOUT deleting. Measured: a 4-component prune pass deleted only
  the last-modelled (active) component and left **9 of 12 models** in the
  scene, while the workflow exited 0. Any prune/sweep over multiple components
  needs `-selectComponent` first, or its success means nothing. FIX VERIFIED:
  with `call :run -selectComponent "%tag%"` added ahead of the deletes, the
  next 3-component prune removed all 9 models (verified by parsing the saved
  `.rsproj`, not by trusting the exit code), and the scene fell 56 -> 34.5 GB. [NA168]
  (2026-08-31) ESTABLISHED

- **`-deleteSelectedModel` + `-save` removes the model from the project graph
  but does NOT reclaim its data files.** After modelling, exporting and pruning
  ONE mid-size component the scene grew **23.7 → 30 GB** with **148 new files**
  left behind — `model<GUID>_tex0..3_2.dat` at 576–706 MB each plus
  `model<N>.dat_rnd.dat` at 343 MB — none referenced by the saved `.rsproj`.
  Pruning models therefore bounds SAVE TIME but not DISK. Same shape as
  "CLI component deletion does not persist through save". Practical reclaim on
  a scratch scene is to discard and re-copy it from a pristine template, not to
  prune harder. [NA168] (2026-08-31) ESTABLISHED

- **Cache is the dominant disk consumer on a multi-day campaign, not the
  deliverables.** Retention defaults to 7 days so nothing is reclaimed while a
  campaign runs. Measured on H2080: **~20–30 GB of cache per component
  modelled** (91 GB after 7, 159 GB after 9) against ~2.5 GB of deliverables
  each. Budget the cache first and flush between batches
  (`FlushCache.bat`, main). Corroborates main's own note "7-day default kept
  918 GB". [NA168] (2026-08-31) ESTABLISHED

- **A `-calculateHighModel` failure is NOT a verdict on the component — retry
  before recording it.** `NA168_H2080_c44` failed at step [1/8] after a clean,
  uninterrupted 6.0 min run, then **modelled successfully in 29.8 min** on
  retry with identical settings, scene and recipe. Two further components the
  size proxy had condemned (`c06`, `c00`) also modelled.
  A second instance, `NA168_H2080_c03`, then failed the same step at 4.4 min
  and gave the code: **2181038105 = `0x82000019`**, from operation 20562 at
  76% progress after 215 s. That code is NOT otherwise recorded in this repo;
  its documented sibling `2181038335` = `0x820000FF` is the warning-class
  result the workflows already whitelist, and `0x82000019` is a different
  member of the same RealityScan-internal family. **Not resource pressure** -
  the run's own resource trace at failure shows 82.9 GB RAM available of
  127 GB, commit 49.8 of 156 GB, and 910.6 GB free disk. So `-calculateHighModel`
  can fail mid-computation with ample headroom, and the failure is transient.
  Drivers should retry such failures at least once rather than treating them
  as unmodellable. [NA168] (2026-08-31)
  ESTABLISHED

- **`assert_bat_safe` refuses RealityScan's own duplicate-component names.**
  RealityScan auto-names duplicates `Component N (K)`, and `(`/`)` are in
  `CMD_METACHARACTERS`, so `run_models.py` / `export_deliverables.py` refuse
  such a component outright. On H2080, 26 of 64 in-scope components carried a
  `(K)` suffix. A GUI-built project therefore cannot be driven by this pipeline
  until its components are renamed. Renaming by rewriting the
  `<component name="...">` attributes in the `.rsproj` XML **is honoured by
  RealityScan** (verified: `-selectComponent NA168_H2080_c37` succeeded after
  an offline rename, 64/64 renamed, 196 components preserved). [NA168]
  (2026-08-31) ESTABLISHED

- **`schtasks` alone does not make a run shell-proof — `/IT` leaves a console
  attached.** A task created with `/IT` runs in the operator's interactive
  session WITH a console; closing an unrelated terminal window delivered a
  console-close event to the process group and killed the Python driver
  mid-batch (`scheduler.log` ends in a literal `^C`). The `GenerateModel.bat`
  chain and its RealityScan instance SURVIVED - item 8 in reverse - and the
  ORPHANED CHAIN RAN THE COMPONENT TO COMPLETION UNSUPERVISED: all 8 steps,
  "Verifying the deliverable still exists", "Saving project", then a clean
  `-quit`, 37 min after the driver died (verified in the workflow log and by
  all three models present in the saved `.rsproj`). On this class of kill the
  correct recovery is therefore to WAIT for the orphan and record its result,
  not to kill it and re-model - but nothing external records that the run was
  interrupted, which is the real hazard. Launch the driver through a `wscript` shim
  (`WScript.Shell.Run "cmd /c <launcher>", 0, False`) so it gets a hidden
  console owned by no terminal, the same reason `ErrorWriterLaunch.vbs` uses
  wscript. [NA168] (2026-08-31) ESTABLISHED

- **Benign, do not chase: the cache-relocation popup is auto-answered "No"
  under `-silent`.** `Title: Resource Cache path is changing / Message: Would
  you like to move cache files to? <RS_CACHE_DIR> / Action: &No` appears in
  `RealityScan.log` on every boot that sets `appCacheCustomLocation`. It only
  declines to MIGRATE pre-existing cache files; the new cache still goes to
  `RS_CACHE_DIR`. Investigated because it is the same class as the recorded
  "export auto-answers its dialog and exports nothing" hazard — it is not that.
  Suppressible with `-set "PUS-6-323328742=1"` if migration is ever wanted.
  [NA168] (2026-08-31) ESTABLISHED

## NA165 H2063 extraction start (2026-08-31)

- **A killed `robocopy /MT` leaves FULL-SIZE, zero-tailed files — size equality
  is NOT a completeness check.** Aborting a 559 GB `robocopy /E /MT:8` mid-run
  left 8 destination `.mov` files whose sizes were byte-for-byte equal to the
  source (robocopy pre-allocates the destination), while everything past the
  written point was zeros. Proof: md5 of a 4 MB window at 60% of the file and
  another 16 MB from the end were IDENTICAL TO EACH OTHER in the local copy
  and different from the source at both offsets — the signature of a zero
  fill, not of a short write. All 4 files that were retained tested corrupt.
  Any resume logic that trusts `os.path.getsize()` (or `os.path.exists()`)
  will silently reuse these. Verify a late-offset hash against the source, or
  delete and re-copy. [NA168] (2026-08-31) ESTABLISHED

- **The Extract Images module reports `Success: True` after decoding 43 of
  26,974 frames.** Same incident: the corrupt ProRes decoded for 43 s and then
  emitted `[prores @ ...] invalid frame header` continuously, yet the module's
  own summary read `Success: True`, `Total Input Frame Count: 26974`,
  `Total Extracted Frame Count: 43`, and `main.py` exited 0. Exit code and the
  module's Success flag are therefore NOT evidence that a video was extracted
  — the extracted count must be compared against duration x rate. This is
  exactly the check `tools/extract_pipeline.py` already performs ("43 frames
  but expected ~900 from 900s - truncated read?"), and it is the only reason
  the corruption was caught; it also correctly KEPT the local copy rather than
  deleting it. Do not extract without that comparison. [NA168] (2026-08-31)
  ESTABLISHED

- **Latent hazard in `tools/extract_pipeline.py`: staging reuse is keyed on
  existence alone.** `if not os.path.exists(dst)` skips the copy, so a video
  whose staged copy is short or zero-tailed is never re-copied; its extraction
  then fails verification on every subsequent run, and because the failure
  path deliberately KEEPS the local copy, the file can never recover without
  manual intervention. A size-and-late-offset check before the skip would close
  it. [NA168] (2026-08-31) ESTABLISHED

- **A HIDDEN console is still a TTY, and the Extract Images module hangs
  forever on one.** Running the extraction under
  `wscript ... WScript.Shell.Run "cmd /c ...", 0, False` (the shim that makes a
  long run survive a terminal close) produced a `main.py` that consumed
  **0.00 CPU seconds over 15 s** with no ffmpeg child and no output, on a video
  that was demonstrably good. The same command with stdin from a pipe or from
  `/dev/null` extracted normally (259 CPU-seconds, 565 frames and climbing).
  Window style 0 hides the console but does not remove it, so `isatty()` stays
  TRUE and an interactive read blocks on input that can never arrive -
  `RS_NO_INTERACTIVE=1` did not prevent it. FIX: redirect stdin explicitly in
  the launcher (`python driver.py < NUL >> log 2>&1`); verified working.
  Applies to ANY scheduled/detached invocation of this pipeline, not just
  extraction - the hidden-console launcher is otherwise the correct pattern.
  [NA168] (2026-08-31) ESTABLISHED

- **`tools/extract_pipeline.py` never implemented the per-video output dir its
  own docstring documents — so it extracts exactly ONE video and then fails
  every remaining one, keeping each staged copy.** `extract_one`'s docstring
  reads *"Extract into a PER-VIDEO output dir ... Reusing one output dir
  therefore works for the FIRST video and fails for every one after it - which
  is exactly what happened on 2026-08-15 ... 25 of those filled the disk. Each
  video gets its own directory; frames are collected afterwards."* The code
  under it passes the SHARED `out_dir` straight to `-o`, is called as
  `extract_one(local, args.out, ...)`, and `grep` finds no move/collect step
  anywhere in the file. The documented fix was lost; the regression it
  describes is live. Reproduced on NA165/H2063 2026-08-31 08:56: video 0005 ok
  (701 frames, 199 pruned outside the on-bottom window), then 0006 and 0007
  back-to-back `ERROR: Extracted images folder already exists and this run is
  non-interactive - refusing to overwrite it` / `exit 1`, each keeping its
  ~17 GB copy, `progress 3/26 videos, 0 frames total`. FIX: extract into
  `<out>/_extract_<stem>`, then move `frames_dir(per_video)` into
  `frames_dir(out)` before `verify()` runs — verify and prune both read
  `frames_dir(out_root)` and need no change. [NA168] (2026-08-31) ESTABLISHED

- **geoall silently falls back to an ARBITRARY nav CSV when the merged
  `final_datatable.csv` is absent — and the alphabetically-first candidate is
  the SURFACE VESSEL's USBL.** `find_rov_datafiles` prefers
  `*final_datatable.csv` and otherwise takes `paths[0]`. On NA165/H2063, whose
  `RUMI_processed` dir had only ROVDataConcat STAGE 1 output, that fallback
  chose `NA165_H2063_USBL_Atalanta.csv` - Atalanta, not Hercules - and printed
  only a `Note:` while ignoring the DVL, octans and sealog files. A dive whose
  Kalman stage has not been run will therefore georeference against the wrong
  platform, with no orientation columns at all, and the only signal is an
  easily-missed Note line. It should refuse instead: no `final_datatable`
  means no authoritative nav. Discovered because the run also hit an unrelated
  path error first; had the paths been right it would have proceeded.
  [NA168] (2026-08-31) ESTABLISHED

- **ROVDataConcat is TWO stages and a dive can look "pre-processed" while
  missing the one geoall needs.** Stage 1 (`main.py`, expedition-wide) emits
  `*_pitch_roll_heading_octans.csv`, `*_dvl_lat_long.csv`, `*_USBL_Hercules.csv`,
  `*_USBL_Atalanta.csv`, `*_sealog_sensors_merged.csv`. Stage 2
  (`main_kalman.py --base <root> --expedition <EXP> --dive <DIVE>`, per dive)
  is what produces `*_filtered_datatable.csv`, `*_kalman_filtered_data.csv` and
  the `*_final_datatable.csv` that geoall treats as authoritative. NA165/H2060
  has all of stage 2; NA165/H2063 had none of it, while still looking like a
  populated `RUMI_processed/<DIVE>` folder. Check for `*final_datatable.csv`
  before georeferencing, not for a non-empty directory. [NA168] (2026-08-31)
  ESTABLISHED

- **The extractor's frame layout does not match what geoall expects.**
  `extract_pipeline.py --out X` writes frames to `X/raw_images`
  (`frames_dir()`), but geoall's `--image-base-dir` wants the frames directly
  inside an `edt` directory - the H2060 precedent is
  `raw/zeuss/edt/*.jpg`. Passing `--out .../raw/zeuss/edt` therefore yields
  `raw/zeuss/edt/raw_images/*.jpg` and geoall reports
  "Reading 0 images from 1 edt directories" and exits. Either pass
  `--out .../raw/zeuss` and rename `raw_images` to `edt`, or move the frames
  up one level after extraction. [NA168] (2026-08-31) ESTABLISHED

- **geoall.py and modules/georeference/ have diverged on the ONE column that
  carries focal length — and CLAUDE.md points you at the wrong one.**
  `modules/georeference/georeference_images.py` writes a **14-column** flight
  log ending in `FocalLength`, which its own `_get_camera_focal_length`
  documents as "THE ONLY ROUTE this value has to RealityScan": sidecars are
  forbidden, and per `modules/prior_groups.py` neither
  `-setPriorCalibrationGroup` nor `-setPriorLensGroup` carries a focal length
  ("the two CLI commands set GROUPING only"). `geoall.py` still writes **13
  columns** and drops it silently. Verified: geoall's NA165/H2063 output, and
  the existing NA165/H2060 and NA168/H2080 logs, are all 13-column with no
  FocalLength. CLAUDE.md rule 6 calls geoall canonical and says to port
  improvements FROM it INTO the module - here the improvement went the other
  way and was never back-ported, so following the documented guidance loses
  the focal prior. Use the module (`RS_MODULES='Georeference Images'`,
  `--g_type Zeuss`, `--g_flight_log <final_datatable.csv>`) when a numeric
  focal prior matters. Confirmed working: 22,770 rows, 14 columns,
  `FocalLength 28.000000` throughout. [NA168] (2026-08-31) ESTABLISHED

- **`RS_NO_INTERACTIVE` must be set BEFORE the repo is imported, not before
  the call.** Setting it inside a wrapper's `main()` and then importing
  `main.py` is too late - parameters are built at import time and the run
  stops on `Whether to continue automatically after each module [False]:`.
  Set it at module scope ahead of every repo import. Same family as the
  hidden-console TTY hang: both are "the non-interactive gate did not take".
  [NA168] (2026-08-31) ESTABLISHED

- **A CLI value that EQUALS the declared default is treated as "not supplied"
  and loses to rs_settings.json.** `batch_directory._explicit_cli_value` tests
  explicitness as `value != param.get_default_value()`, so
  `--b_max_zone 4000` (declared default 4000) returns None, is deemed
  unanswered, and `_stored_default` falls through to the `batch` section -
  which on this machine holds **max_zone_size 8000**. Measured NA165/H2063
  2026-08-31: batching was invoked with `--b_max_zone 4000` and
  `batch_inputs.json` recorded `"batch_max_zone_size": "8000"`, producing a
  zone of **7,842 images (6,535 base + 1,307 overlap)** against an operator
  cap of 6,000. The guard's own docstring says an explicit flag "must WIN
  over rs_settings.json" - and it does, EXCEPT when the operator's chosen
  value coincides with the default, which is exactly when they are most
  likely to type it. Worse, both keys feed `_input_fingerprint`, so the wrong
  zoning is recorded as legitimate provenance (the same failure mode the
  2026-08-07 audit closed for the stored-value-beats-CLI case). Workaround:
  pass a value that differs from the default. Real fix: track suppliedness
  from argparse rather than inferring it by comparison. [NA168] (2026-08-31)
  ESTABLISHED

- **`-load` of a large scene can fail with 2147500037 (`0x80004005`, E_FAIL)
  and it is transient, not a corrupt project.** NA168/H2080 2026-08-31 12:37:
  the export session for `c54` reached only "Loading project" in its workflow
  log and aborted after 12 s with `process 6 finished with result code
  2147500037`. Operation id 6 is the load. The scene was 69 GB with ~12 live
  models; resources were NOT tight (97.7 GB RAM free, commit 77 of 171 GB), and
  a second RealityScan instance was aligning another campaign concurrently.
  The next component's export loaded the SAME project seconds later without
  incident, so the project is intact. This code is not otherwise recorded in
  the repo; its documented neighbours are the RealityScan-internal `0x82...`
  family and `0x80070057`. Treat a load failure as retryable - keep the
  component's models and re-export on a later pass rather than re-modelling.
  [NA168] (2026-08-31) ESTABLISHED

- **AlignZone's "save BEFORE the destructive identity loop" earned its keep:
  the align survived while the identity capture failed.** (SUPERSEDED in
  part: first attributed to memory pressure - WRONG. zone_2 reproduced it
  with commit 70.2 GB and 79.9 GB RAM free. Real cause is the missing
  RegistrationExportParams.xml - see the entry below.) NA165/H2063 zone_1 (4,060 images) ran 6 h 17 m and completed
  scene build, prior groups, 35 alignment settings, flight-log import and the
  alignment itself, logged "Saving project BEFORE the destructive identity
  loop", then failed at
  `-exportRegistration ".../zone_1/identity/zone_1_c0.csv"` with **2147500037
  (0x80004005)**. `AlignZone.bat` exited 1 and the module logged the zone as
  failed - but **three components totalling 2.8 GB were already on disk** in
  `aligned_components/zone_1/latest_components/`, so no alignment work was
  lost. A zone reported as FAILED by the workflow is therefore not necessarily
  a zone without usable components; check `latest_components/` before
  re-running a 6-hour align.
  Resource peaks for that zone: **CPU 100%, commit 139.4 GB of 156 (89%),
  minimum available RAM 37.6 GB** - and Windows GREW the commit limit to
  185 GB during the run. A second campaign (NA168/H2080 modelling) was running
  concurrently. Immediately afterwards, with the much smaller zone_2 (1,983
  images) in flight, commit was 51.4 GB (28%). THE SIZE RULE I FIRST DREW
  FROM THIS IS REFUTED by zone_5, which is LARGER than zone_1 (4,124 vs 4,060
  images) yet peaked at 96.2 GB and finished in ~50 min:

  | zone | images | commit peak | min RAM | duration |
  |---|---:|---:|---:|---:|
  | 1 | 4,060 | **139.4 GB** | 37.6 | **6 h 17 m** |
  | 2 | 1,983 | 70.2 GB | 79.9 | ~15 m |
  | 3 | 2,718 | 66.1 GB | 71.4 | ~23 m |
  | 4 | 2,059 | 69.2 GB | 68.5 | ~26 m |
  | 5 | 4,124 | 96.2 GB | 54.0 | ~50 m |

  zone_1 is an OUTLIER in BOTH time and memory and zone SIZE explains neither.
  It was the campaign's first zone (cold cache) and ran against the concurrent
  H2080 campaign's heaviest phase. Do NOT budget alignment by image count on
  this evidence. What IS reliable: the identity/registration tail fails on
  every zone regardless, while the align and -exportLatestComponents succeed
  throughout.
  [NA168] (2026-08-31) ESTABLISHED

- **AlignZone's non-destructive identity capture CANNOT WORK as shipped:
  `RegistrationExportParams.xml` does not exist, and the documented fallback
  does not hold on a freshly booted instance.** `AlignZone.bat` sets
  `RegistrationParams=%Metadata%\RegistrationExportParams.xml`, blanks it when
  the file is absent, and relies on the comment *"-exportRegistration falls
  back to the instance's current settings when no params xml is given"*. That
  file is NOT shipped (its own comment says so - RealityScan must write it from
  the "Export Registration" dialog) and does not exist anywhere on this
  machine. A fresh headless instance has no "current settings" to fall back
  to, so `-exportRegistration` fails immediately with **2147500037
  (0x80004005)** and `AlignZone.bat` exits 1.
  Measured NA165/H2063 2026-08-31 on BOTH zones run so far - zone_1 (4,060
  images, commit peak 139.4 GB) and zone_2 (1,983 images, commit peak 70.2 GB,
  min RAM 79.9 GB). Identical failure at identical step, three hours apart, at
  opposite ends of the memory envelope: **it is not memory pressure**, it is
  the missing params file. My first diagnosis blamed memory on the zone_1
  evidence alone; zone_2 refuted it.
  IMPACT - CORRECTED. I first called this bounded ('only provenance'). It is
  worse than that: it BLOCKS THE MERGE. `merge_zones` refuses components
  without a manifest ('Components WITHOUT a manifest are refused: the
  feature-aware loop needs membership'), and the manifests are built from
  the identity CSVs this step produces - the chain is
  `-exportRegistration -> identity CSV -> member stems -> <rsalign>.manifest.json -> merge_zones`. No CSVs means no manifests means
  no merge. Membership cannot be recovered from the .rsalign either: it is
  binary TBSM and contains no image filenames at all (0 occurrences of
  '.jpg' in a 151 MB component).
  RECOVERY IS CHEAP THOUGH, because AlignZone saves before the destructive
  loop: every zone keeps `zone_N.rsproj` AND an `RC_projects` dated copy, so
  once a params file exists the identity capture can be re-run per zone in
  minutes - load, select component, export - with NO re-alignment. An
  8-hour campaign is not at risk.
  `-exportLatestComponents` runs BEFORE the identity loop
  and succeeds, so every zone still yields its components - zone_1 three
  (2.7 GB), zone_2 seven (1.7 GB) - which is what a merge `.complist` consumes.
  What is lost is per-component MEMBERSHIP: `<zone>/identity/` is empty on
  every zone, so census and provenance cannot be computed. The zone is also
  reported FAILED, which understates what actually happened.
  FIX: export a registration preset once from the RealityScan GUI's "Export
  Registration" dialog, drop it at
  `RS_CLI/Metadata/RegistrationExportParams.xml` (or point
  RS_REGISTRATION_PARAMS at it), and every later run gets identity data. Until
  then the identity capture is dead code on any machine that has never saved
  those settings. [NA168] (2026-08-31) ESTABLISHED

- **No component manifest is EVER produced on this branch - two independent
  breaks, and fixing either alone is not enough.** Root-caused NA165/H2063
  2026-08-31 after `merge_zones` was found to be blocked:

  **Break 1 - the CSV is never written.** `AlignZone.bat`'s `:identityOne`
  calls `-exportRegistration "<identity>\<zone>_c<K>.csv"` with NO params
  file, because `RS_CLI/Metadata/RegistrationExportParams.xml` is not shipped
  and nothing generates or prompts for it. The .bat's own comment relies on
  "-exportRegistration falls back to the instance's current settings", and
  RealityScan's Help agrees - but a FRESHLY BOOTED HEADLESS instance has no
  such settings, so the call fails with **2147500037 (0x80004005)** and the
  zone exits 1. Confirmed on every zone run, at both ends of the memory
  envelope. The settings can only be produced from the GUI's Export
  Registration dialog (Help: "You can export the settings file from the
  application in the Export Registration dialog"); `-exportGlobalSettings`
  does not help - it writes a BINARY `.rcconfig` (TBES magic), not readable
  keys.

  **Break 2 - nothing would read the CSV even if it existed.** The .bat was
  migrated to the non-destructive registration-CSV method; the Python side was
  not. `RealityScanAlignment.capture_component_identities()` still reads the
  RETIRED harvest layout - `identity_r<K>/*.xmp`, membership by successive
  difference - not `identity/*.csv`. It therefore finds nothing and logs "No
  usable identity harvests". (Its own comment says `identity_c<K>` while the
  code reads `identity_r{index}` - the two halves disagree in the source.)
  A grep confirms NOTHING in the repo parses `identity/*.csv`.

  CONSEQUENCE: `<rsalign>.manifest.json` is never written, and `merge_zones`
  refuses components without one, so the merge stage cannot run at all.
  Membership is not recoverable from the `.rsalign`: it is binary TBSM with
  ZERO occurrences of '.jpg' in a 151 MB component.

  FIX (both halves needed): (a) export the registration preset once from the
  GUI to `RS_CLI/Metadata/RegistrationExportParams.xml`; (b) parse the CSVs
  into schema-v1 manifests - the format is pinned in the repo's own
  `calibration.xml` as `#cameras N` / `#name,x,y,z,...` with the image name in
  field 0, so a parser is ~20 lines against `component_manifest.build_manifest`.
  Recovery for already-aligned zones is cheap because AlignZone saves BEFORE
  the destructive loop: reload `zone_N.rsproj`, select each component, export
  registration, build manifests - minutes per zone, no re-alignment.
  [NA168] (2026-08-31) ESTABLISHED
