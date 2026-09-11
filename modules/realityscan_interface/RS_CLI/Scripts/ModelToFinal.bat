@echo off
setlocal EnableDelayedExpansion
:: Take an ALREADY-COMPUTED model through to final deliverables:
::   [color correction] -> [cull] -> texture -> [simplify] -> unwrap ->
::   reproject -> export -> save
::
:: This is the back half of AlignImagesFromFolder.bat, split out so it can
:: run against a scene whose mesh already exists (e.g. a Normal Detail
:: reconstruction computed interactively in the GUI). It NEVER calculates a
:: mesh and NEVER creates a new scene.
::
:: Arguments (all optional; sensible defaults applied when omitted):
::   %1 target instance      instance name, or * for "first available"
::                           (default: %RS_INSTANCE%, else *)
::   %2 export directory     where final model files are written (required
::                           unless export=none)
::   %3 final model name     base name for the exported model (default Final)
::   %4 texture preset       adaptive|fixed100|fixed50
::                           (default adaptive - AdaptiveTexelSize, 4096 cap)
::   %5 simplify             true/false (default false)
::   %6 export format        obj|objmetric|fbx|glb|none (default obj)
::                           obj = stock preset, scale 100 (Unreal);
::                           objmetric = same OBJ at true scale 1.0
::   %7 cull polygons        true/false (default false)
::   %8 correct colors       true/false (default false)
::   %9 source model name    model to start from; omit to use the model that
::                           is already selected in the scene
::
:: SAFETY: this script attaches to a RUNNING instance. It deliberately does
:: NOT call startRealityScan.bat, because that script issues
:: "-newScene -deleteAutosave" when it finds an instance already running,
:: which would destroy the live scene this workflow exists to finish.

:: Record whether the CALLER set RS_INSTANCE, before SetVariables.bat does.
:: SetVariables.bat runs "if not defined RS_INSTANCE set RS_INSTANCE=RS1"
:: unconditionally, so after that call RS_INSTANCE is ALWAYS defined and any
:: later "if defined RS_INSTANCE" test is dead code.
set "RS_INSTANCE_FROM_CALLER="
if defined RS_INSTANCE set "RS_INSTANCE_FROM_CALLER=1"

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "MetadataDir=%Metadata%"

:: ---------------------------------------------------------------- args
if not "%~1" == "" ( set "RS_TARGET=%~1" ) else ( if defined RS_INSTANCE_FROM_CALLER ( set "RS_TARGET=%RS_INSTANCE%" ) else ( set "RS_TARGET=*" ) )
set "export_dir=%~2"
if "%~3" == "" ( set "final_name=Final" ) else ( set "final_name=%~3" )
:: Default preset "adaptive" (owner 2026-09-05, decision D13):
:: unwrapStyle=AdaptiveTexelSize with a 4096 page cap, matching
:: GenerateModel.bat. The MaxTexturesCount presets (8k, 4x8k, 16k, highpoly)
:: are retired to archive/metadata_retired/ - never 16K, and no forced 4 x 8K
:: page budget - so nothing above 4096 can reach an exported deliverable.
:: fixed100 / fixed50 (FixedTexelSize, also capped at 4096) stay as explicit
:: alternatives.
if "%~4" == "" ( set "tex_preset=adaptive" ) else ( set "tex_preset=%~4" )
if "%~5" == "" ( set "simplify_model=false" ) else ( set "simplify_model=%~5" )
if "%~6" == "" ( set "export_format=obj" ) else ( set "export_format=%~6" )
if "%~7" == "" ( set "cull_polygons=false" ) else ( set "cull_polygons=%~7" )
if "%~8" == "" ( set "correct_colors=false" ) else ( set "correct_colors=%~8" )
set "source_model=%~9"

