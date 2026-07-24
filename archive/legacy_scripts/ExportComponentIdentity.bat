@echo off
setlocal
:: Export ONE component's identity (its .rsalign + per-camera XMP pose
:: sidecars) from a saved zone scene - the membership-capture primitive
:: behind the component manifest system (modules/component_manifest.py).
::
:: Why this exists: the RealityScan CLI cannot enumerate a component's
:: images, and XMP exports from imported-component scenes lose identity
:: (ordinal sidecars, finding B10). Identity therefore has to be captured
:: from the ORIGINAL aligned zone scene, one component at a time, with
:: the Python orchestrator reading + restoring the pose sidecars between
:: invocations (camera_registry.sanitize_and_census): after each run the
:: pose-bearing sidecars ARE that component's images.
::
:: Component export is SELECTION-driven and -selectMaximalComponent
:: always picks the LARGEST component, so per-component iteration deletes
:: the larger ones first - IN MEMORY ONLY. The scene is loaded fresh from
:: the .rsproj saved by AlignZone.bat and is NEVER saved here, so the
:: deletes and renames evaporate at -quit and the saved scene keeps all
:: of its components. Invocation k passes skip_count=k: the k largest
:: components are selected+deleted, then the (k+1)-th largest is renamed
:: and exported. One RealityScan boot per component (zones fragment into
:: 2-5 components; acceptable).
::
:: Exhaustion: when -selectMaximalComponent fails there is no component
:: left to export. That is the loop's EXPECTED terminal state, not an
:: error: the errors marker is MOVED to expected_select_%RS_INSTANCE%.txt
:: (same tolerant pattern as MergeZoneComponents.bat :run_geoimport /
:: GenerateModel.bat :try_filter) and the script exits 0 WITHOUT
:: exporting anything. The Python side detects exhaustion by the absence
:: of a new .rsalign in the output directory.
::
:: Arguments (required):
::   %1 saved zone scene (.rsproj from AlignZone.bat)
::   %2 output directory for the per-component .rsalign export
::   %3 component name to assign before export (e.g. zone_1_c0 -
::      RealityScan names the exported file after the component, so the
::      export lands as "<name>.rsalign")
::   %4 skip count: how many larger components to delete in-memory before
::      selecting the one to export (default 0)

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: scene path required & exit /b 1 )
if [%2] == [] ( echo ERROR: output directory required & exit /b 1 )
if [%3] == [] ( echo ERROR: component name required & exit /b 1 )
set "scene_path=%~1"
set "output_dir=%~2"
set "component_name=%~3"
set "skip_count=%~4"
if "%skip_count%" == "" set "skip_count=0"

if not exist "%scene_path%" ( echo ERROR: scene not found: %scene_path% & exit /b 1 )
if not exist "%output_dir%" mkdir "%output_dir%"

echo Scene: %scene_path%
echo Output: %output_dir%
echo Component name: %component_name%
echo Skipping %skip_count% larger component(s)

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Loading scene
call :run -load "%scene_path%" || goto :fail

:: A saved scene can carry a live image selection (flight-log import
:: leaves its matched images selected, and selection-driven exports under
:: -silent then silently export NOTHING - see FINDINGS.md). Clear it
:: before any export. Image selection is independent of the component
:: selection used below.
call :run -deselectAllImages || goto :fail

:: In-memory skip phase: discard the %skip_count% largest components so
:: -selectMaximalComponent reaches the target. Running out of components
:: here already means exhaustion.
if %skip_count% GTR 0 (
    for /l %%I in (1,1,%skip_count%) do (
        call :select_maximal
        if errorlevel 2 goto :fail
        if errorlevel 1 goto :exhausted
        call :run -deleteSelectedComponent || goto :fail
    )
)

call :select_maximal
if errorlevel 2 goto :fail
if errorlevel 1 goto :exhausted

echo Exporting component as %component_name%
call :run -renameSelectedComponent "%component_name%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
:: Pose sidecars land next to the ORIGINAL images: this is the
:: identity-preserving scene, so they are <stem>.xmp (not ordinal). The
:: Python orchestrator reads membership from them and then restores
:: calibration-only content (bug B7: leftover pose sidecars auto-import
:: as exact-pose priors).
call :run -exportXMPForSelectedComponent || goto :fail

echo COMPONENT_EXPORTED %component_name%
:: Quit WITHOUT saving - the in-memory deletes/rename must not reach the
:: saved scene.
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:exhausted
echo COMPONENT_EXHAUSTED no component left after skipping %skip_count%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: component identity export failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :select_maximal - tolerant -selectMaximalComponent. Exit codes:
::   0 = a component is selected
::   1 = no component left (EXPECTED loop-exhaustion; errors marker moved
::       to expected_select_%RS_INSTANCE%.txt so evidence is preserved
::       while later :run calls see a clean marker)
::   2 = delegation itself failed (hard error)
:select_maximal
%RealityScan% -delegateTo %RS_INSTANCE% -selectMaximalComponent
if errorlevel 1 (
    echo ERROR: Failed to delegate -selectMaximalComponent
    exit /b 2
)
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        echo NOTE: selectMaximalComponent reported an error - no component left
        move /y "%ErrorsFile%" "%ErrorPath%\expected_select_%RS_INSTANCE%.txt" >nul
        exit /b 1
    )
)
exit /b 0

:: :run - delegate one operation to %RS_INSTANCE%, wait for it to finish,
:: and fail if RealityScan reported an error. Delegated commands are
:: queued and -waitCompleted can return prematurely when it runs before
:: the instance picks the queued command up: grace delay, then two
:: -waitCompleted calls with a second grace between them (see
:: AlignZone.bat for the rationale).
:run
%RealityScan% -delegateTo %RS_INSTANCE% %*
if errorlevel 1 (
    echo ERROR: Failed to delegate command: %*
    exit /b 1
)
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        echo ERROR: RealityScan reported a failure during: %*
        exit /b 1
    )
)
exit /b 0
