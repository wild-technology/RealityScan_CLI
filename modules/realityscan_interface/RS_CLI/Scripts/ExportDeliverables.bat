@echo off
:: DisableDelayedExpansion, NOT a plain setlocal. A plain setlocal INHERITS
:: the caller's delayed-expansion state, and a driver that enables it (NA165's
:: export_h2060.bat does) would expand every '!' in what THIS script builds:
:: a list-file line "zone!x!c0" was selected as "zoneinheritedc0", and paths
:: built from %~dp0 are exposed the same way (measured, repo_changes E1 and
:: bat-review D2, 2026-09-26). It cannot protect the ARGUMENTS: a caller with
:: delayed expansion on expands a '!' in %1-%3 on its own `call` line, before
:: this script starts. Nothing here uses !var! outside :charsOk, which turns
:: it on locally to judge a value without re-parsing it.
setlocal DisableDelayedExpansion
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
:: lean. RS_EXPORT_NO_SAVE skips both: the sweep exists only for the save.
::
:: Arguments (the contract - wildscan and modules/export_deliverables.py pass
:: exactly these three):
::   %1 .rsproj project path
::   %2 output directory (per-component subfolders are created)
::   %3 component-name list file (one name per line, e.g. cluster_0_a2_c0)
::
:: Optional environment switches. All unset = the historical behaviour
:: (PNG presets, output named after the component, sweep + save, all three
:: formats). Every one is checked BEFORE an instance boots, and a value that
:: is expanded into a command line is first judged character by character
:: (:charsOk) - anything outside its whitelist is refused unexpanded.
::   RS_EXPORT_SUFFIX    appended to every OUTPUT folder and file stem, never
::                       to what is SELECTED: component zone_1_c0 and models
::                       zone_1_c0_Simplified_Textured / zone_1_c0_HighPoly_Raw
::                       are resolved by their existing names and written as
::                       %2\zone_1_c0_L\obj\zone_1_c0_L_0000000.obj etc. The
::                       stem comes from the path handed to the export, not
::                       from the model name (delivered textures are
::                       zone_2_c3_u1_v1_diffuse.png). Letters, digits, _ and -
::                       only.
::   RS_EXPORT_TEXTURES  png (default) or jpg - which OBJ/FBX presets to use.
::                       jpg = ModelExportParams{OBJ_NiraParts,FBX_Parts}_JPG.xml;
::                       the PNG presets stay untouched for other dives.
::   RS_EXPORT_NO_SAVE   ANY value, 0 included = no residual sweep and no
::                       -save. For exporting from a delivered/snapshotted
::                       project. It governs -save only: an instance the boot
::                       script REUSES keeps whatever autosave setting it has
::                       (run_batch_script always boots a fresh one).
::   RS_EXPORT_SKIP_PLY  any value = OBJ + FBX only. No empty ply\ folder is
::                       made for the skipped PLY any more (the pre-2026-09-27
::                       file made one; nothing reads it).
::   RS_EXPORT_ONLY_PLY  any value = dense PLY only. Both PLY switches
::                       together would export nothing and are refused.
::   RS_EXPORT_TARGET_LOG     a flight log whose positions ARE the wanted
::   RS_EXPORT_TARGET_PARAMS  camera positions, and the FlightLogParams .xml
::                       to import it with - both or neither. After the CRS
::                       pin and before any export: -importFlightLog, then
::                       -update, in memory only (see the block before the
::                       export loop).
::   RS_EXPORT_REGISTRATION_DIR  one <component>.csv of camera poses per
::                       listed component (format {...0A4A} via
::                       Metadata\RegistrationExportParams_Poses.xml), after
::                       the optional -update and before the model exports.
::                       A <component>.csv already there is refused.
::   The three paths may hold letters, digits, space and _ - . \ : ' + # @ $
::   { } [ ] only - no ( ) , ; = ~ and no cmd metacharacter, the boundary
::   run_batch_script already enforces on arguments.

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1

set "MetadataDir=%Metadata%"

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

