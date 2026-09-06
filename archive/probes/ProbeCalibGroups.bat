@echo off
setlocal
:: Miniature probe (2026-08-08): why did -setPriorCalibrationGroup 5
:: fail with 0x8000FFFF in cell B? Tries each candidate selection +
:: grouping command on a 6-image fixture, logging pass/fail per step,
:: then exports XMPs so the GROUP CENSUS (not exit codes) is the
:: verdict. Runs on a disposable RSPROBE instance.
::   %1 fixture image dir   %2 probe output dir

call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"
set "probe_images=%~1"
set "probe_out=%~2"
if not exist "%probe_out%" mkdir "%probe_out%"
set "StepLog=%probe_out%\steps.log"
echo probe start> "%StepLog%"

call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

call :step newScene -newScene
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :step addFolder -addFolder "%probe_images%"

:: V3: does the command work at all, on a full selection?
call :step V3_selectAll -selectAllImages
call :step V3_setPriorCalib5 -setPriorCalibrationGroup 5
call :step V3_setPriorLens5 -setPriorLensGroup 5

:: V1: regex selection, union mode
call :step V1_deselect -deselectAllImages
call :step V1_selectRegexUnion -selectImage "[Ll]_2026-" union
call :step V1_setPriorCalib7 -setPriorCalibrationGroup 7

:: V2: regex selection, no mode argument
call :step V2_deselect -deselectAllImages
call :step V2_selectRegex -selectImage "[Rr]_2026-"
call :step V2_setPriorCalib8 -setPriorCalibrationGroup 8

:: V5: selection-based auto-numbered grouping (no group number arg)
call :step V5_deselect -deselectAllImages
call :step V5_selectLeft -selectImage "[Ll]_2026-" union
call :step V5_constGroup -setConstantCalibrationGroups

:: Ground truth: export XMPs beside the fixture images and census them.
call :step exp_deselect -deselectAllImages
call :step exportXMP -exportXMP

%RealityScan% -delegateTo %RS_INSTANCE% -quit
type "%StepLog%"
exit /b 0

:: step - label, then the delegated command. Failures are RECORDED, not
:: fatal - the probe's whole point is the pass/fail map.
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
