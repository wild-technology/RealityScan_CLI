# NA156 WCA settings evaluation & merge strategy — 2026-07-23

Scope: how metadata, camera priors, prior settings, distortion models, and
alignment/merge settings should be handled for the NA156 H2023 Widefield
Camera Array dataset (and rigs like it), plus the component-merge
architecture. Sources: RealityScan 2.2 local Help (authoritative for this
build: allcommands.htm, alignsettings.htm, setkeyvaluetable.htm,
settings_distortion_models.htm), `testing/MERGE_TEST_PLAN.md` results,
`testing/NA167_SESSION_NOTES.md` (B1-B9), and inspection of the actual
image EXIF.

## 1. Dataset metadata state

- Port `P231C####_<ts>_edt.jpg` (2,296) and Cinema `C231C####_<ts>_edt.jpg`
  (2,302): 4244x2827 (12 MP, 3:2), Lightroom-rendered from Z CAM E2-F6
  (full-frame). EXIF carries Make="Z CAM", Model="E2-F6", exposure data --
  but **no focal length and no lens tag**, and the two cameras are
  **EXIF-identical**.
- Consequence: RealityScan cannot tell the cameras apart from EXIF.
  `appGroupCalibrationByExif` (bool, default false) would group BOTH
  cameras into ONE calibration group if enabled -- wrong (different
  lenses). Left false, images calibrate without EXIF grouping -- weak.
  Neither default is right.
- `sensorsdb.xml` entries are keyed to NA167-era model strings
  ("ZCAM F6 8-15mm Fisheye Upper" etc.) and cannot match this EXIF; it
  also cannot distinguish two cameras with identical EXIF. Not usable here.
- **Correct mechanism: per-image XMP calibration sidecars** with
  `Camera:CalibrationGroup` / `Camera:LensDistortionGroup` -- one group
  per physical camera. This both separates the EXIF-identical cameras and
  pools each camera's images into one shared self-calibration (strongest
  correct constraint). The batcher already has the writer
  (`__generate_xmp_sidecar`); it needs P231C/C231C branches.

## 2. Camera priors: two distinct families

**(a) Pose priors** (flight log): per-image X/Y/Alt (10 m/10 m/1 m stated
accuracy) + yaw/pitch/roll (3/5/3 deg) from the Kalman nav, lever-arm and
mount-angle corrected per camera (Port: 0 deg pitch, 1 m fwd + 1 m down;
Cinema: 45 deg down, 1 m fwd). Consumed during alignment when
`sfmEnableCameraPrior=true` -- this key IS the GUI's **"Use camera priors
for georeferencing"**, i.e. the "use georeferencing for alignment" flag.
It stays ON.

**(b) Calibration priors** (XMP): focal/distortion hints. NA167 A/B testing
showed the *old prior content* (wrong fixed focals) reduced registration,
so generation is opt-in. The rig is FOUR physical cameras, appearing under
era-specific filename families (owner-confirmed 2026-07-23):

| Physical camera | Filename markers | Lens | CalibGroup/LensGroup | CalibrationPrior | FocalLength35mm | DistortionModel |
|---|---|---|---|---|---|---|
| Zeuss | `zeuss`, `z`, `_herc_` | rectilinear 23 mm FF | 1 | Approximate | 23.0 | brown3 |
| Port (aka cammid) | `p231c`, `cammid` | fisheye 14 mm FF | 2 | Approximate | 14.0 | division |
| Cinema (aka camlower) | `c231c`, `camlower` | rectilinear 17 mm FF | 3 | Approximate | 17.0 | brown3 |
| Starboard (aka camupper) | `s231c`, `camupper` | fisheye 14 mm FF | 4 | Approximate | 14.0 | division |

One calibration/distortion group per PHYSICAL camera (never per lens
type): Port and Starboard share a lens spec but are different units with
different real intrinsics. The old writer grouped cammid+camupper+camlower
together at "12 mm fisheye" -- camlower is actually rectilinear 17 mm,
which is plausibly why NA167's A/B found priors harmful. Corrected values
change that calculus; re-validate per rig before trusting either way.
Sidecars remain calibration-ONLY (no pose entries).

## 3. Distortion model

Allowed values (Help, this build): `Division`, `Brown3`, `Brown4`,
`Brown3WithTangential2`, `Brown4WithTangential2`,
`KplusBrown3WithTangential2`, `KplusBrown4WithTangential2`.
App default: Brown3. Repo params had **Division** -- a leftover from the
NA167 8-15 mm fisheye-through-dome rig; wrong default for 14 mm
rectilinear glass.