:: ------------------------------------------------ switches, before boot
if defined RS_EXPORT_SKIP_PLY if defined RS_EXPORT_ONLY_PLY goto :conflictingModes
:: :charsOk judges a value through delayed expansion, which never re-parses
:: it, against an explicit whitelist. The check it replaces piped `set NAME`
:: into findstr and was bypassed two ways (bat-review, 2026-09-27): findstr
:: without /i missed a variable spelled rs_export_suffix (cmd looks names up
:: case-insensitively), and findstr /x accepted a value with an embedded CR,
:: which cmd strips on expansion - both ran the payload at the first echo.
:: No switch below is expanded before its :charsOk.
if defined RS_EXPORT_SUFFIX call :charsOk RS_EXPORT_SUFFIX stem || goto :badSuffix
set "tex=png"
if not defined RS_EXPORT_TEXTURES goto :texChosen
call :charsOk RS_EXPORT_TEXTURES stem || goto :badTextures
if /i "%RS_EXPORT_TEXTURES%" == "png" goto :texChosen
if /i not "%RS_EXPORT_TEXTURES%" == "jpg" goto :badTextures
set "tex=jpg"
:texChosen
set "ObjParams=%MetadataDir%\ModelExportParamsOBJ_NiraParts.xml"
set "FbxParams=%MetadataDir%\ModelExportParamsFBX_Parts.xml"
if "%tex%" == "jpg" set "ObjParams=%MetadataDir%\ModelExportParamsOBJ_NiraParts_JPG.xml"
if "%tex%" == "jpg" set "FbxParams=%MetadataDir%\ModelExportParamsFBX_Parts_JPG.xml"
set "PlyParams=%MetadataDir%\ModelExportParamsPLY_DensePoints.xml"
if not exist "%ObjParams%" goto :missingPreset
if not exist "%FbxParams%" goto :missingPreset
if not exist "%PlyParams%" goto :missingPreset
:: Exact-target georegistration: the log is imported with those params or
:: not at all.
if defined RS_EXPORT_TARGET_PARAMS if not defined RS_EXPORT_TARGET_LOG goto :targetPairing
if not defined RS_EXPORT_TARGET_LOG goto :targetChecked
if not defined RS_EXPORT_TARGET_PARAMS goto :targetPairing
call :charsOk RS_EXPORT_TARGET_LOG path || goto :badTargetPath
call :charsOk RS_EXPORT_TARGET_PARAMS path || goto :badTargetPath
if not exist "%RS_EXPORT_TARGET_LOG%" goto :missingTarget
if not exist "%RS_EXPORT_TARGET_PARAMS%" goto :missingTarget
:targetChecked
set "PoseParams=%MetadataDir%\RegistrationExportParams_Poses.xml"
if not defined RS_EXPORT_REGISTRATION_DIR goto :registrationChecked
call :charsOk RS_EXPORT_REGISTRATION_DIR path || goto :badRegistrationDir
if not exist "%PoseParams%" goto :missingPoseParams
:: -exportRegistration has returned 0 WITHOUT writing its file, so a CSV
:: already at the target path would pass the content gate for a run that
:: wrote nothing - and nothing here overwrites a record. A clash is refused.
set "regClash="
for /f "usebackq delims=" %%N in ("%name_list%") do if exist "%RS_EXPORT_REGISTRATION_DIR%\%%N.csv" set "regClash=%%N"
if defined regClash goto :registrationExists
:registrationChecked
:: The errors file is STICKY and :run fails on ANY non-empty one. Left over
:: from an earlier direct call that ended in :fail, it would let the -load
:: below run to completion (up to 45 min on the NA165 assembly) and then fail
:: it. RealityScanCLI clears it pre-run (hard rule 4); a direct caller is
:: told here, before a boot, rather than after the load.
if exist "%ErrorsFile%" for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 goto :staleErrors

echo Components to export: %name_count%
if not exist "%out_dir%" mkdir "%out_dir%"
if defined RS_EXPORT_REGISTRATION_DIR if not exist "%RS_EXPORT_REGISTRATION_DIR%" mkdir "%RS_EXPORT_REGISTRATION_DIR%" || goto :badRegistrationDir

echo Project:  %scene_path%
echo Output:   %out_dir%
echo Suffix:   [%RS_EXPORT_SUFFIX%]
echo Textures: %tex%
if defined RS_EXPORT_TARGET_LOG echo Targets:  "%RS_EXPORT_TARGET_LOG%" imported with "%RS_EXPORT_TARGET_PARAMS%"
if defined RS_EXPORT_REGISTRATION_DIR echo Poses:    "%RS_EXPORT_REGISTRATION_DIR%"

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

