@echo off
setlocal
:: One within-zone growth PASS on an EXISTING zone scene, driven by
:: grow_zone.py (docs/merge-growth-strategy-2026-07.md, "Revised order of
:: operations", within-zone half). The scene is loaded from %1, operated
:: on, and saved back IN PLACE - checkpoint/rollback is the driver's job
:: (it snapshots the .rsproj + its companion data folder before every
:: mutating pass and restores them to the SAME path on rollback).
::
:: WARNING: this workflow must ONLY be pointed at the ORIGINAL zone scene
:: (the one AlignZone.bat built by adding the zone's image folder), never
:: at a scene reconstructed from component imports: importing components
:: into a fresh project does NOT bring images that are not in those
:: components - the orphan images (the precious missing-link candidates
:: this whole stage exists to register) are simply absent there, and if
:: re-added manually they carry no trajectory data until a flight log is
:: imported (owner-confirmed 2026-07-23, FINDINGS.md).
::
:: Modes (%2):
::   global    - enable ALL images and re-align: RealityScan's component-
::               merge algorithms see every cross-component tie at once.
::   component - disable ALL images, enable only the images listed in the
::               primary .imagelist (the component being grown), set the
::               features source on exactly that selection, then
::               additionally enable the secondary .imagelist (orphans,
::               features source left at per-image defaults) and align.
::   merge     - rigid -mergeComponents consolidation (cannot shrink). No
::               export: -exportLatestComponents covers "components
::               created in the last alignment", which a plain merge is
::               not (see MergeZoneComponents.bat).
::   export    - read-only: export the latest alignment's components
::               (>= min size) + identity XMP census; deliberately no save.
::   cleanup   - delete the components NAMED in the payload file (one
::               in-scene component name per line): stale/twin removal
::               after manifest-verified containment.
::
:: Arguments:
::   %1 scene .rsproj path (must exist)
::   %2 mode: global | component | merge | export | cleanup
::   %3 payload file, or "-": component mode -> primary .imagelist of
::      FULL image paths to enable (one per line); cleanup mode -> the
::      component names to delete (one per line). Always a FILE, never a
::      delimited argument (cmd splits unquoted ; , = - hard rule 8).
::   %4 features source 0|1|2 applied to the PRIMARY selection, or "-" to
::      leave per-image defaults untouched (global/component modes only)
::   %5 component export output directory (global/component/export)
::   %6 minimum component size for exports (default 50)
::   %7 secondary .imagelist (component mode: orphan images to enable
::      WITHOUT touching their features source), or "-"
::
:: Environment knobs (set by grow_zone.py):
::   RS_GROW_SELECT_CMDS  - "editsel" (default): per-selection edits go
::       through -editInputSelection "key=value" (inpEnabled /
::       aligFeaturesMode; tutorials/editselectioncommand.htm). The
::       key=value pair is passed as ONE quoted argument built inside
::       this script, so cmd never splits the '=' (the B5 hazard only
::       bites when key=value crosses a .bat argument boundary).
::       "legacy": use -enableAlignment true|false / -setFeatureSource N
::       instead (kept as the verified fallback).
::   RS_GROW_LOCK_ANCHOR  - "1": component mode only - lock the primary
::       component's camera poses (inpPose=3) before the align so the
::       well-solved component anchors the solve, and unlock (inpPose=0)
::       after. OFF by default until hardening cell U18 verifies that
::       locked cameras are guaranteed retained and that new images still
::       register onto them. Lock/unlock always uses -editInputSelection
::       regardless of RS_GROW_SELECT_CMDS.
::
:: The XMP census export runs in the ORIGINAL zone scene, so sidecars
:: keep image identity (<stem>.xmp - the ordinal-name degradation B10
:: only affects imported-component scenes). The driver reads them as the
:: registration census and restores calibration-only content (bug B7).

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "AlignmentParams=%Metadata%\AlignmentParams.xml"

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: scene .rsproj argument required & exit /b 1 )
if [%2] == [] ( echo ERROR: mode argument required & exit /b 1 )
set "scene_path=%~1"
set "scene_stem=%~n1"
set "mode=%~2"
set "payload=%~3"
if "%payload%" == "-" set "payload="
set "feature_source=%~4"
if "%feature_source%" == "" set "feature_source=-"
set "output_dir=%~5"
if "%output_dir%" == "-" set "output_dir="
set "min_component_size=%~6"
if "%min_component_size%" == "" set "min_component_size=50"
set "secondary_list=%~7"
if "%secondary_list%" == "-" set "secondary_list="

if not defined RS_GROW_SELECT_CMDS set "RS_GROW_SELECT_CMDS=editsel"

if not exist "%scene_path%" ( echo ERROR: scene not found: %scene_path% & exit /b 1 )

set "mode_ok="
for %%M in (global component merge export cleanup) do if /i "%mode%" == "%%M" set "mode_ok=1"
if not defined mode_ok ( echo ERROR: unknown mode "%mode%" & exit /b 1 )

:: Validation stays in single-line chained ifs: an "exit /b 1" inside a
:: multi-statement parenthesized block LOSES its exit code (cmd returns
:: 0 to the caller - reproduced 2026-07-23), silently disarming the
:: driver's failure handling.
if /i "%mode%" == "component" if "%payload%" == "" ( echo ERROR: component mode requires an imagelist payload & exit /b 1 )
if /i "%mode%" == "component" if not exist "%payload%" ( echo ERROR: imagelist not found: %payload% & exit /b 1 )
if /i "%mode%" == "cleanup" if "%payload%" == "" ( echo ERROR: cleanup mode requires a component-name list & exit /b 1 )
if /i "%mode%" == "cleanup" if not exist "%payload%" ( echo ERROR: component-name list not found: %payload% & exit /b 1 )

set "needs_export="
if /i "%mode%" == "global" set "needs_export=1"
if /i "%mode%" == "component" set "needs_export=1"
if /i "%mode%" == "export" set "needs_export=1"
if defined needs_export if "%output_dir%" == "" ( echo ERROR: output directory required for %mode% mode & exit /b 1 )
if defined needs_export if not exist "%output_dir%" mkdir "%output_dir%"

set "needs_align="
if /i "%mode%" == "global" set "needs_align=1"
if /i "%mode%" == "component" set "needs_align=1"
if defined needs_align if not exist "%AlignmentParams%" ( echo ERROR: AlignmentParams.xml not found: %AlignmentParams% & exit /b 1 )

echo Scene: %scene_path%
echo Mode: %mode%
if not "%payload%" == "" echo Payload: %payload%
if not "%secondary_list%" == "" echo Secondary: %secondary_list%
echo Features Source: %feature_source%
if not "%output_dir%" == "" echo Component Output: %output_dir%
echo Min Component Size: %min_component_size%
echo Selection Commands: %RS_GROW_SELECT_CMDS%
if "%RS_GROW_LOCK_ANCHOR%" == "1" echo Lock Anchor: ON - unverified until U18

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Loading scene
call :run -load "%scene_path%" || goto :fail

:: A stray active selection makes selection-driven operations misfire
:: (exports silently empty under -silent - FINDINGS.md); start clean.
call :run -deselectAllImages || goto :fail

set "did_lock="
if /i "%mode%" == "global" goto :mode_global
if /i "%mode%" == "component" goto :mode_component
if /i "%mode%" == "merge" goto :mode_merge
if /i "%mode%" == "export" goto :mode_export
goto :mode_cleanup

:: ---------------------------------------------------------------- global
:mode_global
echo Enabling ALL images for the global re-align
call :run -selectAllImages || goto :fail
call :selEnable || goto :fail
if not "%feature_source%" == "-" (
    echo Setting features source %feature_source% on all images
    call :selFeature || goto :fail
)
goto :align_and_export

:: ------------------------------------------------------------- component
:mode_component
set /a primary_count=0
for /f "usebackq delims=" %%L in ("%payload%") do set /a primary_count+=1
if %primary_count% EQU 0 ( echo ERROR: imagelist is empty: %payload% & goto :fail )

echo Disabling ALL images
call :run -selectAllImages || goto :fail
call :selDisable || goto :fail
call :run -deselectAllImages || goto :fail

echo Selecting %primary_count% primary images from the imagelist
call :selectFromList "%payload%"
echo Enabling the primary selection
call :selEnable || goto :fail
if not "%feature_source%" == "-" (
    echo Setting features source %feature_source% on the primary selection
    call :selFeature || goto :fail
)
if "%RS_GROW_LOCK_ANCHOR%" == "1" (
    echo Locking the primary component's camera poses as the solve anchor
    call :run -editInputSelection "inpPose=3" || goto :fail
    set "did_lock=1"
)

if "%secondary_list%" == "" goto :align_and_export
if not exist "%secondary_list%" ( echo ERROR: secondary imagelist not found: %secondary_list% & goto :fail )
set /a secondary_count=0
for /f "usebackq delims=" %%L in ("%secondary_list%") do set /a secondary_count+=1
if %secondary_count% EQU 0 goto :align_and_export
echo Enabling %secondary_count% secondary images - features source untouched
call :run -deselectAllImages || goto :fail
call :selectFromList "%secondary_list%"
call :selEnable || goto :fail
goto :align_and_export

:: ----------------------------------------------------- align + export
:align_and_export
echo Applying alignment settings from AlignmentParams.xml
:: -align takes NO parameters in RealityScan 2.x; apply the sfm*/lis*
:: keys via -set first (instant, FIFO-ordered before the queued align) -
:: same pattern as AlignZone.bat: never align on instance defaults.
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)

