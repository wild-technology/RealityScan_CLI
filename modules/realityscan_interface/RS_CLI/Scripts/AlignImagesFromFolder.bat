@echo off
setlocal
:: DEPRECATED (2026-07-23): production zone alignment now uses
:: AlignZone.bat (exports ALL components, applies AlignmentParams.xml)
:: and model generation moved to GenerateModel.bat. This script remains
:: only for testing/run_zone9_tests.py; do not build new workflows on it.
::
:: Align a folder of images in RealityScan and optionally generate, cull,
:: texture, and simplify the model.
::
:: Arguments (all optional; prompted for when omitted):
::   %1 input image directory        %2 component output directory
::   %3 flight log path (or "")      %4 flight log params xml (or "")
::   %5 generate model (true/false)  %6 cull polygons (true/false)
::   %7 scene/component name         %8 texture model (true/false)
::   %9 simplify model (true/false)
::
:: Every RealityScan operation goes through the :run subroutine, which
:: delegates to the %RS_INSTANCE% headless instance, waits for completion,
:: and aborts the workflow if RealityScan's process trigger reported an
:: error (see startRealityScan.bat and ErrorWriter.bat).

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "MetadataDir=%Metadata%"
set "HighModelTexture=%MetadataDir%\Texturing_HighPolyTexture.xml"
set "SimplifiedModelTexture=%MetadataDir%\Texturing_SimplifiedTexture.xml"
set "SimplifyParams=%MetadataDir%\SimplifyAutomationParams.xml"
set "UnwrapSimplified=%MetadataDir%\Unwrapping_Simplified.xml"

:: Per-instance marker files written by RealityScan / ErrorWriter.bat
set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

echo Setting workflow variables

if [%1] == [] (
    set /P input_dir="Image Input Directory: "
) else (
    set "input_dir=%~1"
)

if [%2] == [] (
    set /P output_dir="Component Output Directory: "
) else (
    set "output_dir=%~2"
)

if [%3] == [] (
    set /P flight_log_dir="Path to Flight Log (or empty if no flight log): "
) else (
    set "flight_log_dir=%~3"
)

if not "%flight_log_dir%" == "" if [%4] == [] (
    set /P flight_log_params_dir="Path to Flight Log Params: "
) else (
    set "flight_log_params_dir=%~4"
)

:: CHOICE results are read with "if errorlevel 2" (N) immediately after the
:: prompt instead of %ERRORLEVEL% inside a parenthesized block, which would
:: expand at parse time and always see a stale value.
if not [%5] == [] ( set "generate_model=%~5" & goto :haveGenerate )
CHOICE /C YN /M "Generate Model"
if errorlevel 2 ( set "generate_model=false" ) else ( set "generate_model=true" )
:haveGenerate

set "GENERATE_MODEL_BOOL="
if /i "%generate_model%" == "true" set GENERATE_MODEL_BOOL=1
if /i "%generate_model%" == "y" set GENERATE_MODEL_BOOL=1
if "%generate_model%" == "1" set GENERATE_MODEL_BOOL=1

:: scene_name is needed for the final -save even when no model is generated
if not [%7] == [] ( set "scene_name=%~7" & goto :haveSceneName )
set /P scene_name="Scene name: "
:haveSceneName

if not [%6] == [] ( set "cull_polygons=%~6" & goto :haveCull )
if not defined GENERATE_MODEL_BOOL ( set "cull_polygons=false" & goto :haveCull )
CHOICE /C YN /M "Cull Polygons"
if errorlevel 2 ( set "cull_polygons=false" ) else ( set "cull_polygons=true" )
:haveCull

if not [%8] == [] ( set "texture_model=%~8" & goto :haveTexture )
if not defined GENERATE_MODEL_BOOL ( set "texture_model=false" & goto :haveTexture )
CHOICE /C YN /M "Texture"
if errorlevel 2 ( set "texture_model=false" ) else ( set "texture_model=true" )
:haveTexture

if not [%9] == [] ( set "simplify_model=%~9" & goto :haveSimplify )
if not defined GENERATE_MODEL_BOOL ( set "simplify_model=false" & goto :haveSimplify )
CHOICE /C YN /M "Simplify"
if errorlevel 2 ( set "simplify_model=false" ) else ( set "simplify_model=true" )
:haveSimplify

echo Input Directory: %input_dir%
echo Output Directory: %output_dir%
echo Flight Log Directory: %flight_log_dir%
echo Flight Log Params Directory: %flight_log_params_dir%
echo Generate Model: %generate_model%
echo Cull Polygons: %cull_polygons%
echo Scene Name: %scene_name%
echo Texture Model: %texture_model%
echo Simplify Model: %simplify_model%

set "CULL_POLYGONS_BOOL="
if /i "%cull_polygons%" == "true" set CULL_POLYGONS_BOOL=1
if /i "%cull_polygons%" == "y" set CULL_POLYGONS_BOOL=1
if "%cull_polygons%" == "1" set CULL_POLYGONS_BOOL=1

set "TEXTURE_MODEL_BOOL="
if /i "%texture_model%" == "true" set TEXTURE_MODEL_BOOL=1
if /i "%texture_model%" == "y" set TEXTURE_MODEL_BOOL=1
if "%texture_model%" == "1" set TEXTURE_MODEL_BOOL=1

