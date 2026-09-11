@echo off
setlocal
:: Model generation for an already-aligned scene - owner-specified recipe
:: (2026-07-23):
::   Generate High -> remove marginal (edge) triangles -> remove large
::   triangles (30 threshold) -> keep largest connected component ->
::   close holes -> clean model (the CLI equivalent of the GUI Check
::   Integrity / Check Topology FIX actions; the checks themselves have
::   no CLI commands) -> simplify (noise) -> generate texture ->
::   simplify 75% per pass until at or under RS_TARGET_TRIS (default
::   10,000,000; owner 2026-09-06, D12 - a model already under needs
::   none) with clean between -> unwrap -> reproject high-poly texture.
::
:: Selection semantics: RealityScan's Filter Selection
:: (-removeSelectedTriangles) removes the SELECTED triangles, so the
:: edge/large steps filter directly and only the largest-component step
:: needs -invertTrianglesSelection first.
::
:: Texture-with-holes rationale: texture is generated AFTER
:: closeHoles+cleanModel, so hole-fill triangles receive real image
:: texture with multi-band blending (underwater holes are usually
:: weakly-reconstructed but CAMERA-VISIBLE areas). The final
:: reprojection then maps between two already-manifold models - no
:: nodata patches. Never texture the holey model and reproject onto the
:: closed one. (docs/settings-evaluation-2026-07.md)
::
:: Models kept, each prefixed with the component name (see model_tag
:: below): <comp>_HighPoly_Raw (generate high), <comp>_HighPoly_Textured
:: (textured, pre-simplification), <comp>_Simplified_Textured (final).
:: The prefix is what makes running this once per component against one
:: shared project safe.
::
:: Arguments:
::   %1 .rsproj scene path (from AlignZone.bat or MergeZoneComponents.bat)
::   %2 component name to model ("" = maximal component)
::   %3 large-triangle threshold (default 30; -selectLargeTrianglesRel
::      units: multiples of the average edge length)
::
:: Daily saves (RS_PROJECTS_DIR/RS_PROJECT_LABEL/RS_PROJECT_DATE set by
:: the Python orchestrator): after texture and after the final model,
:: to RC_projects\{label}_merged_YYYYMMDD.rsproj.

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "MetadataDir=%Metadata%"
:: Texture policy (owner 2026-09-05, decision D13): BOTH texture passes use
:: unwrapStyle=AdaptiveTexelSize with a 4096 page cap - never 16K, and the
:: final unwrap is never forced to a 4 x 8K page budget. AdaptiveTexelSize
:: clamps an estimated texel between unwrapMinTexelSize and
:: unwrapMaxTexelSize and emits however many pages that needs; it is a
:: DIFFERENT style from MaxTexturesCount (which auto-fits the texel to a
:: page count and which this repo mislabelled "adaptive" for a month,
:: FINDINGS 2026-09-03). The retired MaxTexturesCount presets live in
:: archive/metadata_retired/ for citation only.
::
:: AdaptiveTexelSize can reject a particular mesh outright (FINDINGS
:: 2026-09-03, H2060 c5: 0x83000003 in 3 s, scene revision unchanged, three
:: times) and an untextured model still exports "successfully". The final
:: unwrap therefore goes through :try_unwrap - adaptive first, then
:: MaxTexturesCount 4 x 4096 (still inside the cap) when adaptive reports an
:: error - exactly what run_decimate.py does.
set "HighModelTexture=%MetadataDir%\Texturing_AdaptiveTexel_4k.xml"
set "SimplifyNoise=%MetadataDir%\SimplifyNoise_Params.xml"
set "UnwrapSimplified=%MetadataDir%\Unwrapping_AdaptiveTexel_4k.xml"
set "UnwrapFallback=%MetadataDir%\Unwrapping_MaxCount4_4k.xml"
set "ReprojectionParams=%MetadataDir%\ReprojectionParams.xml"
:: Simplification target (D12): 75%% KEPT per pass (mvsFltTargetTrisCountRel)
:: until the model is at or under RS_TARGET_TRIS triangles. Small models
:: need no pass at all. The pass count is whatever the measurement says.
if not defined RS_TARGET_TRIS set "RS_TARGET_TRIS=10000000"
set "SimplifyTarget=%MetadataDir%\Simplify75per_Params.xml"
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

