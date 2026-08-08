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
echo Sweeping default-named residual models
for %%M in ("Model 1" "Model 2" "Model 3" "Model 4" "Model 5" "Model 6" "Model 7" "Model 8" "Model 9") do (
    call :try_delete_model %%M
)

echo Saving project - residuals removed, before any in-memory coloring
call :run -save "%scene_path%" || goto :fail

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

echo   OBJ (Nira, by parts)
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%comp%\obj\%comp%.obj" "%ObjParams%" || exit /b 1

echo   FBX (by parts)
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%comp%\fbx\%comp%.fbx" "%FbxParams%" || exit /b 1

echo   Dense colored PLY from %comp%_HighPoly_Raw
call :run -selectModel "%comp%_HighPoly_Raw" || exit /b 1
call :run -calculateVertexColors || exit /b 1
call :run -exportModel "%comp%_HighPoly_Raw" "%out_dir%\%comp%\ply\%comp%_dense.ply" "%PlyParams%" || exit /b 1
exit /b 0

:emptyList
echo ERROR: component name list "%name_list%" names NOTHING.
echo   Populate it from the merge report final_components before exporting.
exit /b 1

:fail
echo ERROR: export workflow failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :try_delete_model <name> - tolerant delete with the full double-wait
:: shape (a single short wait can race the instance and leave the previous
:: selection live for the delete - GenerateModel audit #4). Evidence files
:: are named per MODEL (spaces flattened) so nine sweep iterations cannot
:: overwrite each other's records (final review).
:try_delete_model
set "evname=%~1"
set "evname=%evname: =_%"
%RealityScan% -delegateTo %RS_INSTANCE% -selectModel "%~1"
if errorlevel 1 (
    echo NOTE: could not delegate -selectModel %~1 - skipping
    exit /b 0
)
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        move /y "%ErrorsFile%" "%ErrorPath%\expected_select_%RS_INSTANCE%_%evname%.txt" >nul
        exit /b 0
    )
)
%RealityScan% -delegateTo %RS_INSTANCE% -deleteSelectedModel
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        move /y "%ErrorsFile%" "%ErrorPath%\expected_delete_%RS_INSTANCE%_%evname%.txt" >nul
    )
)
echo   removed residual %~1
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
