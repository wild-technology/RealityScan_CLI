@echo off
setlocal
:: Model generation for an already-aligned scene - owner-specified recipe
:: (2026-07-23):
::   Generate High -> remove marginal (edge) triangles -> remove large
::   triangles (30 threshold) -> keep largest connected component ->
::   close holes -> clean model (the CLI equivalent of the GUI Check
::   Integrity / Check Topology FIX actions; the checks themselves have
::   no CLI commands) -> simplify (noise) -> generate texture ->
::   simplify (smooth) 80% x4 with clean between -> unwrap -> reproject
::   high-poly texture.
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
:: Texture budget (owner 2026-07-29): no more than FOUR large textures,
:: adaptive. unwrapStyle=MaxTexturesCount IS the adaptive mode - texel size
:: adapts to fit the count - so 4 x 16K caps the budget while small
:: components use fewer/smaller. Previously 2 x 16K (high poly) and
:: 1 x 16K (simplified unwrap).
:: 8K cap (owner 2026-07-31): both texture passes limited to 4 x 8K.
set "HighModelTexture=%MetadataDir%\Texturing_MaxTextureCount4_8k.xml"
set "SimplifyNoise=%MetadataDir%\SimplifyNoise_Params.xml"
set "SimplifySmooth=%MetadataDir%\SimplifySmooth_80per_Params.xml"
set "UnwrapSimplified=%MetadataDir%\Unwrapping_Simplified_4x8k.xml"
set "ReprojectionParams=%MetadataDir%\ReprojectionParams.xml"

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

echo [7/8] Smooth simplification - four 80%% passes with clean between
call :run -simplify "%SimplifySmooth%" || goto :fail
call :run -renameSelectedModel "%model_tag%_SimplifyPass1Raw" || goto :fail
call :run -cleanModel || goto :fail
call :run -renameSelectedModel "%model_tag%_SimplifyPass1" || goto :fail

call :run -simplify "%SimplifySmooth%" || goto :fail
call :run -renameSelectedModel "%model_tag%_SimplifyPass2Raw" || goto :fail
call :run -cleanModel || goto :fail
call :run -renameSelectedModel "%model_tag%_SimplifyPass2" || goto :fail

call :run -simplify "%SimplifySmooth%" || goto :fail
call :run -renameSelectedModel "%model_tag%_SimplifyPass3Raw" || goto :fail
call :run -cleanModel || goto :fail
call :run -renameSelectedModel "%model_tag%_SimplifyPass3" || goto :fail

call :run -simplify "%SimplifySmooth%" || goto :fail
call :run -renameSelectedModel "%model_tag%_SimplifyPass4Raw" || goto :fail
call :run -cleanModel || goto :fail
call :run -renameSelectedModel "%model_tag%_Simplified" || goto :fail

echo [8/8] Unwrapping and reprojecting high-poly texture
call :run -unwrap "%UnwrapSimplified%" || goto :fail
call :run -reprojectTexture "%model_tag%_HighPoly_Textured" "%model_tag%_Simplified" "%ReprojectionParams%" || goto :fail
call :run -selectModel "%model_tag%_Simplified" || goto :fail
call :run -renameSelectedModel "%model_tag%_Simplified_Textured" || goto :fail

:: NO save before the cleanup loop. Saving with all ~15 models still present
:: costs an inordinate amount of time and disk - owner-observed, and measured
:: here: zone_1_c0's saves consumed ~81 GB with the extra write in place. The
:: deliverable is protected instead by the double-wait in :try_delete_model,
:: which reliably detects a no-op select on a missing intermediate before any
:: delete runs (audit #4). Only the three kept models are ever saved.
echo Deleting intermediate models
for %%M in (Cleanup1 Cleanup2 Cleanup3 Manifold HighPoly SimplifyPass1Raw SimplifyPass1 SimplifyPass2Raw SimplifyPass2 SimplifyPass3Raw SimplifyPass3 SimplifyPass4Raw) do (
    call :try_delete_model "%model_tag%_%%M"
)
:: A filter/simplify step can leave a DEFAULT-NAMED residual behind - the
:: H2024 run produced one "Model N" per component (owner-observed in the
:: GUI, 2026-07-29), most likely from the large-triangle cleanup path.
:: Default names carry no component prefix, so they are swept separately.
:: Residuals from EARLIER components persist in the shared project, so by
:: the sixth component the name can be "Model 6" - sweep to 9.
:: try_delete_model is tolerant: absent names are skipped silently.
for %%M in ("Model 1" "Model 2" "Model 3" "Model 4" "Model 5" "Model 6" "Model 7" "Model 8" "Model 9") do (
    call :try_delete_model %%M
)

echo Saving project
call :run -save "%scene_path%" || goto :fail

if defined RS_PROJECTS_DIR if defined RS_PROJECT_LABEL (
    echo Saving daily project copy - final model milestone
    call :run -save "%RS_PROJECTS_DIR%\%RS_PROJECT_LABEL%_merged_%RS_PROJECT_DATE%.rsproj" || goto :fail
)

echo Shutting down RealityScan instance %RS_INSTANCE%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:fail
echo ERROR: model workflow failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :try_filter <selectCmd...> - tolerant select + remove pair: when the
:: selection finds nothing (or the remove balks at an empty selection),
:: the step is SKIPPED, evidence preserved, workflow continues - a clean
:: mesh with no marginal/large triangles must not abort the recipe.
:try_filter
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

:: :try_delete_model <name> - delete an intermediate model if it exists;
:: missing intermediates (skipped filter steps) are not an error.
:: Uses the SAME double-wait shape as every other subroutine: the old single
:: short wait could return before the instance picked the select up, so a
:: no-op select on a missing name left the PREVIOUS selection live - which at
:: loop entry is the final textured model - and the delete that followed
:: targeted the deliverable (audit #4). Evidence moves get per-model names so
:: twelve iterations stop overwriting each other.
:try_delete_model
%RealityScan% -delegateTo %RS_INSTANCE% -selectModel "%~1"
if errorlevel 1 (
    echo NOTE: could not delegate -selectModel %~1 - leaving intermediate in place
    exit /b 0
)
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        move /y "%ErrorsFile%" "%ErrorPath%\expected_select_%RS_INSTANCE%_%~1.txt" >nul
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
        move /y "%ErrorsFile%" "%ErrorPath%\expected_delete_%RS_INSTANCE%_%~1.txt" >nul
    )
)
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