:: RS_EXPORT_NO_SAVE: the delivered project is never written. The sweep is
:: skipped with the save - its only purpose is to keep residuals out of what
:: gets SAVED, and deleting models in memory before a quit-without-save
:: changes nothing on disk.
if defined RS_EXPORT_NO_SAVE goto :skipSave
echo Sweeping default-named residual models
for %%M in ("Model 1" "Model 2" "Model 3" "Model 4" "Model 5" "Model 6" "Model 7" "Model 8" "Model 9") do (
    call :try_delete_model %%M
)

echo Saving project - residuals removed, before any in-memory coloring
call :run -save "%scene_path%" || goto :fail
goto :saveDone
:skipSave
echo RS_EXPORT_NO_SAVE set (any value) - no residual sweep and NO -save of the project
:saveDone

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

:: ------------------------------- exact-target georegistration (opt-in)
:: RS_EXPORT_TARGET_LOG: a flight log whose positions ARE the wanted camera
:: positions (accuracy 0.01 m, orientation accuracy 180 deg, the assembly's
:: own FlightLogParams, image column = the FULL image path - two zones can
:: hold the same file name). Imported, then -update: every component and its
:: models land on the targets to 0.0000 m with textures untouched (FINDINGS
:: [NA165] 2026-09-26, proven on two fixtures). After the CRS pin, before any
:: export, and AFTER the one -save, so the move lives in memory only and is
:: never saved. The import's documented warning-class result is tolerated
:: exactly as MergeZoneComponents.bat does (:run_geoimport); -update gets
:: the plain :run.
if not defined RS_EXPORT_TARGET_LOG goto :targetDone
echo Importing the target flight log
call :run_geoimport -importFlightLog "%RS_EXPORT_TARGET_LOG%" "%RS_EXPORT_TARGET_PARAMS%" || goto :fail
echo Georegistering every component onto the targets
call :run -update || goto :fail
:targetDone

:: --------------------------------------------- camera poses (opt-in)
:: RS_EXPORT_REGISTRATION_DIR: one <component>.csv per listed component, in
:: the frames that show what -update did - lat/lon/alt, ECEF euclidX..Z and
:: the rotation matrices (FINDINGS [NA165] 2026-09-26). -exportRegistration
:: writes the SELECTED cameras if any are selected, else every camera of the
:: selected component - hence -deselectAllImages after each -selectComponent.
if not defined RS_EXPORT_REGISTRATION_DIR goto :registrationDone
echo Exporting camera poses per component
for /f "usebackq delims=" %%N in ("%name_list%") do (
    call :export_registration "%%N" || goto :fail
)
:registrationDone

for /f "usebackq delims=" %%N in ("%name_list%") do (
    call :export_component "%%N" || goto :fail
)

echo Shutting down RealityScan instance %RS_INSTANCE% - NOT saving
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:: ---------------------------------------------------------- per component
:export_component
:: comp = what is SELECTED (existing names in the project); stem = what is
:: WRITTEN (folder and file stem). They differ only by RS_EXPORT_SUFFIX,
:: validated above.
set "comp=%~1"
set "stem=%~1%RS_EXPORT_SUFFIX%"
echo === Exporting %comp% as %stem% ===
if not defined RS_EXPORT_ONLY_PLY if not exist "%out_dir%\%stem%\obj" mkdir "%out_dir%\%stem%\obj"
if not defined RS_EXPORT_ONLY_PLY if not exist "%out_dir%\%stem%\fbx" mkdir "%out_dir%\%stem%\fbx"
if not defined RS_EXPORT_SKIP_PLY if not exist "%out_dir%\%stem%\ply" mkdir "%out_dir%\%stem%\ply"

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

if defined RS_EXPORT_ONLY_PLY goto :export_ply

echo   OBJ (Nira, by parts)
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%stem%\obj\%stem%.obj" "%ObjParams%" || exit /b 1

echo   FBX (by parts)
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%stem%\fbx\%stem%.fbx" "%FbxParams%" || exit /b 1

