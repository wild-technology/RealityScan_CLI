@echo off
setlocal enabledelayedexpansion
:: Import every .rsalign component from a folder into a fresh scene, merge
:: them, and export the merged component.
::
:: Merge mechanisms (RealityScan 2.2):
::   - "merge": the -mergeComponents command. Merges existing components
::     without adding new images; needs shared cameras, control points,
::     or (with sfmMergeGeoreferencedComponents=true) georeferencing.
::   - "align": -align with components present - RealityScan's align
::     update re-registers components and can fuse them, modulated by
::     sfmForceComponentRematch / sfmMergeGeoreferencedComponents.
::
:: Arguments:
::   %1 folder containing .rsalign files, OR a .complist file: a text file
::      naming one .rsalign path per line. Prefer the .complist form with
::      components at their ORIGINAL export locations: -importComponent of
::      a component file that was copied elsewhere has been observed to
::      hang indefinitely in a #timeout state (2026-07-23). A file (not a
::      delimited argument) because cmd splits unquoted ; , = into
::      separate arguments and subprocess does not quote them.
::   %2 output directory
::   %3 merged component/scene name
::   %4 merge mode: "merge" (default) or "align"
::   %5 minimum component size for the all-components export (default 50;
::      align mode only - exportLatestComponents covers "components
::      created in the last alignment", which a plain -mergeComponents is
::      not)
::   %6..%9 optional "key:value" settings applied via -set before merging
::          (e.g. "sfmMergeGeoreferencedComponents:true"). COLON, not
::          equals: cmd splits unquoted '=' arguments in two, which both
::          broke the -set (err:7155) and aborted the workflow via the
::          errors marker. The colon is converted to '=' here.
::
:: Environment (set by merge_zones.py; env because %1-%9 are exhausted):
::   RS_MERGE_FLIGHT_LOG / RS_MERGE_FLIGHT_LOG_PARAMS - union flight log
::   + CRS params for the merge scene. REQUIRED for a georeferenced
::   result: a merged component is a NEW component, and without
::   constraints in the scene RealityScan has nothing to georegister it
::   against - the zone components' own georeferencing does NOT carry
::   over (observed NA156 H2023, 2026-07-23). After the merge, -update
::   fits all components to the imported constraints by a rigid
::   transformation, which is what georeferences the merged component.

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: components folder argument required & exit /b 1 )
if [%2] == [] ( echo ERROR: output directory argument required & exit /b 1 )
if [%3] == [] ( echo ERROR: merged name argument required & exit /b 1 )
set "components_dir=%~1"
set "output_dir=%~2"
set "merged_name=%~3"
set "merge_mode=%~4"
if "%merge_mode%" == "" set "merge_mode=merge"
set "min_component_size=%~5"
if "%min_component_size%" == "" set "min_component_size=50"

:: list mode when %1 is a .complist file; folder mode otherwise
set "list_mode="
if /i "%components_dir:~-9%" == ".complist" set "list_mode=1"

set /a component_count=0
if defined list_mode (
    if not exist "%components_dir%" ( echo ERROR: complist not found: %components_dir% & exit /b 1 )
    for /f "usebackq delims=" %%F in ("%components_dir%") do (
        if not exist "%%~F" ( echo ERROR: component not found: %%~F & exit /b 1 )
        set /a component_count+=1
    )
) else (
    for %%F in ("%components_dir%\*.rsalign") do set /a component_count+=1
)
if %component_count% LSS 2 (
    echo ERROR: need at least 2 components, found %component_count%
    exit /b 1
)
if not exist "%output_dir%" mkdir "%output_dir%"

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Creating new scene
call :run -newScene || goto :fail

echo Importing %component_count% components
if defined list_mode (
    for /f "usebackq delims=" %%F in ("%components_dir%") do (
        echo    importing %%~nxF
        call :run -importComponent "%%~F" || goto :fail
    )
) else (
    for %%F in ("%components_dir%\*.rsalign") do (
        echo    importing %%~nxF
        call :run -importComponent "%%F" || goto :fail
    )
)

:: Apply optional -set overrides (instant; delegated FIFO guarantees they
:: execute before the merge/align below). key:value -> key=value.
if not [%6] == [] call :applySet "%~6"
if not [%7] == [] call :applySet "%~7"
if not [%8] == [] call :applySet "%~8"
if not [%9] == [] call :applySet "%~9"
goto :afterSets

:applySet
set "kv=%~1"
set "kv=%kv::==%"
echo Setting %kv%
%RealityScan% -delegateTo %RS_INSTANCE% -set "%kv%"
exit /b 0

