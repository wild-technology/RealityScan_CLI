@echo off
setlocal
:: Grow one alignment scene incrementally: add an imagelist, import its
:: flight log, align; repeat for up to three (list, log) pairs. -align in
:: an existing scene EXTENDS existing components with the newly added
:: images (RealityScan's align/update semantics), so consecutive zones
:: that share cameras chain into a single component without an explicit
:: merge step.
::
:: Arguments:
::   %1 flight log params xml    %2 output directory   %3 scene name
::   %4 imagelist 1  %5 flight log 1
::   %6 imagelist 2  %7 flight log 2   (optional)
::   %8 imagelist 3  %9 flight log 3   (optional)

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: flight log params argument required & exit /b 1 )
if [%2] == [] ( echo ERROR: output directory argument required & exit /b 1 )
if [%3] == [] ( echo ERROR: scene name argument required & exit /b 1 )
if [%4] == [] ( echo ERROR: at least one imagelist required & exit /b 1 )
set "flight_log_params=%~1"
set "output_dir=%~2"
set "scene_name=%~3"

if not exist "%output_dir%" mkdir "%output_dir%"

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Creating new scene
call :run -newScene || goto :fail

call :grow "%~4" "%~5" || goto :fail
if not [%6] == [] call :grow "%~6" "%~7" || goto :fail
if not [%8] == [] call :grow "%~8" "%~9" || goto :fail

:: -selectAllComponents does not exist in RealityScan 2.2; export the
:: maximal component (the grown one, if the chaining worked)
echo Exporting maximal component
call :run -setMinComponentSize 1 || goto :fail
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "%scene_name%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
call :run -exportXMPForSelectedComponent || goto :fail

echo Saving project
call :run -save "%output_dir%\%scene_name%.rsproj" || goto :fail

%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:grow
echo Growing scene: adding %~1
call :run -add "%~1" || exit /b 1
if not "%~2" == "" (
    echo    importing flight log %~2
    call :run -importFlightLog "%~2" "%flight_log_params%" || exit /b 1
)
echo    aligning...
call :run -align || exit /b 1
exit /b 0

:fail
echo ERROR: sequential grow workflow failed - see %ErrorsFile%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

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
