# cesium2unreal

The far end of the publish pipeline. `publish_cesium.py` pushes a RealityScan
mesh export **up** to Cesium ion; this pulls those assets back **down** into an
Unreal Engine 5.7 level, georeferenced and snapped to a terrain tileset.

```
RealityScan export ──publish_cesium.py──▶ ion ──cesium2unreal──▶ Unreal level
                                            │                        │
                              lon/lat from tileset.json         snap to terrain
                                                              + snap-report.json
```

Point it at a name pattern. It finds the matching ion assets, works out where
each one sits on the globe, spawns a `Cesium3DTileset` for each in a level you
already set up, and corrects its height against your bathymetry.

## Stdlib only, and it has to stay that way

**Unreal's bundled Python has none of this repo's dependencies** — no numpy, no
geopandas, no pyproj. So `cesium2unreal` imports nothing outside the standard
library, including its own ECEF→geodetic conversion (Bowring's closed form in
`ion_locate.py`) rather than the `+proj=geocent` path `modules/flight_logs.py`
uses. That duplication is deliberate. Refactoring it onto pyproj breaks the
Unreal half, where the failure shows up as an import error inside the editor.

## Use

```bash
set CESIUM_ION_TOKEN=...             # assets:list + assets:read, read-only
py -3.13 -m cesium2unreal.ion_locate "Transect_*" > manifest.json
```

Then in the Unreal editor's Python console (Output Log → Cmd → Python):

```python
import sys; sys.path.append(r'C:\path\to\RealityScan_CLI')
from cesium2unreal import populate
populate.run('config.json')
```

Copy `config.example.json` to `config.json` and fill in your level path,
terrain asset ID and name pattern. `name_pattern` is a case-insensitive shell
glob; prefix with `re:` for a regular expression.

## Requirements

- Unreal Engine **5.7**, with the **Python Editor Script Plugin** enabled
- **Cesium for Unreal v2.21.0+** (v2.21.0 added 5.7; v2.29.0 requires 5.6+)
- A level that already has a `CesiumGeoreference` and a terrain
  `Cesium3DTileset`

## Two halves, on purpose

`ion_locate` talks to nothing but the ion REST API and runs anywhere — CI, a
laptop, Unreal's Python. `populate` drives the editor.

The split matters because ion's `/v1/assets/{id}` returns **no geographic
extent**. Location has to come from the tileset itself: ask ion for a signed
endpoint, fetch `tileset.json`, and reduce `root.transform ×
root.boundingVolume` to a cartographic centre. Three bounding-volume shapes are
handled, and `region` is the trap — its angles are in radians and it is already
ECEF-aligned, so the root transform must *not* be applied to it.

## What it will not do

**It never creates or moves the `CesiumGeoreference`.** The georeference origin
decides where the whole globe sits relative to anything authored in Unreal
coordinates; moving it slides every tileset relative to your terrain. The level
must already have one, and the script errors out if it does not.

**It must run in a ticking editor.** Cesium's height sampler is asynchronous —
it loads the terrain tiles it needs on demand and calls back several frames
later. A `-run=pythonscript` commandlet has no tick loop and will time out at
the sampling step. Discovery is headless-safe; snapping is not.

## Height, and why the report exists

Every model is snapped to the terrain surface. That is also, by construction, a
way to hide a systematic error: Cesium heights are metres above the **WGS 84
ellipsoid**, not depth and not mean sea level. A sounding of 32 m becomes
roughly `h = N + tide − 32`, where `N` is the geoid separation — tens of metres
in most of the world.

If that conversion is wrong, snapping makes it invisible. So `populate` writes
`snap-report.json` recording the correction applied to each asset, and warns
when the corrections cluster:

```
every asset moved by -37.2 m +/- 0.3 m. That is a datum offset, not
scattered placement error — worth fixing in ion rather than re-snapping
on every import.
```

Scattered deltas are genuine placement error. A tight cluster is a datum bug,
and the right fix is upstream in ion — `options.position` at upload, or the 3D
Tiles Location Editor — so CesiumJS and everything else downstream agree.

## The offset is not a Z nudge

Unreal's +Z is "up" only at the georeference origin. `populate` converts both
the old and new cartographic positions through the georeference and uses the
difference, so the shift follows the local vertical wherever the site is.
Measured against the reference geodesy in `tests/`, the horizontal component a
raw Z nudge would get wrong:

| distance from origin | error |
|---|---|
| 5 km | 1.6 cm |
| 50 km | 16 cm |
| 200 km | 63 cm |

## Tests

```bash
py -3.13 cesium2unreal/tests/test_populate.py     # or: pytest cesium2unreal/tests
```

`tests/fake_unreal.py` stands in for the editor, implementing the real
ECEF→ESU geodesy rather than a stub, so the offset assertions mean something.
Ten tests cover placement, idempotency on re-run, the terrain being excluded
from its own population, unsampled sites being left alone, the datum warning,
and both offset cases. No Unreal required.

What the tests **cannot** cover is whether the plugin's Python bindings match.
`SampleHeightMostDetailed` is a Blueprint async node whose factory and
`Activate` are `BlueprintInternalUseOnly`, so they get no snake_case binding
and are reached through `call_method()`. Verify once per project, in the editor
console:

```python
import unreal; print(hasattr(unreal, 'CesiumSampleHeightMostDetailedAsyncAction'))
```

If that prints `False`, the sampling step needs an Editor Utility Blueprint
wrapper instead.
