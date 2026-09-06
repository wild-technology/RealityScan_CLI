"""Texture policy - decision D13 (owner 2026-09-05), pinned mechanically.

1. AdaptiveTexelSize at a 4096 cap is the texture style of every workflow:
   GenerateModel.bat (both passes), ModelToFinal.bat (default preset AND the
   final unwrap, whatever texture preset was chosen), and the deprecated
   AlignImagesFromFolder.bat.
2. Never 16K, never a forced 4 x 8K page budget: every live Metadata preset
   caps unwrapMaxTexResolution at 4096; the MaxTexturesCount presets are
   retired to archive/metadata_retired/ and no live script or driver names
   them.
3. Deliverable textures are JPG: every export preset that names a texture
   image format says jpg/jpeg, with a no-alpha pixel format.
4. The final unwrap has a MaxTexturesCount 4 x 4096 fallback, because
   AdaptiveTexelSize rejected H2060 c5 outright and the untextured model
   still exported (FINDINGS 2026-09-03).
5. preflight BLOCKS a preset that breaks 1-3, so the policy cannot regress
   by editing an XML.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import finish_model  # noqa: E402
from modules import preflight as pf  # noqa: E402
from testing.test_preflight import _charter, _dataset  # noqa: E402

META = REPO / "modules/realityscan_interface/RS_CLI/Metadata"
SCRIPTS = REPO / "modules/realityscan_interface/RS_CLI/Scripts"
ARCHIVE = REPO / "archive/metadata_retired"

CAP = 4096
ADAPTIVE_TEXTURE = "Texturing_AdaptiveTexel_4k.xml"
ADAPTIVE_UNWRAP = "Unwrapping_AdaptiveTexel_4k.xml"
FALLBACK_UNWRAP = "Unwrapping_MaxCount4_4k.xml"

RETIRED = (
    "Texturing_MaxTextureCount1_8k.xml",
    "Texturing_MaxTextureCount4_8k.xml",
    "Texturing_MaxTextureCount1_16k.xml",
    "Texturing_MaxTextureCount4_16k.xml",
    "Texturing_HighPolyTexture.xml",
    "Texturing_SimplifiedTexture.xml",
    "Unwrapping_Simplified.xml",
    "Unwrapping_Simplified_4x8k.xml",
    "Unwrapping_Simplified_4x16k.xml",
)


def _entries(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {e.get("key"): e.get("value") for e in root.findall("entry")}


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


# ------------------------------------------------------------- 1. the cap

def test_every_live_texture_and_unwrap_preset_respects_the_cap():
    presets = sorted(list(META.glob("Texturing_*.xml")) + list(META.glob("Unwrapping_*.xml")))
    assert presets, "no texture presets found"
    for path in presets:
        res = _entries(path).get("unwrapMaxTexResolution")
        assert res is not None, path.name
        assert int(res) <= CAP, (path.name, res)


def test_the_adaptive_pair_is_really_the_adaptive_style():
    for name in (ADAPTIVE_TEXTURE, ADAPTIVE_UNWRAP):
        e = _entries(META / name)
        assert e["unwrapStyle"] == "AdaptiveTexelSize", name
        assert int(e["unwrapMaxTexResolution"]) == CAP, name
        assert "unwrapMaximalTexCount" not in e, name


def test_the_fallback_unwrap_is_max_count_inside_the_cap():
    e = _entries(META / FALLBACK_UNWRAP)
    assert e["unwrapStyle"] == "MaxTexturesCount"
    assert int(e["unwrapMaxTexResolution"]) <= CAP
    assert int(e["unwrapMaximalTexCount"]) == 4


# ------------------------------------------------- 2. retired, not deleted

@pytest.mark.parametrize("name", RETIRED)
def test_retired_presets_are_archived_and_gone_from_the_live_dir(name):
    assert (ARCHIVE / name).is_file(), f"{name} missing from archive"
    assert not (META / name).exists(), f"{name} still live"


def _live_sources():
    yield from sorted(SCRIPTS.glob("*.bat"))
    yield from sorted(REPO.glob("*.py"))
    for path in sorted((REPO / "modules").rglob("*.py")):
        yield path
    yield from sorted((REPO / "module_base").glob("*.py"))


def test_no_live_script_or_driver_names_a_retired_preset():
    offenders = []
    for path in _live_sources():
        text = _text(path)
        for name in RETIRED:
            if name in text:
                offenders.append(f"{path.relative_to(REPO)}: {name}")
    assert offenders == [], offenders


# ---------------------------------------------------- 3. the workflows

def test_generate_model_textures_and_unwraps_adaptively_with_a_fallback():
    text = _text(SCRIPTS / "GenerateModel.bat")
    assert f'set "HighModelTexture=%MetadataDir%\\{ADAPTIVE_TEXTURE}"' in text
    assert f'set "UnwrapSimplified=%MetadataDir%\\{ADAPTIVE_UNWRAP}"' in text
    assert f'set "UnwrapFallback=%MetadataDir%\\{FALLBACK_UNWRAP}"' in text
    assert "call :try_unwrap || goto :fail" in text
    assert ":try_unwrap" in text and ":unwrapFallback" in text
    # the adaptive attempt's error is evidence, then the fallback runs
    # through :run so a second failure still aborts
    assert "expected_unwrap_adaptive_" in text
    assert 'call :run -unwrap "%UnwrapFallback%" || exit /b 1' in text


def test_model_to_final_defaults_to_adaptive_and_never_pairs_unwrap_with_preset():
    text = _text(SCRIPTS / "ModelToFinal.bat")
    assert 'set "tex_preset=adaptive"' in text
    assert f'"adaptive"  set "TexParams=%MetadataDir%\\{ADAPTIVE_TEXTURE}"' in text
    assert f'set "UnwrapSimplified=%MetadataDir%\\{ADAPTIVE_UNWRAP}"' in text
    assert f'set "UnwrapFallback=%MetadataDir%\\{FALLBACK_UNWRAP}"' in text
    assert "call :try_unwrap || goto :fail" in text
    # the retired presets may be NAMED in comments; they may not be SELECTED
    for gone in ("4x8k", "highpoly", "16k", "8k"):
        assert f'== "{gone}"' not in text, gone
        assert f'set "tex_preset={gone}"' not in text, gone
    # attach lane: success is a scene-revision advance, not a lastError read
    assert "RS_UNWRAP_REV0" in text and ":unwrapBothFailed" in text


def test_deprecated_align_images_from_folder_is_capped_too():
    text = _text(SCRIPTS / "AlignImagesFromFolder.bat")
    assert ADAPTIVE_TEXTURE in text and ADAPTIVE_UNWRAP in text


def test_set_variables_points_at_live_presets_only():
    text = _text(SCRIPTS / "SetVariables.bat")
    for var in ("TexturingAdaptive4k", "UnwrappingAdaptive4k", "UnwrappingMaxCount4x4k"):
        assert f"set {var}=" in text, var
    for name in re.findall(r"%Metadata%\\([A-Za-z0-9_]+\.xml)", text):
        assert (META / name).is_file(), f"SetVariables names a missing preset {name}"


@pytest.mark.parametrize("name", ["GenerateModel.bat", "ModelToFinal.bat",
                                  "AlignImagesFromFolder.bat", "SetVariables.bat"])
def test_edited_workflow_scripts_are_still_crlf(name):
    raw = (SCRIPTS / name).read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n"), f"{name} has bare LF"


def test_finish_model_presets_match_the_script():
    assert finish_model.TEXTURE_PRESETS == ("adaptive", "fixed100", "fixed50")
    src = (REPO / "finish_model.py").read_text(encoding="utf-8")
    assert "default='adaptive'" in src
    bat = _text(SCRIPTS / "ModelToFinal.bat")
    for preset in finish_model.TEXTURE_PRESETS:
        assert f'"{preset}"' in bat, preset


# ------------------------------------------------------ 4. JPG deliverables

def test_every_export_preset_writes_jpg_textures_without_alpha():
    presets = sorted(META.glob("ModelExportParams*.xml"))
    assert presets
    for path in presets:
        e = _entries(path)
        fmts = {k: v for k, v in e.items() if k.startswith("MvsMeshExportTexImgFormat")}
        pix = {k: v for k, v in e.items() if k.startswith("MvsMeshExportTexPixFormat")}
        for key, value in fmts.items():
            assert value.lower() in ("jpg", "jpeg"), (path.name, key, value)
        for key, value in pix.items():
            assert value == "24bppBGR", (path.name, key, value)


# ------------------------------------------------------- 5. preflight gate

def test_preflight_knows_the_live_model_presets():
    for name in pf.STAGE_XML["model"]:
        assert (META / name).is_file(), name
    assert ADAPTIVE_TEXTURE in pf.STAGE_XML["model"]
    assert ADAPTIVE_UNWRAP in pf.STAGE_XML["model"]
    assert FALLBACK_UNWRAP in pf.STAGE_XML["model"]


def _model_export_charter(tmp_path):
    originals, nav = _dataset(tmp_path)
    return _charter(tmp_path, originals, nav, stages=("model", "export"), answers={})


def test_preflight_blocks_a_16k_unwrap_preset(tmp_path, monkeypatch):
    meta = tmp_path / "meta"
    shutil.copytree(pf.METADATA_DIR, meta)
    target = meta / ADAPTIVE_UNWRAP
    text = target.read_text(encoding="utf-8")
    assert 'value="4096"' in text
    target.write_text(text.replace('value="4096"', 'value="16384"'), encoding="utf-8")
    monkeypatch.setattr(pf, "METADATA_DIR", str(meta))
    report = pf.preflight_charter(_model_export_charter(tmp_path))
    assert any("16384" in b and "D13" in b for b in report["blocking"]), report["blocking"]


def test_preflight_blocks_a_png_export_preset(tmp_path, monkeypatch):
    meta = tmp_path / "meta"
    shutil.copytree(pf.METADATA_DIR, meta)
    target = meta / "ModelExportParamsOBJ_NiraParts.xml"
    text = target.read_text(encoding="utf-8")
    assert 'value="jpg"' in text
    target.write_text(text.replace('value="jpg"', 'value="png"', 1), encoding="utf-8")
    monkeypatch.setattr(pf, "METADATA_DIR", str(meta))
    report = pf.preflight_charter(_model_export_charter(tmp_path))
    assert any("non-JPG" in b for b in report["blocking"]), report["blocking"]


def test_preflight_passes_the_repo_presets(tmp_path):
    report = pf.preflight_charter(_model_export_charter(tmp_path))
    texture_blocks = [b for b in report["blocking"] if "D13" in b or "non-JPG" in b]
    assert texture_blocks == [], texture_blocks


def test_archive_dir_is_documented():
    readme = ARCHIVE / "README.md"
    assert readme.is_file()
    text = readme.read_text(encoding="utf-8")
    for name in RETIRED:
        assert name in text, name
    assert "metadata_retired" in (REPO / "archive/README.md").read_text(encoding="utf-8")


def test_this_repo_has_no_stray_16384_in_live_metadata():
    for path in sorted(META.glob("*.xml")):
        assert "16384" not in _text(path), path.name
    assert not os.path.exists(META / "Unwrapping_Simplified.xml")
