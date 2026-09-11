@echo off
setlocal
:: Canonical per-zone alignment workflow (2026-07 consolidation of
:: AlignImagesFromFolder.bat's chaining/CRS handling and
:: AlignZonesSequentially.bat's settings application - see
:: docs/settings-evaluation-2026-07.md).
::
:: Aligns one zone as ONE scene and exports ALL resulting components
:: (>= min size), not just the maximal one: underwater zones routinely
:: fragment, and every pocket is input to the merge stage. Model
:: generation deliberately does NOT happen here - models are built once,
:: on the merged component (GenerateModel.bat).
::
:: Arguments (required):
::   %1 zone input directory (images; subfolders included)
::   %2 component output directory (per-zone folder recommended)
::   %3 flight log path (or "" to align without georeferencing priors)
::   %4 flight log params xml (or "")
::   %5 scene name (used for the saved .rsproj)
::   %6 minimum component size in cameras (e.g. 50)
::
:: SETTINGS CONTRACT (owner, 2026-08-15): Metadata\AlignmentParams.xml is
:: AUTHORITATIVE for every setting it names - ALL of them are applied.
:: Settings the file does NOT name are explicitly UNDEFINED: they keep
:: whatever the instance holds, and this workflow makes no claim about
:: them. The file names 35 of RealityScan's settings, not the whole
:: namespace, so the previous "never from instance defaults" promise was
:: never achievable - it described a guarantee this script cannot make.

echo Reading default variables
call "%~dp0SetVariables.bat"
if errorlevel 1 exit /b 1
set "AlignmentParams=%Metadata%\AlignmentParams.xml"
:: Test-cell override (PRIORS_DISTORTION_TEST_PLAN): a cell may point at
:: a variant params file without touching the canonical Metadata copy.
if defined RS_ALIGN_PARAMS if not "%RS_ALIGN_PARAMS%" == "" set "AlignmentParams=%RS_ALIGN_PARAMS%"

:: Registration-export settings for the identity capture below. REQUIRED,
:: and SHIPPED: Metadata\RegistrationExportParams.xml names the export
:: format by GUID under calexFileFormatId - the exact structural analogue
:: of gpsLogFileFormat in FlightLogParams.xml.
::
:: It used to be optional, on the belief that RealityScan had to write it
:: from its own "Export Registration" dialog because the keys were "not
:: documented well enough to hand-author safely". That belief came from a
:: probe that searched RealityScan.exe for the keys as ASCII; the exe
:: stores them as UTF-16LE, so the probe could not have found them
:: whatever the answer was (FINDINGS 2026-09-02: run the control before
:: trusting a negative result). The fallback it justified is worse than
:: the gap it covered - -exportRegistration with no params xml blocks
:: forever headless (HANDOFF), and with the WRONG format it writes a CSV
:: the membership parser cannot read, silently, exit code 0.
set "RegistrationParams=%Metadata%\RegistrationExportParams.xml"
if defined RS_REGISTRATION_PARAMS if not "%RS_REGISTRATION_PARAMS%" == "" set "RegistrationParams=%RS_REGISTRATION_PARAMS%"

set "ResultsLog=%ErrorPath%\results_%RS_INSTANCE%.log"
set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"

if [%1] == [] ( echo ERROR: zone input directory required & exit /b 1 )
if [%2] == [] ( echo ERROR: component output directory required & exit /b 1 )
if [%5] == [] ( echo ERROR: scene name required & exit /b 1 )
set "input_dir=%~1"
set "output_dir=%~2"
set "flight_log_dir=%~3"
set "flight_log_params_dir=%~4"
set "scene_name=%~5"
set "min_component_size=%~6"
if "%min_component_size%" == "" set "min_component_size=50"

if not exist "%input_dir%" ( echo ERROR: input directory not found: %input_dir% & exit /b 1 )

