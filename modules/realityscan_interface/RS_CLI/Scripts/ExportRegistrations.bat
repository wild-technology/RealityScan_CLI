@echo off
setlocal
:: Per-component camera registration from a SAVED project - READ-ONLY.
:: One RealityScan session: load, then per component named in the list
:: file (one per line):
::   -selectComponent "<name>"  ->  -exportRegistration "<out>\<name>.csv"
:: with RegistrationExportParams.xml (the RUMI membership + pose format,
:: requiresGeoref="0" so an ungeoreferenced component still exports).
:: There is NO -save anywhere: the project on disk is never modified, so
:: this is safe against a baseline project that must stay as it is.
::
:: What the CSVs are for: camera MEMBERSHIP (to match components across two
:: projects whose component names differ) and solved camera POSITIONS (to
:: measure metric scale against the nav with modules/scale_oracle.py)
:: without generating or exporting any mesh.
::
:: Every CSV is gated on CONTENT, exactly as AlignZone.bat gates its own:
:: an unresolved calexFileFormatId falls back to the instance's current
:: export settings and writes some other layout with exit code 0, so only
:: a first line of "#cameras N" proves the RUMI format actually ran.
::
:: Arguments:
::   %1 .rsproj project path (loaded, never saved)
::   %2 output directory (one <name>.csv per component)
::   %3 component-name list file (one name per line)

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "RegistrationParams=%Metadata%\RegistrationExportParams.xml"
if defined RS_REGISTRATION_PARAMS if not "%RS_REGISTRATION_PARAMS%" == "" set "RegistrationParams=%RS_REGISTRATION_PARAMS%"

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: project path required & exit /b 1 )
if [%2] == [] ( echo ERROR: output directory required & exit /b 1 )
if [%3] == [] ( echo ERROR: component name list required & exit /b 1 )
set "scene_path=%~1"
set "out_dir=%~2"
set "name_list=%~3"

if not exist "%scene_path%" ( echo ERROR: project not found: %scene_path% & exit /b 1 )
if not exist "%name_list%" ( echo ERROR: name list not found: %name_list% & exit /b 1 )
if not exist "%RegistrationParams%" ( echo ERROR: RegistrationExportParams.xml not found: %RegistrationParams% & exit /b 1 )
:: An empty list runs the loop zero times and exits 0 - a no-op that looks
:: like success (ExportDeliverables.bat, audit 2026-08-07). Count first.
set /a name_count=0
for /f "usebackq delims=" %%N in ("%name_list%") do set /a name_count+=1
if %name_count% EQU 0 goto :emptyList
echo Components to export: %name_count%
if not exist "%out_dir%" mkdir "%out_dir%"

echo Project: %scene_path%
echo Output:  %out_dir%

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Loading project (read-only - this workflow never saves)
call :run -load "%scene_path%" || goto :fail

:: Positions are written in the OUTPUT coordinate system. Unpinned, that is
:: whatever the application last held - NA165/H2060's v1 master declared a
:: 55N system for a 2S dive (ExportDeliverables.bat). Pinned here in memory
:: only; nothing is saved, so the project keeps whatever it had.
if defined RS_PROJECT_CRS if not "%RS_PROJECT_CRS%" == "" (
    echo Pinning project/output coordinate system to %RS_PROJECT_CRS% - in memory only
    call :run -setProjectCoordinateSystem %RS_PROJECT_CRS% || goto :fail
    call :run -setOutputCoordinateSystem %RS_PROJECT_CRS% || goto :fail
)

for /f "usebackq delims=" %%N in ("%name_list%") do (
    call :export_one "%%N" || goto :fail
)

echo Shutting down RealityScan instance %RS_INSTANCE% - NOT saving
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:: ---------------------------------------------------------- per component
:export_one
set "comp=%~1"
set "registration_csv=%out_dir%\%comp%.csv"
echo === %comp% ===
call :run -selectComponent "%comp%" || exit /b 1
call :run -exportRegistration "%registration_csv%" "%RegistrationParams%" || exit /b 1
if not exist "%registration_csv%" goto :registrationMissing
%SystemRoot%\System32\findstr.exe /n /r /c:"#cameras [0-9][0-9]*" "%registration_csv%" | %SystemRoot%\System32\findstr.exe /b /c:"1:" >nul
if errorlevel 1 goto :registrationFormat
exit /b 0

:: Both return from :export_one (exit /b 1), not goto :fail - the caller
:: turns the non-zero return into goto :fail, and jumping there from inside
:: the call would run the teardown twice (AlignZone.bat :identityOne).
:registrationMissing
echo ERROR: -exportRegistration wrote no CSV for %comp%
echo   expected: %registration_csv%
echo   The delegated command reported success, which is what a silent
echo   params/format fallback looks like. Check %RegistrationParams% and
echo   that its calexFileFormatId is installed: python -m modules.flightlog_format --install
exit /b 1

:registrationFormat
echo ERROR: %registration_csv% does not start with the "#cameras N" header.
echo   An unresolved calexFileFormatId falls back to the instance's current
echo   export settings instead of erroring. Reinstall the RUMI formats:
echo   python -m modules.flightlog_format --install
exit /b 1

:emptyList
echo ERROR: component name list "%name_list%" names NOTHING.
exit /b 1

:fail
echo ERROR: registration export failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :run - delegate one operation, double-wait, abort on reported error
:: (see AlignZone.bat for the rationale).
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
