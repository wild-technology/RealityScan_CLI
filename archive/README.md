# Archive

Kept for reference and provenance; nothing here is imported by live code
(`modules/`, the root drivers, `rs.py`) and nothing here is wired back in.
`docs/history/README.md` maps every 2026-09-05 relocation old -> new.

| Folder | Contents |
|---|---|
| `wildscan_tui/` | The WildScan Textual console - archived 2026-09-05 but FUNCTIONAL (`python archive/wildscan_tui/run_wildscan.py <ws>`); its planner now lives in `modules/run_plan.py`. |
| `probes/` | Probe and one-off `.bat` workflows retired from `RS_CLI/Scripts/` (calibration-group, flight-log, settings-dump probes; NightGrow; CalibCellAlign). |
| `campaign_drivers/` | Finished campaign drivers (H2023/H2024/NA167/ON2026) and analysis one-offs; citation targets for FINDINGS. |
| `legacy_scripts/` | Superseded `.bat` workflows. |
| `colmap/` | Retired COLMAP scripts and the frozen COLMAP fact base (`colmap/docs/`). |
| `reference_data/` | `sensorsdb.xml` - RealityScan's install-tree sensor database, read by nothing here. |

## colmap/

COLMAP-based reconstruction and vocabulary-tree training scripts. The active
pipeline uses RealityScan 2.2 exclusively; these are retained only in case a
COLMAP workflow is ever revisited.

| Script | Purpose |
|---|---|
| `colmap_processor.py` | Hierarchical COLMAP reconstruction (per-zone SfM → align → merge → global bundle adjustment). Hardcoded to `E:/RUMI/NA173_H2102`. |
| `vocabtrainer_shipwrecks.py` | COLMAP vocab-tree trainer for the NA173 + Zeuss dive datasets (256k visual words). Most complete variant. |
| `vocabtrainer_shipwrecks2.py` | Slimmed variant of the above with per-camera decimation (175k visual words). |
| `vocabtrainer_shallow.py` | Resumable variant retargeted at the `NA173 Shallow` dataset (50k visual words). |

The three `vocabtrainer_*.py` scripts are near-duplicates of one trainer with
different datasets/decimation settings; if the tool is ever needed again,
consolidate them into a single parameterized script rather than resurrecting
all three.

No Gaussian-splatting scripts existed in the repo at the time of archiving.

### colmap/docs/

`COLMAP_CROSSOVER.md` (the inventory of where COLMAP and RealityScan
material touched, 2026-07-24) and `COLMAP_FINDINGS_UNIFIED.md` (the frozen
COLMAP fact base received from the owner). Canonical home is the
colmap_studio repo; these are read-only copies moved from `docs/` on
2026-09-05.
