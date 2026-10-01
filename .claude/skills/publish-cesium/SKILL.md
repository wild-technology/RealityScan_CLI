---
name: publish-cesium
description: Publish a mesh to Cesium ion at its real depth, or diagnose an asset sitting at the sea surface. Use when asked to publish, upload to ion, share a model, fix an asset's position or altitude, or when Cesium "ignores depth". Also covers Nira publishing and the batch publisher.
disable-model-invocation: true
---

# Publishing to Cesium ion

Brought up to date 2026-10-01 against the code (geoid on both routes, true
ENU on the projected route, BUGS.md B25-B28). A line marked UNVERIFIED is
carried over from the earlier skill and is not something the code or its
tests establish.

`python` = the interpreter that HAS `requests` and `boto3`. On the
NA165/NA168 machine that is the Microsoft Store `python`, NOT
`tools\.venv` (which has `textual` but neither of those) - CLAUDE.md
"Starting a session". `py -3.13` where the launcher exists.

**ion honours below-ellipsoid heights exactly.** A probe asked for
h = -512.46 m and read back h = -512.46 m, error -0.000 m
(`testing/probe_cesium_depth.py`; FINDINGS `[CESIUM]`). If an asset is in
the wrong place vertically, the fault is upstream:

1. **RealityScan's own "Share to Cesium ion" never georeferences.** Epic's
   Help says the model "does not have to be georeferenced ... define its
   approximate position" later - i.e. hand-placed at ~sea level.
2. **The project CRS is 2D and declares no vertical datum**, while the Z
   it carries is a depth below the **sea surface**. Cesium reads every
   height as above the **ellipsoid**. The gap is the geoid undulation N:
   +25.2 m at NA165 H2060, **+72.7 m** at NA168 H2080, +70.4 m Solomon
   Sea, -27.1 m Gulf of Mexico. An asset published without it sits N too
   DEEP, not at the surface.

## What `modules/cesium_placement.py` does

- Reads the export's `.rsInfo` for the CRS, the export type and
  `transformToModel`, and DERIVES which reading of that matrix is correct
  (CRS area of use, a determinant test that rules out mirrored readings,
  and the nav envelope when one is given).
- **Geocentric export** (`exportCoordinateSystemType="3"`, vertices are
  ECEF whatever CRS the sidecar names): rotated into East-North-Up at the
  anchor, `vn` normals with it. RealityScan puts the flight log's -depth in
  the ellipsoidal slot (measured 2026-09-28), so the anchor height gets
  **+ N** exactly as the projected route's does. Before that fix this
  route applied none and placed assets N too deep.
- **Projected export** (any other type, e.g. EPSG:32702 with Z = -depth):
  localised to **true** East-North-Up - grid -> geodetic -> ECEF -> ENU at
  the anchor, normals turned with it (BUGS.md B28, 2026-10-01). Before
  that it only subtracted the anchor, which left the mesh turned by the
  grid convergence and at grid scale: 0.48 deg and 0.025 % at H2060. The
  anchor itself did not change.
- N goes on the anchor height ONLY. The staged mesh is the same with and
  without `--no-geoid`.
- Localised: one projected CRS, easting then northing, in metres (any UTM
  zone, either hemisphere; a polar stereographic grid). REFUSED with a
  `PlacementError`: a geographic or compound CRS, a northing-first or
  westing / southing grid, a grid in feet, and a geocentric / projected
  mix in one upload.

## Publish

```bash
python publish_cesium.py --name "<name>" --dir <export>/obj \
    --no-proj-network --staging <a scratch folder OUTSIDE the export> \
    --flight-log <cruise>/raw_images/flight_log_<zone>_UTM.txt --poll --verify
```

- **Always `--staging <a folder you can lose>`, never an export, package
  or dive folder.** `stage()` DELETES whatever `--staging` names before it
  writes, and does so before the `--dry-run` gate; the default is
  `<dir>/_cesium_local`, inside the export (B25, OPEN).
- **Always `--no-proj-network`.** With the EGM2008 grid installed (it is,
  for both interpreters here) nothing needs fetching, and with PROJ
  network on a grid that cannot be fetched comes back as `inf` instead of
  an error (B26, OPEN).
- **Never publish without `--verify`.** It decodes the finished tileset
  and checks the placement that landed against the PLAN - so it cannot
  catch a plan that is itself wrong (B27, OPEN).
