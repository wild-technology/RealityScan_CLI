# ROVScan installation and dependency gate

The deployment target is regular **CPython 3.13, AMD64, Windows 11**. Use a
complete checkout/source release, including `modules`, `desktop`, `integrations`,
the RealityScan scripts/XML catalogs and `packaging`. Python and licensed
RealityScan 2.2 are separate, explicit owner-managed installations. The bootstrap
does not install either, invoke RealityScan, request elevation, alter global
Python/PATH, or change file associations during installation.

## Chosen distribution

This is a source release plus a managed `venv`, not a frozen executable/MSI.
The application uses Qt, NumPy/SciPy, GDAL/PROJ, OpenCV, external batch scripts
and versioned XML resources. Keeping their supported wheels and filesystem
layout avoids inventing an untested freezing/resource-discovery layer.
[Python documents venv isolation and its non-portability](https://docs.python.org/3.13/library/venv.html).
Keep the source release and base Python at their selected paths; recreate the
environment after moving either. Activation is unnecessary: launch its absolute
Python executable. ARM64, 32-bit, free-threaded Python and other Python minor
versions are refused by this lock, not implicitly declared compatible.

The source release itself is trusted input. Hashes authenticate selected package
artifacts against the reviewed lock; they are not a signature for the source
checkout or a guarantee that upstream package code is safe. A production release
still needs a source revision/archive digest and clean-machine acceptance.

## Dependency audit and provenance

`requirements.txt` and `requirements-desktop.txt` contain exact **direct** pins.
The old lower bounds excluded the actual reference NumPy 2.4.3, Matplotlib 3.10.8
and Pillow 12.1.1. The audit added `pygeomag` for magnetic declination and moved
the navigation imports FilterPy/rasterio into the base runtime dependency list.
PySide6 is the additional desktop input. Archived TUI, CUDA/COLMAP experiments
and unrelated packages installed on the reference computer are not bundled.

`packaging/deployment-lock.json` is authoritative: 59 packages, comprising 56
runtime distributions and three installation tools (`pip==25.1.1`,
`setuptools==70.2.0`, `wheel==0.45.1`). It includes **pandas 3.0.5**, **PySide6
6.11.2**, its matching Essentials/Addons/shiboken6 distributions, and the complete
Windows dependency closure. **pytest is not a runtime dependency and is not in
this deployment lock.** The repository's existing developer/test environment
remains separate; this bootstrap does not install an optional testing profile.

Each locked package records its version, active Requires-Dist constraints,
Requires-Python, metadata URL, selected artifact URL/filename/byte size/SHA-256,
publication time and smoke-import modules. The exact compatible wheel was chosen
using `packaging.tags.sys_tags()` on CPython 3.13.5/Windows AMD64. Versions came
from the installed reference environment, except previously documented
`pygeomag==1.1.0` and the pinned pure-Python wheel build tool. The generator
verifies the active dependency constraints against **official PyPI metadata**;
it neither resolves floating versions nor installs packages.

`packaging/refresh_lock.py` is a maintainer-only regeneration tool. Run it in a
reviewed reference environment after changing direct pins, then review all
artifact/version changes and rerun the scoped tests. `tools.lock`, `wheels.lock`
and `source.lock` are reviewable pip representations. The bootstrap derives
equivalent hash requirements from the JSON, so edited sidecar lock text cannot
silently change its install inputs. Exact versions plus hashes follow
[pip's repeatable-install guidance](https://pip.pypa.io/en/stable/topics/repeatable-installs/)
and [hash-checking requirements](https://pip.pypa.io/en/stable/topics/secure-installs/).

### FilterPy source exception

[FilterPy 1.4.5 publishes only a source ZIP](https://pypi.org/project/filterpy/1.4.5/).
Its [tagged setup.py](https://raw.githubusercontent.com/rlabbe/filterpy/1.4.5/setup.py)
declares NumPy, SciPy and Matplotlib and no compiled extensions. PyPI's legacy
metadata omits Requires-Dist, so the generator explicitly records those three
dependencies from that source. No other package may fall back to a source build.

The bootstrap installs the pinned pip/setuptools/wheel tools first, then all
runtime wheels, then that exact source ZIP. Every pip phase uses `--no-index`,
`--no-deps`, `--require-hashes` and `--no-cache-dir`. FilterPy uses
`--no-build-isolation`, so there is no floating build-environment download;
[pip makes the caller responsible for those build dependencies](https://pip.pypa.io/en/stable/reference/build-system/).
Its runtime import passes on the reference Python 3.13 machine. Main's subsequent
explicitly authorized managed-environment validation also **built FilterPy
successfully** using this bootstrap and its pinned build tools (evidence below).
Locked inputs do not claim byte-identical locally built wheel output.

## Plan, install, launch

Use a trusted, explicitly selected Python 3.13 AMD64 installation. In PowerShell,
set `$Python` to its absolute `python.exe`, `$Source` to this release's absolute
directory and `$InstallDir` to a new empty installation directory. Never choose
source imagery as the destination. Use an explicitly owned application directory
or an approved project temporary directory for validation. Installation state/artifacts
live directly in `$InstallDir` and the actual venv is **`$InstallDir\env`**.

```powershell
# Read-only plan. No downloads, environment creation, package or registry writes.
& $Python -I -B "$Source\packaging\bootstrap.py" plan --destination $InstallDir

# Explicit install action: downloads verified artifacts, creates an isolated venv.
& $Python -I -B "$Source\packaging\bootstrap.py" install --destination $InstallDir

# All subsequent launches use this executable, not the original/global Python.
& "$InstallDir\env\Scripts\python.exe" -I -B "$Source\packaging\launch.py"
& "$InstallDir\env\Scripts\python.exe" -I -B "$Source\packaging\launch.py" $ProjectDocument
```

The default bootstrap action is `plan`; `--destination` is required. If its parent
does not exist, the plan returns `ready_to_install: false` and a concrete
`create_install_parent` action with the exact path; it creates nothing. The
explicit `install` action refuses until that selected parent exists. A nonempty
unowned directory, a different lock/source/interpreter ownership record, or a
destination inside/containing global Python is refused. Paths are argv elements,
never interpolated into cmd/PowerShell shell code. Downloaded artifacts are
bounded by their locked byte sizes and promoted only after SHA-256 verification.
Installation disk exhaustion is a reported failure, not a reason to clean data.
The plan's artifact byte total excludes extraction/installed size; provision
additional space for the venv, source-build scratch and logs. Project capacity
is independently enforced by the existing storage policy before processing.

`ready.json` appears only after `pip check`, exact version checks and isolated
import probes succeed. That readiness covers dependencies, not licensed software
activation, camera science, project approval, GPU/driver compatibility or live
RealityScan behavior. Launching the desktop invokes the dependency gate; its
controller must invoke the complete deployment gate before dispatching stages.

## Offline use and interrupted installation

On a connected machine with the same supported platform and reviewed source:

```powershell
& $Python -I -B "$Source\packaging\bootstrap.py" fetch --destination $BundleDir
# Transfer $BundleDir\artifacts with the matching source release/lock.
& $Python -I -B "$Source\packaging\bootstrap.py" install --destination $InstallDir --offline --wheelhouse $TransferredArtifacts
```

`fetch` is an explicit network/file-write action; it creates no venv and runs no
pip. Offline installation never falls back to a network index. Missing, truncated
or wrong-hash artifacts block with the exact filename. Verified artifacts are
reused on retry. Interrupted downloads discard only their own partial file and
restart that artifact; this is artifact-level, not byte-range, resumption.

An OS-held installation lock prevents concurrent installers. Handled pip failure
or Ctrl-C records failure after the child exits; retry the identical install
command/destination to reconcile an unfinished venv. All pinned distributions
are reinstalled there to repair partial installs, then checked again. An abrupt
parent death during child installation leaves ownership **unconfirmed**: the
bootstrap refuses in-place retry, because an orphaned pip child may still be
writing. Select a new empty destination; no unrelated processes are killed.

A verified ready environment is only checked, never automatically reinstalled or
upgraded. If its later checks fail, choose a new empty destination for repair.
Each attempt has a unique log and durable state. Logs/artifacts are retained for
diagnosis; no automatic cleanup or storage reclamation is performed. Redirected
symlink/junction install entries are refused before resuming. This is protection
against accidental redirected paths, not a hostile-local-user security boundary.

## Optional .rovscan association

Only the explicit command below writes the **current user's** registry:

```powershell
& $Python -I -B "$Source\packaging\bootstrap.py" associate --destination $InstallDir
```

It registers `ROVScan.Project` and `.rovscan\OpenWithProgids`, pointing to the
verified environment's `pythonw.exe` and this release's launcher. It preserves
the extension's existing default and Windows `UserChoice`; select ROVScan in
Windows **Open with > Choose another app** to make it the default. There is no
HKLM/admin change, PATH modification or implicit association during `install`.
This follows [Windows file-type/ProgID registration](https://learn.microsoft.com/en-us/windows/win32/shell/fa-file-types).
Code/interpreter paths with quotes, percent placeholders or control line breaks
are refused for this registry action; normal argv execution supports spaces and
ampersands. Only pass trusted `.rovscan` files to the application; the existing
project loader validates their contents.

## Controller API and actionable states

`modules.deployment_preflight` imports only the standard library before its
checks. No alternative RealityScan launcher or planner exists here.

```python
from modules.deployment_preflight import require_deployment, DeploymentBlocked
from modules.storage_policy import StorageDemand

report = require_deployment(
    install_dir=approved_executable.parent,
    project_root=project_root,
    cache_root=cache_root,
    demands=[StorageDemand(project_root, remaining_project_gib, "project"),
             StorageDemand(cache_root, remaining_cache_gib, "cache")],
    reserve_gib=approved_reserve_gib,
    probe_writes=True,                 # UI's explicit Test write access choice
    protected_roots=source_and_protected_roots,
)
```

`inspect_deployment(**same_arguments)` returns JSON-ready evidence without
raising on a failed check. `require_deployment` raises `DeploymentBlocked` whose
`.report` contains that same evidence. Fields: `ready`, `machine_ready`,
`project_ready`, `checks`, `dependencies`, `installation`, `directories`,
`storage`, `repair_choices`. Demand labels `project` and `cache` must each occur
exactly once and match the selected paths; other volume demands may be included.
Unknown estimates never become zero. `storage_policy.assess_storage` handles
mount identity, shared-volume aggregation and reserve charging.

`rs_installation.inspect_installation` supplies the actual executable's strict
2.2 resource/hash check and required XML GUID/semantic contracts. Inspection
never calls its repair methods. UI choices are select supported installation,
review a concrete XML repair proposal, install/resume a managed environment, or
review project/cache paths and capacity. Installation/repair remains a separate
explicit action. Pass the resulting selected executable to the existing child
lane as `RS_EXECUTABLE` with `RS_NO_SETTINGS_INHERITANCE=1`.

`RealityScanCLI.find_executable` also enforces 2.2 at execution discovery. An
explicit project environment path wins saved machine settings. An invalid
explicit path blocks instead of falling back to a different installation. It
captures this selection at CLI construction; recreate the CLI after approved
changes. Unchanged file identity caches resource/hash validation during status
polls; a changed identity forces revalidation. Required XML contracts remain
the full preflight's responsibility. No old 2.1/2.0 discovery candidates remain.

`inspect_dependencies(require_isolation=True)` is the setup/launcher-only gate.
Each distribution has expected/actual versions and `missing`, `metadata_error`,
`version_mismatch`, `import_error`, `binary_error`, `import_timeout`, `probe_error`
or `ok`. Selected imports run in separate isolated child interpreters with a
45-second per-import bound, so a broken DLL cannot crash the controller.
Temporary import caches are confined to system scratch and removed. The gate
does not prove GPU execution or a working on-screen Qt platform plugin.

Without `probe_writes=True`, selected directories report `unconfirmed`; ACL
guesses cannot authorize processing. With it, short uniquely named temporary
files are written/flushed/removed only in existing selected directories, after
protected/source containment checks. Probing a project root containing a protected
`raw` child is allowed because the temporary file is directly in the parent;
probing inside `raw` is refused. No source/deliverable files are touched. A
fresh full gate is needed immediately before dispatch; past free-space/write
evidence is not a reservation. `--allow-unmanaged` on the diagnostic CLI only
relaxes the venv check and must not be used as a production readiness override.

## New-computer failure matrix

| Condition | Deterministic response | Explicit recovery |
| --- | --- | --- |
| Unsupported Python minor, architecture, implementation or Windows build | Platform gate blocks before install | Select supported regular CPython 3.13 AMD64/Windows 11 |
| Parent directory does not exist | Plan returns exact parent creation action; install refuses | Create that selected parent or choose another |
| Existing unowned/foreign destination | Refuse adoption; preserve contents | Choose an empty directory |
| Missing/offline artifact, wrong hash/size or interrupted download | No affected artifact is promoted or installed | Supply matching bundle or retry network; prior verified artifacts remain |
| Floating/inherited pip index, target or config | Removed; offline pip with explicit hashes/argv | Repair the reviewed lock/bundle, not a global pip setting |
| FilterPy source build failure | No ready marker; detailed unique install log | Review pinned build failure; retry only after handled child exit |
| Graceful interrupt or failed pip exit | Wait for child, record failed state | Resume identical unfinished destination |
| Abrupt death with possible live child / Popen outcome unknown | Refuse in-place retry | Select new empty destination; reconcile abandoned environment separately |
| Concurrent installer | OS lock refuses second owner | Wait for the first owner to finish |
| Missing package, exact-version drift, broken native import | Dependency gate blocks | Explicit new managed environment repair |
| Wrong RS version or XML contract | Shared installation gate and CLI version discovery refuse | Select RS 2.2 or review/apply a separate selected XML repair |
| Protected output path, failed write probe, unknown/low free space | Project gate blocks | Review selected paths and volume budgets; no automatic cleanup |
| Ready environment later damaged | Check fails without reinstalling it in place | Create and verify a replacement environment |
| Association not requested | Registry untouched | Run separate `associate`, then choose Windows default if desired |

## Verified limits (2026-09-11)

The latest scoped run passed **70 deployment tests**. An earlier combined scoped
run passed **146 deployment/runtime/progress tests** before the additional
protected-raw-child regression. The final attach fixture change only overrides
`find_executable` for its intentional `.bat`/`.sh` fake; it does not bypass strict
2.2 checks in production. Main owns the pending full-suite run, including that
updated attach fixture; the packaging agent did not run shared-marker fixtures.

Focused offline tests cover platform/version failures, exact dependency closure,
import/native failures, writable/protected paths, storage composition, hash and
network failures, offline behavior, installer ownership/resume, quoting, opt-in
registry writes (mocked), and actual CLI discovery against mocked version
resources. They never install packages or boot RealityScan.

On the existing CPython 3.13.5 AMD64 / Windows build 26200 environment, all 55
installed runtime distributions matched the lock and the configured import
probes passed. `pygeomag==1.1.0` is missing, so the 56-distribution runtime gate
correctly refuses readiness. That environment is global, which the normal
production isolation check also refuses. It was not modified by the bootstrap.

### Owner-authorized managed installation evidence

Main subsequently ran the explicit `install` action under the owner's deployment
validation authorization. This reference installation is **READY**:

- Interpreter: `F:/NA171/proc/tmp/deployment_validation/env/Scripts/python.exe`.
- Log: `F:/NA171/proc/tmp/deployment_validation/install-317b15c4bb544c138d3988f5d6b9538b.log`.
- `state.json`: `{"phase": "ready", "ready": true}`; matching `ready.json` exists.
- CPython 3.13.5, AMD64, Windows build 26200, `isolated_environment: true`.
- All **59 exact distribution checks** passed: 56 runtime plus three build tools;
  every configured import probe passed, with no non-`ok` package rows.
- The log records `Successfully built filterpy` and `No broken requirements found.`
- Lock identity: `2179863e8471514906cb13e5822249779250bc95008b5b3b8defc2cc3ea847e7`.
- Manifest file SHA-256: `bf8178d145ea86c0d7816b5d878199066dd2a593b78ea613827e9622d57402dd`.

The packaging agent subsequently read those completed log/state/ready records
without modifying the installation. No lock regeneration occurred during the
install. These paths identify reference evidence only; the installer has no
campaign-specific path or parameter defaults.

This validates creation of a new isolated environment **on this existing machine**,
including the source-build exception. It does not establish fresh-machine Windows
prerequisites, an offline bundle transfer, real registry association, on-screen Qt
platform plugins, GPU/driver behavior, RealityScan licensing, actual XML import
semantics or a full photogrammetry run. Those remain separate acceptance work.
No full test suite, commit or licensed application operation was performed by the
packaging agent. Main owns integration and the full-suite validation.
