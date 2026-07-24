@echo off
setlocal
:: HARDENING PROBE (cells U1/U19/U2, testing/ALIGN_MERGE_HARDENING_PLAN.md)
:: Load a scene, disable ALL images via -editInputSelection, re-enable a
:: regexp-selected subset, delete all components in-memory, align from
:: scratch, export the XMP census. Quit WITHOUT saving - the on-disk
:: scene is untouched.
::
:: A registered census <= subset size proves in one shot:
::   - selectImage regexp form matches (U1)
::   - editInputSelection inpEnabled applies per selected image (U19)
::   - -align honors enable/disable (U2)
::
:: Arguments: %1 scene rsproj, %2 regexp for the subset to keep enabled

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: scene path required & exit /b 1 )
if [%2] == [] ( echo ERROR: subset regexp required & exit /b 1 )
set "scene_path=%~1"
set "subset_regexp=%~2"
if not exist "%scene_path%" ( echo ERROR: scene not found: %scene_path% & exit /b 1 )

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Loading scene
call :run -load "%scene_path%" || goto :fail

echo Disabling ALL images
call :run -selectAllImages || goto :fail
call :run -editInputSelection "inpEnabled=false" || goto :fail

echo Enabling subset: %subset_regexp%
call :run -deselectAllImages || goto :fail
call :run -selectImage "%subset_regexp%" || goto :fail
call :run -editInputSelection "inpEnabled=true" || goto :fail

echo Deleting existing components in-memory for a clean-signal align
call :run -deleteAllComponents || goto :fail

echo Applying alignment settings
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%Metadata%\AlignmentParams.xml") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)

echo Aligning enabled subset
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