Strategy (endorsed verbatim by the Help: "starting with a simpler
Division model first, and later change it to Brown and click Align Images
to optimize"). The rig is MIXED -- fisheye (Port/Starboard) and
rectilinear (Cinema/Zeuss) -- so the model must be set **per camera via
the XMP sidecars** (per-image XMP overrides the global key), not globally:
- **Zone aligns (pass 1)**: Port/Starboard `division` (the fisheye model;
  Brown only covers <180 deg optics), Cinema/Zeuss `brown3`. Global
  `sfmDistortionModel=Brown3` stays as the fallback for un-sidecarred
  images.
- **Post-merge refinement pass**: upgrade the RECTILINEAR groups to
  Brown4WithTangential2 + re-align on the merged scene (mid-vs-edge
  distortion from housing ports; tangential2 absorbs lens/port axis
  offset). Fisheye groups stay division. K+ variants (skew/aspect) only
  if refinement residuals stay high -- freeing skew/aspect on
  weak-texture underwater data risks overfitting.

## 4. Alignment settings (AlignmentParams.xml, pass-1 zone aligns)

| Key | Old | New | Why |
|---|---|---|---|
| sfmEnableCameraPrior | true | **true** | The "use georeferencing" flag -- required for georeferenced components and for merge-by-georeference downstream. |
| sfmCameraPriorWeight / ...Orientation | 10.0 | **10.0** | Kept: proven on this data class (NA167 93.4% zone_13); accuracies (10 m/1 m/deg-level) already give vision free rein inside the trusted envelope. Fallback variant: 1.0 if a zone under-registers. |
| sfmDistortionModel | Division | **Brown3** | Rectilinear rig (see 3). |
| sfmDetectorSensitivity | Ultra | **Ultra** | Weak underwater texture; the CLAHE A/B was validated with this. |
| sfmMaxFeaturesPerMpx / PerImage | 14000 / 50000 | keep | More features = fewer components on low-texture seabed. |
| sfmPreselectorFeatures | 20000 | keep | Help: 1/4-1/2 of detected. |
| sfmImagesOverlap | Low | **Medium** | 2-3 s spacing + two interleaved cameras + track revisits: Low (legacy) narrows pair search and costs loop closures; Medium buys them at acceptable runtime. |
| sfmForceComponentRematch | false | **false** (pass 1) | Merge-stage tool; wasted per-zone. |
| sfmMergeGeoreferencedComponents | false | **false** (pass 1) | Deliberate: per-zone components must stay HONEST. Auto-fusing disjoint pockets by georef during zone aligns would freeze bad geometry invisibly; fusion is the merge stage's explicit, inspectable job. |
| appIncSubdirs | (unset) | **true** | This build does NOT recurse by default -- "Added 0 layer images" failure, fixed 2026-07-23. |

## 5. "Use georeferencing" vs "Merge georeferenced components"

- `sfmEnableCameraPrior` ("Use camera priors for georeferencing"): pose
  priors participate **inside the bundle adjustment** -- they constrain
  each camera's solve and georeference the resulting component(s).
  Per-camera, during alignment.
- `sfmMergeGeoreferencedComponents`: **component-level** post-solve
  behavior -- components that are each already georeferenced may fuse
  "even without visual overlap" purely by their world placement.
  Per-component, during align/merge operations.
- They compose: (a) makes every component georeferenced; (b) then allows
  those components to merge where no shared cameras/features exist.
  (b) without (a) is inert; (a) without (b) leaves disjoint-but-
  georeferenced components separate.

## 6. Component handling & merge architecture

CLI facts that reshape the old plan:
- **`-exportLatestComponents <dir>`** exports ALL components from the last
  alignment (gated by `-setMinComponentSize`) -- the maximal-only export
  in the old scripts was an unnecessary loss; zones that fragment keep
  every pocket >= min size.
- **`-setFeatureSource 0|1|2`** (per selected images; select with
  `-selectImage <regexp>` set/union/sub/intersect) IS CLI-accessible --
  the "Merge using overlaps / component features / all image features"
  trio previously believed GUI-only. Per-camera merge-mode experiments are
  scriptable: e.g. `-selectImage "P231C.*"` then `-setFeatureSource 2`.
- `selectComponent <name>` / `selectMaximalComponent` /
  `selectComponentWithLeastReprojectionError` / `deleteComponent <idx>` /
  `deleteSelectedComponent` / `deleteAllComponents` all exist for
  component surgery.

**Architecture** (replaces the AlignImagesFromFolder vs
AlignZonesSequentially duplication -- which was historical, not
intentional):

1. **Per-zone align** (one canonical workflow): boot -> appIncSubdirs ->
   addFolder(zone) -> importFlightLog(auto-CRS from zone tag) ->
   [optional -importXMP calibration priors] -> apply AlignmentParams ->
   -align -> setMinComponentSize 50 -> **exportLatestComponents** to
   aligned_components/<zone>/ -> exportXMP (registration census) -> save
   .rsproj -> verified quit. NO model generation per zone (models are
   built once, on the merged result -- per-zone meshing wastes GPU-hours
   on geometry that merging supersedes).
2. **Iterative merge** (fresh project): boot with priors ON +
   `sfmMergeGeoreferencedComponents=true` -> -importComponent every
   .rsalign FROM ITS EXPORT LOCATION (relocated imports hang forever, B1)
   -> `-mergeComponents` (cheap georef+identity fuse, no new images) ->
   census. If fragments remain: `-align` pass with
   `sfmForceComponentRematch=true` (align/update fuses via features; the
   20% duplicated overlap bands give strong cross-zone visual ties even
   though duplicate copies have no shared path identity). Escalation
   ladder per attempt: featureSource experiments (per-camera regex
   selection), overlap Medium->High, distortion-model upgrade
   (Brown4WithTangential2) + re-align refinement on the merged scene.
3. **Model generation** on the final merged component only:
   mesh -> cull -> texture -> simplify -> export (existing model steps,
   extracted into their own workflow).

Rationale for per-zone-then-merge over the alternatives (matrix evidence):
sequential single-scene growth (B) has no per-zone recovery -- one bad
zone poisons the scene; joint align of everything (C) maximizes peak
memory/runtime and restarts from zero on failure; per-zone + deliberate
merge is restartable, auditable (per-zone censuses), and parallelizable
across GPUs later. This matches the "align zones sequentially, then load
components into a new project for iterative merging" model.

## 7. Model recipe & texture-reprojection-with-holes (2026-07-23 addendum)

Owner-specified default recipe (GenerateModel.bat): Generate High ->
remove marginal/edge triangles -> remove large triangles (threshold 30)
-> keep largest connected component -> close holes -> clean model ->
simplify (noise) -> texture -> simplify (smooth) 80% x4 with clean
between -> unwrap -> reproject high-poly texture. Kept models:
HighPoly_Raw, HighPoly_Textured (pre-simplification), Simplified_Textured.

CLI facts discovered mapping this:
- `-removeSelectedTriangles` = the Filter Selection tool and removes the
  SELECTED set -> edge/large steps filter directly; only the
  largest-component step needs `-invertTrianglesSelection`.
- Check Integrity / Check Topology have NO CLI commands (GUI-only
  checks); their FIX action maps to `-cleanModel` ("remove non-manifold
  edges and vertices, close small holes") + `-closeHoles`.
- `-selectLargeTrianglesRel <t>` threshold is in MULTIPLES OF AVERAGE
  EDGE LENGTH, not pixels - the "30px" GUI intuition maps approximately;
  verify visually and tune the third GenerateModel.bat argument.
- `-simplify` takes params.xml exported from the GUI Simplify tool.
  SimplifyNoise_Params.xml (70% rel) and SimplifySmooth_80per_Params.xml
  (80% rel) are placeholders derived from the 50% template - if the
  owner has specific GUI presets for "noise" and "smooth"
  simplification, export them over these files.

**Reprojection from a holey model onto a hole-closed manifold** - the
options and the chosen answer:
1. Texture the holey model, close holes, reproject (WRONG): reprojection
   samples the source surface; fill triangles have no source -> nodata
   patches with no color blending.
2. Texture AFTER closeHoles+cleanModel (CHOSEN): `-calculateTexture`
   projects from the source IMAGES with multi-band blending, so
   hole-fill triangles that any camera saw get real, blended color -
   underwater mesh holes are usually weakly-reconstructed but
   camera-visible seabed, so this covers the vast majority. The final
   `-reprojectTexture HighPoly_Textured Simplified` then maps between
   two already-manifold models (simplify+clean preserve closure), so no
   nodata is introduced at that stage either.
3. Residual limitation: fill areas NO camera ever saw (true occlusions)
   have no image color under any strategy; they come out untextured and
   would need external inpainting (e.g. Blender) if they matter.
   ReprojectionParams.xml keys (reprojectionTool_colorSampling /
   supersampling) affect sampling quality, not unseen-area synthesis.

## 8. Multi-component expectation

Zones are expected to produce MULTIPLE components (fragmented visual
chains are normal underwater). Handling: min-size 50 keeps every
meaningful pocket; all pockets export; the merge project ingests all of
them, not just maximal. `selectComponentWithLeastReprojectionError`
offers a quality-first alternative to size-first selection when a
representative component must be chosen. Merge order: largest first, then
descending -- each fuse is checked (census delta) before the next.