if [%1] == [] ( echo ERROR: scene path required & exit /b 1 )
set "scene_path=%~1"
set "component_name=%~2"
set "large_tri_threshold=%~3"
if "%large_tri_threshold%" == "" set "large_tri_threshold=30"

:: Every model name is namespaced by the component being modelled.
:: WHY: this workflow is run ONCE PER COMPONENT against the SAME saved
:: project (merge_zones --auto_model), so fixed names collide across runs.
:: The killer is step [8/8], which resolves its operands BY NAME - with a
:: second component's "HighPoly_Textured" in the scene, -reprojectTexture
:: can map one component's texture onto another's mesh, silently. Names
:: are also how the intermediate-cleanup loop finds what to delete.
set "model_tag=%component_name%"
if "%model_tag%" == "" set "model_tag=maximal"

if not exist "%scene_path%" ( echo ERROR: scene not found: %scene_path% & exit /b 1 )

echo Scene: %scene_path%
echo Component: %component_name%
echo Large-triangle threshold: %large_tri_threshold%

echo Starting RealityScan
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

echo Loading scene
call :run -load "%scene_path%" || goto :fail

if "%component_name%" == "" (
    call :run -selectMaximalComponent || goto :fail
) else (
    call :run -selectComponent "%component_name%" || goto :fail
)

echo [1/8] Generating high model
call :run -calculateHighModel || goto :fail
call :run -renameSelectedModel "%model_tag%_HighPoly_Raw" || goto :fail

echo [2/8] Removing marginal (edge) triangles
set "step_skipped="
call :try_filter -selectMarginalTriangles
if not defined step_skipped call :run -renameSelectedModel "%model_tag%_Cleanup1" || goto :fail

echo [3/8] Removing large triangles (threshold %large_tri_threshold%)
set "step_skipped="
call :try_filter -selectLargeTrianglesRel %large_tri_threshold%
if not defined step_skipped call :run -renameSelectedModel "%model_tag%_Cleanup2" || goto :fail

echo [4/8] Keeping only the largest connected component
call :run -selectLargestModelComponent || goto :fail
call :run -invertTrianglesSelection || goto :fail
set "step_skipped="
call :try_remove
if not defined step_skipped call :run -renameSelectedModel "%model_tag%_Cleanup3" || goto :fail

echo [5/8] Closing holes and cleaning to a manifold model
call :run -closeHoles || goto :fail
call :run -cleanModel || goto :fail
call :run -renameSelectedModel "%model_tag%_Manifold" || goto :fail

echo [6/8] Noise-reduction simplify + texture
call :run -simplify "%SimplifyNoise%" || goto :fail
call :run -renameSelectedModel "%model_tag%_HighPoly" || goto :fail
call :run -calculateTexture "%HighModelTexture%" || goto :fail
call :run -renameSelectedModel "%model_tag%_HighPoly_Textured" || goto :fail

if defined RS_PROJECTS_DIR if defined RS_PROJECT_LABEL (
    if not exist "%RS_PROJECTS_DIR%" mkdir "%RS_PROJECTS_DIR%"
    echo Saving daily project copy - texture milestone
    call :run -save "%RS_PROJECTS_DIR%\%RS_PROJECT_LABEL%_merged_%RS_PROJECT_DATE%.rsproj" || goto :fail
)

echo [7/8] Simplify to target: 75%% per pass until at or under %RS_TARGET_TRIS% triangles
set /a pass=0
call :select_verified "%model_tag%_HighPoly_Textured" || goto :fail
echo   start: %RS_MODEL_TRIS% triangles
:simplifyLoop
if %RS_MODEL_TRIS% LEQ %RS_TARGET_TRIS% goto :simplifyDone
set /a pass+=1
call :run -simplify "%SimplifyTarget%" || goto :fail
call :run -renameSelectedModel "%model_tag%_SimplifyPass%pass%Raw" || goto :fail
call :run -cleanModel || goto :fail
call :run -renameSelectedModel "%model_tag%_SimplifyPass%pass%" || goto :fail
call :select_verified "%model_tag%_SimplifyPass%pass%" || goto :fail
echo   pass %pass%: %RS_MODEL_TRIS% triangles
goto :simplifyLoop
:simplifyDone
if %pass% EQU 0 goto :noSimplification
call :run -renameSelectedModel "%model_tag%_Simplified" || goto :fail
call :select_verified "%model_tag%_Simplified" || goto :fail
echo   %pass% pass(es); simplified model: %RS_MODEL_TRIS% triangles

