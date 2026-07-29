@echo off
setlocal
:: Load a saved scene and write ONE dated copy of it, then quit.
::
:: Exists because the daily RC_projects copy is now DEFERRED: GenerateModel.bat
:: takes two copies per component - one of them MID-RECIPE with every
:: intermediate model still live - and a project carrying ~15 models saves
:: inordinately slowly (owner-observed 2026-07-28; zone_1_c0's saves cost
:: ~81 GB). Drivers therefore run the model workflow with RS_PROJECTS_DIR
:: UNSET, which skips both copies, and call this once at the end when the
:: project holds only the three kept models per component.
::
:: Arguments:
::   %1 .rsproj scene path to copy
::   %2 destination .rsproj path for the dated copy

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: scene path required & exit /b 1 )
if [%2] == [] ( echo ERROR: destination path required & exit /b 1 )
set "scene_path=%~1"
set "dest_path=%~2"

if not exist "%scene_path%" ( echo ERROR: scene not found: %scene_path% & exit /b 1 )

for %%D in ("%dest_path%") do set "dest_dir=%%~dpD"
if not exist "%dest_dir%" mkdir "%dest_dir%"

echo Scene: %scene_path%
echo Dated copy: %dest_path%

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Loading scene
call :run -load "%scene_path%" || goto :fail

echo Saving dated copy
call :run -save "%dest_path%" || goto :fail

echo Shutting down RealityScan instance %RS_INSTANCE%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: dated copy failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :run - delegate one operation, double-wait, abort on reported error
:: (see AlignZone.bat for the rationale).
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