:: Resolve the texture preset to one of the repo's parameter XMLs.
set "TexParams="
if /i "%tex_preset%" == "adaptive"  set "TexParams=%MetadataDir%\Texturing_AdaptiveTexel_4k.xml"
if /i "%tex_preset%" == "fixed100"  set "TexParams=%MetadataDir%\Texturing_FixedTexelSize100perQuality.xml"
if /i "%tex_preset%" == "fixed50"   set "TexParams=%MetadataDir%\Texturing_FixedTexelSize50perQuality.xml"
:: NOTE: every failure below jumps to a label that ends in a single-line
:: "exit /b 1". A multi-statement parenthesized block containing exit /b
:: returns 0 to the process caller, which would make these guards silent.
if not defined TexParams goto :badPreset
if not exist "%TexParams%" goto :noTexParams

:: Simplification target (D12, owner 2026-09-06), matching GenerateModel.bat:
:: 75%% KEPT per pass until the model is at or under RS_TARGET_TRIS
:: triangles; a model already under needs no pass and is exported as is.
:: (Until 2026-09-06: four fixed 80%% passes = 41%% of the input, whatever
:: the input was.)
if not defined RS_TARGET_TRIS set "RS_TARGET_TRIS=10000000"
set "SimplifyTarget=%MetadataDir%\Simplify75per_Params.xml"
set "ReprojParams=%MetadataDir%\ReprojectionParams.xml"
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
set "ReportHtml=%TEMP%\rs_model_report_modeltofinal.html"

:: The UV layout of the FINAL model comes from the unwrap preset, not from
:: the texture preset - with simplify on, the exported model is the
:: simplified one and it is unwrapped fresh. That unwrap is ALWAYS
:: AdaptiveTexelSize at the 4096 cap, whatever texture preset was chosen
:: (D13: never 16K, never a forced 4 x 8K page budget). Until 2026-09-05
:: every preset but 4x8k fell through to a 1 x 16384 unwrap here
:: (rs-reference 10 A4). AdaptiveTexelSize can reject a particular mesh
:: (FINDINGS 2026-09-03, c5), so :try_unwrap falls back to MaxTexturesCount
:: 4 x 4096 - still inside the cap - when adaptive does nothing.
set "UnwrapSimplified=%MetadataDir%\Unwrapping_AdaptiveTexel_4k.xml"
set "UnwrapFallback=%MetadataDir%\Unwrapping_MaxCount4_4k.xml"
if not exist "%UnwrapSimplified%" goto :noUnwrapParams
if not exist "%UnwrapFallback%" goto :noUnwrapParams

:: Resolve the export format to an extension + parameter XML.
set "ExportExt="
set "ExportParams="
if /i "%export_format%" == "obj" ( set "ExportExt=obj" & set "ExportParams=%MetadataDir%\ModelExportParamsObj.xml" )
:: objmetric = the same OBJ at TRUE SCALE. Every stock export preset scales
:: up (100 for the Unreal presets, 10 for GLB), which is right for engines
:: and wrong for survey/GIS work: an ON2026 export at scale 100 put vertex 0
:: at -179.90 1101.54 43.67 where the local frame is metres. Without this
:: branch ModelExportParamsObj_Metric.xml is unreachable dead config.
if /i "%export_format%" == "objmetric" ( set "ExportExt=obj" & set "ExportParams=%MetadataDir%\ModelExportParamsObj_Metric.xml" )
if /i "%export_format%" == "fbx" ( set "ExportExt=fbx" & set "ExportParams=%MetadataDir%\ModelExportParamsFBX_U1V1_material.xml" )
if /i "%export_format%" == "glb" ( set "ExportExt=glb" & set "ExportParams=%MetadataDir%\ModelExportParamsGLB.xml" )
if /i "%export_format%" == "none" ( set "ExportExt=" & set "ExportParams=" & goto :formatOk )
if not defined ExportExt goto :badFormat
if "%export_dir%" == "" goto :noExportDir
if not exist "%export_dir%" mkdir "%export_dir%"
:formatOk

