@echo off
setlocal
:: HARDENING PROBE (cell U18, testing/ALIGN_MERGE_HARDENING_PLAN.md)
:: Load a scene, LOCK every currently-registered image's pose via
:: -editInputSelection inpPose=3, re-align, export the census. Quit
:: WITHOUT saving.
::
:: Interpretation (python side compares against the pre-align census):
::   - identical camera count + identical poses -> Locked anchors hold
::     (U18 pass: pose-locking is a solver-level never-shrink anchor)
::   - fewer cameras or moved poses -> Locked does not guarantee
::     retention (U18 fail: rollback stays the primary mechanism)
::
:: Arguments: %1 scene rsproj, %2 lock mode ("locked" -> inpPose=3,
::            "baseline" -> no lock, just align)

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: scene path required & exit /b 1 )
set "scene_path=%~1"
set "lock_mode=%~2"
if "%lock_mode%" == "" set "lock_mode=locked"
if not exist "%scene_path%" ( echo ERROR: scene not found: %scene_path% & exit /b 1 )

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Loading scene
call :run -load "%scene_path%" || goto :fail

:: mode "export": no lock, no align - just the census of current poses
:: (the pre-align baseline the python side diffs against)
if /i "%lock_mode%" == "export" goto :census

if /i "%lock_mode%" == "locked" (
    echo Locking all image poses
    call :run -selectAllImages || goto :fail
    call :run -editInputSelection "inpPose=3" || goto :fail
)

echo Applying alignment settings
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%Metadata%\AlignmentParams.xml") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)

echo Re-aligning
call :run -align || goto :fail

:census

echo Exporting census
call :run -setMinComponentSize 1 || goto :fail
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail

echo Quitting WITHOUT saving
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: probe failed - see %ErrorsFile%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

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