:: POOL layout (owner directive 2026-08-08/09, FLIGHTLOG_ARCHITECTURE):
:: RS_ALIGN_POOL_DIR set = the zone holds NO images, only a .imagelist
:: of canonical pool paths + a full-path flight log. Images are added
:: from the list, and the identity harvest sweeps the POOL (exportXMP
:: writes sidecars beside the source images). Unset = byte-identical
:: legacy behavior.
set "harvest_dir=%input_dir%"
if defined RS_ALIGN_POOL_DIR if not "%RS_ALIGN_POOL_DIR%" == "" set "harvest_dir=%RS_ALIGN_POOL_DIR%"
if not exist "%AlignmentParams%" ( echo ERROR: AlignmentParams.xml not found: %AlignmentParams% & exit /b 1 )
:: Hard error, exactly like AlignmentParams above. A missing registration
:: params file used to blank %RegistrationParams% and fall through to the
:: instance's own export settings - the silent-fallback shape this
:: workflow refuses everywhere else.
if not exist "%RegistrationParams%" ( echo ERROR: RegistrationExportParams.xml not found: %RegistrationParams% & exit /b 1 )
if not exist "%output_dir%" mkdir "%output_dir%"

echo Zone Input: %input_dir%
echo Component Output: %output_dir%
echo Flight Log: %flight_log_dir%
echo Flight Log Params: %flight_log_params_dir%
echo Scene Name: %scene_name%
echo Min Component Size: %min_component_size%

echo Starting RealityScan
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
call "%~dp0startRealityScan.bat"
if errorlevel 1 exit /b 1

:: ------------------------------------------------- georegister-only mode
:: RS_GEOREG_ONLY=<path to an existing .rsproj> loads that project and jumps
:: straight to the georegistration below, skipping scene construction and
:: -align entirely.
::
:: WHY THIS EXISTS. B19 was fixed by adding -update after -align, but three
:: zones of NA165/H2060 were already aligned without it and are saved at
:: whatever gauge the solver picked. -update is a POST-alignment fit; it needs
:: no re-solve. Re-aligning those zones to gain it would cost ~19 h (zone_2
:: alone is 13.3 h) and would re-roll the align's run-to-run variation, so the
:: components the owner has already reviewed would come back subtly different.
:: Loading and updating costs minutes and leaves the component structure alone.
::
:: It reuses everything after this point - update, export, identity harvest,
:: save - rather than duplicating it. This repo has been bitten twice by the
:: same logic living in two places (the align identity ceiling B13 and the
:: merge peel ceiling B16 were the same defect, fixed months apart).
::
:: The loaded project already carries its imported flight-log constraints and
:: its coordinate system, which is why the CRS pin, the prior groups, the
:: settings loop and -importFlightLog are all skipped: redoing them would
:: either be a no-op or would overwrite what the project was solved with.
if defined RS_GEOREG_ONLY (
    echo GEOREGISTER-ONLY: loading %RS_GEOREG_ONLY%
    echo   Skipping scene construction and -align. The saved solve is kept;
    echo   only its fit to the flight-log constraints is redone.
    call :run -load "%RS_GEOREG_ONLY%" deleteAutosave || goto :fail
    goto :georegister
)

echo Creating new scene
:: Fresh alignments require measured priors before -align. Continuation above
:: retains its saved-scene inputs and bypasses this fresh-input contract.
if not defined RS_INPUT_PRIOR_MANIFEST ( echo ERROR: input-prior contract required & goto :fail )
if not defined RS_INPUT_PRIOR_SHA256 ( echo ERROR: input-prior hash required & goto :fail )
if not defined RS_INPUT_PRIOR_TEMPLATE ( echo ERROR: input-prior report template required & goto :fail )
if not defined RS_INPUT_PRIOR_REPORT ( echo ERROR: input-prior report path required & goto :fail )
if not defined RS_INPUT_PRIOR_RESULT ( echo ERROR: input-prior result path required & goto :fail )
if not defined RS_PYTHON ( echo ERROR: canonical Python interpreter required & goto :fail )
call :run -newScene || goto :fail

if defined RS_ALIGN_POOL_DIR if not "%RS_ALIGN_POOL_DIR%" == "" goto :addViaList
echo Adding images to project
:: Subfolder recursion is NOT the default in this 2.2 build: without
:: appIncSubdirs a zone tree whose images live in per-camera or
:: preprocessed_images subfolders adds 0 layer images and the flight-log
:: import then fails err:18002 (observed live on NA156 H2023). Instant
:: -set, FIFO-ordered before the queued addFolder, no wait needed.
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "%input_dir%" || goto :fail
goto :imagesAdded