set "CULL_BOOL="
if /i "%cull_polygons%" == "true" set CULL_BOOL=1
set "SIMPLIFY_BOOL="
if /i "%simplify_model%" == "true" set SIMPLIFY_BOOL=1
set "COLOR_BOOL="
if /i "%correct_colors%" == "true" set COLOR_BOOL=1

echo.
echo === ModelToFinal ===
echo Target instance : %RS_TARGET%
echo Source model    : %source_model%
echo Correct colors  : %correct_colors%
echo Cull polygons   : %cull_polygons%
echo Texture preset  : %tex_preset% (%TexParams%)
echo Simplify        : %simplify_model%
echo Unwrap (final)  : %UnwrapSimplified%
echo Unwrap fallback : %UnwrapFallback%
echo Export          : %export_format%  -^> %export_dir%
echo Final name      : %final_name%
echo.

:: ------------------------------------------------------- attach safely
:: Only ever attach to an instance that already exists. Never boot one and
:: never reset a scene from here.
%RealityScan% -getStatus %RS_TARGET% >nul 2>&1
if errorlevel 1 goto :noInstance

echo Waiting for any in-flight operation on %RS_TARGET% to finish...
%RealityScan% -waitCompleted %RS_TARGET%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_TARGET%

:: ------------------------------------------------------------ workflow
if not "%source_model%" == "" (
    echo Selecting source model "%source_model%"
    call :run -selectModel "%source_model%" || goto :fail
)

if defined COLOR_BOOL (
    echo Correcting image colors
    call :run -correctColors || goto :fail
)

if defined CULL_BOOL (
    echo Culling polygons
    call :run -cleanModel || goto :fail
    call :run -renameSelectedModel "CullTemp1" || goto :fail

    call :run -selectLargeTrianglesRel 20 || goto :fail
    call :run -removeSelectedTriangles || goto :fail
    call :run -renameSelectedModel "CullTemp2" || goto :fail

    call :run -cleanModel || goto :fail
    call :run -renameSelectedModel "Culled" || goto :fail

    call :delete_verified "CullTemp1"
    call :delete_verified "CullTemp2"
    call :select_verified "Culled" || goto :fail
)

echo Texturing model
call :run -calculateTexture "%TexParams%" || goto :fail
call :run -renameSelectedModel "HighPolyTextured" || goto :fail
set "final_source=HighPolyTextured"

if not defined SIMPLIFY_BOOL goto :exportStage

echo Simplifying model - 75%% per pass until at or under %RS_TARGET_TRIS% triangles
set /a pass=0
call :select_verified "HighPolyTextured" || goto :fail
echo   start: %RS_MODEL_TRIS% triangles
:simplifyLoop
if %RS_MODEL_TRIS% LEQ %RS_TARGET_TRIS% goto :simplifyDone
set /a pass+=1
call :run -simplify "%SimplifyTarget%" || goto :fail
call :run -renameSelectedModel "SimplifyPass%pass%Raw" || goto :fail
call :run -cleanModel || goto :fail
call :run -renameSelectedModel "SimplifyPass%pass%" || goto :fail
call :select_verified "SimplifyPass%pass%" || goto :fail
echo   pass %pass%: %RS_MODEL_TRIS% triangles
goto :simplifyLoop
:simplifyDone
:: Already at or under the target: the textured high-poly is exported as
:: is (final_source is still HighPolyTextured).
if %pass% EQU 0 goto :exportStage
call :run -renameSelectedModel "Simplified" || goto :fail

echo Deleting intermediate simplification models
for /L %%I in (1,1,%pass%) do call :delete_verified "SimplifyPass%%IRaw"
for /L %%I in (1,1,%pass%) do if %%I LSS %pass% call :delete_verified "SimplifyPass%%I"

echo Unwrapping simplified model
call :select_verified "Simplified" || goto :fail
call :try_unwrap || goto :fail

