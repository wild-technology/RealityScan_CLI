@echo off
setlocal
:: CALIBRATION-LADDER variant of AlignZone.bat (2026-08-08). Same
:: argument contract, settings application, and identity-loop machinery
:: as AlignZone.bat, plus env-driven calibration hooks. It exists as a
:: SEPARATE file because production run2 holds AlignZone.bat open (cmd
:: reads .bat by byte offset - a mid-run edit corrupts execution); the
:: Python module selects it via RS_ALIGN_SCRIPT.
::
:: Owner finding 2026-08-08: same-name XMP sidecar auto-import is
:: UNRELIABLE; calibration priors travel via EXPLICIT commands
:: (FINDINGS.md "sidecar AUTO-IMPORT retired"). Hooks:
::
::   RS_CALIB_MODE  ""/unset : control cell - behaves as AlignZone.bat
::                  groups   : per-eye PRIOR calibration+lens groups via
::                             -selectImage regex + -setPriorCalibrationGroup
::                             / -setPriorLensGroup (no files involved)
::                  xmp      : add every image WITH its calibration XMP
::                             (-addImageWithCalibration, whole paths,
::                             xmps in a SEPARATE directory) by executing
::                             the .rscmd file RS_CALIB_XMP_RSCMD built
::                             by testing/run_calib_ladder.py
::
::   RS_CALIB_LEFT_RE / RS_CALIB_RIGHT_RE   selectImage regexes
::   RS_CALIB_LEFT_GRP / RS_CALIB_RIGHT_GRP group numbers (voyis: 5 / 6)
::
:: Arguments (same as AlignZone.bat):
::   %1 zone input dir  %2 component output dir  %3 flight log ("" ok)
::   %4 flight log params xml ("" ok)  %5 scene name  %6 min comp size

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "AlignmentParams=%Metadata%\AlignmentParams.xml"
if defined RS_ALIGN_PARAMS if not "%RS_ALIGN_PARAMS%" == "" set "AlignmentParams=%RS_ALIGN_PARAMS%"

if not defined RS_CALIB_MODE set "RS_CALIB_MODE="
if not defined RS_CALIB_LEFT_GRP set "RS_CALIB_LEFT_GRP=5"
if not defined RS_CALIB_RIGHT_GRP set "RS_CALIB_RIGHT_GRP=6"
if not defined RS_CALIB_LEFT_RE set "RS_CALIB_LEFT_RE=[Ll]_2026-"
if not defined RS_CALIB_RIGHT_RE set "RS_CALIB_RIGHT_RE=[Rr]_2026-"

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: zone input directory required & exit /b 1 )
if [%2] == [] ( echo ERROR: component output directory required & exit /b 1 )
if [%5] == [] ( echo ERROR: scene name required & exit /b 1 )
set "input_dir=%~1"
set "output_dir=%~2"
set "flight_log_dir=%~3"
set "flight_log_params_dir=%~4"
set "scene_name=%~5"
set "min_component_size=%~6"
if "%min_component_size%" == "" set "min_component_size=50"

if not exist "%input_dir%" ( echo ERROR: input directory not found: %input_dir% & exit /b 1 )
if not exist "%AlignmentParams%" ( echo ERROR: AlignmentParams.xml not found: %AlignmentParams% & exit /b 1 )
if not exist "%output_dir%" mkdir "%output_dir%"

echo Zone Input: %input_dir%
echo Component Output: %output_dir%
echo Flight Log: %flight_log_dir%
echo Flight Log Params: %flight_log_params_dir%
echo Scene Name: %scene_name%
echo Min Component Size: %min_component_size%
echo Calibration Mode: [%RS_CALIB_MODE%]

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Creating new scene
call :run -newScene || goto :fail

if /I "%RS_CALIB_MODE%" == "xmp" goto :addViaXmp
echo Adding images to project
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "%input_dir%" || goto :fail
goto :imagesAdded

:addViaXmp
echo Adding images WITH explicit calibration XMPs (command file)
if not defined RS_CALIB_XMP_RSCMD ( echo ERROR: xmp mode needs RS_CALIB_XMP_RSCMD & goto :fail )
if not exist "%RS_CALIB_XMP_RSCMD%" ( echo ERROR: rscmd file not found: %RS_CALIB_XMP_RSCMD% & goto :fail )
call :run -execRSCMD "%RS_CALIB_XMP_RSCMD%" || goto :fail

