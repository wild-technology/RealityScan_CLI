:: SUPERSEDED (archived 2026-08-07). Inverse-ordering hardening-probe for
:: cells U1/U19/U2, RESOLVED (testing/ALIGN_MERGE_HARDENING_PLAN.md:15-21
:: status update, 2026-07-23 9-boot probe session): selectImage = literal
:: paths only (U1), editInputSelection works (U19), align honors
:: enable/disable (U2). Kept for reference only - not wired into any
:: workflow.
@echo off
setlocal
:: HARDENING PROBE variant (U1/U2/U19): inverse ordering - keep everything
:: enabled, select the COMPLEMENT regexp and disable it, then align.
:: Discriminates the "disabled images cannot be re-selected by
:: selectImage" trap suspected from ProbeSubsetAlign's zero-census runs.
:: Arguments: %1 scene rsproj, %2 regexp of images to DISABLE

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: scene path required & exit /b 1 )
if [%2] == [] ( echo ERROR: disable regexp required & exit /b 1 )
set "scene_path=%~1"
set "disable_regexp=%~2"
if not exist "%scene_path%" ( echo ERROR: scene not found: %scene_path% & exit /b 1 )

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Loading scene
call :run -load "%scene_path%" || goto :fail

echo Ensuring ALL images enabled
call :run -selectAllImages || goto :fail
call :run -editInputSelection "inpEnabled=true" || goto :fail

echo Disabling complement: %disable_regexp% (mode: %~3)
call :run -deselectAllImages || goto :fail
if [%3] == [] (
    call :run -selectImage "%disable_regexp%" || goto :fail
) else (
    call :run -selectImage "%disable_regexp%" %~3 || goto :fail
)
call :run -editInputSelection "inpEnabled=false" || goto :fail

echo Deleting existing components in-memory
call :run -deleteAllComponents || goto :fail

echo Applying alignment settings
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%Metadata%\AlignmentParams.xml") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)

echo Aligning
call :run -align || goto :fail

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
