:: SUPERSEDED (owner decision 2026-08-07). Retired with zero callers -
:: superseded by AlignZone.bat + GrowZone.bat. Carries an unfixed
:: HANDOFF SHOULD-FIX by design (retired instead of fixed): no
:: AlignmentParams application, no deselect before exports
:: (HANDOFF.md 2026-07-24 clean-sweep review backlog, SHOULD-FIX list).
:: Kept for reference only - do not wire back into the pipeline.
@echo off
setlocal
:: Align images given by an .imagelist file (full paths, one per line) in a
:: fresh scene, import a flight log, and export every resulting component.
::
:: Unlike AlignImagesFromFolder.bat this references the images at their
:: ORIGINAL paths, so components produced from overlapping imagelists share
:: cameras by identity and can be merged with -mergeComponents
:: (MergeZoneComponents.bat).
::
:: Arguments (all required):
::   %1 imagelist file               %2 flight log path (or "")
::   %3 flight log params xml (or "") %4 component output directory
::   %5 scene/component name

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: imagelist argument required & exit /b 1 )
if [%4] == [] ( echo ERROR: output directory argument required & exit /b 1 )
if [%5] == [] ( echo ERROR: scene name argument required & exit /b 1 )
set "image_list=%~1"
set "flight_log=%~2"
set "flight_log_params=%~3"
set "output_dir=%~4"
set "scene_name=%~5"

if not exist "%image_list%" ( echo ERROR: imagelist not found: %image_list% & exit /b 1 )
if not exist "%output_dir%" mkdir "%output_dir%"

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Creating new scene
call :run -newScene || goto :fail

echo Adding images from list %image_list%
call :run -add "%image_list%" || goto :fail

if not "%flight_log%" == "" (
    echo Importing flight log
    call :run -importFlightLog "%flight_log%" "%flight_log_params%" || goto :fail
)

echo Aligning images
call :run -align || goto :fail

:: Export the maximal component (the -selectAllComponents command does
:: NOT exist in RealityScan 2.2 - verified against allcommands.htm after
:: it failed with 0x82000060; only selectComponent/selectMaximalComponent do)
echo Exporting maximal component
call :run -setMinComponentSize 1 || goto :fail
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "%scene_name%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
:: XMP sidecars for the maximal component = registration ground truth
call :run -exportXMPForSelectedComponent || goto :fail

echo Saving project
call :run -save "%output_dir%\%scene_name%.rsproj" || goto :fail

%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: imagelist workflow failed - see %ErrorsFile%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :run - delegate one operation, double-wait, abort if RealityScan
:: reported an error (see AlignImagesFromFolder.bat for the rationale).
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