- `--flight-log` is consulted only when the sidecar carries a non-identity
  `transformToModel`. On a geocentric export and on a `georef_v2` /
  nav-placed product it checks nothing (B27).
- **A publish creates a NEW asset id.** `publish_cesium.py` only ever
  POSTs `/v1/assets`; it updates and deletes nothing. Re-publishing a
  corrected model leaves the old asset where it was, for the owner to
  retire.
- Plan without uploading: `--dry-run` (it still stages - same `--staging`
  rule) and `--plan-json <file>` to keep the plan.
- Whole workspace: `python publish_batch.py --workspace <ws> --prefix
  "<wreck>"`. It passes NEITHER `--staging` NOR `--no-proj-network` to
  `publish_cesium.py`, so a real batch run stages inside every export
  folder; its `--dry-run` only prints the commands.

## Audit what is on the account

`python validate_cesium_assets.py --flight-log <zone-tagged log>
[--flight-log ...] --out <report.json> [--compare <previous report>]` -
READ ONLY (four kinds of GET, nothing else). It needs the token and talks
to ion, so run it when the owner asks for an audit, not as a reflex.

- Read **`best_bracket_verdict`** per asset: `ok`, `MISSING-GEOID` (the
  model is N too deep), `ambiguous` (a box taller than about N - 10 m
  cannot tell), `FAULT`. The older centre-rule `verdict` misleads where
  passes overlap.
- Or check a re-publish directly: its `best_height_ellipsoidal_m` is the
  old asset's **plus exactly N** (`geoid_n_m`). `--compare` lists what
  changed between two reports.
- The report's `conventions` block states the signs and datums: nav Alt is
  orthometric (-depth), N is positive up with h = H + N, every
  `*_height_ellipsoidal_m` is above the WGS84 ellipsoid,
  `vertical_vs_cameras_m` negative = below the cameras.
- The audit cannot see a grid-convergence turn: the H2060 meshes uploaded
  from the other machine are in UTM grid axes inside a frame ion labels
  East-North-Up (measured on `zone_1_c0`, inferred for the other 46).

## Traps

- **PROJ applies a ZERO geoid correction when the grid is missing** -
  `Transformer.from_crs('EPSG:9518','EPSG:4979')` succeeds offline and
  returns Z unchanged. Everything here passes `allow_ballpark=False`,
  which raises instead. The EGM2008 grid (~80 MB) needs a local
  `projsync --file us_nga_egm08_25.tif`, or `PROJ_NETWORK=ON` (and then
  see B26).
- **`root.boundingVolume.box` is NOT the geometry** - it is the padded
  octree root cell (20x20x20 m for a 20x8x3 m probe). Use
  `root.metadata.properties.tightBoundingBox`.
- **Can an asset be moved after tiling? UNTESTED here.** Over REST,
  `PATCH /v1/assets/{id}` accepts only name / description / attribution
  (docs sec. 17.2, FINDINGS `[CESIUM]`) and nothing in this repo moves an
  asset. Whether ion's web "location editor" can move a tiled asset has
  not been tried: this skill used to say it cannot, Cesium staff on the
  forum say it can (bottom centre of the bounding box), nobody here has
  done it. Until someone does, treat placement as fixed at creation and
  correct by re-publishing from source.
- **`3D_MODEL` + `position` fails tiling** - recorded as a
  staff-acknowledged ion bug (docs sec. 17.2); not re-tested. The code
  always sends `sourceType=3D_CAPTURE`.
- **The exported OBJ may sit in a scrambled local frame** - NA168's is
  ~350 km from its site. Never publish on the flight-log CRS alone.
- `--no-geoid` is a deliberate escape hatch and warns loudly. UNVERIFIED:
  the earlier skill said it "has never been run live".

## Nira

Nira's guidance for RealityScan is **OBJ**, and it refuses PLY point
clouds (LAS / LAZ / E57 only). UNVERIFIED: the earlier skill said "not
FBX"; the code does not say FBX is refused.
`python publish_nira.py --name <name> --dir <export>/obj --niraclient <niraclient checkout>`
(required argument); `publish_batch.py` finds the checkout through
`NIRACLIENT_DIR` instead.

## Reference

`docs/rs-reference/10-reconstruction-texturing-export.md` sec. 17.2 carries
the live-verified API contract. `docs/rs-reference/06-georeferencing-
flightlogs-and-scale.md` covers the vertical datum. `BUGS.md` B25-B28 are
the publisher's known defects and what was fixed. Raw log: `FINDINGS.md`
`[CESIUM]` entries.
