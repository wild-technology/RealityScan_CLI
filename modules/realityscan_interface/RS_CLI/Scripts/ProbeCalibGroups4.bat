@echo off
setlocal
:: Probe round 4 (2026-08-08): cell C's exact mechanism on the fixture -
:: -addImageWithCalibration via -execRSCMD (registry XMPs, groups 5/6,
:: approximate manufacturer focal), align, export. Oracle: L eyes share
:: one solved focal, R eyes share another; groups echo in the export.
::   %1 rscmd file   %2 fixture image dir   %3 probe output dir

call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"
set "rscmd_file=%~1"
set "probe_images=%~2"
set "probe_out=%~3"
if not exist "%probe_out%\v_addwithcalib" mkdir "%probe_out%\v_addwithcalib"
set "StepLog=%probe_out%\steps4.log"
echo probe4 start> "%StepLog%"

call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

call :step newScene -newScene
call :step execAdds -execRSCMD "%rscmd_file%"
call :step align -align
call :step deselect -deselectAllImages
call :step minComp2 -setMinComponentSize 2
call :step exportXMP -exportXMP
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%probe_images%' -Filter *.xmp | Move-Item -Destination '%probe_out%\v_addwithcalib' -Force"

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