echo [8/8] Unwrapping and reprojecting high-poly texture
call :try_unwrap || goto :fail
call :run -reprojectTexture "%model_tag%_HighPoly_Textured" "%model_tag%_Simplified" "%ReprojectionParams%" || goto :fail
call :select_verified "%model_tag%_Simplified" || goto :fail
call :run -renameSelectedModel "%model_tag%_Simplified_Textured" || goto :fail
goto :sweep

:noSimplification
:: Already at or under the target (owner 2026-09-06: small models need
:: none). The adaptive-4K-textured high-poly IS the deliverable: it keeps
:: its texture and takes the deliverable name; there is nothing to unwrap
:: or reproject. _HighPoly_Raw stays for the dense PLY export.
echo   already at or under the target - no simplification, no reprojection
call :run -renameSelectedModel "%model_tag%_Simplified_Textured" || goto :fail

:sweep
:: NO save before the cleanup loop. Saving with all ~15 models still present
:: costs an inordinate amount of time and disk - owner-observed, and measured
:: here: zone_1_c0's saves consumed ~81 GB with the extra write in place. The
:: deliverable is protected instead by :delete_verified, which reads the
:: selected model's name back from the report before every delete (D12,
:: 2026-09-06; a no-op select is skipped, never acted on). Only the three
:: kept models are ever saved. The pass names are dynamic (%pass% passes).
echo Deleting intermediate models
for %%M in (Cleanup1 Cleanup2 Cleanup3 Manifold HighPoly) do call :delete_verified "%model_tag%_%%M"
for /L %%I in (1,1,%pass%) do call :delete_verified "%model_tag%_SimplifyPass%%IRaw"
for /L %%I in (1,1,%pass%) do if %%I LSS %pass% call :delete_verified "%model_tag%_SimplifyPass%%I"
:: A filter/simplify step can leave a DEFAULT-NAMED residual behind - the
:: H2024 run produced one "Model N" per component (owner-observed in the
:: GUI, 2026-07-29), most likely from the large-triangle cleanup path.
:: Default names carry no component prefix, so they are swept separately.
:: Residuals from EARLIER components persist in the shared project, so by
:: the sixth component the name can be "Model 6" - sweep to 9.
:: delete_verified is tolerant: absent names are skipped, by proof.
for %%M in ("Model 1" "Model 2" "Model 3" "Model 4" "Model 5" "Model 6" "Model 7" "Model 8" "Model 9") do call :delete_verified %%M

:: POSITIVE PROOF the deliverable survived the sweep AND is textured,
:: before the save persists whatever is left: the model report names the
:: selection (F-102) and carries Textured (F-103 - an untextured model
:: exports "successfully"). A silently eaten or untextured model can no
:: longer be written to disk as if it were the product.
echo Verifying the deliverable still exists and is textured
call :select_verified "%model_tag%_Simplified_Textured" || goto :deliverableGone
if /i not "%RS_MODEL_TEXTURED%" == "true" goto :deliverableUntextured
echo   deliverable: %RS_MODEL_TRIS% triangles, %RS_MODEL_TEXTURES% texture page(s), %RS_MODEL_UNWRAP%, max %RS_MODEL_RESOLUTION% px

echo Saving project
call :run -save "%scene_path%" || goto :fail

if defined RS_PROJECTS_DIR if defined RS_PROJECT_LABEL (
    echo Saving daily project copy - final model milestone
    call :run -save "%RS_PROJECTS_DIR%\%RS_PROJECT_LABEL%_merged_%RS_PROJECT_DATE%.rsproj" || goto :fail
)

