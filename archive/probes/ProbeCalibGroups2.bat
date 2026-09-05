@echo off
setlocal
:: Probe round 2 (2026-08-08): the exact cell-B fix - regex selectImage
:: WITHOUT the union mode argument, per-eye groups, then ALIGN so
:: exportXMP has cameras to export and the group census is real.
::   %1 fixture image dir   %2 probe output dir

call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"
set "probe_images=%~1"
set "probe_out=%~2"
if not exist "%probe_out%" mkdir "%probe_out%"
set "StepLog=%probe_out%\steps2.log"
echo probe2 start> "%StepLog%"

call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

call :step newScene -newScene
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :step addFolder -addFolder "%probe_images%"
call :step deselectL -deselectAllImages
call :step selectLeft -selectImage "[Ll]_2026-"
call :step setCalibL5 -setPriorCalibrationGroup 5
call :step setLensL5 -setPriorLensGroup 5
call :step deselectR -deselectAllImages
call :step selectRight -selectImage "[Rr]_2026-"
call :step setCalibR6 -setPriorCalibrationGroup 6
call :step setLensR6 -setPriorLensGroup 6
call :step deselectAll -deselectAllImages
call :step align -align
call :step exportXMP -exportXMP

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
