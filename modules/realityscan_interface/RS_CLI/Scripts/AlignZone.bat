@echo off
setlocal
:: Canonical per-zone alignment workflow (2026-07 consolidation of
:: AlignImagesFromFolder.bat's chaining/CRS handling and
:: AlignZonesSequentially.bat's settings application - see
:: docs/settings-evaluation-2026-07.md).
::
:: Aligns one zone as ONE scene and exports ALL resulting components
:: (>= min size), not just the maximal one: underwater zones routinely
:: fragment, and every pocket is input to the merge stage. Model
:: generation deliberately does NOT happen here - models are built once,
:: on the merged component (GenerateModel.bat).
::
:: Arguments (required):
::   %1 zone input directory (images; subfolders included)
::   %2 component output directory (per-zone folder recommended)
::   %3 flight log path (or "" to align without georeferencing priors)
::   %4 flight log params xml (or "")
::   %5 scene name (used for the saved .rsproj)
::   %6 minimum component size in cameras (e.g. 50)
::
:: Alignment settings ALWAYS come from Metadata\AlignmentParams.xml -
:: never from instance defaults (an instance carries whatever the last
:: GUI/CLI session set; aligning on unknown settings is not reproducible).

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "AlignmentParams=%Metadata%\AlignmentParams.xml"

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: zone input directory required & exit /b 1 )
if [%2] == [] ( echo ERROR: component output directory required & exit /b 1 )
if [%5] == [] ( echo ERROR: scene name required & exit /b 1 )
set "input_dir=%~1"
set "output_dir=%~2"
set "flight_log_dir=%~3"
set "flight_log_params_dir=%~4"
set "scene_name=%~5"
set "min_component_size=%~6"
if "%min_component_size%" == "" set "min_component_size=50"

if not exist "%input_dir%" ( echo ERROR: input directory not found: %input_dir% & exit /b 1 )
if not exist "%AlignmentParams%" ( echo ERROR: AlignmentParams.xml not found: %AlignmentParams% & exit /b 1 )
if not exist "%output_dir%" mkdir "%output_dir%"

echo Zone Input: %input_dir%
echo Component Output: %output_dir%
echo Flight Log: %flight_log_dir%
echo Flight Log Params: %flight_log_params_dir%
echo Scene Name: %scene_name%
echo Min Component Size: %min_component_size%

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Creating new scene
call :run -newScene || goto :fail

echo Adding images to project
:: Subfolder recursion is NOT the default in this 2.2 build: without
:: appIncSubdirs a zone tree whose images live in per-camera or
:: preprocessed_images subfolders adds 0 layer images and the flight-log
:: import then fails err:18002 (observed live on NA156 H2023). Instant
:: -set, FIFO-ordered before the queued addFolder, no wait needed.
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "%input_dir%" || goto :fail

if not "%flight_log_dir%" == "" (
    echo Importing flight log
    call :run -importFlightLog "%flight_log_dir%" "%flight_log_params_dir%" || goto :fail
)

echo Applying alignment settings from AlignmentParams.xml
:: -align takes NO parameters in RealityScan 2.x (a params xml passed to
:: it is silently ignored), so apply the sfm*/lis* keys via -set first.
:: Delegated commands queue FIFO, so the sets execute before the align;
:: they are instant and need no completion wait.
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)

echo Aligning images - this may take a long time
call :run -align || goto :fail

:: Flight-log import leaves its matched images ACTIVELY SELECTED, and
:: selection-driven exports under -silent then silently export NOTHING
:: (the "Export Selection" dialog is auto-answered; see FINDINGS.md,
:: 2026-07-23). Clear the selection before every export step.
call :run -deselectAllImages || goto :fail

call :run -setMinComponentSize %min_component_size% || goto :fail

echo Saving project BEFORE the destructive identity loop
call :run -save "%output_dir%\%scene_name%.rsproj" || goto :fail

:: Daily project-save schema (owner requirement 2026-07-23): a dated copy
:: in RC_projects (one level up from the zone image directory) after the
:: components milestone, named {expedition_dive}_{zone}_YYYYMMDD.
:: RS_PROJECT_LABEL/RS_PROJECT_DATE are computed by the Python
:: orchestrator.
if defined RS_PROJECTS_DIR if defined RS_PROJECT_LABEL (
    if not exist "%RS_PROJECTS_DIR%" mkdir "%RS_PROJECTS_DIR%"
    echo Saving daily project copy
    call :run -save "%RS_PROJECTS_DIR%\%RS_PROJECT_LABEL%_%scene_name%_%RS_PROJECT_DATE%.rsproj" || goto :fail
)

:: ------------------------------------------------------------------
:: In-session identity capture. The scene (with all components) is
:: already saved above, so this loop is destructive IN MEMORY ONLY and
:: the workflow quits WITHOUT saving.
:: Membership by SUCCESSIVE DIFFERENCE (2026-07-23 rework): only
:: -exportXMP writes stem-named sidecars; -exportXMPForSelectedComponent
:: is ALWAYS ordinal (FINDINGS.md). So each lap exports the stems of ALL
:: remaining components (>= min size, still gated by the earlier
:: setMinComponentSize), harvests them to identity_r<K>, then exports +
:: deletes the maximal component. members(c<K>) = stems(r<K>) minus
:: stems(r<K+1>), computed by the Python orchestrator. An EMPTY harvest
:: is the exhaustion terminal (also fires when only sub-min components
:: remain) - selectMaximalComponent/rename/delete silently no-op on an
:: empty scene, so file-existence checks, not errors, drive the loop.
echo Capturing per-component identity (destructive in-memory loop)
set /a comp_index=0
:identityLoop
if %comp_index% GEQ 20 goto :identityDone
if not exist "%output_dir%\identity_r%comp_index%" mkdir "%output_dir%\identity_r%comp_index%"
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%input_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force"
set "have_poses="
for %%F in ("%output_dir%\identity_r%comp_index%\*.xmp") do set have_poses=1
if not defined have_poses goto :identityDone
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "%scene_name%_c%comp_index%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
if not exist "%output_dir%\%scene_name%_c%comp_index%.rsalign" goto :identityDone
call :run -deleteSelectedComponent || goto :fail
set /a comp_index+=1
goto :identityLoop
:identityDone
echo Identity capture finished after %comp_index% component(s)

echo Shutting down RealityScan instance %RS_INSTANCE% - NO save after identity loop
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: zone workflow failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :run - delegate one operation to %RS_INSTANCE%, wait for it to finish,
:: and fail if RealityScan reported an error. Delegated commands are
:: queued and -waitCompleted can return prematurely when it runs before
:: the instance picks the queued command up: grace delay, then two
:: -waitCompleted calls with a second grace between them. Do NOT gate on
:: results log growth (heartbeat processes also write it).
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
