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

## The seafloor is the depth datum

Multibeam bathymetry is the accurate measurement here, so the seafloor is
ground truth for depth: nothing is placed below it, and the correction that
puts models onto it is derived from it rather than guessed.

Models are grouped first — two cluster when their footprints genuinely
intersect, using the horizontal radius and vertical extent read from each
tileset's own root bounding volume, so there is no threshold to invent.
Grouping is single-link: A overlapping B and B overlapping C makes one group,
which is what consecutive survey passes look like.

Each group then gets **one rigid vertical correction**. For every member, the
lift needed to raise its deepest point to the seafloor beneath it is
`terrain − height_min`; the group takes the largest of those. The model that
most violates the seafloor ends up resting exactly on it, nothing else is left
buried, and every member moves by that same amount.

That last part is the whole point. Snapping each model onto the surface
independently — or stacking them into contact — flattens real vertical
structure. **A seawall is genuinely several metres above the seafloor its
neighbour sits on**, and that separation is a survey measurement, not an
artefact to be corrected away. A rigid shift fixes the datum without touching
the geometry between models.

Note that the binding member is the most *buried* model, not the deepest one.
Where the seafloor varies across a group, a deep model over a deep trench can
clear the bottom comfortably while a shallower one is underground; anchoring
on depth alone would leave the second buried.

| config | effect |
|---|---|
| `cluster_models` | `false` corrects every model on its own |
| `cluster_radius_m` | fixed separation in metres instead of footprint overlap |
| `seafloor_clearance_m` | lift the group this far clear of the surface; `0` rests on it |

### What the report tells you

`snap-report.json` gives each asset a `placement`:

| | |
|---|---|
| `anchor` | defines its group's correction; rests on the seafloor |
| `offset` | carried by the same shift, depth relative to the anchor preserved |
| `carried` | no terrain of its own, corrected with its group anyway |
| `unsampled` | no terrain anywhere in its group; left where ion put it |

plus `base_above_seafloor_m` — how far the model's own base ends up above the
seafloor beneath it. Zero for the anchor; for a seawall, the height of its base
above the floor. That number is a survey result, so it is worth reading.

The corrections themselves are the datum diagnostic. Cesium heights are metres
above the **WGS 84 ellipsoid**, not depth and not mean sea level: a sounding of
32 m becomes roughly `h = N + tide − 32`, where `N` is the geoid separation —
tens of metres in most of the world. If that conversion is wrong, the
correction silently absorbs it. So the summary counts one correction per group
and warns when they agree too well:

```
every asset moved by -37.2 m +/- 0.3 m. That is a datum offset, not
scattered placement error — worth fixing in ion rather than re-snapping
on every import.
```

Scattered corrections are genuine placement error. A tight cluster across
independent groups is a datum bug, and the right fix is upstream in ion —
`options.position` at upload, or the 3D Tiles Location Editor — so CesiumJS
and everything else downstream agree.

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
Twenty-three tests cover placement, idempotency on re-run, the terrain being
excluded from its own population, the datum warning, both offset cases, and
the seafloor-datum rules — that relative depths survive the correction (the
seawall case), that one shift moves a whole group, that the most buried model
rests on the surface, that nothing is left below it, that the binding member
is the most buried rather than the deepest, that clearance lifts the group,
and that a member without terrain is carried by its group. No Unreal required.

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
