# RealityScan 2.2 installation audit and selected XML repair

`modules.rs_installation` provides a read-only installation audit and a separate,
explicit repair interface. It never launches RealityScan, inherits saved settings,
installs software, or repairs anything while inspecting. The default directory is
`C:/Program Files/Epic Games/RealityScan_2.2`. Supply `--install-dir` to choose a
different directory containing `RealityScan.exe`.

## Current strict guards and legacy behavior

The project execution lane sets `RS_NO_SETTINGS_INHERITANCE=1`. Either that
flag or `RS_REQUIRE_INSTALL_CONTRACT=1` enables the strict guards below. Empty,
`0`, `false`, `no`, and `off` disable an individual flag; any other nonempty
value enables it. One disabled flag cannot override the other enabled flag.

| Code | Current behavior and integration consequence |
| --- | --- |
| `flightlog_format.INSTALL_DIRS`, `installed_path()` | Without an explicit audit directory, `RS_EXECUTABLE` selects its parent after validating actual RS 2.2 resources. An invalid explicit executable or missing adjacent XML never falls back. Strict mode without an executable uses only the validated default 2.2 directory. Generic/legacy discovery remains only for nonstrict callers without an explicit executable. An explicit `install_dir` passed to this low-level lookup remains authoritative for read-only installation audits. |
| `RealityScanCLI.find_executable()` | The selected `RS_EXECUTABLE` wins over stored settings; an invalid explicit selection fails closed. Strict project execution suppresses settings inheritance and validates actual RS 2.2 resources. Older 2.1/2.0 candidates are no longer the supported execution policy. |
| `flightlog_format.MANAGED_FILES` | Authoritative list of managed application XML names and repository catalogs. Reused directly. Currently `flightlogs.xml` and `calibration.xml`. |
| `flightlog_format._parse()`, `configured_guid()` | Legacy helpers tolerate `&tab;` and extract a GUID. Strict guards reuse `rs_installation._xml()` and its `_semantic()` hashes, require one exact params GUID entry, and reject duplicate definitions, malformed XML and DTD/entity declarations. |
| `assert_format_installed()`, `assert_calibration_format_installed()` | **Strict:** read-only validation of the selected GUID against the repository definition, including fields, indices, parser settings and export template text. Missing or drifted GUIDs refuse execution with a repair proposal. An `install_dir` conflicting with `RS_EXECUTABLE` is refused. **Legacy nonstrict:** missing GUIDs can still trigger additive automatic repair; an existing GUID alone is accepted. |
| `install_all_managed()` | **Strict:** validates standard required import/export contracts and returns zero additions, without writing. This protects the existing unconditional pre-export call. **Legacy:** adds absent GUIDs to managed XML. |
| `install_repo_formats()` | **Strict:** refuses automatic installation and directs the caller to selected repair. **Legacy:** adds absent GUIDs, uses one `.bak` name and writes directly; it neither corrects drift nor implements the reviewed atomic repair API. |

Strict guard failures raise `FlightLogFormatError`. For repairable missing or
changed GUIDs, its `repair_proposal` attribute contains the concrete read-only
`rs_installation.propose_repair()` result: selected GUID, target, hashes, diff and
repair ID. The UI can present this proposal and pass the approved ID to
`apply_repair()`. Nothing in a guard invokes that mutating API. If the executable,
XML, or params cannot be validated, `repair_proposal` is `None` and the diagnostic
directs the operator to inspect/select the installation or restore vendor XML
before proposing a repair. Missing whole XML files are never created implicitly.

These checks compare the selected contract immediately before use; they do not
lock out an external application updater. Reinspect after an update and keep
external writers quiescent during processing or an explicitly approved repair.

## Read-only inspection

```powershell
python -m modules.rs_installation inspect
python -m modules.rs_installation inspect --install-dir 'D:/Applications/RealityScan_2.2'
```

Exit status is 0 when `ready` is true and 2 otherwise; output is JSON. This verdict
covers installation resources and required XML contracts only. It does not certify
dataset readiness, licensing, GPU support, or an actual import/export result.

