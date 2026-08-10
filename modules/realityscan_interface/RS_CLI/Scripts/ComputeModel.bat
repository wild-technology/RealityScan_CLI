@echo off
setlocal
:: Mesh-only FRONT half of the per-feature model chain (2026-08-08):
:: load a merged scene, select ONE component, calculate the high model,
:: give it a feature-bound name, save - and LEAVE THE INSTANCE RUNNING
:: with the scene loaded, so finish_model.py / ModelToFinal.bat (the
:: attach-only back half) can texture/simplify/export it. The caller owns
:: quitting the instance afterwards.
::
:: WHY IT EXISTS: GenerateModel.bat's owner recipe includes unconditional
:: keep-largest-mesh-component + large-triangle culls - correct for noisy
:: hull zones, destructive for thin features (masts, a stern flag-pole)
:: that mesh as several islands. ModelToFinal.bat deliberately NEVER
:: calculates a mesh. This is the missing headless mesh step, with NO
:: cleanup: cull decisions belong to the back half's optional gentle cull.
::
:: Arguments:
::   %1 .rsproj scene path (required)
::   %2 component name to model ("" = maximal component)
::   %3 model name to assign (required; feature-bound, e.g.
::      ON2026_RH0041_RH2042_mast_a_HighPoly)

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: scene path required & exit /b 1 )
if [%3] == [] ( echo ERROR: model name required & exit /b 1 )
set "scene_path=%~1"
set "component_name=%~2"
set "model_name=%~3"

if not exist "%scene_path%" ( echo ERROR: scene not found: %scene_path% & exit /b 1 )

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

:: RS_MESH_DOWNSCALE (env, optional): depth-map downscale factor for
:: THIS mesh. 2 quarters the depth-map cache footprint (the full-res
:: hull mesh needs ~1.4+ TB and exhausted M: on 2026-08-10, the
:: historical 0x80070070 killer); texture resolution is unaffected.
:: Unset = RealityScan's current setting (full res).
if defined RS_MESH_DOWNSCALE if not "%RS_MESH_DOWNSCALE%" == "" (
    echo Setting depth-map downscale %RS_MESH_DOWNSCALE%
    call :run -setDownscaleForDepthMaps %RS_MESH_DOWNSCALE% || goto :fail
)

echo Calculating high model
call :run -calculateHighModel || goto :fail
call :run -renameSelectedModel "%model_name%" || goto :fail

echo Saving scene with the computed model
call :run -save "%scene_path%" || goto :fail

echo ComputeModel done - instance %RS_INSTANCE% left RUNNING with the
echo scene loaded for the attach-only finish step (caller quits it).
exit /b 0

:fail
echo ERROR: ComputeModel workflow failed - see %ErrorsFile%
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :run - delegate one operation, double-wait, abort if RealityScan
:: reported an error (shared pattern - see AlignZone.bat).
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