:addViaList
set "zone_list="
for %%F in ("%input_dir%\*.imagelist") do set "zone_list=%%~fF"
if not defined zone_list ( echo ERROR: pool mode but no .imagelist in %input_dir% & goto :fail )
echo Adding images from %zone_list% (pool: %RS_ALIGN_POOL_DIR%)
call :run -add "%zone_list%" || goto :fail
:imagesAdded

:: Explicit per-input use; never inherit masking behavior from a user profile.
:: Both folder and pool imports converge here. Saved-scene continuation skips
:: this fresh-input path and keeps its existing input settings.
call :run -selectAllImages || goto :fail
call :run -editInputSelection "inpMaskOpts=3" || goto :fail

:: Pin the PROJECT and OUTPUT coordinate systems before importing the
:: trajectory. RealityScan holds three CRS scopes: project (measuring and
:: reporting), output (MODEL/MESH EXPORT), and per-object (the params XML's
:: CoordinateSystemFlightLog - only "the CRS the imported numbers are in").
:: This repo set only the third, and RealityScan's own Help says to set the
:: project CRS FIRST, then import (docs/rs-reference/06 3.2).
:: Consequence observed on NA165/H2060: the project accumulates a LIST of
:: coordinate systems across cruises, kept its selection on a leftover
:: (epsg:32757, NA173's 57S), and the exported .rsInfo declared the list's
:: FIRST entry (epsg:32655, 55N) - while the dive is 2S. The geometry was
:: correct; the DECLARED CRS was arbitrary, which is worse than wrong
:: because it looks authoritative.
:: RS_PROJECT_CRS is set by the align module from the flight log's own zone
:: tag, so this can never disagree with the trajectory it is importing.
if defined RS_PROJECT_CRS if not "%RS_PROJECT_CRS%" == "" (
    echo Pinning project coordinate system to %RS_PROJECT_CRS%
    call :run -setProjectCoordinateSystem %RS_PROJECT_CRS% || goto :fail
    echo Pinning output coordinate system to %RS_PROJECT_CRS%
    call :run -setOutputCoordinateSystem %RS_PROJECT_CRS% || goto :fail
)

:: Calibration/lens prior groups, IN-SESSION (replaces the XMP calibration
:: sidecars that used to sit beside every image). One
:: -selectImage/-setPriorCalibrationGroup/-setPriorLensGroup triple per
:: camera family, generated by modules/prior_groups.py from the registry
:: and delivered as a FILE - hard rule 8: a regexp carries backslashes and
:: delimiters that cmd would split as bare arguments.
:: The WCA JPGs are EXIF-identical (one Z CAM E2-F6 model string, no focal
:: tag), so WITHOUT these groups RealityScan calibrates all four physical
:: cameras as one - which is what the sidecars were there to prevent.
if defined RS_PRIOR_GROUPS_FILE if not "%RS_PRIOR_GROUPS_FILE%" == "" (
    if not exist "%RS_PRIOR_GROUPS_FILE%" (
        echo ERROR: prior-group command file not found: %RS_PRIOR_GROUPS_FILE%
        goto :fail
    )
    echo Applying calibration/lens prior groups
    for /f usebackq^ delims^= %%L in ("%RS_PRIOR_GROUPS_FILE%") do (
        echo %%L| %SystemRoot%\System32\findstr.exe /b /c:"::" >nul
        if errorlevel 1 ( call :run %%L || goto :fail )
    )
)

echo Applying alignment settings from AlignmentParams.xml
:: -align takes NO parameters in RealityScan 2.x (a params xml passed to
:: it is silently ignored), so every key goes in via -set first.
:: Delegated commands queue FIFO, so the sets execute before the align;
:: they are instant and need no completion wait.
::
:: EVERY entry is applied, not just an sfm*/lis* subset. RealityScan
:: serializes part of its own Alignment Settings dialog under OBFUSCATED
:: numeric ids (s235l, s236l, s237l, s251l-s254l) instead of readable
:: sfm* names. The old `findstr /b "sfm" "lis"` filter dropped those 7
:: silently - 28 of 35 entries applied, the other 7 inherited from the
:: instance while the header claimed otherwise (PRODUCT_READINESS gap,
:: closed 2026-08-15).
::
:: The KEY gates the line, NEVER token 1. Token 1 is "  (entry key=" and
:: the angle bracket in it is a cmd REDIRECTION operator, so echoing it
:: sends the shell hunting for a file named "entry" and every setting is
:: lost - 35 of 35, measured 2026-08-15 before this shipped. A key must
:: instead start with a LETTER, which admits every real setting and
:: rejects the "(Configuration id=" header, whose quoted token is a
:: brace-led GUID. A non-empty value is required too. Comment lines carry
:: no quotes at all and never reach token 2.
::
:: app* keys are REFUSED, not skipped. They are application-wide, persist
:: into the user's own GUI session, and need per-instance approval
:: (docs/AGENT_OPERATIONS.md rule 9). The one this workflow needs,
:: appIncSubdirs, is set deliberately above. Silently dropping keys is the
:: bug being fixed here, so an app* key fails closed rather than vanishing.
::
:: The count is the point. If the XML attribute order changes, or an
:: RS_ALIGN_PARAMS variant yields no matching tokens, this loop applied
:: ZERO settings and -align then succeeded on whatever the instance last
:: held - silently, with exit code 0 (audit 2026-08-07). set /a inside the
:: block is safe under plain expansion because the total is only READ
:: after the loop.
set /a applied_settings=0
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    if not "%%B" == "" (
        echo %%A| %SystemRoot%\System32\findstr.exe /b /r "[a-zA-Z]" >nul
        if not errorlevel 1 (
            echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"app" >nul
            if not errorlevel 1 (
                echo ERROR: app-global key "%%A" found in the params file
                goto :appGlobalKey
            )
            call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
            %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
            set /a applied_settings+=1
        )
    )
)
if %applied_settings% EQU 0 goto :noSettings
echo Applied %applied_settings% alignment setting(s) from %AlignmentParams%

