---
name: publish-cesium
description: Publish a mesh to Cesium ion at its real depth, or diagnose an asset sitting at the sea surface. Use when asked to publish, upload to ion, share a model, fix an asset's position or altitude, or when Cesium "ignores depth". Also covers Nira publishing and the batch publisher.
disable-model-invocation: true
---

# Publishing to Cesium ion

`python` = the interpreter with the deps (CLAUDE.md "Environment";
`py -3.13` where the launcher exists).

**ion honours below-ellipsoid heights exactly.** A probe asked for
h = -512.46 m and read back h = -512.46 m, error -0.000 m. If an asset
sits at the surface, the fault is upstream - it is one of these two:

1. **RealityScan's own "Share to Cesium ion" never georeferences.** Epic's
   Help says the model "does not have to be georeferenced ... define its
   approximate position" later - i.e. hand-placed at ~sea level.
2. **The project CRS is 2D and declares no vertical datum**, while the Z
   it carries is a depth below the **sea surface**. Cesium reads every
   height as above the **ellipsoid**. The gap is the geoid undulation N:
   **+72.69 m** at NA168 H2080, +70.4 m Solomon Sea, -27.1 m Gulf of
   Mexico.

`modules/cesium_placement.py` closes both: it reads the export's `.rsInfo`
for CRS and `transformToModel`, DERIVES which reading of that matrix is
correct (validated against the CRS area of use, the dive's nav envelope,
and a determinant test that rules out mirrored readings), converts
sea-surface depth to ellipsoidal height through EGM2008, and localises the
mesh into East-North-Up metres.

## Publish

```bash
python publish_cesium.py --name "<name>" --dir <export>/obj \
    --flight-log <cruise>/raw_images/flight_log_<zone>_UTM.txt --poll --verify
```

**Never publish without `--verify`.** It decodes the finished tileset
independently and checks the placement that actually landed.

Plan without uploading: `--dry-run`. Whole workspace:
`python publish_batch.py --workspace <ws> --prefix "<wreck>"`.

## Traps

- **PROJ applies a ZERO geoid correction when the grid is missing** -
  `Transformer.from_crs('EPSG:9518','EPSG:4979')` succeeds offline and
  returns Z unchanged. Everything here passes `allow_ballpark=False`,
  which raises instead. The EGM2008 grid (~80 MB) needs
  `PROJ_NETWORK=ON` or a local `projsync`.
- **`root.boundingVolume.box` is NOT the geometry** - it is the padded
  octree root cell (20x20x20 m for a 20x8x3 m probe). Use
  `root.metadata.properties.tightBoundingBox`.
- **ion cannot reposition after tiling.** `PATCH /v1/assets/{id}` accepts
  only name/description/attribution. Placement must be right at creation;
  fixing an old asset means re-publishing from source.
- **`3D_MODEL` + `position` is a staff-acknowledged ion bug** (tiling
  fails). Use `sourceType=3D_CAPTURE`.
- **The exported OBJ may sit in a scrambled local frame** - NA168's is
  ~350 km from its site. Never publish on the flight-log CRS alone.
- `--no-geoid` exists as a deliberate escape hatch, warns loudly, and has
  never been run live.

## Nira

Nira wants **OBJ, not FBX**, and refuses PLY point clouds.
`python publish_nira.py --name <name> --dir <export>/obj --niraclient <niraclient checkout>`
(required argument); `publish_batch.py` finds the checkout through
`NIRACLIENT_DIR` instead.

## Reference

`docs/rs-reference/10-reconstruction-texturing-export.md` sec. 17.2 carries
the live-verified API contract. `docs/rs-reference/06-georeferencing-
flightlogs-and-scale.md` covers the vertical datum. Raw log: `FINDINGS.md`
`[CESIUM]` entries.