echo Shutting down RealityScan instance %RS_INSTANCE%
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:deliverableUntextured
echo ERROR: %model_tag%_Simplified_Textured reports Textured=false ^(%RS_MODEL_TEXTURES% page^(s^)^)
echo   - the unwrap or the reprojection did nothing ^(rs-reference 12 F-103^).
echo   The project was NOT saved.
goto :fail

:deliverableUntextured
echo ERROR: %model_tag%_Simplified_Textured reports Textured=false ^(%RS_MODEL_TEXTURES% page^(s^)^)
echo   - the unwrap or the reprojection did nothing ^(rs-reference 12 F-103^).
echo   The project was NOT saved.
goto :fail

:deliverableGone
echo ERROR: %model_tag%_Simplified_Textured is GONE after the intermediate
echo   sweep - the project was NOT saved, so the pre-sweep scene on disk is
echo   still intact. Re-run and check the delete loop.
goto :fail

:fail
echo ERROR: model workflow failed - see %ErrorsFile% and the RealityScan log
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :try_filter <selectCmd...> - tolerant select + remove pair: when the
:: selection finds nothing (or the remove balks at an empty selection),
:: the step is SKIPPED, evidence preserved, workflow continues - a clean
:: mesh with no marginal/large triangles must not abort the recipe.
:try_filter
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
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
        %SystemRoot%\System32\findstr.exe /c:"2147942487" /c:"2181038335" "%ErrorsFile%" >nul || (
            echo ERROR: selection %* reported a NON-whitelisted failure
            exit /b 1
        )
        echo NOTE: selection %* reported a whitelisted empty-selection code - skipping filter
        move /y "%ErrorsFile%" "%ErrorPath%\expected_select_%RS_INSTANCE%.txt" >nul
        set "step_skipped=1"
        exit /b 0
    )
)
call :try_remove
exit /b 0

:: :try_remove - tolerant -removeSelectedTriangles (empty selections may
:: error; skipping is the correct outcome).
:try_remove
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
%RealityScan% -delegateTo %RS_INSTANCE% -removeSelectedTriangles
if errorlevel 1 (
    echo ERROR: Failed to delegate -removeSelectedTriangles
    exit /b 1
)
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        %SystemRoot%\System32\findstr.exe /c:"2147942487" /c:"2181038335" "%ErrorsFile%" >nul || (
            echo ERROR: removeSelectedTriangles reported a NON-whitelisted failure
            exit /b 1
        )
        echo NOTE: removeSelectedTriangles reported a whitelisted empty-selection code
        move /y "%ErrorsFile%" "%ErrorPath%\expected_select_%RS_INSTANCE%.txt" >nul
        set "step_skipped=1"
    )
)
exit /b 0

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
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
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

:: :try_unwrap - AdaptiveTexelSize first, MaxTexturesCount 4 x 4096 second.
:: The adaptive attempt is delegated with the same double-wait shape as
:: :run, but an error is a FALLBACK, not an abort: the errors file moves to
:: an evidence name and the fallback unwrap runs through :run, so a second
:: failure still aborts the workflow. What this cannot see is an unwrap
:: that neither errors nor mutates the scene; the Python census
:: (run_decimate.info / rs verify) is what proves "Textured" downstream.
:: Single-line exits only: `exit /b N` inside a parenthesized block returns
:: 0 to the caller (CLAUDE.md, Windows automation traps).
:try_unwrap
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
%RealityScan% -delegateTo %RS_INSTANCE% -unwrap "%UnwrapSimplified%"
if errorlevel 1 goto :unwrapDelegateFailed
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if not exist "%ErrorsFile%" exit /b 0
for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 goto :unwrapFallback
exit /b 0

:unwrapFallback
echo NOTE: adaptive unwrap reported an error on %model_tag% - falling back to MaxTexturesCount 4 x 4096
move /y "%ErrorsFile%" "%ErrorPath%\expected_unwrap_adaptive_%RS_INSTANCE%_%model_tag%.txt" >nul
call :run -unwrap "%UnwrapFallback%" || exit /b 1
exit /b 0

:unwrapDelegateFailed
echo ERROR: Failed to delegate -unwrap "%UnwrapSimplified%"
exit /b 1

:: :run - delegate one operation, double-wait, abort on reported error
:: (see AlignZone.bat for the rationale).
:run
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
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