:: Flight log LAST, after the prior groups and the params settings (owner
:: sequence 2026-08-14: load images -> select by camera pattern -> set
:: priors/params -> load flight log for geo data). It used to be imported
:: BEFORE the settings loop, which meant the georeferencing priors were
:: taken in while sfmEnableCameraPrior / sfmCameraPriorWeight /
:: sfmCameraPriorAccuracy* still held whatever the instance last had -
:: the very keys that govern how those priors are weighted.
if not "%flight_log_dir%" == "" (
    echo Importing flight log
    call :run -importFlightLog "%flight_log_dir%" "%flight_log_params_dir%" || goto :fail
)

:: INPUT_PRIOR_CENSUS_V1: numeric defaults alone do not prove active priors.
if exist "%RS_INPUT_PRIOR_REPORT%" ( echo ERROR: prior report already exists & goto :fail )
if exist "%RS_INPUT_PRIOR_RESULT%" ( echo ERROR: prior census already exists & goto :fail )
call :run -exportReport "%RS_INPUT_PRIOR_REPORT%" "%RS_INPUT_PRIOR_TEMPLATE%" true || goto :fail
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
pushd "%~dp0..\..\..\.." || goto :fail
"%RS_PYTHON%" -B -m modules.prior_census --input-manifest "%RS_INPUT_PRIOR_MANIFEST%" --expected-sha256 "%RS_INPUT_PRIOR_SHA256%" --input-report "%RS_INPUT_PRIOR_REPORT%" --output "%RS_INPUT_PRIOR_RESULT%"
if errorlevel 1 ( popd & goto :fail )
popd

echo Aligning images - this may take a long time
call :run -align || goto :fail

