# Reference data (archived 2026-09-05)

| File | What it is |
|---|---|
| `sensorsdb.xml` | A copy of RealityScan's install-tree sensor database (camera sensor sizes). No code in this repo reads it; RealityScan resolves its OWN copy under the install directory. Kept as the source `docs/rs-reference/05-metadata-xmp-and-sidecars.md` was written from. |

The two format files RealityScan DOES need from this repo - `flightlogs.xml`
and `calibration.xml` - stay at the repo root: `modules/flightlog_format.py`
merges them into the install directory before every align.