echo Reprojecting texture onto simplified model
call :run -reprojectTexture "HighPolyTextured" "Simplified" "%ReprojParams%" || goto :fail
:: Re-select the reprojection TARGET explicitly before renaming. -reproject-
:: Texture takes source and result as arguments and does not document which
:: of the two it leaves selected, so renaming "whatever is selected" could
:: rename the source. GenerateModel.bat does the same re-select for the same
:: reason.
call :select_verified "Simplified" || goto :fail
call :run -renameSelectedModel "SimplifiedTextured" || goto :fail
set "final_source=SimplifiedTextured"

:exportStage
echo Selecting final model "%final_source%"
call :select_verified "%final_source%" || goto :fail
if /i not "%RS_MODEL_TEXTURED%" == "true" goto :deliverableUntextured
echo   deliverable: %RS_MODEL_TRIS% triangles, %RS_MODEL_TEXTURES% texture page(s), %RS_MODEL_UNWRAP%, max %RS_MODEL_RESOLUTION% px
call :run -renameSelectedModel "%final_name%" || goto :fail

if "%export_format%" == "none" goto :saveProject
if /i "%export_format%" == "none" goto :saveProject

echo Exporting %final_name%.%ExportExt% to %export_dir%
call :run -exportSelectedModel "%export_dir%\%final_name%.%ExportExt%" "%ExportParams%" || goto :fail

:saveProject
:: RS_SAVE_PATH is an environment variable rather than a 10th positional
:: argument because cmd only exposes %1-%9, and because a path is exactly the
:: kind of value that must not be squeezed through argument splitting.
:: Bare -save writes back to the project's original location; with no original
:: location (a scene built interactively and never saved) that has nothing to
:: write to, so prefer an explicit path.
if defined RS_SAVE_PATH (
    echo Saving project as "%RS_SAVE_PATH%"
    call :run -save "%RS_SAVE_PATH%" || goto :fail
) else (
    echo Saving project to its original location
    call :run -save || goto :fail
)

echo.
echo ModelToFinal completed successfully.
exit /b 0

:fail
echo.
echo ERROR: ModelToFinal failed - see the RealityScan log at
echo        %%LOCALAPPDATA%%\Temp\RealityScan.log
echo        The instance was left running and the scene untouched by teardown.
exit /b 1

:deliverableUntextured
echo ERROR: "%final_source%" reports Textured=false ^(%RS_MODEL_TEXTURES% page^(s^)^) - the
echo        unwrap or the reprojection did nothing ^(rs-reference 12 F-103^). Nothing exported.
exit /b 1

:badPreset
echo ERROR: unknown texture preset "%tex_preset%" - use adaptive^|fixed100^|fixed50
exit /b 1

:noTexParams
echo ERROR: texture parameter file not found: %TexParams%
exit /b 1

:noUnwrapParams
echo ERROR: unwrap parameter file not found: %UnwrapSimplified% or %UnwrapFallback%
exit /b 1

:badFormat
echo ERROR: unknown export format "%export_format%" - use obj^|objmetric^|fbx^|glb^|none
exit /b 1

:noExportDir
echo ERROR: an export directory is required unless the export format is "none"
exit /b 1

:noInstance
echo ERROR: no reachable RealityScan instance "%RS_TARGET%".
echo        This workflow attaches to a running instance whose mesh is already
echo        computed; it does not start one and never resets a scene. Boot an
echo        instance and load the project first, or pass the right instance name.
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
call :run -selectModel "%~1"
if errorlevel 1 goto :deleteDelegateFailed
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

