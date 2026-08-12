@echo off
setlocal
:: ATTACH-ONLY night-growth primitive set (owner directive 2026-08-11).
:: Drives the ALREADY-RUNNING GUI instance %RS_TARGET% (RSGUI). Never
:: boots, never -newScene, never -quit: the GrowZone/startRealityScan
:: reuse path would WIPE the loaded workbench (-newScene) and this
:: build rejects -deleteAutosave (err:7180, async - FINDINGS
:: 2026-08-11); run_batch_script would SHUT the instance DOWN. Modeled
:: on ModelToFinal.bat's attach contract instead.
::
:: Modes (%1):
::   saveonly   %2 scene
::   census     %2 scene  %3 outdir  %4 harvest_root_a  %5 harvest_root_b
::              save -> destructive in-memory peel (successive
::              difference; min comp 2) -> reload scene = NON-DESTRUCTIVE
::              census (probe-validated 2026-08-11: byte-identical
::              re-export after reload)
::   delete2nd  %2 scene  %3 component_name   (checkpoint FIRST - caller)
::   addorphans %2 scene  %3 imagelist  %4 flightlog  %5 flparams
::              add -> priors -> select added -> ALL-FEATURES (2) +
::              enable -> save   (owner: added images are 'All Features',
::              registered images keep their existing source)
::   seedpass   %2 scene  %3 enable_imagelist  %4 alignparams_xml
::              disable ALL -> enable ONLY the list (small comps +
::              orphans; largest stays disabled per owner) -> pinned
::              sfm keys -> align -> save
::   mergefinal %2 scene  %3 alignparams_xml  %4 engine(merge|align)
::              enable ALL -> pinned keys -> rigid -mergeComponents
::              (free consolidation, cannot shrink) or -align rung ->
::              save
::
:: Every mutating mode SAVES the scene at the end; the caller owns
:: checkpoints (module_base/scene_checkpoint) and the never-shrink
:: verdict from the census.

call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

:: Attach contract (run_attach_script): %1 = TARGET instance name -
:: RS_INSTANCE keeps meaning "the instance this checkout boots", which
:: NightGrow never does.
if [%1] == [] ( echo ERROR: target instance required & exit /b 1 )
set "RS_TARGET=%~1"
set "ErrorsFile=%ErrorPath%\errors_%RS_TARGET%.txt"

if [%2] == [] ( echo ERROR: mode required & exit /b 1 )
set "mode=%~2"
set "scene=%~3"
if not exist "%scene%" ( echo ERROR: scene not found: %scene% & exit /b 1 )

:: Attach guard - the instance must already be up; we never boot it.
%RealityScan% -getStatus %RS_TARGET%
if errorlevel 1 ( echo ERROR: instance %RS_TARGET% is not running & exit /b 1 )