:: DENSE PLY. Still skippable via RS_EXPORT_SKIP_PLY=1 as an escape hatch,
:: but it is NOT expected to fail: <comp>_HighPoly_Raw is present for every
:: component in the master project, and the earlier "missing model" was the
:: absent -selectComponent above.
if defined RS_EXPORT_SKIP_PLY (
    echo   Dense PLY SKIPPED ^(RS_EXPORT_SKIP_PLY set^)
    exit /b 0
)
:export_ply
echo   Dense colored PLY from %comp%_HighPoly_Raw
call :run -selectModel "%comp%_HighPoly_Raw" || exit /b 1
call :run -calculateVertexColors || exit /b 1
call :run -exportModel "%comp%_HighPoly_Raw" "%out_dir%\%stem%\ply\%stem%_dense.ply" "%PlyParams%" || exit /b 1
exit /b 0

:: --------------------------------------------- per component: camera poses
:export_registration
set "comp=%~1"
set "regcsv=%RS_EXPORT_REGISTRATION_DIR%\%~1.csv"
echo   poses of "%comp%"
call :run -selectComponent "%comp%" || exit /b 1
call :run -deselectAllImages || exit /b 1
call :run -exportRegistration "%regcsv%" "%PoseParams%" || exit /b 1
:: GATE ON CONTENT, NOT ON THE EXIT CODE (AlignZone.bat :identityOne): an
:: unresolved calexFileFormatId falls back SILENTLY to the instance's current
:: export settings with exit code 0, and the call has also returned 0 without
:: writing the file at all. Line 1 "#cameras N" is AlignZone's proof that a
:: RUMI format ran (/n plus "1:" pins it to the first line; the inner match
:: is not /b-anchored, so a byte-order mark cannot fail a good file). Line 2
:: tells THIS format ({...0A4A}, "#name,lat,lon,alt,...") from the
:: membership format, which opens with the same "#cameras N".
if not exist "%regcsv%" goto :registrationMissing
%SystemRoot%\System32\findstr.exe /n /r /c:"#cameras [0-9][0-9]*" "%regcsv%" | %SystemRoot%\System32\findstr.exe /b /c:"1:" >nul
if errorlevel 1 goto :registrationFormat
%SystemRoot%\System32\findstr.exe /n /b /c:"#name,lat,lon,alt," "%regcsv%" | %SystemRoot%\System32\findstr.exe /b /c:"2:" >nul
if errorlevel 1 goto :registrationFormat
exit /b 0

:: Both return from :export_registration (exit /b 1), NOT goto :fail - the
:: caller turns a non-zero return into goto :fail, which quits the instance
:: once.
:registrationMissing
echo ERROR: -exportRegistration wrote no CSV for "%comp%"
echo   expected: "%regcsv%"
echo   The delegated command reported success - the silent fallback. Check
echo   %PoseParams% and that {E7C3B1A9-4D2F-4A6E-8B15-3C7D9E2F0A4A} is in
echo   RealityScan's own calibration.xml: python -m modules.flightlog_format --install
exit /b 1

:registrationFormat
echo ERROR: "%regcsv%" is not in the camera-poses format: line 1 must be
echo   "#cameras N" and line 2 "#name,lat,lon,alt,...". An unresolved
echo   calexFileFormatId exports in whatever format the instance last held,
echo   exit code 0. Reinstall the RUMI formats: python -m modules.flightlog_format --install
exit /b 1

:emptyList
echo ERROR: component name list "%name_list%" names NOTHING.
echo   Populate it from the merge report final_components before exporting.
exit /b 1

:conflictingModes
echo ERROR: RS_EXPORT_SKIP_PLY and RS_EXPORT_ONLY_PLY are both set - that
echo   exports nothing. Set at most one. Refused before booting an instance.
exit /b 1

:badSuffix
echo ERROR: RS_EXPORT_SUFFIX may hold only letters, digits, underscore and
echo   hyphen - it is expanded into every output path. Refused unexpanded:
set RS_EXPORT_SUFFIX
exit /b 1

:badTextures
echo ERROR: RS_EXPORT_TEXTURES must be png or jpg:
set RS_EXPORT_TEXTURES
exit /b 1

:missingPreset
echo ERROR: an export preset is missing - refusing to export with a default:
echo   OBJ %ObjParams%
echo   FBX %FbxParams%
echo   PLY %PlyParams%
exit /b 1

:targetPairing
echo ERROR: RS_EXPORT_TARGET_LOG and RS_EXPORT_TARGET_PARAMS go together - the
echo   flight log is imported with those params or not at all. Refused before
echo   booting an instance:
set RS_EXPORT_TARGET
exit /b 1