:: ------------------------------------------------------------------
:: :try_unwrap - AdaptiveTexelSize first, MaxTexturesCount 4 x 4096 second.
:: In attach mode the truth is -getStatus, and "rev" tracks scene
:: MUTATIONS: an unwrap that took advances it, one that did nothing leaves
:: it where it was (FINDINGS 2026-09-03, c5: lastError 0x83000003, rev
:: unchanged, three times). The adaptive attempt succeeds only when :run
:: passes AND rev moved. Otherwise the fallback runs - through :run, with
:: all three of its gates: lastError is sticky only while the instance is
:: IDLE and clears the instant the next operation starts (FINDINGS
:: 2026-08-04, 2026-08-07, ESTABLISHED), so :run's baseline reads the
:: adaptive failure's code and a successful fallback lands on lastError 0.
:: On the pipeline's OWN instance the adaptive failure also sits in
:: errors_<inst>.txt, which :run's marker gate would otherwise blame on the
:: fallback (or on the -reprojectTexture after it); it is MOVED to an
:: evidence file first - the sanctioned tolerant-variant pattern
:: (rs-reference 11 sec.2.3). Both attempts leaving rev unchanged = the
:: model is not unwrapped = abort. Single-line exits only.
:: ------------------------------------------------------------------
:try_unwrap
call :readstat
set "RS_UNWRAP_REV0=%RS_REV%"
call :run -unwrap "%UnwrapSimplified%"
if errorlevel 1 goto :unwrapFallback
call :readstat
if not "%RS_REV%" == "%RS_UNWRAP_REV0%" exit /b 0
echo NOTE: adaptive unwrap left the scene revision unchanged at %RS_REV% - it did nothing

:unwrapFallback
echo NOTE: falling back to MaxTexturesCount 4 x 4096: %UnwrapFallback%
if "%RS_TARGET%" == "%RS_INSTANCE%" for %%A in ("%ErrorPath%\errors_%RS_INSTANCE%.txt") do if %%~zA GTR 0 move /y "%%~A" "%ErrorPath%\expected_unwrap_adaptive_%RS_INSTANCE%_%final_name%.txt" >nul
call :readstat
set "RS_UNWRAP_REV0=%RS_REV%"
call :run -unwrap "%UnwrapFallback%" || exit /b 1
call :readstat
if "%RS_REV%" == "%RS_UNWRAP_REV0%" goto :unwrapBothFailed
exit /b 0

:unwrapBothFailed
echo ERROR: both unwrap styles left the scene revision unchanged at %RS_REV% - the model is NOT unwrapped
exit /b 1

:: ------------------------------------------------------------------
:: :run <command...> - delegate one operation to %RS_TARGET%, wait for it
:: to finish, and fail if RealityScan reported an error.
::
:: Same delegate/grace/double-waitCompleted contract as the other workflow
:: scripts (delegated commands are queued, and -waitCompleted can return
:: prematurely when it runs before the instance picks the command up).
::
:: Error gate: an instance that was started from the GUI has no
:: ErrorWriter.bat process hook, so errors_<instance>.txt does not exist for
:: it. Instead this reads the "lastError:" field that -getStatus prints, and
:: still honours the marker file when one IS present (CLI-booted instances).
:: ------------------------------------------------------------------
:run
:: Baseline BOTH fields first. lastError is STICKY between operations
:: (a failed -save left lastError:-2113863583 across four idle polls), so
:: gating on lastError alone blames this command for someone else's error.
:: And "rev" tracks scene MUTATIONS, not operations - live-probed
:: 2026-08-07: a failed -selectModel left rev unchanged (11 -> 11) while
:: setting lastError 0x80070057 through the process trigger. So "rev
:: advanced" cannot be the only failure signal either. The gate below:
::   lastError changed to non-zero  -> OUR failure (rev irrelevant)
::   same non-zero code, rev moved  -> failure (conservative)
::   same non-zero code, same rev   -> stale carry-over, warn + continue
call :readstat
set "RS_REV0=%RS_REV%"
set "RS_LASTERR0=%RS_LASTERR%"

call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
%RealityScan% -delegateTo %RS_TARGET% %*
if errorlevel 1 goto :runDelegateFailed
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_TARGET%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_TARGET%

