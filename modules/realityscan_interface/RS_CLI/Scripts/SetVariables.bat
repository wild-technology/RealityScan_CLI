:: Shared variables for every RealityScan CLI workflow script.
:: Based on the Epic Games Slovakia CLI samples, adapted for RealityScan 2.2.

:: Switch on/off console output.
@echo off

:: Path to the RealityScan executable.
:: Resolution order: RS_EXECUTABLE environment variable (set by the Python
:: orchestrator or the user), then standard install locations, newest first.
if defined RS_EXECUTABLE (
    set RealityScan="%RS_EXECUTABLE%"
    goto :exeResolved
)
for %%P in (
    "C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"
    "C:\Program Files\Capturing Reality\RealityScan 2.2\RealityScan.exe"
    "C:\Program Files\Epic Games\RealityScan_2.1\RealityScan.exe"
    "C:\Program Files\Capturing Reality\RealityScan 2.1\RealityScan.exe"
    "C:\Program Files\Epic Games\RealityScan_2.0\RealityScan.exe"
) do (
    if not defined RealityScan if exist %%P set RealityScan=%%P
)
:exeResolved
if not defined RealityScan (
    echo ERROR: RealityScan.exe not found in any standard install location.
    echo Set the RS_EXECUTABLE environment variable to the full path of RealityScan.exe.
    exit /b 1
)

:: Name of the headless instance all commands are delegated to. Override
:: RS_INSTANCE to run several instances in parallel (e.g. one per GPU).
if not defined RS_INSTANCE set RS_INSTANCE=RS1

:: Headless toggle: set RS_HEADLESS=0 to boot the instance with its GUI
:: visible (delegation and monitoring work identically); any other value
:: (or unset) keeps the default headless boot.
:: NOTE (2026-08-07): the Python layer always passes RS_HEADLESS
:: explicitly, resolved from rs_settings.json ('realityscan.headless',
:: default = visible; see module_base/settings_store.py). The headless
:: fallback below is therefore only the .bat-side default for hand-run
:: scripts - do not change it here.
set RS_HEADLESS_FLAG=-headless
if /I "%RS_HEADLESS%"=="0" set RS_HEADLESS_FLAG=

:: Root path to work folders where all the datasets are stored
set RootFolder=%~dp0..\

:: Variable storing path to working directory
set workingDir=%~dp0

:: A path to the metadata folder.
set Metadata=%RootFolder%Metadata

:: A path to the models folder.
if defined RS_RUNTIME_ROOT (
    set "Models=%RS_RUNTIME_ROOT%\models"
) else (
    set "Models=%RootFolder%Models"
)
if not exist "%Models%" mkdir "%Models%" || exit /b 1

:: A path to the Errors folder (progress/results/error marker files).
if defined RS_ERRORS_DIR (
    if not defined RS_RUNTIME_ROOT (
        echo ERROR: RS_ERRORS_DIR requires RS_RUNTIME_ROOT and the canonical Python launcher.
        exit /b 1
    )
    set "ErrorPath=%RS_ERRORS_DIR%"
) else (
    if defined RS_RUNTIME_ROOT (
        echo ERROR: Runtime marker helpers must be prepared by RealityScanCLI.
        exit /b 1
    )
    set "ErrorPath=%RootFolder%Errors"
)
if not exist "%ErrorPath%" mkdir "%ErrorPath%" || exit /b 1
if defined RS_ERRORS_DIR (
    if not exist "%ErrorPath%\ErrorWriter.bat" exit /b 1
    if not exist "%ErrorPath%\ErrorWriterLaunch.vbs" exit /b 1
)

:: Variable storing name of file with Error write script.
set ErrorWriter=%ErrorPath%\ErrorWriter.bat

:: Variable storing path to xmp metadata.
set XMPMetadata=%Metadata%\xmp

:: Variable storing name of file with parameters for Alignment settings
set AlignParams=%Metadata%\AlignmentParams.xml

:: Variable storing name of file with parameters for exporting model to .* file format.
set ModelExportParams=%Metadata%\ModelExportParams.xml

:: Variable storing name of file with parameters for exporting model to .glb file format.
set ModelExportParamsGLB=%Metadata%\ModelExportParamsGLB.xml

:: Variable storing name of file with parameters for exporting model to .obj file format.
set ModelExportParamsOBJ=%Metadata%\ModelExportParamsOBJ.xml

:: Variable storing name of file with parameters for exporting model to .fbx file format with U1_V1 tile type.
set ModelExportParamsFBXU1V1=%Metadata%\ModelExportParamsFBX_U1V1.xml

:: Variable storing name of file with parameters for exporting model to .fbx file format with U1_V1 tile type.
set ModelExportParamsFBXU1V1Material=%Metadata%\ModelExportParamsFBX_U1V1_material.xml

:: Variable storing name of file with parameters for exporting model to .fbx file format with U_V tile type.
set ModelExportParamsFBXUV=%Metadata%\ModelExportParamsFBX_UV.xml

:: Variable storing name of file with parameters for exporting model to .fbx file format with UDIM tile type and material creation OFF.
set ModelExportParamsFBXUDIM=%Metadata%\ModelExportParamsFBX_UDIM.xml

:: Variable storing name of file with parameters for exporting model to .fbx file format with UDIM tile type and material creation ON.
set ModelExportParamsFBXUDIMMaterial=%Metadata%\ModelExportParamsFBX_UDIM_material.xml

:: Variable storing name of file with parameters for texturing (AdaptiveTexelSize, 4096 cap - decision D13)
set TexturingAdaptive4k=%Metadata%\Texturing_AdaptiveTexel_4k.xml

:: Variable storing name of file with parameters for unwrapping (AdaptiveTexelSize, 4096 cap - decision D13)
set UnwrappingAdaptive4k=%Metadata%\Unwrapping_AdaptiveTexel_4k.xml

:: Variable storing name of file with parameters for the fallback unwrap (MaxTexturesCount 4 x 4096)
set UnwrappingMaxCount4x4k=%Metadata%\Unwrapping_MaxCount4_4k.xml

:: Variable storing name of file with parameters for texturing (Fixed texel size 50% quality UV unwrap)
set TexturingFixedTexSize50=%Metadata%\Texturing_FixedTexelSize50perQuality.xml

:: Variable storing name of file with parameters for texturing (Fixed texel size 100% quality UV unwrap)
set TexturingFixedTexSize100=%Metadata%\Texturing_FixedTexelSize100perQuality.xml

:: Variable storing name of file with parameters for texture reprojection
set ReprojectionParams=%Metadata%\ReprojectionParams.xml

:: Variable storing name of file with parameters for simplification to 500k
set Simplify500k=%Metadata%\Simplify500k_Params.xml

:: Variable storing name of file with parameters for simplification by 50%
set Simplify50per=%Metadata%\Simplify50Per_Params.xml

:: Variable storing name of file with parameters for smoothing to 0.2 and 2 iterations
set SmoothingParams=%Metadata%\Smoothing_02_2_Params.xml

::set variable "reconRegion" for counting files in
set ReconRegion=%RootFolder%ReconRegion