Validation checks the executable's Windows version resource without executing it:
product name must be RealityScan, and both file and product versions must be 2.2.
The report includes the executable SHA-256, full version strings, and fixed numeric
versions. These representations can differ: the shipped build string 119430 exceeds
the fixed resource's 16-bit component and is stored there as 53894. A missing exe,
unreadable resource, wrong product or unsupported version produces a diagnostic
asking for a user-selected RS 2.2 directory. There is no older-version fallback.

Each managed file reports separate application and repository paths, whole-file
SHA-256 hashes, root attributes under `version`, root names, per-GUID contract hashes,
field mappings, and missing/extra/changed GUIDs. XML generally has no independent
version field: empty root attributes are reported as `{}`, never inferred from the
application build. The executable version and content hashes provide provenance.
Readable malformed XML retains its whole-file hash along with its parse error.

The application XML is the registry RealityScan reads. The repository XML is the
catalog of definitions this pipeline knows about; it is not a complete replacement
for the vendor registry. In particular, shipped `calibration.xml` uses `<Calibration>`
while the repo extension catalog uses `<CalibrationExport>`. Both wrappers are
recognized, and repair preserves the application's wrapper and attributes.

Readiness requires the GUIDs selected by both standard flight-log params files and
`RegistrationExportParams.xml` to exist and match their repository contracts. Pass
`--params PATH` to check an additional flight-log params file. Checking only the GUID
or the maximum column index is insufficient: swapped fields, changed parser options,
or a different reader can still parse the wrong values. The report contains actual
field names, zero-based indices and format attributes on both sides.

The current default import GUID is `{D1F2A3B4-5C6D-4E7F-8A9B-0C1D2E3F4A5B}`:

| Index | Field | Index | Field |
| --- | --- | --- | --- |
| 0 | Image | 7 | Yaw |
| 1 | X | 8 | Pitch |
| 2 | Y | 9 | Roll |
| 3 | Altitude | 10 | YawAccuracy |
| 4 | XAccuracy | 11 | PitchAccuracy |
| 5 | YAccuracy | 12 | RollAccuracy |
| 6 | AltitudeAccuracy | 13 | FocalLength |

Different vendor catalogs, extra third-party GUIDs, cosmetic dialog labels and
XML indentation do not by themselves fail readiness. Contract comparison ignores
`desc`/`descID` and formatting around elements, while preserving import attributes
and exact export `<body>` text. Differences in non-required GUIDs are advisory;
whole-file equality with the repository is never required. This is a structural
contract comparison, not a complete interpreter of RealityScan's format language.

Save an inspection JSON in an operator-selected workspace to compare later using
`inspect --baseline PATH`. Drift lists before/after executable versions/hashes and
application/repository XML hashes/root attributes. A different installation path or
unsupported snapshot schema is refused. Hash drift is informational; present required
contracts determine readiness.

## Concrete proposals and explicit application

The API has four entry points:

```python
validate_installation(install_dir=None)
inspect_installation(install_dir=None, *, params_path=None, baseline=None)
propose_repair(install_dir, filename, guids)
apply_repair(proposal, *, selected_repair_id)
```

Choose a managed file and one or more GUIDs. A proposal contains exact paths,
add/replace actions, before/after definitions, a unified diff, resulting UTF-8 XML,
source/target/executable hashes, application versions, and a content-derived
`repair_id`. Proposal creation does not change the installation; the CLI writes
only the specified new proposal file and refuses to overwrite an existing file.

```powershell
python -m modules.rs_installation propose --file flightlogs.xml --guid '{D1F2A3B4-5C6D-4E7F-8A9B-0C1D2E3F4A5B}' --output 'D:/OperatorWorkspace/repair.json'
```

Review the proposal's exact diff and selected GUIDs. A changed existing GUID may
represent a deliberate local customization; selecting its repair explicitly replaces
that one definition with the repo definition. No GUID is selected automatically,
and requesting an already-matching or unknown GUID is refused. Missing entire XML
files, unsupported encodings, malformed registries, duplicate IDs, self-closing root
elements and unfamiliar root names need diagnosis rather than reconstruction from
the partial repo catalog.