:: Marker-file gate. Only meaningful when we are actually talking to the
:: instance that owns that marker file. Attached to a foreign instance via
:: "*", errors_RS1.txt belongs to somebody else and is never cleared by us
:: (RealityScanCLI._clear_markers only runs inside run_batch_script, which
:: this script deliberately does not use), so a stale non-empty file would
:: abort our FIRST operation on an unrelated error.
if not "%RS_TARGET%" == "%RS_INSTANCE%" goto :statusGate
if not exist "%ErrorPath%\errors_%RS_INSTANCE%.txt" goto :statusGate
for %%A in ("%ErrorPath%\errors_%RS_INSTANCE%.txt") do if %%~zA GTR 0 goto :runMarkerErr

:statusGate
call :readstat
:: Silence is not success: an empty status from a VANISHED instance means
:: it died or was closed mid-operation - especially poisonous on the final
:: -save, which would otherwise report "completed successfully" over a
:: crash (clean-sweep 2026-08-07). Distinguish "no status text" (benign,
:: instance idle-and-quiet) from "instance gone" via the getStatus
:: errorlevel that :readstat just recorded.
if not defined RS_STATUS (
    if not "%RS_STAT_RC%" == "0" goto :runInstanceGone
    goto :runOk
)
if "%RS_LASTERR%" == "" goto :runOk
if "%RS_LASTERR%" == "0" goto :runOk
if not "%RS_LASTERR%" == "%RS_LASTERR0%" goto :runNewErr
if not "%RS_REV%" == "%RS_REV0%" goto :runNewErr
goto :runStaleErr

:runNewErr
echo ERROR: RealityScan reported lastError:%RS_LASTERR% (was %RS_LASTERR0%, rev %RS_REV0%-^>%RS_REV%) during: %*
exit /b 1

:runInstanceGone
echo ERROR: instance %RS_TARGET% VANISHED during: %*
echo        getStatus no longer answers - the instance crashed or was
echo        closed mid-operation. The operation result is UNKNOWN.
exit /b 1

:runStaleErr
echo WARNING: stale lastError:%RS_LASTERR% carried over from an earlier
echo          operation (rev unchanged at %RS_REV%) - not attributing it to: %*
goto :runOk

:runOk
exit /b 0

:runDelegateFailed
echo ERROR: Failed to delegate command: %*
exit /b 1

:runMarkerErr
echo ERROR: RealityScan reported a failure during: %*
exit /b 1

:: ------------------------------------------------------------------
:: :readstat - set RS_STATUS / RS_REV / RS_LASTERR from -getStatus.
:: Delayed expansion throughout: the status line contains a literal '%'
:: (progress:50.0%) which must not be reinterpreted at parse time.
:: ------------------------------------------------------------------
:readstat
set "RS_STATUS="
set "RS_REV="
set "RS_LASTERR="
set "RS_STAT_RC=1"
for /f "usebackq tokens=*" %%S in (`%RealityScan% -getStatus %RS_TARGET% 2^>nul`) do set "RS_STATUS=%%S"
:: Existence probe, separate from the capture: for /f eats the errorlevel.
%RealityScan% -getStatus %RS_TARGET% >nul 2>&1
if not errorlevel 1 set "RS_STAT_RC=0"
if not defined RS_STATUS exit /b 0
echo !RS_STATUS! | %SystemRoot%\System32\find.exe "rev:" >nul
if not errorlevel 1 (
    set "RS_TMP=!RS_STATUS:*rev:=!"
    for /f "tokens=1 delims= " %%R in ("!RS_TMP!") do set "RS_REV=%%R"
)
echo !RS_STATUS! | %SystemRoot%\System32\find.exe "lastError:" >nul
if not errorlevel 1 (
    set "RS_TMP=!RS_STATUS:*lastError:=!"
    for /f "tokens=1 delims= " %%E in ("!RS_TMP!") do set "RS_LASTERR=%%E"
)
exit /b 0