:afterSets

:: Georeferencing constraints: import the union flight log BEFORE the
:: merge so the solve/update has priors to fit. Rows referencing images
:: absent from the scene (never-registered) make the import report a
:: warning-class failure (err:18002, 0x820000FF) even though the
:: trajectory imports fine for every present image (session notes) -
:: handled by the tolerant :run_geoimport below.
if defined RS_MERGE_FLIGHT_LOG if not "%RS_MERGE_FLIGHT_LOG%" == "" (
    echo Importing union flight log for georeferencing
    call :run_geoimport -importFlightLog "%RS_MERGE_FLIGHT_LOG%" "%RS_MERGE_FLIGHT_LOG_PARAMS%" || goto :fail
)

:: No pre-selection: -selectAllComponents does not exist in RealityScan
:: 2.2, and -mergeComponents/-align operate on the scene's components.
echo Merging components (mode: %merge_mode%)
if /i "%merge_mode%" == "align" (
    call :run -align || goto :fail
) else (
    call :run -mergeComponents || goto :fail
)

:: Rigid-fit every component to the imported constraints - this is the
:: step that actually georeferences the freshly merged component.
if defined RS_MERGE_FLIGHT_LOG if not "%RS_MERGE_FLIGHT_LOG%" == "" (
    echo Georegistering components against flight-log constraints
    call :run -update || goto :fail
)

:: In align mode the merge IS an alignment, so every surviving component
:: (>= min size) can be exported for the next iteration - fragments are
:: inputs to further merging, not discards. -mergeComponents is not an
:: alignment, so exportLatestComponents does not apply there.
if /i "%merge_mode%" == "align" (
    echo Exporting all components of at least %min_component_size% cameras
    call :run -deselectAllImages || goto :fail
    call :run -setMinComponentSize %min_component_size% || goto :fail
    if not exist "%output_dir%\all_components" mkdir "%output_dir%\all_components"
    call :run -exportLatestComponents "%output_dir%\all_components" || goto :fail
)

echo Exporting merged component
:: The flight-log import leaves the matched images ACTIVELY SELECTED and
:: exports are selection-driven - under -silent the "Export Selection"
:: dialog auto-answer then exports NOTHING (census read 0; FINDINGS.md).
call :run -deselectAllImages || goto :fail
call :run -setMinComponentSize 1 || goto :fail
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "%merged_name%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
:: XMP sidecars for the merged component = camera-count ground truth
call :run -exportXMPForSelectedComponent || goto :fail

echo Saving project
call :run -save "%output_dir%\%merged_name%.rsproj" || goto :fail

:: Daily project-save schema: dated copy after the merge milestone,
:: named {expedition_dive}_merged_YYYYMMDD (see AlignZone.bat).
if defined RS_PROJECTS_DIR if defined RS_PROJECT_LABEL (
    if not exist "%RS_PROJECTS_DIR%" mkdir "%RS_PROJECTS_DIR%"
    echo Saving daily project copy
    call :run -save "%RS_PROJECTS_DIR%\%RS_PROJECT_LABEL%_merged_%RS_PROJECT_DATE%.rsproj" || goto :fail
)

%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: merge workflow failed - see %ErrorsFile%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :run_geoimport - like :run, but tolerates the DOCUMENTED warning-class
:: import failure err:18002 ("file contains images which are not in the
:: current scene"): the trajectory still imports for every present image.
:: The errors marker is MOVED (not deleted) to expected_18002_<inst>.txt
:: so the evidence is preserved while later :run calls see a clean
:: marker. Any other error content fails the workflow as usual.
:run_geoimport
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
        rem The errors marker carries only ErrorWriter's numeric process
        rem result, NOT the err:18002 text (that lives in RealityScan.log
        rem only). 2181038335 = 0x820000FF, the warning-class result this
        rem import reports when log rows reference absent images.
        %SystemRoot%\System32\findstr.exe /c:"2181038335" "%ErrorsFile%" >nul
        if errorlevel 1 (
            echo ERROR: RealityScan reported a failure during: %*
            exit /b 1
        )
        echo NOTE: flight log import reported warning-class 0x820000FF -
        echo       expected when rows reference never-registered images;
        echo       the trajectory imported for every present image
        move /y "%ErrorsFile%" "%ErrorPath%\expected_18002_%RS_INSTANCE%.txt" >nul
    )
)
exit /b 0

:: :run - delegate one operation, double-wait, abort on reported error
:: (see AlignImagesFromFolder.bat for the rationale).
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
