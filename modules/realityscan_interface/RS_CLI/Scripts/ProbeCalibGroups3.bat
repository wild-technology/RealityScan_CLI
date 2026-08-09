@echo off
setlocal
:: Probe round 3 (2026-08-08): does -selectImage select at all from CLI,
:: and in which form? Scene 1 selects by FULL PATH + union (the form
:: GrowZone.bat uses live in production); scene 2 by full-path regex.
:: Each scene aligns + exports XMPs; the group census is the verdict.
::   %1 fixture image dir   %2 probe output dir

call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"
set "probe_images=%~1"
set "probe_out=%~2"
if not exist "%probe_out%\v_path" mkdir "%probe_out%\v_path"
if not exist "%probe_out%\v_regex" mkdir "%probe_out%\v_regex"
set "StepLog=%probe_out%\steps3.log"
echo probe3 start> "%StepLog%"

call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

:: ----- scene 1: full-path + union selection
call :step s1_newScene -newScene
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :step s1_addFolder -addFolder "%probe_images%"
call :step s1_deselect -deselectAllImages
for %%F in ("%probe_images%\L_*.jpg") do call :step s1_selL_%%~nF -selectImage "%%~fF" union
call :step s1_setCalibL5 -setPriorCalibrationGroup 5
call :step s1_setLensL5 -setPriorLensGroup 5
call :step s1_deselect2 -deselectAllImages
for %%F in ("%probe_images%\R_*.jpg") do call :step s1_selR_%%~nF -selectImage "%%~fF" union
call :step s1_setCalibR6 -setPriorCalibrationGroup 6
call :step s1_setLensR6 -setPriorLensGroup 6
call :step s1_deselect3 -deselectAllImages
call :step s1_align -align
call :step s1_export -exportXMP
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%probe_images%' -Filter *.xmp | Move-Item -Destination '%probe_out%\v_path' -Force"

:: ----- scene 2: full-path regex selection
call :step s2_newScene -newScene
call :step s2_addFolder -addFolder "%probe_images%"
call :step s2_deselect -deselectAllImages
call :step s2_selRegex -selectImage ".*[Ll]_2026-.*"
call :step s2_setCalib5 -setPriorCalibrationGroup 5
call :step s2_deselect2 -deselectAllImages
call :step s2_align -align
call :step s2_export -exportXMP
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%probe_images%' -Filter *.xmp | Move-Item -Destination '%probe_out%\v_regex' -Force"

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