set "SIMPLIFY_MODEL_BOOL="
if /i "%simplify_model%" == "true" set SIMPLIFY_MODEL_BOOL=1
if /i "%simplify_model%" == "y" set SIMPLIFY_MODEL_BOOL=1
if "%simplify_model%" == "1" set SIMPLIFY_MODEL_BOOL=1

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Adding images to project
:: Subfolder recursion is NOT the default in this 2.2 build: without
:: appIncSubdirs a zone tree whose images live in per-camera or
:: preprocessed_images subfolders adds 0 layer images and the flight-log
:: import then fails err:18002 (observed live on NA156 H2023). Instant
:: -set, FIFO-ordered before the queued addFolder, no wait needed.
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "%input_dir%" || goto :fail

if not "%flight_log_dir%" == "" (
    call :run -importFlightLog "%flight_log_dir%" "%flight_log_params_dir%" || goto :fail
)

echo Applying alignment settings from AlignmentParams.xml
:: Never align on instance defaults (policy 2026-07-23): apply the
:: sfm*/lis* keys via instant delegated -set, FIFO-ordered before -align.
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%MetadataDir%\AlignmentParams.xml") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)

echo Aligning images
call :run -align || goto :fail

echo Selecting maximal component and exporting
:: No -mergeComponents here: it is a no-op with a single component, and its
:: async re-reconstruction races the next command and clears the component
:: selection (err:5605 on the rename). Select the maximal component instead.
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "Merged" || goto :fail
:: exportXMPForSelectedComponent writes sidecars for the selected
:: component's cameras (plain -exportXMP only covers the last alignment
:: and silently skips components smaller than setMinComponentSize=5)
call :run -setMinComponentSize 1 || goto :fail
call :run -exportXMPForSelectedComponent || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail

if not defined GENERATE_MODEL_BOOL goto :saveProject

echo Generating model
call :run -calculateHighModel || goto :fail
call :run -renameSelectedModel "HighPoly" || goto :fail

if defined CULL_POLYGONS_BOOL (
    echo Culling polygons
    call :run -cleanModel || goto :fail
    call :run -renameSelectedModel "CullTemp1" || goto :fail

    call :run -selectLargeTrianglesRel 20 || goto :fail
    call :run -removeSelectedTriangles || goto :fail
    call :run -renameSelectedModel "CullTemp2" || goto :fail

    call :run -cleanModel || goto :fail
    call :run -renameSelectedModel "Culled" || goto :fail

    call :run -selectModel "CullTemp1" || goto :fail
    call :run -deleteSelectedModel || goto :fail

    call :run -selectModel "CullTemp2" || goto :fail
    call :run -deleteSelectedModel || goto :fail

    call :run -selectModel "Culled" || goto :fail
)

if defined TEXTURE_MODEL_BOOL (
    echo Texturing model
    call :run -calculateTexture "%HighModelTexture%" || goto :fail
    call :run -renameSelectedModel "HighPolyTextured" || goto :fail
)

if not defined SIMPLIFY_MODEL_BOOL goto :saveProject

echo Simplifying model - four simplify/clean passes
for /L %%I in (1,1,3) do (
    call :run -simplify "%SimplifyParams%" || goto :fail
    call :run -renameSelectedModel "SimplifyPass%%IRaw" || goto :fail
    call :run -cleanModel || goto :fail
    call :run -renameSelectedModel "SimplifyPass%%IClean" || goto :fail
)
call :run -simplify "%SimplifyParams%" || goto :fail
call :run -renameSelectedModel "SimplifyPass4Raw" || goto :fail
call :run -cleanModel || goto :fail
call :run -renameSelectedModel "Simplified" || goto :fail

echo Deleting intermediate simplification models
for /L %%I in (1,1,3) do (
    call :run -selectModel "SimplifyPass%%IRaw" || goto :fail
    call :run -deleteSelectedModel || goto :fail
    call :run -selectModel "SimplifyPass%%IClean" || goto :fail
    call :run -deleteSelectedModel || goto :fail
)
call :run -selectModel "SimplifyPass4Raw" || goto :fail
call :run -deleteSelectedModel || goto :fail

if defined TEXTURE_MODEL_BOOL (
    echo Unwrapping simplified model
    call :run -selectModel "Simplified" || goto :fail
    call :run -unwrap "%UnwrapSimplified%" || goto :fail

    echo Reprojecting onto simplified model
    call :run -reprojectTexture "HighPolyTextured" "Simplified" || goto :fail
    call :run -renameSelectedModel "SimplifiedTextured" || goto :fail
)

:saveProject
echo Saving project
call :run -save "%output_dir%\%scene_name%.rsproj" || goto :fail

echo Shutting down RealityScan instance %RS_INSTANCE%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: Workflow failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: ------------------------------------------------------------------
:: :run <command...> - delegate one operation to %RS_INSTANCE%, wait for it
:: to finish, and fail if RealityScan reported an error.
::
:: Delegated commands are queued, and -waitCompleted can return prematurely
:: when it runs before the instance has picked the queued command up, so:
:: grace delay for pickup, then two -waitCompleted calls with a second
:: grace between them. Do NOT gate on results_<instance>.log growth as a
:: completion signal: RealityScan 2.2 emits periodic internal heartbeat
:: processes through the same trigger, so "the log grew" does not mean
:: "our command finished" (observed racing ahead of a running -align).
:: errors_<instance>.txt is checked afterwards because it is written by
:: RealityScan itself and is authoritative even when the delegating call
:: returned 0.
:: ------------------------------------------------------------------
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