if /I "%mode%" == "saveonly"   goto :saveonly
if /I "%mode%" == "census"     goto :census
if /I "%mode%" == "censuslight" goto :censuslight
if /I "%mode%" == "delete2nd"  goto :censuslight
set "outdir=%~4"
set "harvest_a=%~5"
set "harvest_b=%~6"
if not exist "%outdir%" mkdir "%outdir%"
call :run -save "%scene%" || goto :fail
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { foreach ($r in @('%harvest_a%','%harvest_b%')) { if ($r -and (Test-Path -LiteralPath $r)) { Get-ChildItem -LiteralPath $r -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%outdir%' -Force } } } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 ( echo ERROR: light census harvest failed & goto :fail )
echo NIGHTGROW OK censuslight
exit /b 0

:deletesecond
:: Name-free second-largest deletion. -selectComponent silently no-ops
:: on RS-generated names like 'Component 23 (1)', and BARE
:: selectMaximal/delete after a -load ALSO silently no-op (2026-08-12:
:: identical census after "ok" exit) - the census peel's deselect +
:: exportXMP preamble is what makes component ops take effect, so this
:: mode reproduces the census context EXACTLY, then: delete maximal
:: (promotes victim), delete new maximal (victim), re-import the
:: largest from its census export (%4), save. Exported hydration XMPs
:: are swept to %5 (trash dir). Verified by the caller's census.
set "largest_rsalign=%~4"
set "xmp_trash=%~5"
set "harvest_a=%~6"
set "harvest_b=%~7"
if not exist "%largest_rsalign%" ( echo ERROR: largest export not found: %largest_rsalign% & exit /b 1 )
if not exist "%xmp_trash%" mkdir "%xmp_trash%"
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { foreach ($r in @('%harvest_a%','%harvest_b%')) { if ($r -and (Test-Path -LiteralPath $r)) { Get-ChildItem -LiteralPath $r -Recurse -Filter *.xmp | Move-Item -Destination '%xmp_trash%' -Force } } } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 ( echo ERROR: hydration sweep failed & goto :fail )
call :run -selectMaximalComponent || goto :fail
call :run -deleteSelectedComponent || goto :fail
call :run -selectMaximalComponent || goto :fail
call :run -deleteSelectedComponent || goto :fail
call :run -importComponent "%largest_rsalign%" || goto :fail
call :run -save "%scene%" || goto :fail
echo NIGHTGROW OK deletesecond
exit /b 0

:delete2nd
if /I "%mode%" == "addorphans" goto :addorphans
if /I "%mode%" == "seedpass"   goto :seedpass
if /I "%mode%" == "mergefinal" goto :mergefinal
echo ERROR: unknown mode %mode%
exit /b 1

:saveonly
call :run -save "%scene%" || goto :fail
echo NIGHTGROW OK saveonly
exit /b 0

:census
set "outdir=%~4"
set "harvest_a=%~5"
set "harvest_b=%~6"
if not exist "%outdir%" mkdir "%outdir%"
call :run -save "%scene%" || goto :fail
call :run -setMinComponentSize 2 || goto :fail
set /a comp_index=0
:censusLoop
if %comp_index% GEQ 24 goto :censusDone
if not exist "%outdir%\census_r%comp_index%" mkdir "%outdir%\census_r%comp_index%"
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { foreach ($r in @('%harvest_a%','%harvest_b%')) { if ($r -and (Test-Path -LiteralPath $r)) { Get-ChildItem -LiteralPath $r -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%outdir%\census_r%comp_index%' -Force } } } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 ( echo ERROR: census harvest move failed & goto :fail )
set "have_poses="
for %%F in ("%outdir%\census_r%comp_index%\*.xmp") do set have_poses=1
if not defined have_poses goto :censusDone
call :run -selectMaximalComponent || goto :fail
call :run -exportSelectedComponentDir "%outdir%" || goto :fail
call :run -deleteSelectedComponent || goto :fail
set /a comp_index+=1
goto :censusLoop
:censusDone
echo Census captured %comp_index% component peel(s) - reloading saved scene
call :run -load "%scene%" || goto :fail
echo NIGHTGROW OK census %comp_index%
exit /b 0

:censuslight
set "outdir=%~4"
set "harvest_a=%~5"
set "harvest_b=%~6"
if not exist "%outdir%" mkdir "%outdir%"
call :run -save "%scene%" || goto :fail
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { foreach ($r in @('%harvest_a%','%harvest_b%')) { if ($r -and (Test-Path -LiteralPath $r)) { Get-ChildItem -LiteralPath $r -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%outdir%' -Force } } } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 ( echo ERROR: light census harvest failed & goto :fail )
echo NIGHTGROW OK censuslight
exit /b 0

:deletesecond
:: Name-free second-largest deletion. -selectComponent silently no-ops
:: on RS-generated names like 'Component 23 (1)', and BARE
:: selectMaximal/delete after a -load ALSO silently no-op (2026-08-12:
:: identical census after "ok" exit) - the census peel's deselect +
:: exportXMP preamble is what makes component ops take effect, so this
:: mode reproduces the census context EXACTLY, then: delete maximal
:: (promotes victim), delete new maximal (victim), re-import the
:: largest from its census export (%4), save. Exported hydration XMPs
:: are swept to %5 (trash dir). Verified by the caller's census.
set "largest_rsalign=%~4"
set "xmp_trash=%~5"
set "harvest_a=%~6"
set "harvest_b=%~7"
if not exist "%largest_rsalign%" ( echo ERROR: largest export not found: %largest_rsalign% & exit /b 1 )
if not exist "%xmp_trash%" mkdir "%xmp_trash%"
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { foreach ($r in @('%harvest_a%','%harvest_b%')) { if ($r -and (Test-Path -LiteralPath $r)) { Get-ChildItem -LiteralPath $r -Recurse -Filter *.xmp | Move-Item -Destination '%xmp_trash%' -Force } } } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 ( echo ERROR: hydration sweep failed & goto :fail )
call :run -selectMaximalComponent || goto :fail
call :run -deleteSelectedComponent || goto :fail
call :run -selectMaximalComponent || goto :fail
call :run -deleteSelectedComponent || goto :fail
call :run -importComponent "%largest_rsalign%" || goto :fail
call :run -save "%scene%" || goto :fail
echo NIGHTGROW OK deletesecond
exit /b 0

:delete2nd
set "compname=%~4"
if [%4] == [] ( echo ERROR: component name required & exit /b 1 )
call :run -selectComponent "%compname%" || goto :fail
call :run -deleteSelectedComponent || goto :fail
call :run -save "%scene%" || goto :fail
echo NIGHTGROW OK delete2nd %compname%
exit /b 0

:addorphans
set "addlist=%~4"
set "flog=%~5"
set "flparams=%~6"
if not exist "%addlist%" ( echo ERROR: imagelist not found: %addlist% & exit /b 1 )
call :run -add "%addlist%" || goto :fail
if not "%flog%" == "" (
    echo Importing flight log for added images
    call :run -importFlightLog "%flog%" "%flparams%" || goto :fail
)
call :run -deselectAllImages || goto :fail
call :selectFromList "%addlist%" || goto :fail
call :run -editInputSelection "aligFeaturesMode=2" || goto :fail
call :run -editInputSelection "inpEnabled=true" || goto :fail
call :run -deselectAllImages || goto :fail
call :run -save "%scene%" || goto :fail
echo NIGHTGROW OK addorphans
exit /b 0

:seedpass
set "enablelist=%~4"
set "alignparams=%~5"
if not exist "%enablelist%" ( echo ERROR: enable list not found: %enablelist% & exit /b 1 )
if not exist "%alignparams%" ( echo ERROR: align params not found: %alignparams% & exit /b 1 )
call :run -selectAllImages || goto :fail
call :run -editInputSelection "inpEnabled=false" || goto :fail
call :run -deselectAllImages || goto :fail
call :selectFromList "%enablelist%" || goto :fail
call :run -editInputSelection "inpEnabled=true" || goto :fail
call :run -deselectAllImages || goto :fail
call :applyAlignKeys "%alignparams%" || goto :fail
echo Seed-growth align starting
call :run -align || goto :fail
call :run -deselectAllImages || goto :fail
call :run -save "%scene%" || goto :fail
echo NIGHTGROW OK seedpass
exit /b 0

:mergefinal
set "alignparams=%~4"
set "engine=%~5"
if "%engine%" == "" set "engine=merge"
call :run -selectAllImages || goto :fail
call :run -editInputSelection "inpEnabled=true" || goto :fail
call :run -deselectAllImages || goto :fail
call :applyAlignKeys "%alignparams%" || goto :fail
if /I "%engine%" == "align" (
    echo Final merge attempt via ALIGN engine
    call :run -align || goto :fail
) else (
    echo Final merge attempt via rigid -mergeComponents
    call :run -mergeComponents || goto :fail
)
call :run -deselectAllImages || goto :fail
call :run -save "%scene%" || goto :fail
echo NIGHTGROW OK mergefinal %engine%
exit /b 0

:: ---------------- helpers ----------------

:: selectFromList <imagelist> - union-select literal FULL paths, one
:: delegated -selectImage per line (instant, FIFO; no per-line wait).
:selectFromList
for /f "usebackq delims=" %%L in ("%~1") do (
    %RealityScan% -delegateTo %RS_TARGET% -selectImage "%%~L" union
)
exit /b 0

:: applyAlignKeys <xml> - pin every sfm*/lis* key (never align on
:: instance defaults; zero applied keys is a hard failure).
:applyAlignKeys
set /a applied_keys=0
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%~1") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 (
        %RealityScan% -delegateTo %RS_TARGET% -set "%%A=%%B"
        set /a applied_keys+=1
    )
)
if %applied_keys% EQU 0 ( echo ERROR: zero alignment keys applied & exit /b 1 )
echo Applied %applied_keys% alignment key(s)
exit /b 0

:fail
echo ERROR: NightGrow %mode% failed - see %ErrorsFile% and RealityScan.log
exit /b 1

:: :run - delegate + double waitCompleted + errors-file check (AlignZone
:: pattern; the errors file is cleared by the PYTHON caller per phase so
:: async attribution slips are diagnosed there, not silently absorbed).
:run
%RealityScan% -delegateTo %RS_TARGET% %*
if errorlevel 1 (
    echo ERROR: Failed to delegate command: %*
    exit /b 1
)
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_TARGET%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_TARGET%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        echo ERROR: RealityScan reported a failure during: %*
        exit /b 1
    )
)
exit /b 0