:georegister
:: ---------------------------------------------------------- B19
:: GEOREGISTER AFTER ALIGNING. Without this the align path imports priors,
:: solves, and saves whatever gauge the solver happened to pick - it never
:: fits the result to the constraints. The merge path has always done this
:: (MergeZoneComponents.bat, "the step that actually georeferences"); the
:: align path never did.
::
:: WHY IT MATTERS. Rescaling a component about its own centroid is an EXACT
:: gauge freedom of the reprojection term - cameras and points scale together
:: and every projected pixel is unchanged - so the position priors are the
:: only thing in the objective that can see scale. Measured on NA165/H2060
:: (2026-09-09), sweeping the weighted prior chi-squared against a rescale
:: factor k, per camera:
::
::     component     k* (priors' optimum)   unclaimed residual
::     zone_3 c0            0.777                 54.6%
::     zone_3 c1            1.524                 82.0%
::     zone_2 c0            0.986                  0.8%
::     zone_1 c0            1.019                  2.7%
::
:: Every zone_3 component sat at a scale its OWN priors scored as strictly
:: worse, and 1/0.777 = 1.287 - the measured 1.27x error. The priors held the
:: right answer and nothing applied it. zone_3 reconstructed its shape
:: correctly (it agrees with zone_2's solve of 2,054 shared frames to
:: 1.2-22.8 mm) and only its SIZE was wrong.
::
:: Dive-wide corroboration: across all 46 components of >=100 cameras,
:: as-placed position sat within a median 6.2% of the best RIGID (scale-1)
:: fit to its own priors while leaving a median 22.8% residual reduction
:: unclaimed that only rescaling could capture - rigid placement, no
:: similarity fit.
::
:: THE RISK, and it is real. The reference records -update as the step that
:: "will rotate geometry to satisfy mis-converted constraints": it TRUSTS the
:: nav. On a dive whose flight log is in the wrong frame or whose CRS is
:: mis-declared, this step will faithfully wreck a good solve. That is why
:: the frame guard (ensure_frame_match) and the CRS pin above are
:: preconditions for it, not decoration - and why a big correction here is
:: worth reading as evidence the solve drifted rather than as a tidy-up.
::
:: Only runs when there ARE constraints: with no flight log there is nothing
:: to fit to and -update would be a no-op at best. RS_SKIP_GEOREG_UPDATE=1
:: disables it for a deliberate no-georeference control arm.
if not "%flight_log_dir%" == "" (
    if not defined RS_SKIP_GEOREG_UPDATE (
        echo Georegistering components against the flight-log constraints
        call :run -update || goto :fail
    ) else (
        echo RS_SKIP_GEOREG_UPDATE set - SKIPPING post-align georegistration.
        echo   Component scale will be whatever the solver's gauge produced
        echo   and is NOT fitted to the nav. See BUGS.md B19.
    )
)

:: Flight-log import leaves its matched images ACTIVELY SELECTED, and
:: selection-driven exports under -silent then silently export NOTHING
:: (the "Export Selection" dialog is auto-answered; see FINDINGS.md,
:: 2026-07-23). Clear the selection before every export step.
call :run -deselectAllImages || goto :fail

call :run -setMinComponentSize %min_component_size% || goto :fail

echo Saving project BEFORE the destructive identity loop
call :run -save "%output_dir%\%scene_name%.rsproj" || goto :fail

:: Daily project-save schema (owner requirement 2026-07-23): a dated copy
:: in RC_projects (one level up from the zone image directory) after the
:: components milestone, named {expedition_dive}_{zone}_YYYYMMDD.
:: RS_PROJECT_LABEL/RS_PROJECT_DATE are computed by the Python
:: orchestrator.
if defined RS_PROJECTS_DIR if defined RS_PROJECT_LABEL (
    if not exist "%RS_PROJECTS_DIR%" mkdir "%RS_PROJECTS_DIR%"
    echo Saving daily project copy
    call :run -save "%RS_PROJECTS_DIR%\%RS_PROJECT_LABEL%_%scene_name%_%RS_PROJECT_DATE%.rsproj" || goto :fail
)

:: ------------------------------------------------------------------
:: In-session identity capture. The scene (with all components) is
:: already saved above, so this loop is destructive IN MEMORY ONLY and
:: the workflow quits WITHOUT saving.
:: Membership by SUCCESSIVE DIFFERENCE (2026-07-23 rework): only
:: -exportXMP writes stem-named sidecars; -exportXMPForSelectedComponent
:: is ALWAYS ordinal (FINDINGS.md). So each lap exports the stems of ALL
:: remaining components (>= min size, still gated by the earlier
:: setMinComponentSize), harvests them to identity_r<K>, then exports +
:: deletes the maximal component. members(c<K>) = stems(r<K>) minus
:: stems(r<K+1>), computed by the Python orchestrator. An EMPTY harvest
:: is the exhaustion terminal (also fires when only sub-min components
:: remain) - selectMaximalComponent/rename/delete silently no-op on an
:: empty scene, so file-existence checks, not errors, drive the loop.
:: IDENTITY MECHANISM SWITCH (merge 2026-09-03, owner rules R1/R3; decision
:: D1 open - FINDINGS [RECON] 2026-09-03). Default = main's destructive XMP
:: harvest below (:legacyIdentity). RS_LEGACY_XMP_IDENTITY=0 selects the
:: non-destructive -exportLatestComponents / -exportRegistration capture the
:: remove-xmp-sidecars branch ran on NA168 H2080 and NA165 H2063.
:: RS_LEGACY_XMP_IDENTITY=1 (that branch's spelling) is the same as unset.
:: realityscan_interface.py gates its sidecar repair on this SAME test.
if not "%RS_LEGACY_XMP_IDENTITY%" == "0" goto :legacyIdentity

:: ------------------------------------------------------------------
:: NON-DESTRUCTIVE identity capture (RS_LEGACY_XMP_IDENTITY=0; the sidecars
:: branch's default, opt-in on the reconciled tree pending decision D1).
:: -exportLatestComponents writes every component >= setMinComponentSize
:: as its own .rsalign, so the component SET is known without deleting
:: anything; membership is then read per component with
:: -exportRegistration instead of being INFERRED by successive difference
:: of XMP stem harvests.
::
:: This retires the harvest's collateral damage: it MOVED every
:: pose-bearing .xmp out of the image tree, the last-peeled component's
:: sidecars were never re-exported, and 796 of 4,540 zone_1 images (17.5%)
:: were left with no calibration prior at all - which confounded PD-4 and
:: PD-4a (FINDINGS 2026-07-25). Nothing is written into %input_dir% here.
echo Capturing per-component identity (non-destructive)
set "latest_dir=%output_dir%\latest_components"
set "identity_dir=%output_dir%\identity"
if not exist "%latest_dir%" mkdir "%latest_dir%"
if not exist "%identity_dir%" mkdir "%identity_dir%"

call :run -exportLatestComponents "%latest_dir%" || goto :fail

set /a comp_index=0
for %%F in ("%latest_dir%\*.rsalign") do call :identityOne "%%~nF" || goto :fail
echo Identity capture finished after %comp_index% component(s)

echo Shutting down RealityScan instance %RS_INSTANCE% - scene already saved
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:: :identityOne - select ONE component by its exported name, give it the
:: canonical <scene>_c<K> name, and record its camera membership.
:: A subroutine (not an inline block) so %comp_index% expands per call
:: without enabling delayed expansion for the whole script.
:identityOne
call :run -selectComponent "%~1" || exit /b 1
call :run -renameSelectedComponent "%scene_name%_c%comp_index%" || exit /b 1
set "registration_csv=%identity_dir%\%scene_name%_c%comp_index%.csv"
call :run -exportRegistration "%registration_csv%" "%RegistrationParams%" || exit /b 1

:: GATE ON CONTENT, NOT ON THE EXIT CODE. RealityScan resolves this file's
:: calexFileFormatId against calibration.xml in its INSTALL directory, and
:: an id it cannot resolve does NOT error - it falls back to the instance's
:: current export settings and writes some other layout, exit code 0. That
:: is the same silent-fallback that dropped the flight log's orientation
:: accuracies on every import before 2026-08-16, so a green :run here
:: proves nothing about the format. Our format's body opens with
:: "#cameras $(cameraCount)", so line 1 of the CSV is the proof.
:: /n plus a "1:" match pins it to the FIRST line; the inner match is
:: deliberately NOT anchored with /b so a byte-order mark ahead of the
:: hash cannot fail a good export.
if not exist "%registration_csv%" goto :registrationMissing
%SystemRoot%\System32\findstr.exe /n /r /c:"#cameras [0-9][0-9]*" "%registration_csv%" | %SystemRoot%\System32\findstr.exe /b /c:"1:" >nul
if errorlevel 1 goto :registrationFormat

call :run -exportSelectedComponentDir "%output_dir%" || exit /b 1
set /a comp_index+=1
exit /b 0

:: Both of these return from :identityOne (exit /b 1), NOT goto :fail - the
:: caller already turns a non-zero return into goto :fail, and jumping
:: there from inside the call would run the teardown twice.
:registrationMissing
echo ERROR: -exportRegistration wrote no CSV for %scene_name%_c%comp_index%
echo   expected: %registration_csv%
echo   The delegated command reported success, which is exactly what a
echo   silent params/format fallback looks like. Check %RegistrationParams%
echo   and that its calexFileFormatId GUID is defined in RealityScan's own
echo   calibration.xml: python -m modules.flightlog_format --install
exit /b 1

:registrationFormat
echo ERROR: %registration_csv% does not start with the "#cameras N" header.
echo   The export succeeded but ran a DIFFERENT format: an unresolved
echo   calexFileFormatId falls back to the instance's current export
echo   settings instead of erroring, and the membership parser cannot read
echo   the CSV that produces. Check %RegistrationParams% and reinstall the
echo   RUMI formats: python -m modules.flightlog_format --install
exit /b 1

:legacyIdentity
echo NOTE: destructive XMP identity harvest (main default; set
echo   RS_LEGACY_XMP_IDENTITY=0 for the -exportRegistration capture). It
echo   writes sidecars beside the images under %harvest_dir% and STRIPS the
echo   calibration priors of the last-peeled component; the Python caller
echo   repairs those on every exit path. Decision D1 is open.
echo Capturing per-component identity (destructive in-memory loop)
:: Ceiling raised 20 -> 50 and made configurable (owner directive 2026-09-07).
:: MEASURED on NA165/H2060 zone_1 (8,757 images): the loop exited at the old
:: ceiling of 20 with identity_r19 still holding 915 pose sidecars and
:: identity_r20 never written - i.e. it stopped because it ran out of LAPS,
:: not because it ran out of components. Everything past c19 was dropped from
:: the merge inputs with no record, and c19's own manifest then claimed all
:: 915 remaining stems (its bbox spanned the whole zone, 181 x 487 m, against
:: 3-90 m for every genuine component).
:: RS_MAX_IDENTITY_COMPONENTS overrides it; realityscan_interface.py reads the
:: SAME variable with the same DEFAULT. The defaults cannot drift; a malformed
:: OVERRIDE still can, which is why it is validated below rather than trusted.
:: Python sanitizes (falls back to 50 on a non-int or a value <= 0); cmd does
:: not, and an unvalidated value reaches an UNQUOTED numeric comparison:
::   "0"/"-5" -> the ceiling fires on lap 0 and NO component is ever exported
::   "abc"    -> cmd compares as STRINGS, so the ceiling effectively never fires
::   "5 0"    -> syntax error mid-run, hours in
:: Only an all-digit, non-zero value is accepted; anything else warns loudly
:: and keeps the default, so the two sides stay in step.
:: Flat gotos, not nested parenthesised blocks: this script runs under a plain
:: `setlocal` with NO delayed expansion, and a `set` inside a block whose value
:: is read in the same block silently expands to the PARSE-time value. The rest
:: of this file is goto-structured for the same reason.
set "max_components=50"
if not defined RS_MAX_IDENTITY_COMPONENTS goto :ceilingReady
if "%RS_MAX_IDENTITY_COMPONENTS%" == "" goto :ceilingReady
echo %RS_MAX_IDENTITY_COMPONENTS%| findstr /r /x "[1-9][0-9]*" >nul
if errorlevel 1 goto :ceilingBadValue
set "max_components=%RS_MAX_IDENTITY_COMPONENTS%"
goto :ceilingReady
:ceilingBadValue
echo WARNING: RS_MAX_IDENTITY_COMPONENTS=%RS_MAX_IDENTITY_COMPONENTS% is not a positive
echo   integer - ignoring it and using the default 50, which is what
echo   realityscan_interface.py will also use. Left unsanitized this would have
echo   reached an unquoted numeric comparison: 0 or a negative exports NOTHING,
echo   a non-numeric makes cmd compare as strings so the ceiling never fires.
:ceilingReady
echo Identity component ceiling: %max_components%
set /a comp_index=0
:identityLoop
if %comp_index% GEQ %max_components% goto :identityCeiling
if not exist "%output_dir%\identity_r%comp_index%" mkdir "%output_dir%\identity_r%comp_index%"
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
:: $ErrorActionPreference=Stop plus try/catch: Move-Item failures are
:: NON-TERMINATING, so powershell.exe exited 0 on a partial harvest and
:: this step had no errorlevel check at all. Membership is
:: stems(identity_r<K>) minus stems(r<K+1>), so an under-harvest shifts
:: members BETWEEN components - and the merge camera-count attribution
:: is built on those numbers (audit 2026-08-07).
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { Get-ChildItem -LiteralPath '%harvest_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 ( echo ERROR: identity harvest move failed & goto :fail )
set "have_poses="
for %%F in ("%output_dir%\identity_r%comp_index%\*.xmp") do set have_poses=1
if not defined have_poses goto :identityDone
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "%scene_name%_c%comp_index%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
if not exist "%output_dir%\%scene_name%_c%comp_index%.rsalign" goto :identityDone
call :run -deleteSelectedComponent || goto :fail
set /a comp_index+=1
goto :identityLoop

:identityCeiling
:: The loop ran out of LAPS, not components. Membership is
:: stems(r<K>) - stems(r<K+1>), so without a final harvest the LAST exported
:: component's manifest absorbs every stem still in the scene: on zone_1 that
:: made c19 claim 915 cameras across a zone-spanning bbox, which then borders
:: every other component in the merge's bbox graph and pollutes the plan.
:: One more harvest costs a single -exportXMP and makes c<N-1> computable;
:: it also leaves a NON-EMPTY identity_r<N> on disk as the durable evidence
:: that truncation happened, which is exactly what nothing recorded before.
:: comp_index == max_components here (that is the branch condition), but the
:: LAST EXPORTED component is c<max_components - 1> - the increment happens
:: after the export. Naming c%comp_index% would send an operator looking for a
:: .rsalign that does not exist and reading a clean ceiling stop as a failed
:: export.
set /a last_captured=%comp_index%-1
echo WARNING: identity ceiling of %max_components% reached - harvesting the
echo   remainder so the last component's membership stays computable.
echo   Components c0..c%last_captured% were captured; anything past c%last_captured% is NOT.
echo   Raise RS_MAX_IDENTITY_COMPONENTS and re-run the zone to capture them.
if not exist "%output_dir%\identity_r%comp_index%" mkdir "%output_dir%\identity_r%comp_index%"
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { Get-ChildItem -LiteralPath '%harvest_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 ( echo ERROR: ceiling harvest move failed & goto :fail )

:identityDone
echo Identity capture finished after %comp_index% component(s)

echo Shutting down RealityScan instance %RS_INSTANCE% - NO save after identity loop
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0

:appGlobalKey
echo ERROR: %AlignmentParams% names an app-global (app*) setting.
echo   app* keys are application-wide: they persist into the user's own
echo   RealityScan GUI session, so they need per-instance approval
echo   (docs/AGENT_OPERATIONS.md rule 9). Set them deliberately in this
echo   workflow - appIncSubdirs already is - not through the params file.
goto :fail

:noSettings
echo ERROR: ZERO alignment settings were applied from %AlignmentParams%.
echo   The file exists but no "entry key=... value=..." pair could be
echo   parsed from it. The params file is authoritative for what it
echo   names - applying none of it is not reproducible; see this header.
goto :fail

:fail
echo ERROR: zone workflow failed - see %ErrorsFile% and the RealityScan log
call "%~dp0RuntimeAbortGuard.bat" || exit /b 1223
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 1

:: :run - delegate one operation to %RS_INSTANCE%, wait for it to finish,
:: and fail if RealityScan reported an error. Delegated commands are
:: queued and -waitCompleted can return prematurely when it runs before
:: the instance picks the queued command up: grace delay, then two
:: -waitCompleted calls with a second grace between them. Do NOT gate on
:: results log growth (heartbeat processes also write it).
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
