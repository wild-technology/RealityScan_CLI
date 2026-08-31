# First run on real data

A checklist for the first time this touches a real survey. The short version:
get four things ready the night before, then run `preflight` before anything
else in the morning.

## The night before

**1. A read-only ion token.** Not the one `publish_cesium.py` uses — that has
`assets:write`. Make a second token at
[ion → Access Tokens](https://ion.cesium.com/tokens) with only `assets:list`
and `assets:read`. Nothing here writes to ion, and a read-only token means a
mistake cannot damage the assets.

**2. The bathymetry, tiled in ion, and its asset ID.** The multibeam surface
has to be an ion asset like everything else — this reads heights from it by
streaming it, not from a local grid. Note the asset ID from the ion dashboard;
it goes in `terrain_ion_asset_id`.

**3. Model assets `COMPLETE`, with names that a pattern can select.** Check the
ion dashboard: anything still `IN_PROGRESS` is skipped. The pattern must match
your models and **not** the bathymetry — the terrain is filtered out by asset
ID as a backstop, but a pattern that sweeps it in will confuse the report.

**4. A level, saved, containing both:**

- a `CesiumGeoreference` with its origin set near the survey area — within a
  few tens of km, since precision degrades further out
- the bathymetry as a `Cesium3DTileset`, added through the Cesium panel, and
  visibly loading in the viewport

Plus the plugins: **Cesium for Unreal v2.21.0+** and the **Python Editor Script
Plugin** (Edit → Plugins → search "Python"), then restart the editor.

**Work on a copy of the level.** The script spawns actors and saves. Nothing
targets `main`, but a copy makes the first run free.

## In the morning

### 1. Build the manifest — no Unreal needed

```bash
set CESIUM_ION_TOKEN=...
py -3.13 -m cesium2unreal.ion_locate "Transect_*" > manifest.json
```

Open it. Every entry should carry `lon`, `lat`, `height`, `height_min`,
`height_max`, `radius_m`. **Check two or three coordinates against where the
survey actually was.** If they are in the wrong ocean, the problem is upstream
in how the assets were uploaded, and no amount of Unreal will fix it. This step
costs nothing and catches the worst class of error before the editor is
involved.

Entries with an `error` key could not be located — usually an asset that is
not `COMPLETE`.

### 2. Preflight, in the editor

Open the level. Window → Output Log, switch the **Cmd** dropdown to **Python**:

```python
import sys; sys.path.append(r'C:\path\to\RealityScan_CLI')
from cesium2unreal import populate
populate.preflight('config.json')
```

It changes nothing and prints a PASS/FAIL line per check, with the fix on the
failures. Do not skip it — it answers the one question nothing else can:

```
PASS  height sampler binding
```

That line is the real unknown. `SampleHeightMostDetailed` is a Blueprint async
node whose factory is `BlueprintInternalUseOnly`, so it reaches Python only
through `call_method()`, and nothing guarantees the binding exists. **If it says
FAIL, stop** — the height-sampling half cannot run and needs an Editor Utility
Blueprint wrapper instead. Everything up to step 1 is still valid.

### 3. The run

```python
populate.run('config.json')
```

Sampling is asynchronous: it loads terrain tiles on demand and calls back
several frames later. **Keep the editor focused and ticking** — do not alt-tab
away, and do not run this from a `-run=pythonscript` commandlet, which has no
tick loop and will sit there until the 300 s timeout. Wait for
`done — level saved`.

## Reading `snap-report.json`

The point of the first run is this file, not the viewport.

| field | what to look at |
|---|---|
| `placement` | `anchor` per group, `offset` carried with it, `carried` for no terrain of its own, `unsampled` for a group that found none |
| `delta_m` | the correction applied. Identical across a group, by design |
| `base_above_seafloor_m` | how far the model's base sits above the seafloor beneath it. `0` for the anchor; for a seawall, its height above the floor — a survey number worth checking against what you saw |
| `summary.outliers` | groups whose correction disagrees with the rest |

Three patterns and what they mean:

**Everything `unsampled`.** The bathymetry tileset has no coverage at those
coordinates. Cross-check a manifest lat/lon against the bathymetry's extent in
the ion dashboard — this is usually a CRS mismatch at upload, not a bug here.

**Every group moved by nearly the same large amount.** That is the geoid, and
the warning says so. Correcting it here works but hides it; the real fix is
upstream in ion so CesiumJS and everything else agree.

**One group in `summary.outliers`.** A stray vertex at the bottom of one model
dragged its group's correction. `height_min` comes off the root bounding
volume, which is an extremum, so a single bad point decides the shift. The
planned fix is `depth_anchor: "surface_percentile"` — sampling a grid across
the footprint against both tilesets and taking a high percentile of the
residual rather than its maximum. The seam is in place (`DEPTH_ANCHORS` in
`populate.py`) and it is not implemented yet; the report telling you it is
needed is the point of this first run.

## If something goes wrong

| symptom | cause |
|---|---|
| `no CesiumGeoreference in this level` | level not set up; the script will not create one, because its origin decides where the globe sits relative to your terrain |
| `terrain tileset not found` | `terrain_ion_asset_id` does not match any `Cesium3DTileset` in the level |
| timed out after 300 s | editor not ticking, or terrain tiles not loading — check the token and asset ID by looking at the terrain in the viewport |
| `CesiumSampleHeightMostDetailedAsyncAction is not in the unreal module` | plugin older than v2.21.0, or the binding is not exposed |
| models appear but at the wrong depth | read `delta_m` before moving anything — this is what the report is for |

Re-running is safe. Placement is idempotent on the ion asset ID: it rebinds the
actor already carrying each one rather than spawning duplicates.
