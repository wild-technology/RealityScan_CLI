@echo off
setlocal
:: Probe round 6 (P1b): does an import under RANDOM-GUID params actually
:: APPLY (not silently no-op)? Reuses probe5's aligned scene state is
:: gone (instance quit), so: newScene, add, import +200 log with the
:: random-GUID params, align, export, census expects ~200/300 positions.
::   %1 probe base dir

call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"
set "base=%~1"
set "StepLog=%base%\out\steps6.log"
if not exist "%base%\out\v_p1b" mkdir "%base%\out\v_p1b"
echo probe6 start> "%StepLog%"

call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

call :step p1b_newScene -newScene
call :step p1b_addFolder -addFolder "%base%\images"
call :step p1b_import_rndguid_200 -importFlightLog "%base%\log_scene_shift200.txt" "%base%\params_randomguid.xml"
call :step p1b_align -align
call :step p1b_deselect -deselectAllImages
call :step p1b_minComp2 -setMinComponentSize 2
call :step p1b_export -exportXMP
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%base%\images' -Filter *.xmp | Move-Item -Destination '%base%\out\v_p1b' -Force"

%RealityScan% -delegateTo %RS_INSTANCE% -quit
type "%StepLog%"
exit /b 0

:: step - see ProbeCalibGroups.bat
:step
set "label=%~1"
shift
set "cmdline="
:collect
if [%1] == [] goto :send
set cmdline=%cmdline% %1
shift
goto :collect
:send
if exist "%ErrorsFile%" del "%ErrorsFile%"
%RealityScan% -delegateTo %RS_INSTANCE% %cmdline%
if errorlevel 1 ( echo %label% DELEGATE-FAIL>> "%StepLog%" & exit /b 0 )
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
set "failed="
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 set failed=1
)
if defined failed ( echo %label% FAIL>> "%StepLog%" ) else ( echo %label% OK>> "%StepLog%" )
exit /b 0
