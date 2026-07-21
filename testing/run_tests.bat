@echo off
:: One-click launcher for the zone_9 CLI test plan (see TEST_PLAN.md).
:: Installs the two python dependencies if needed, then runs phases 0-2.
:: Pass-through args go to run_zone9_tests.py (e.g. run_tests.bat --full).

where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python launcher 'py' not found. Install Python 3.11+ from
    echo https://www.python.org/downloads/ - check "Add python.exe to PATH".
    exit /b 1
)

py -3 -m pip install --quiet opencv-python numpy
if errorlevel 1 (
    echo ERROR: failed to install opencv-python/numpy
    exit /b 1
)

py -3 "%~dp0run_zone9_tests.py" %*