echo Aligning - this may take a long time
call :run -align || goto :fail

if "%did_lock%" == "1" (
    echo Unlocking the anchored component poses
    call :run -deselectAllImages || goto :fail
    call :selectFromList "%payload%"
    call :run -editInputSelection "inpPose=0" || goto :fail
)

echo Exporting components of at least %min_component_size% cameras
call :run -setMinComponentSize %min_component_size% || goto :fail
:: Exports are selection-driven; a leftover selection empties them.
call :run -deselectAllImages || goto :fail
call :run -exportLatestComponents "%output_dir%" || goto :fail
:: Identity XMP census for the driver's never-shrink invariant. Covers
:: the LAST alignment's components >= min size; the driver restores the
:: sidecars to calibration-only after reading (bug B7).
call :run -exportXMP || goto :fail
goto :save_quit

:: ----------------------------------------------------------------- merge
:mode_merge
echo Merging components - rigid consolidation, cannot shrink
call :run -mergeComponents || goto :fail
goto :save_quit

:: ---------------------------------------------------------------- export
:mode_export
echo Exporting components of at least %min_component_size% cameras - read-only pass
call :run -setMinComponentSize %min_component_size% || goto :fail
call :run -deselectAllImages || goto :fail
call :run -exportLatestComponents "%output_dir%" || goto :fail
call :run -exportXMP || goto :fail
:: Read-only pass: deliberately NO save.
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:: --------------------------------------------------------------- cleanup
:mode_cleanup
echo Deleting stale components listed in %payload%
for /f "usebackq delims=" %%C in ("%payload%") do (
    echo    deleting component %%C
    call :run -selectComponent "%%C" || goto :fail
    call :run -deleteSelectedComponent || goto :fail
)
goto :save_quit

