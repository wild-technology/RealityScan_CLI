@echo off
:: Plain setlocal - delayed expansion corrupts any path containing '!' and
:: nothing here uses !var! (final review).
setlocal
:: Export deliverables from a finished, modelled assembly project - one
:: RealityScan session for everything (the project load is the expensive
:: part). Per component (names come from a list file, one per line):
::
::   1. <name>_Simplified_Textured  -> OBJ, mesh saved BY PARTS - Nira's
::      recommended photogrammetry format and settings (help.nira.app
::      article 5591333681307: parts yes, no vertex colors, decimal-6,
::      textures as separate files).
::   2. <name>_Simplified_Textured  -> FBX, mesh saved by parts
::      (owner-requested format, same parts guidance).
::   3. <name>_HighPoly_Raw -> ultra-dense colored PLY: the raw high-poly
::      vertices are the densest geometry in the project;
::      -calculateVertexColors colors them (in MEMORY only), then PLY
::      exports with per-vertex color. NOTE Nira does NOT accept PLY
::      point clouds (LAS/LAZ/E57 only) - this deliverable is for local
::      use.
::
:: Before any export, default-named "Model N" residuals are swept and the
:: project SAVED once - the vertex colors computed later are deliberately
:: NOT saved (quit without save, AlignZone pattern), so the project stays
:: lean.
::
:: Arguments:
::   %1 .rsproj project path
::   %2 output directory (per-component subfolders are created)
::   %3 component-name list file (one name per line, e.g. cluster_0_a2_c0)

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "MetadataDir=%Metadata%"
set "ObjParams=%MetadataDir%\ModelExportParamsOBJ_NiraParts.xml"
set "FbxParams=%MetadataDir%\ModelExportParamsFBX_Parts.xml"
set "PlyParams=%MetadataDir%\ModelExportParamsPLY_DensePoints.xml"
:: Model MEASUREMENT (D12, owner 2026-09-06). -selectModel on a missing name
:: inside a populated component is a SILENT no-op (FINDINGS 2026-09-03,
:: rs-reference 12 F-102), so every destructive step below proves its
:: selection by reading the model report back, and the simplification is
:: driven by the MEASURED triangle count, not a fixed pass count:
::   -exportReport <html> "<install>\Reports\SelectedModel.html"   (~4 s)
:: parsed by modules/realityscan_interface/model_report.py into
:: RS_MODEL_NAME / RS_MODEL_TRIS / RS_MODEL_TEXTURED / ... RealityScanCLI sets
:: RS_PYTHON to its own interpreter; a hand-run script falls back to the
:: `python` on PATH (the hooks' interpreter).
if not defined RS_PYTHON set "RS_PYTHON=python"
set "ModelReportPy=%~dp0..\..\model_report.py"
for %%I in (%RealityScan%) do set "ReportTemplate=%%~dpIReports\SelectedModel.html"
set "ReportHtml=%ErrorPath%\model_report_%RS_INSTANCE%.html"

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
:: An EMPTY (or whitespace-only) list makes the per-component `for /f`
:: below run ZERO iterations: it falls through to -quit and exits 0 -
:: a no-op that reports success and produces no deliverables at all
:: (audit 2026-08-07). Count the names FIRST, before an instance boots.
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

echo Loading project
call :run -load "%scene_path%" || goto :fail

:: One residual per component was observed and names are unique per project,
:: so a six-component assembly can hold "Model 1".."Model 6"; sweep to 9 for
:: headroom (absent names are skipped silently).
:: Re-assert the OUTPUT coordinate system on the project we just loaded.
:: The export writes globalCoordinateSystem into every .rsInfo, and a project
:: assembled from imported components inherits a LIST of coordinate systems
:: without a correct selection - NA165/H2060's master declared 55N for a 2S
:: dive. Setting it here makes the sidecar say what the deliverable is in,
:: rather than whichever leftover sorted first.
if defined RS_PROJECT_CRS if not "%RS_PROJECT_CRS%" == "" (
    echo Pinning output coordinate system to %RS_PROJECT_CRS%
    call :run -setOutputCoordinateSystem %RS_PROJECT_CRS% || goto :fail
)

echo Sweeping default-named residual models
for %%M in ("Model 1" "Model 2" "Model 3" "Model 4" "Model 5" "Model 6" "Model 7" "Model 8" "Model 9") do call :delete_verified %%M

echo Saving project - residuals removed, before any in-memory coloring
call :run -save "%scene_path%" || goto :fail

:: Output CRS. WITHOUT this the export inherits whatever coordinate system
:: the application last held, and nothing in the pipeline ever set one:
:: H2077's first export (a 53N cruise) was stamped
:: globalCoordinateSystemName="epsg:32757 - WGS 84 / UTM zone 57S" - the
:: stale FlightLogParams placeholder zone - so a correctly aligned model
:: carried georeferencing from the wrong hemisphere (2026-08-14).
:: write_flight_log_params only rewrites the CRS of the flight log being
:: IMPORTED; it has no bearing on what is EXPORTED.
:: Merge 2026-09-03: this block came from remove-xmp-sidecars keyed on
:: RS_OUTPUT_CRS (set by export_deliverables.py --crs / --flight-log). It is
:: folded onto main's repo-wide RS_PROJECT_CRS - the same variable the block
:: after -load pins BEFORE the save (persisted output scope). This one adds
:: the PROJECT scope, in memory only, for the export that follows. One
:: variable, so a run can never pin two different systems.
if defined RS_PROJECT_CRS if not "%RS_PROJECT_CRS%" == "" (
    echo Setting project/output coordinate system to %RS_PROJECT_CRS%
    call :run -setProjectCoordinateSystem %RS_PROJECT_CRS% || goto :fail
    call :run -setOutputCoordinateSystem %RS_PROJECT_CRS% || goto :fail
)

for /f "usebackq delims=" %%N in ("%name_list%") do (
    call :export_component "%%N" || goto :fail
)

echo Shutting down RealityScan instance %RS_INSTANCE% - NOT saving
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:: ---------------------------------------------------------- per component
:export_component
set "comp=%~1"
echo === Exporting %comp% ===
if not exist "%out_dir%\%comp%\obj" mkdir "%out_dir%\%comp%\obj"
if not exist "%out_dir%\%comp%\fbx" mkdir "%out_dir%\%comp%\fbx"
if not exist "%out_dir%\%comp%\ply" mkdir "%out_dir%\%comp%\ply"

:: SELECT THE COMPONENT FIRST. -exportModel resolves a model by name on its
:: own, which is why OBJ and FBX worked without this, but -selectModel needs
:: component context and fails without it - with the SAME signature RealityScan
:: emits for a genuinely missing model ("process 21856 ... result code
:: 2147942487" = 0x80070057), which is what made this look like a missing
:: model for so long. GenerateModel.bat:93 selects the component before its own
:: -selectModel calls; this workflow never did.
:: Cost of the omission on NA165/H2060 (2026-09-01): every dense PLY refused,
:: and because :run treats a non-empty errors file as fatal, the FIRST
:: component's failure killed a 20-component export outright.
:: Same defect, found independently on NA168/H2080 (remove-xmp-sidecars, 2026-08-31):
:: Make this component ACTIVE before any model operation. -exportModel
:: resolves a model name GLOBALLY, but -selectModel resolves it only within
:: the ACTIVE component: a multi-component list wrote c44's OBJ and FBX
:: happily and then failed -selectModel "<comp>_HighPoly_Raw" with
:: 2147942487 for a model verified present, and the same run succeeded on
:: the first attempt with this line added (NA168/H2080 2026-08-31). The
:: stock workflow only ever worked because the component GenerateModel left
:: active happened to be the one exported. Selected here rather than at the
:: PLY step (where it bites) so all three exports are scoped alike.
call :run -selectComponent "%comp%" || exit /b 1

echo   OBJ (Nira, by parts)
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%comp%\obj\%comp%.obj" "%ObjParams%" || exit /b 1

echo   FBX (by parts)
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%comp%\fbx\%comp%.fbx" "%FbxParams%" || exit /b 1

:: DENSE PLY. Still skippable via RS_EXPORT_SKIP_PLY=1 as an escape hatch,
:: but it is NOT expected to fail: <comp>_HighPoly_Raw is present for every
:: component in the master project, and the earlier "missing model" was the
:: absent -selectComponent above.
if defined RS_EXPORT_SKIP_PLY (
    echo   Dense PLY SKIPPED ^(RS_EXPORT_SKIP_PLY set^)
    exit /b 0
)
echo   Dense colored PLY from %comp%_HighPoly_Raw
call :run -selectModel "%comp%_HighPoly_Raw" || exit /b 1
call :run -calculateVertexColors || exit /b 1
call :run -exportModel "%comp%_HighPoly_Raw" "%out_dir%\%comp%\ply\%comp%_dense.ply" "%PlyParams%" || exit /b 1
exit /b 0
)
echo   Dense colored PLY from %comp%_HighPoly_Textured
call :run -selectModel "%comp%_HighPoly_Textured" || exit /b 1
call :run -calculateVertexColors || exit /b 1
call :run -exportModel "%comp%_HighPoly_Textured" "%out_dir%\%comp%\ply\%comp%_dense.ply" "%PlyParams%" || exit /b 1
exit /b 0

:emptyList
echo ERROR: component name list "%name_list%" names NOTHING.
echo   Populate it from the merge report final_components before exporting.
exit /b 1

:fail
echo ERROR: export workflow failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :measure - -exportReport for the SELECTED model, parsed into
:: RS_MODEL_NAME / RS_MODEL_TRIS / RS_MODEL_TEXTURED / RS_MODEL_TEXTURES /
:: RS_MODEL_UNWRAP / RS_MODEL_RESOLUTION by model_report.py. The report is
:: the only way to know what is selected (F-102) and whether it is
:: textured (F-103). Single-line exits only.
:measure
set "RS_MODEL_NAME="
set "RS_MODEL_TRIS="
set "RS_MODEL_TEXTURED="
set "RS_MODEL_TEXTURES="
set "RS_MODEL_UNWRAP="
set "RS_MODEL_RESOLUTION="
if exist "%ReportHtml%" del /q "%ReportHtml%"
if exist "%ReportHtml%.txt" del /q "%ReportHtml%.txt"
call :run -exportReport "%ReportHtml%" "%ReportTemplate%" || exit /b 1
"%RS_PYTHON%" "%ModelReportPy%" "%ReportHtml%" --write "%ReportHtml%.txt"
if errorlevel 1 goto :measureMissing
for /f "usebackq tokens=1,* delims==" %%A in ("%ReportHtml%.txt") do set "RS_MODEL_%%A=%%B"
if not defined RS_MODEL_NAME goto :measureMissing
if not defined RS_MODEL_TRIS goto :measureMissing
exit /b 0
:measureMissing
echo ERROR: could not read the model report %ReportHtml% ^(template %ReportTemplate%, parser %ModelReportPy%^)
exit /b 1

:: :select_verified <name> - -selectModel and PROVE it took: a missing name
:: inside a populated component leaves the previous selection live with no
:: error at all (F-102).
:select_verified
call :run -selectModel "%~1" || exit /b 1
call :measure || exit /b 1
if /i not "%RS_MODEL_NAME%" == "%~1" goto :selectMismatch
exit /b 0
:selectMismatch
echo ERROR: -selectModel "%~1" left "%RS_MODEL_NAME%" selected - the model is absent
exit /b 1

:: :delete_verified <name> - delete a model ONLY after a verified select; an
:: absent name is a safe skip, never a delete of whatever was selected
:: (F-102). A select that RealityScan refuses outright (an empty component)
:: is evidence, not an abort.
:delete_verified
%RealityScan% -delegateTo %RS_INSTANCE% -selectModel "%~1"
if errorlevel 1 goto :deleteDelegateFailed
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 move /y "%ErrorsFile%" "%ErrorPath%\expected_select_%RS_INSTANCE%_%~1.txt" >nul
call :measure || exit /b 1
if /i not "%RS_MODEL_NAME%" == "%~1" goto :deleteSkip
call :run -deleteSelectedModel || exit /b 1
echo   deleted %~1
exit /b 0
:deleteSkip
echo   skip %~1 - not present ^(selection is %RS_MODEL_NAME%^)
exit /b 0
:deleteDelegateFailed
echo NOTE: could not select %~1 - leaving it in place
exit /b 0

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