After the operator explicitly chooses that proposal, application requires its exact
ID as a separate argument:

```powershell
python -m modules.rs_installation apply 'D:/OperatorWorkspace/repair.json' --repair-id '<reviewed repair_id>'
```

The new module does not elevate itself or interpret elapsed time as permission.
Program Files may require an operator-elevated shell. No application of a proposal
to Program Files was performed during this implementation.

Application rebuilds the proposal from current resources and refuses altered or
stale proposals. It acquires an exclusive sibling lock, writes and fsyncs a sibling
temporary file, verifies its format contracts, creates and fsyncs a unique exclusive
backup, and replaces the target with `os.replace`. It verifies the resulting hash.
Existing backups are never overwritten. A failed replacement leaves the original
and a recovery backup; temporary files and this operation's lock are cleaned up.
A crash can leave a lock/temp file for operator diagnosis; stale locks are not
automatically deleted.

Edits splice only selected `<format>` byte ranges or append absent definitions
before the real root close tag. Unselected content, BOM, original line endings,
comments, CDATA, unknown elements and vendor/third-party formats remain byte-for-byte
unchanged. Added/replaced blocks use the repository's bytes. Application rejects
symlink/junction paths, hardlinked target files and a repo catalog used as its own
application target. Repairs are atomic per XML file, not across several files.

The lock coordinates this module's callers; it cannot lock out the application,
updater or unrelated editors. Those writers must be quiescent. Rechecks detect
observed drift, but an external write between the final check and replace remains
a race. Backup/atomic replacement protects file content; it is not a transaction
over NTFS ACLs, alternate streams or application state.

## Evidence and verification, 2026-09-11

The rs-lookup source route is `docs/rs-reference/06-georeferencing-flightlogs-and-scale.md`,
section 2.3: format GUIDs and zero-based field mapping are [OFFICIAL] and
[VERIFIED-by-inspection]. The repo's `FlightLogParams.xml` pins the 14-column GUID;
the older 13-column discussion in that reference is historical. The new module
uses the actual params and catalog files rather than that historical column count.

[VERIFIED-by-inspection] The selected default installation reports product version
`2.2.0.119430`, file version `2.2.0.119430.RS`, and executable SHA-256
`a0ad8b75e7f15865322e5dcc05856df60005502379d035d0816f840a4240583e`.
The corrected live audit returns `ready: true`; both default import mappings and
the required registration-export contract match. The legacy, non-required
`{B438A617-2434-5A24-C1B7-58980F28345A}` definition differs and is reported without
automatically replacing it. The application catalogs include additional GUIDs.

[VERIFIED offline] `python -m pytest testing/test_rs_installation.py -q`:
**52 passed**. Fixtures exercise version/path refusals, complete mapping checks,
root-role differences, hash drift, selected add/replace, BOM/CRLF/entity/CDATA
preservation, stale and tampered proposals, backup preservation, failed replacement,
cooperating locks, hardlinks, and a target changed during temporary-file preparation.
All repair targets are temporary fixtures; no tests launch RealityScan.

[VERIFIED offline, strict-guard integration] The focused combined run
`python -m pytest testing/test_flightlog_install_contract.py testing/test_flightlog_format.py testing/test_rs_installation.py -q`
passed **95 tests**: 35 strict-contract cases, 8 legacy format cases, and 52
installation audit/repair cases. The new cases cover same-GUID semantic drift,
missing GUID proposals, unchanged installation bytes, malformed/ambiguous XML,
explicit executable precedence and refusal, flag precedence, both automatic
installation entry points, and continued legacy additive behavior. This run used
mock executable version resources and temporary XML, not an actual RS operation.

Full-suite runs belong to the main integration agent. The initial concurrent
baseline had 1062 passed, 1 skipped and 3 shared attach-marker failures; all 8 attach
tests passed when their marker directory was isolated in memory. That is evidence
of the concurrency problem, not a claim that a new full suite passed. No further
full-suite runs were made by this worker after coordination.
