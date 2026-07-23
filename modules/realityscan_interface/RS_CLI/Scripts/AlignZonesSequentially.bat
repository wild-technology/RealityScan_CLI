@echo off
setlocal

echo ============================================================
echo RealityScan Zone Alignment Script
echo ============================================================
echo.

rem Read default variables
echo [1/10] Reading default variables...
call "%~dp0SetVariables.bat"
if errorlevel 1 (
    echo ERROR: Failed to load SetVariables.bat
    exit /b 1
)

set "MetadataDir=%Metadata%"
set "AlignmentParams=%MetadataDir%\AlignmentParams.xml"
set "FlightLogParams=%MetadataDir%\FlightLogParams.xml"

rem Per-instance marker files written by RealityScan / ErrorWriter.bat
set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

rem Validate metadata files exist
if not exist "%AlignmentParams%" (
    echo ERROR: AlignmentParams.xml not found at: %AlignmentParams%
    exit /b 1
)
if not exist "%FlightLogParams%" (
    echo ERROR: FlightLogParams.xml not found at: %FlightLogParams%
    exit /b 1
)
echo    SUCCESS: Metadata files validated
echo.

rem Parse input arguments
echo [2/10] Parsing input arguments...
if [%1] == [] (
    set /P zone_input="Zone Input Directory: "
) else (
    set "zone_input=%~1"
)

if [%2] == [] (
    set /P zone_output="Zone Output Directory: "
) else (
    set "zone_output=%~2"
)

rem Validate input directory exists
if not exist "%zone_input%" (
    echo ERROR: Zone input directory does not exist: %zone_input%
    exit /b 1
)

rem Count images in input directory
set /a image_count=0
for /r "%zone_input%" %%F in (*.jpg *.jpeg *.png *.heif) do (
    set /a image_count+=1
)
if %image_count% == 0 (
    echo ERROR: No images found in input directory: %zone_input%
    exit /b 1
)

echo    Zone Input: %zone_input%
echo    Zone Output: %zone_output%
echo    Images Found: %image_count%
echo    SUCCESS: Input validated
echo.

rem Create required directories
echo [3/10] Creating required directories...
if not exist "%zone_output%" (
    mkdir "%zone_output%"
    if errorlevel 1 (
        echo ERROR: Failed to create output directory: %zone_output%
        exit /b 1
    )
    echo    SUCCESS: Created %zone_output%
) else (
    echo    INFO: Output directory already exists
)
echo.

rem Start RealityScan (headless instance %RS_INSTANCE% with monitoring hooks)
echo [4/10] Starting RealityScan...
call "%~dp0startRealityScan.bat"
if errorlevel 1 (
    echo ERROR: Failed to start RealityScan
    exit /b 1
)
echo    SUCCESS: RealityScan started
echo.

rem Create new project
echo [5/10] Creating new project...
call :run -newScene || goto :fail
echo    SUCCESS: New scene created
echo.

rem Add images from zone folder
echo [6/10] Adding images from zone folder...
echo    This may take several minutes for large image sets...
call :run -addFolder "%zone_input%" || goto :fail
echo    SUCCESS: Images added from %zone_input%
echo.

rem Find and import flight log
echo [7/10] Importing flight log...
set /a flight_log_found=0
for %%F in ("%zone_input%\flight_log*.txt") do (
    echo    Importing: %%F
    call :run -importFlightLog "%%F" "%FlightLogParams%" || goto :fail
    echo    SUCCESS: Flight log imported
    set /a flight_log_found=1
)
if %flight_log_found% == 0 (
    echo ERROR: No flight log found in %zone_input%
    echo    Flight log is REQUIRED for georeferenced alignment
    goto :fail
)
echo.

rem Verify XMP sidecars exist
echo [8/10] Verifying XMP sidecars for camera calibration...
set /a xmp_count=0
for /r "%zone_input%" %%F in (*.xmp) do (
    set /a xmp_count+=1
)
if %xmp_count% == 0 (
    echo ERROR: No XMP sidecar files found in %zone_input%
    echo    XMP files are REQUIRED for camera calibration priors
    goto :fail
)
echo    Found %xmp_count% XMP files

rem Import XMP sidecars with calibration priors
echo    Importing XMP sidecars...
call :run -importXMP || goto :fail
echo    SUCCESS: XMP sidecars imported with camera priors
echo.

rem Run alignment
echo [9/10] Running alignment with custom parameters...
rem -align takes NO parameters in RealityScan 2.x (a params xml passed to it
rem is silently ignored), so apply the sfm*/lis* keys from AlignmentParams.xml
rem via -set first. Delegated commands queue FIFO on the instance, so the
rem sets are guaranteed to execute before the align; they are instant and
rem need no completion wait.
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)
echo    This may take a significant amount of time...
echo    Please wait...
call :run -align || goto :fail
echo    SUCCESS: Alignment completed
echo.

rem Export the maximal component (-selectAllComponents does NOT exist in
rem RealityScan 2.2 - it fails with 0x82000060; verified 2026-07-23)
echo [10/10] Exporting aligned component...
call :run -setMinComponentSize 1 || goto :fail
call :run -selectMaximalComponent || goto :fail
call :run -exportSelectedComponentDir "%zone_output%" || goto :fail
echo    SUCCESS: Component exported to %zone_output%
echo.

rem Save project
echo Saving project...
for %%Z in ("%zone_input%") do set "zone_name=%%~nxZ"
call :run -save "%zone_input%\%zone_name%.rsproj" || goto :fail
echo    SUCCESS: Project saved as %zone_input%\%zone_name%.rsproj
echo.

echo Closing RealityScan...
%RealityScan% -delegateTo %RS_INSTANCE% -quit

echo ============================================================
echo PROCESSING COMPLETE
echo ============================================================
echo Zone: %zone_name%
echo Components: %zone_output%
echo Project: %zone_input%\%zone_name%.rsproj
echo ============================================================
exit /b 0

:fail
echo ERROR: Zone workflow failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: ------------------------------------------------------------------
:: :run <command...> - delegate one operation to %RS_INSTANCE%, wait for it
:: to finish, and fail if RealityScan reported an error.
::
:: Delegated commands are queued, and -waitCompleted can return prematurely
:: when it runs before the instance has picked the queued command up, so:
:: grace delay for pickup, then two -waitCompleted calls with a second
:: grace between them. Do NOT gate on results_<instance>.log growth as a
:: completion signal: RealityScan 2.2 emits periodic internal heartbeat
:: processes through the same trigger, so "the log grew" does not mean
:: "our command finished" (observed racing ahead of a running -align).
:: errors_<instance>.txt is checked afterwards because it is written by
:: RealityScan itself and is authoritative even when the delegating call
:: returned 0.
:: ------------------------------------------------------------------
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
