@echo off
setlocal
:: Owner directive 2026-08-10: load ALL final alignments into a NEW
:: project in a VISIBLE GUI instance and leave it running for manual
:: work. Imports every .rsalign listed in the complist (files must be
:: at their original export locations - B1), imports the flight log,
:: saves the project, and does NOT quit.
::   %1 complist (one .rsalign path per line)
::   %2 flight log   %3 flight log params xml
::   %4 project save path (.rsproj)

call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

call :run -newScene || goto :fail

for /f "usebackq delims=" %%L in ("%~1") do (
    echo Importing component %%L
    call :run -importComponent "%%~L" || goto :fail
)

if not "%~2" == "" (
    echo Importing flight log
    call :run -importFlightLog "%~2" "%~3" || goto :fail
    call :run -deselectAllImages || goto :fail
)

echo Saving workbench project
call :run -save "%~4" || goto :fail
echo GUI workbench ready - instance %RS_INSTANCE% left RUNNING for manual work.
exit /b 0

:fail
echo ERROR: GUI workbench setup failed - see %ErrorsFile%
exit /b 1

:: run - delegate + double-wait + errors-file check (AlignZone pattern)
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
