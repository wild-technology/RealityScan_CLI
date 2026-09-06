@echo off
setlocal
:: Probe round 5 (2026-08-08, FLIGHTLOG_ARCHITECTURE P1/P3/P4):
::  P3  matching semantics - does a flight-log row match by FULL PATH or
::      by basename? Import a full-path log whose paths point at COPIES
::      of the scene's images in a DIFFERENT folder: basename-matching
::      imports silently; path-matching warns/errors per row.
::  P1  format-ID resolution - import with a params file whose
::      gpsLogFileFormat is a RANDOM GUID: success means the ID is
::      decorative (header/registry-independent parsing) and the custom
::      {B438A617} registry entry is NOT load-bearing on 2.2.
::  P4  re-import onto an ALIGNED scene - align on the correct log,
::      then import a POSITION-SHIFTED log + -update: do exported
::      positions follow the new priors without a re-align?
::   %1 probe base dir (contains images\, log_*.txt, params_*.xml)

call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"
set "base=%~1"
set "StepLog=%base%\out\steps5.log"
if not exist "%base%\out\v_p4_before" mkdir "%base%\out\v_p4_before"
if not exist "%base%\out\v_p4_after" mkdir "%base%\out\v_p4_after"
echo probe5 start> "%StepLog%"

call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

:: ----- P3: full-path rows pointing at a DIFFERENT folder's copies
call :step p3_newScene -newScene
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=false"
call :step p3_addFolder -addFolder "%base%\images"
call :step p3_import_elsewhere -importFlightLog "%base%\log_elsewhere_fullpath.txt" "%base%\params_local.xml"
call :step p3_import_scenepath -importFlightLog "%base%\log_scene_fullpath.txt" "%base%\params_local.xml"
call :step p3_import_basename -importFlightLog "%base%\log_basename.txt" "%base%\params_local.xml"

:: ----- P1: random-GUID params on the KNOWN-GOOD full-path log
call :step p1_import_randomguid -importFlightLog "%base%\log_scene_fullpath.txt" "%base%\params_randomguid.xml"

:: ----- P4: align on correct priors, export, shifted re-import + update
call :step p4_align -align
call :step p4_deselect -deselectAllImages
call :step p4_minComp2 -setMinComponentSize 2
call :step p4_export_before -exportXMP
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%base%\images' -Filter *.xmp | Move-Item -Destination '%base%\out\v_p4_before' -Force"
call :step p4_import_shifted -importFlightLog "%base%\log_scene_shifted.txt" "%base%\params_local.xml"
call :step p4_update -update
call :step p4_deselect2 -deselectAllImages
call :step p4_export_after -exportXMP
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%base%\images' -Filter *.xmp | Move-Item -Destination '%base%\out\v_p4_after' -Force"

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
