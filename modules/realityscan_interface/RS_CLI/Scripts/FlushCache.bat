@echo off
setlocal
:: Sanctioned cache flush (owner directive 2026-08-09): the documented
:: -clearCache requires a saved project first ("You must save the
:: project before clearing the application cache"); Epic guidance says
:: never hand-delete cache files from a live cache. Boots a throwaway
:: instance bound to the target cache (env RS_CACHE_DIR), saves a
:: scratch scene, clears, quits.
::   %1 scratch .rsproj path

call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

call :run -newScene || goto :fail
call :run -save "%~1" || goto :fail
:: appAutoClearCache is a RETENTION policy (default 7 days) and
:: -clearCache HONORS it: on a 2-day-old campaign the first flush
:: freed 26 GB and left 918 GB (measured 2026-08-09). 0 = clear ALL;
:: restored to the documented default afterwards so instance exits do
:: not silently wipe warm caches from then on.
%RealityScan% -delegateTo %RS_INSTANCE% -set "appAutoClearCache=0"
echo Clearing application cache (retention 0 = everything)
call :run -clearCache || goto :fail
%RealityScan% -delegateTo %RS_INSTANCE% -set "appAutoClearCache=7"
%RealityScan% -delegateTo %RS_INSTANCE% -quit
echo Cache flush complete
exit /b 0

:fail
echo ERROR: cache flush failed - see %ErrorsFile%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: run - delegate + double-wait + errors-file check (AlignZone pattern)
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