:: ------------------------------------------------------------ save/quit
:save_quit
:: Component-mode passes disable most of the scene (inpEnabled=false)
:: and that state PERSISTS INTO THE SAVE - a saved zone project must
:: always be the all-enabled state (it is the authoritative artifact;
:: FINDINGS 2026-07-24). Re-enable everything before every save; a
:: no-op for modes that never disabled anything.
echo Re-enabling all images before save
call :run -selectAllImages || goto :fail
call :selEnable || goto :fail
call :run -deselectAllImages || goto :fail
echo Saving scene in place
call :run -save "%scene_path%" || goto :fail

:: Daily project-save schema (owner requirement 2026-07-23), armed by the
:: driver via set_project_save_env: {label}_{scene}_YYYYMMDD.rsproj.
if defined RS_PROJECTS_DIR if defined RS_PROJECT_LABEL (
    if not exist "%RS_PROJECTS_DIR%" mkdir "%RS_PROJECTS_DIR%"
    echo Saving daily project copy
    call :run -save "%RS_PROJECTS_DIR%\%RS_PROJECT_LABEL%_%scene_stem%_%RS_PROJECT_DATE%.rsproj" || goto :fail
)

%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: grow workflow failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :selectFromList - compose the current selection as the UNION of every
:: image path in the given list file. -selectImage <imagePath|regexp>
:: [set|union|sub|intersect|toggle] (session notes B11), one image path
:: per delegated call. Selection commands are instant and delegated
:: commands execute FIFO, so no per-command wait (the same pattern
:: AlignZone.bat uses for -set): a :run-style double-wait per image would
:: add ~5 s x thousands of images. The NEXT :run call flushes the whole
:: queue before checking the errors marker, so a bad path still aborts
:: the pass there.
:selectFromList
for /f "usebackq delims=" %%L in ("%~1") do (
    %RealityScan% -delegateTo %RS_INSTANCE% -selectImage "%%~L" union
)
exit /b 0

:: :selEnable / :selDisable / :selFeature - apply enable-for-alignment /
:: features-source to the CURRENT image selection. Default path is the
:: -editInputSelection "key=value" family (inpEnabled, aligFeaturesMode -
:: tutorials/editselectioncommand.htm); RS_GROW_SELECT_CMDS=legacy falls
:: back to -enableAlignment / -setFeatureSource. The key=value pair is a
:: single quoted argument composed HERE, so cmd never splits the '='.
:selEnable
if /i "%RS_GROW_SELECT_CMDS%" == "legacy" goto :selEnableLegacy
call :run -editInputSelection "inpEnabled=true"
exit /b
:selEnableLegacy
call :run -enableAlignment true
exit /b

:selDisable
if /i "%RS_GROW_SELECT_CMDS%" == "legacy" goto :selDisableLegacy
call :run -editInputSelection "inpEnabled=false"
exit /b
:selDisableLegacy
call :run -enableAlignment false
exit /b

:selFeature
if /i "%RS_GROW_SELECT_CMDS%" == "legacy" goto :selFeatureLegacy
call :run -editInputSelection "aligFeaturesMode=%feature_source%"
exit /b
:selFeatureLegacy
call :run -setFeatureSource %feature_source%
exit /b

:: :run - delegate one operation to %RS_INSTANCE%, wait for it to finish,
:: and fail if RealityScan reported an error. Delegated commands are
:: queued and -waitCompleted can return prematurely when it runs before
:: the instance picks the queued command up: grace delay, then two
:: -waitCompleted calls with a second grace between them (see
:: AlignZone.bat for the full rationale).
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