:imagesAdded
if "%flight_log_dir%" == "" goto :flightLogDone
echo Importing flight log
call :run -importFlightLog "%flight_log_dir%" "%flight_log_params_dir%" || goto :fail
:flightLogDone

if /I not "%RS_CALIB_MODE%" == "groups" goto :groupsDone
:: Per-eye grouping through EXPLICIT selection commands - no files, no
:: sidecar pairing. The post-align detector for this cell is the group
:: census over the harvested identity XMPs (run_calib_ladder.py): a
:: regex that matched nothing shows up there as an ungrouped census,
:: never as a silent pass.
echo Applying per-eye prior calibration/lens groups (L=%RS_CALIB_LEFT_GRP% R=%RS_CALIB_RIGHT_GRP%)
call :run -deselectAllImages || goto :fail
call :run -selectImage "%RS_CALIB_LEFT_RE%" union || goto :fail
call :run -setPriorCalibrationGroup %RS_CALIB_LEFT_GRP% || goto :fail
call :run -setPriorLensGroup %RS_CALIB_LEFT_GRP% || goto :fail
call :run -deselectAllImages || goto :fail
call :run -selectImage "%RS_CALIB_RIGHT_RE%" union || goto :fail
call :run -setPriorCalibrationGroup %RS_CALIB_RIGHT_GRP% || goto :fail
call :run -setPriorLensGroup %RS_CALIB_RIGHT_GRP% || goto :fail
call :run -deselectAllImages || goto :fail
:groupsDone

echo Applying alignment settings from AlignmentParams.xml
:: -align takes NO parameters in RealityScan 2.x; apply sfm*/lis* keys
:: via -set first (FIFO before the queued align). Zero applied settings
:: is a hard failure - see AlignZone.bat (audit 2026-08-07).
set /a applied_settings=0
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 (
        %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
        set /a applied_settings+=1
    )
)
if %applied_settings% EQU 0 goto :noSettings
echo Applied %applied_settings% alignment setting(s) from %AlignmentParams%

echo Aligning images - this may take a long time
call :run -align || goto :fail

:: Flight-log import leaves its matched images ACTIVELY SELECTED, and
:: selection-driven exports under -silent then silently export NOTHING.
call :run -deselectAllImages || goto :fail

call :run -setMinComponentSize %min_component_size% || goto :fail

echo Saving project BEFORE the destructive identity loop
call :run -save "%output_dir%\%scene_name%.rsproj" || goto :fail

if defined RS_PROJECTS_DIR if defined RS_PROJECT_LABEL (
    if not exist "%RS_PROJECTS_DIR%" mkdir "%RS_PROJECTS_DIR%"
    echo Saving daily project copy
    call :run -save "%RS_PROJECTS_DIR%\%RS_PROJECT_LABEL%_%scene_name%_%RS_PROJECT_DATE%.rsproj" || goto :fail
)

:: In-session identity capture - identical to AlignZone.bat (successive
:: difference over -exportXMP stem harvests; empty harvest terminates).
echo Capturing per-component identity (destructive in-memory loop)
set /a comp_index=0
:identityLoop
if %comp_index% GEQ 20 goto :identityDone
if not exist "%output_dir%\identity_r%comp_index%" mkdir "%output_dir%\identity_r%comp_index%"
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { Get-ChildItem -LiteralPath '%input_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 ( echo ERROR: identity harvest move failed & goto :fail )
set "have_poses="
for %%F in ("%output_dir%\identity_r%comp_index%\*.xmp") do set have_poses=1
if not defined have_poses goto :identityDone
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "%scene_name%_c%comp_index%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
if not exist "%output_dir%\%scene_name%_c%comp_index%.rsalign" goto :identityDone
call :run -deleteSelectedComponent || goto :fail
set /a comp_index+=1
goto :identityLoop
:identityDone
echo Identity capture finished after %comp_index% component(s)

echo Shutting down RealityScan instance %RS_INSTANCE% - NO save after identity loop
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:noSettings
echo ERROR: ZERO alignment settings were applied from %AlignmentParams%.
echo   The file exists but no sfm*/lis* key/value pair could be parsed from it.
echo   Aligning on instance defaults is not reproducible - see this file header.
goto :fail

:fail
echo ERROR: calibration-cell workflow failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :run - delegate one operation to %RS_INSTANCE%, wait, fail on reported
:: error. Same grace-delay double-wait as AlignZone.bat.
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
