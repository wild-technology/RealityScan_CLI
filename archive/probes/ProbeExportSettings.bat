@echo off
setlocal
:: Dump the FULL global settings registry from a live instance so key
:: names (not GUI labels) are known. %1 output xml path.
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1
%RealityScan% -delegateTo %RS_INSTANCE% -exportGlobalSettings "%~1"
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0