:badTargetPath
echo ERROR: RS_EXPORT_TARGET_LOG and RS_EXPORT_TARGET_PARAMS may hold only
echo   letters, digits, space and _ - . \ : ' + # @ $ { } [ ] - both are
echo   expanded into a command line. Refused unexpanded:
set RS_EXPORT_TARGET
exit /b 1

:missingTarget
echo ERROR: the target flight log or its params file does not exist:
echo   RS_EXPORT_TARGET_LOG    "%RS_EXPORT_TARGET_LOG%"
echo   RS_EXPORT_TARGET_PARAMS "%RS_EXPORT_TARGET_PARAMS%"
exit /b 1

:badRegistrationDir
echo ERROR: RS_EXPORT_REGISTRATION_DIR must be a directory that exists or can
echo   be created, and may hold only letters, digits, space and
echo   _ - . \ : ' + # @ $ { } [ ] - it is expanded into a command line:
set RS_EXPORT_REGISTRATION_DIR
exit /b 1

:missingPoseParams
echo ERROR: RS_EXPORT_REGISTRATION_DIR is set but the poses format selector
echo   is missing: %PoseParams%
exit /b 1

:registrationExists
echo ERROR: RS_EXPORT_REGISTRATION_DIR already holds the CSV of a listed
echo   component. -exportRegistration has returned 0 without writing its
echo   file, so an old CSV would pass for a new one, and nothing here
echo   overwrites a record. Use a fresh directory. Refused before boot:
set regClash
exit /b 1

:staleErrors
echo ERROR: %ErrorsFile% is not empty - it is left over from an earlier run.
echo   :run fails on ANY non-empty errors file, so this run would load the
echo   project and then stop at the first command. Run through
echo   modules/export_deliverables.py - RealityScanCLI clears the markers
echo   pre-run, hard rule 4 - or read it and move it aside yourself.
exit /b 1

:fail
echo ERROR: export workflow failed - see %ErrorsFile% and the RealityScan log
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :charsOk <VARNAME> stem|path - errorlevel 0 iff every character of the
:: variable's value is in the whitelist. stem: letters, digits, _ and -.
:: path: those plus space and . \ : ' + # @ $ { } [ ]. The value is read
:: with delayed expansion (!%~1!), which never re-parses it, and each allowed
:: character is substituted away; whatever is left - a quote, % ! ^ & | < >,
:: ( ) , ; = * ? ~, a CR or LF, a tab, anything non-ASCII - refuses it.
:: Substitution is case-insensitive, so A-Z also removes a-z; the variable
:: NAME is looked up case-insensitively too, as cmd does everywhere else.
:charsOk
setlocal EnableDelayedExpansion
set "rest=!%~1!"
for %%C in (A B C D E F G H I J K L M N O P Q R S T U V W X Y Z 0 1 2 3 4 5 6 7 8 9 _ -) do if defined rest set "rest=!rest:%%C=!"
if /i "%~2" == "stem" goto :charsOkVerdict
for %%C in (. \ : ' + # @ $ { } [ ]) do if defined rest set "rest=!rest:%%C=!"
if defined rest set "rest=!rest: =!"
:charsOkVerdict
if defined rest exit /b 1
exit /b 0

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

:: :run_geoimport - like :run, but tolerates the DOCUMENTED warning-class
:: import failure err:18002 ("file contains images which are not in the
:: current scene"): the trajectory still imports for every present image.
:: The errors marker is MOVED (not deleted) to expected_18002_<inst>.txt
:: so the evidence is preserved while later :run calls see a clean
:: marker. Any other error content fails the workflow as usual. Copied from
:: MergeZoneComponents.bat, which has tolerated exactly this since 2026-08.
:run_geoimport
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
        rem The errors marker carries only ErrorWriter's numeric process
        rem result, NOT the err:18002 text (that lives in RealityScan.log
        rem only). 2181038335 = 0x820000FF, the warning-class result this
        rem import reports when log rows reference absent images.
        %SystemRoot%\System32\findstr.exe /c:"2181038335" "%ErrorsFile%" >nul
        if errorlevel 1 (
            echo ERROR: RealityScan reported a failure during: %*
            exit /b 1
        )
        echo NOTE: flight log import reported warning-class 0x820000FF -
        echo       expected when rows reference never-registered images;
        echo       the trajectory imported for every present image
        move /y "%ErrorsFile%" "%ErrorPath%\expected_18002_%RS_INSTANCE%.txt" >nul
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
