@echo off
:: RealityScanCLI creates this sticky sentinel only after validating an owned
:: abort_current request. Never clear it in a workflow or an optional fallback.
if defined RS_STARTUP_REFUSED exit /b 1223
if defined RS_STARTUP_REFUSED_FILE if exist "%RS_STARTUP_REFUSED_FILE%" exit /b 1223
if not defined RS_ABORT_SENTINEL exit /b 0
if exist "%RS_ABORT_SENTINEL%" exit /b 1223
exit /b 0
