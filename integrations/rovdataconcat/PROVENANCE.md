# ROVDataConcat integration

Upstream: https://github.com/wild-technology/ROVDataConcat

Imported baseline: `93ea56a` (main, fetched 2026-09-11). The source belongs to
the same owner's GitHub organization. No third-party licence is asserted here.

This directory is the distributable, audited integration. `.external/` is a
development checkout and is never a runtime dependency. Local changes add an
explicit single-dive entry point, separate immutable raw copies from generated
outputs, recognize tab-delimited statistics named `.csv`, derive expedition
identity from report data, and validate duplicate-index selection and UTM edges.
Scientific assumptions remain explicit in the navigation quality report.

The SDYN integrity revision uses the full UTC receipt prefix to resolve the GGA
acquisition date across adjacent days, with an explicit 60-second disagreement
limit. It retains the existing filename rollover rule only for bare legacy GGA
and counts that fallback. Checksum, quality/beacon policy, fields and numeric
ranges are checked before use; rejected observations have reason counts and
bounded source-line examples. These are integrity rules, not sensor calibration.

The single-dive planner selects DAT/SDYN logs by record-time coverage (unknown
coverage remains included for diagnosis), including renamed/multi-day files.
Coverage assessment may read a complete non-overlapping log; it does not copy
the whole expedition by default. Execution passes only hashed manifest entries
to the DAT/SDYN processors, preventing accumulated raw copies from silently
entering a later attempt. Original files and prior candidates remain unchanged.
This revision does not tune 3-sigma rejection, Kalman noise, bottom-lock policy
or uncertainty interpretation. A comparison of existing raw copies does not
authorize a fresh navigation run or establish absolute accuracy.

The subsequent inventory latency correction separates `source_window` (shared
delivery/dive-report validation only) from full `source_plan` coverage. The full
planner accepts caller-owned metadata-identity coverage caching and cooperative
cancellation/progress, without source or cache writes. Window-only callers must
not request the full plan. This correction has focused offline evidence; the
existing live inventory worker was neither interrupted nor reconfigured.

Run tests from this directory: `python -m pytest tests -q`. Run `navigation.py
--help` for the source/project contract. Default invocation prints a copy plan;
`--execute` creates a fresh attempt. The final vehicle table excludes the
terrain-offset visualization stage. Do not use `kalman_offset` output as camera
navigation.

Future upstream updates must be diffed against this baseline and pass this
integration's tests plus the main application's navigation contract tests.
