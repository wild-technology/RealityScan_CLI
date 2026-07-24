@echo off
setlocal enabledelayedexpansion
:: Import every .rsalign component from a folder into a fresh scene, merge
:: them, and export the merged component.
::
:: Merge mechanisms (RealityScan 2.2, empirically verified - see
:: testing/FINDINGS.md #23-#26, #30):
::   - "merge": the -mergeComponents command. Fuses ONLY through cameras
::     shared by identity (same image path in both components). With no
::     shared cameras it exits SUCCESS and silently leaves components
::     separate - verify merges by camera count, never exit status.
::     sfmMergeGeoreferencedComponents did NOT enable overlap-free
::     merging headless, despite the official docs.
::   - "align": -align with components present - RealityScan's align
::     update; same shared-camera requirement observed.
::
:: Arguments:
::   %1 folder containing .rsalign files, OR a .complist file: a text file
::      naming one .rsalign path per line. Prefer the .complist form with
::      components at their ORIGINAL export locations: -importComponent of
::      a component file that was copied elsewhere has been observed to
::      hang indefinitely in a #timeout state (2026-07-23). A file (not a
::      delimited argument) because cmd splits unquoted ; , = into
::      separate arguments and subprocess does not quote them.
::   %2 output directory
::   %3 merged component/scene name
::   %4 merge mode: "merge" (default) or "align"
::   %5..%9 optional "key:value" settings applied via -set before merging
::          (e.g. "sfmMergeGeoreferencedComponents:true"). COLON, not
::          equals: cmd splits unquoted '=' arguments in two, which both
::          broke the -set (err:7155) and aborted the workflow via the
::          errors marker. The colon is converted to '=' here.

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: components folder argument required & exit /b 1 )
if [%2] == [] ( echo ERROR: output directory argument required & exit /b 1 )
if [%3] == [] ( echo ERROR: merged name argument required & exit /b 1 )
set "components_dir=%~1"
set "output_dir=%~2"
set "merged_name=%~3"
set "merge_mode=%~4"
if "%merge_mode%" == "" set "merge_mode=merge"

:: list mode when %1 is a .complist file; folder mode otherwise
set "list_mode="
if /i "%components_dir:~-9%" == ".complist" set "list_mode=1"

set /a component_count=0
if defined list_mode (
    if not exist "%components_dir%" ( echo ERROR: complist not found: %components_dir% & exit /b 1 )
    for /f "usebackq delims=" %%F in ("%components_dir%") do (
        if not exist "%%~F" ( echo ERROR: component not found: %%~F & exit /b 1 )
        set /a component_count+=1
    )
) else (
    for %%F in ("%components_dir%\*.rsalign") do set /a component_count+=1
)
if %component_count% LSS 2 (
    echo ERROR: need at least 2 components, found %component_count%
    exit /b 1
)
if not exist "%output_dir%" mkdir "%output_dir%"

echo Starting RealityScan
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Creating new scene
call :run -newScene || goto :fail

echo Importing %component_count% components
if defined list_mode (
    for /f "usebackq delims=" %%F in ("%components_dir%") do (
        echo    importing %%~nxF
        call :run -importComponent "%%~F" || goto :fail
    )
) else (
    for %%F in ("%components_dir%\*.rsalign") do (
        echo    importing %%~nxF
        call :run -importComponent "%%F" || goto :fail
    )
)

:: Apply optional -set overrides (instant; delegated FIFO guarantees they
:: execute before the merge/align below). key:value -> key=value.
if not [%5] == [] call :applySet "%~5"
if not [%6] == [] call :applySet "%~6"
if not [%7] == [] call :applySet "%~7"
if not [%8] == [] call :applySet "%~8"
if not [%9] == [] call :applySet "%~9"
goto :afterSets

:applySet
set "kv=%~1"
set "kv=%kv::==%"
echo Setting %kv%
%RealityScan% -delegateTo %RS_INSTANCE% -set "%kv%"
exit /b 0

:afterSets

:: No pre-selection: -selectAllComponents does not exist in RealityScan
:: 2.2, and -mergeComponents/-align operate on the scene's components.
echo Merging components (mode: %merge_mode%)
if /i "%merge_mode%" == "align" (
    call :run -align || goto :fail
) else (
    call :run -mergeComponents || goto :fail
)

echo Exporting merged component
:: setMinComponentSize is deprecated in 2.2 ("removed in the next
:: release") but still required here - without it small components are
:: silently excluded from selection/export (default threshold 5)
call :run -setMinComponentSize 1 || goto :fail
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "%merged_name%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
:: XMP sidecars for the merged component = camera-count ground truth
call :run -exportXMPForSelectedComponent || goto :fail

echo Saving project
call :run -save "%output_dir%\%merged_name%.rsproj" || goto :fail

%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: merge workflow failed - see %ErrorsFile%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :run - delegate one operation, double-wait, abort on reported error
:: (see AlignImagesFromFolder.bat for the rationale).
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
