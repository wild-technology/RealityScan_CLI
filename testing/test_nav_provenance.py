"""Cross-zone navigation provenance - one nav table behind every zone.

The guard modules.verify ships compares each zone's align_inputs.json
``flight_log`` sha256 across zones. In a batched dive that file is a
per-zone ROW SUBSET, so nine legitimate slices read as nine navigations
and every batched dive on this machine was reported as the two-frames
incident class (C-20260805-01) it exists to catch.

Half of these tests prove the false positive is gone. The other half -
the ones that matter - prove the guard still BLOCKS every way a real
navigation disagreement can arrive, and still blocks when it merely
cannot measure. A guard that stopped firing would be a worse bug than
the one being fixed.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import nav_provenance
from modules.nav_provenance import (
    columns_compatible, find_by_sha, index_rows, pairwise_agreement, read_nav,
    same_row, sha256_file)
from modules.verify import verify_workspace
from modules.workspace_census import Workspace

HEADER_MASTER = "Name;X (East);Y (North);Alt"
HEADER_SLICE = "filename;X (East);Y (North);Alt"


def _row(i, x=None):
    return "IMG_%04d.jpg;%s;8428000.0;-680.0" % (i, x if x else "710800.%d" % i)


def _write(path, text, bom=False, newline="\r\n", encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = text.replace("\n", newline).encode(encoding)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + raw)
    return str(path)


def _dive(tmp_path, zones, nested="rs", master_rows=None, marker_sha=None):
    """A workspace shaped like a real batched dive.

    ``zones`` maps zone name -> list of row indices that zone holds.
    Returns (ws_root, master_path, {zone: slice_path}).
    """
    ws = tmp_path / "proc"
    every = sorted({i for ids in zones.values() for i in ids})
    rows = master_rows if master_rows is not None else [_row(i) for i in every]
    master = _write(ws / "flight_log_NA165_TEST_2L_UTM.txt",
                    HEADER_MASTER + "\n" + "\n".join(rows) + "\n", bom=True)

    batched = ws / nested / "batched_images_by_zone" if nested else \
        ws / "batched_images_by_zone"
    slices = {}
    for zone, ids in zones.items():
        zdir = batched / zone
        zdir.mkdir(parents=True, exist_ok=True)
        for i in ids:
            (zdir / ("IMG_%04d.jpg" % i)).write_bytes(b"x")
        slices[zone] = _write(
            zdir / "flight_log_NA165_TEST_2L_UTM.txt",
            HEADER_SLICE + "\n" + "\n".join(_row(i) for i in ids) + "\n")

    (batched / "batch_inputs.json").write_text(json.dumps({
        "flight_log": os.path.basename(master),
        "flight_log_sha256": marker_sha or sha256_file(master),
        "status": "complete"}), encoding="utf-8")

    for zone, ids in zones.items():
        adir = ws / "aligned_components" / zone
        adir.mkdir(parents=True, exist_ok=True)
        (adir / ("%s_c0.rsalign" % zone)).write_bytes(b"x")
        (adir / ("%s_c0.rsalign.manifest.json" % zone)).write_text(json.dumps(
            {"schema": 1, "zone": zone, "component": "%s_c0" % zone,
             "camera_count": len(ids)}), encoding="utf-8")
        (adir / "align_inputs.json").write_text(json.dumps({
            "schema": 1, "frame": "utm",
            "flight_log": {"path": slices[zone],
                           "sha256": sha256_file(slices[zone])},
            "align_settings": {"sha256": "sss"},
            "flight_log_params": {"sha256": "ppp"},
            "min_component_size": 10}), encoding="utf-8")
    return ws, master, slices


def _fp(ws, zone):
    return ws / "aligned_components" / zone / "align_inputs.json"


def _nav(out):
    return out["provenance"]["nav"]


def _says(out, needle):
    return any(needle in b for b in out["blocking"])


# --------------------------------------------------------- the false positive

def test_legitimate_slices_of_one_table_are_unanimous(tmp_path):
    """The H2060 case: nine slices, nine hashes, one nav table."""
    ws, master, _ = _dive(tmp_path, {"zone_1": [1, 2, 3], "zone_2": [3, 4, 5]})
    out = verify_workspace(str(ws))
    assert out["verdict"] == "ok", out["blocking"]
    nav = _nav(out)
    assert nav["method"] == "slices"
    assert nav["unanimous"] is True and nav["proven"] is True
    assert os.path.samefile(nav["source"], master)
    assert nav["source_origin"] == "batch_marker"
    # and the raw byte comparison is not also shouting
    assert not _says(out, "navigation flight log DIFFERS")


def test_identical_logs_still_pass_without_any_table(tmp_path):
    ws, _master, _s = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [1, 2]})
    out = verify_workspace(str(ws))
    assert out["verdict"] == "ok", out["blocking"]
    assert _nav(out)["method"] == "identical"


def test_bom_and_name_rename_are_not_differences():
    master = read_nav_text(HEADER_MASTER, [_row(1)], bom=True)
    slice_ = read_nav_text(HEADER_SLICE, [_row(1)])
    assert columns_compatible(master["header"], slice_["header"])
    assert master["rows"][0][0] == slice_["rows"][0][0]
    assert same_row(master["rows"][0][1], slice_["rows"][0][1])


def read_nav_text(header, rows, bom=False, newline="\r\n", tmp=None):
    import tempfile
    from pathlib import Path
    tmp = tmp or tempfile.mkdtemp()
    p = Path(tmp) / ("t%d.txt" % len(rows))
    _write(p, header + "\n" + "\n".join(rows) + "\n", bom=bom, newline=newline)
    return read_nav(str(p))


def test_crlf_and_lf_rows_are_identical():
    a = read_nav_text(HEADER_MASTER, [_row(1)], newline="\r\n")
    b = read_nav_text(HEADER_SLICE, [_row(1)], newline="\n")
    assert a["rows"] == b["rows"]


def test_requoted_field_is_not_a_difference():
    assert same_row('a;"b";c', "a;b;c")


def test_a_genuinely_different_field_is_a_difference():
    assert not same_row("a;b;c", "a;b;d")


# ------------------------------------------------- the guard must still fire

def test_one_changed_row_in_one_zone_blocks(tmp_path):
    """A zone whose nav was solved differently - the whole point."""
    ws, _m, slices = _dive(tmp_path, {"zone_1": [1, 2, 3], "zone_2": [3, 4]})
    bad = _write_slice_variant(slices["zone_2"], [3, 4], moved=3)
    _repoint(ws, "zone_2", bad)
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "row(s) differ from")
    assert _nav(out)["unanimous"] is False


def _write_slice_variant(path, ids, moved=None, extra=None):
    from pathlib import Path
    rows = []
    for i in ids:
        rows.append(_row(i, x="999999.9") if i == moved else _row(i))
    if extra is not None:
        rows.append(_row(extra))
    return _write(Path(path), HEADER_SLICE + "\n" + "\n".join(rows) + "\n")


def _repoint(ws, zone, slice_path):
    fp = json.loads(_fp(ws, zone).read_text(encoding="utf-8"))
    fp["flight_log"] = {"path": slice_path, "sha256": sha256_file(slice_path)}
    _fp(ws, zone).write_text(json.dumps(fp), encoding="utf-8")


def test_a_row_the_table_lacks_blocks(tmp_path):
    ws, _m, slices = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3]})
    bad = _write_slice_variant(slices["zone_2"], [2, 3], extra=99)
    # the extra row needs its image too, or the zone fails the imagery
    # reconciliation first and never reaches the containment check
    with open(os.path.join(os.path.dirname(bad), "IMG_0099.jpg"), "wb") as fh:
        fh.write(b"x")
    _repoint(ws, "zone_2", bad)
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "are absent from the navigation table")


def test_unrecorded_nav_sha_blocks(tmp_path):
    """Two zones that both recorded NOTHING used to group together and pass."""
    ws, _m, _s = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3]})
    for zone in ("zone_1", "zone_2"):
        fp = json.loads(_fp(ws, zone).read_text(encoding="utf-8"))
        fp["flight_log"] = {"path": None, "sha256": None}
        _fp(ws, zone).write_text(json.dumps(fp), encoding="utf-8")
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "NOT RECORDED")


def test_slice_edited_after_alignment_blocks(tmp_path):
    ws, _m, slices = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3]})
    with open(slices["zone_2"], "a", encoding="utf-8") as fh:
        fh.write(_row(77) + "\n")
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "CHANGED ON DISK")


def test_header_only_slice_cannot_prove_itself(tmp_path):
    ws, _m, slices = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3]})
    from pathlib import Path
    empty = _write(Path(slices["zone_2"]), HEADER_SLICE + "\n")
    _repoint(ws, "zone_2", empty)
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "zero data rows")


def test_a_slice_cut_short_of_its_own_source_blocks(tmp_path):
    """Rows the TABLE has and the slice omits: the proof covers less than
    the zone, so it says nothing about the cameras it left out."""
    ws, _m, slices = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3, 4]})
    short = _write_slice_variant(slices["zone_2"], [2])
    _repoint(ws, "zone_2", short)
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "the slice was cut short of its own source")


def test_images_no_flight_log_covers_are_not_a_nav_fault(tmp_path):
    """H2082 zone_1 holds 180 images (00000.jpeg ...) that appear in no
    flight log at all, its own master included. Carrying no navigation is
    a real condition, not a cross-zone disagreement - an exact
    row-to-image equality blocked that dive for it."""
    ws, _m, _s = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3]})
    zdir = ws / "rs" / "batched_images_by_zone" / "zone_2"
    for n in range(5):
        (zdir / ("%05d.jpeg" % n)).write_bytes(b"x")
    out = verify_workspace(str(ws))
    assert out["verdict"] == "ok", out["blocking"]
    rec = _nav(out)["zones"]["zone_2"]
    assert rec["images_without_a_row"] == 5
    assert rec["omitted_rows_the_table_has"] == 0


def test_a_table_naming_one_image_twice_is_refused(tmp_path):
    rows = [_row(1), _row(2), _row(2, x="555555.5")]
    ws, _m, _s = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2]},
                       master_rows=rows)
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "twice with DIFFERENT navigation")


def test_a_marker_naming_a_table_not_on_disk_blocks(tmp_path):
    ws, master, _s = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3]},
                           marker_sha="f" * 64)
    os.remove(master)
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "no file hashing to")


def test_a_hand_written_marker_cannot_manufacture_a_pass(tmp_path):
    """The marker supplies a sha; the file must still be FOUND by hashing."""
    ws, master, _s = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3]})
    batched = ws / "rs" / "batched_images_by_zone"
    (batched / "batch_inputs.json").write_text(
        json.dumps({"flight_log_sha256": "0" * 64}), encoding="utf-8")
    assert os.path.isfile(master)
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "no file hashing to")


def test_a_marker_with_no_sha_blocks(tmp_path):
    ws, _m, _s = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3]})
    batched = ws / "rs" / "batched_images_by_zone"
    (batched / "batch_inputs.json").write_text(
        json.dumps({"status": "complete"}), encoding="utf-8")
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert _says(out, "records no flight_log_sha256")


def test_an_operator_override_still_has_to_contain_every_row(tmp_path):
    ws, _m, _s = _dive(tmp_path, {"zone_1": [1, 2], "zone_2": [2, 3]})
    from pathlib import Path
    wrong = _write(Path(str(ws)) / "other_table.txt",
                   HEADER_MASTER + "\n" + _row(1) + "\n", bom=True)
    out = verify_workspace(str(ws), source_flight_log=wrong)
    assert out["verdict"] == "blocked"
    assert _says(out, "are absent from the navigation table")


# ----------------------------------------------------------- anchor selection

def test_find_by_sha_ignores_a_name_match_with_different_content(tmp_path):
    wanted = _write(tmp_path / "a" / "flight_log_2L_UTM.txt", "x")
    _write(tmp_path / "b" / "flight_log_2L_UTM.txt", "different")
    hits = find_by_sha([tmp_path], sha256_file(wanted))
    assert [os.path.normcase(h) for h in hits] == [os.path.normcase(wanted)]


def test_find_by_sha_never_returns_a_derived_log(tmp_path):
    """A merge union is built FROM the slices, so proving against it is
    circular - and a zone slice is the thing under test."""
    text = "Name;X\nIMG.jpg;1\n"
    _write(tmp_path / "merged_v3" / "assembly" / "flight_log_2L_UTM.txt", text)
    _write(tmp_path / "rs" / "batched_images_by_zone" / "zone_1"
           / "flight_log_2L_UTM.txt", text)
    real = _write(tmp_path / "nav" / "flight_log_2L_UTM.txt", text)
    hits = find_by_sha([tmp_path], sha256_file(real))
    assert [os.path.normcase(h) for h in hits] == [os.path.normcase(real)]


def test_undecodable_log_is_an_error_not_a_match(tmp_path):
    p = tmp_path / "flight_log_2L_UTM.txt"
    p.write_bytes(b"Name;X\n\xff\xfe\x00\x81\x8d;1\n".replace(b"\x00", b""))
    got = read_nav(str(p))
    # cp1252 leaves 0x81/0x8d undefined; whatever the outcome, two
    # different undefined bytes must never collapse onto one U+FFFD
    assert got["error"] is None or "decodable" in got["error"]
    assert "\ufffd" not in (got["header"] + "".join(t for _k, t in got["rows"]))


# ------------------------------------------------------------ pairwise, layout

def test_pairwise_finds_a_disagreement_without_any_table():
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    a = _write(tmp / "a.txt", HEADER_SLICE + "\n" + _row(1) + "\n" + _row(2)
               + "\n")
    b = _write(tmp / "b.txt", HEADER_SLICE + "\n" + _row(2, x="1.0") + "\n")
    got = pairwise_agreement({"zone_1": a, "zone_2": b})
    assert got["shared_keys"] == 1 and got["conflicts"] == 1


def test_locator_prefers_a_flat_tree(tmp_path):
    (tmp_path / "batched_images_by_zone").mkdir()
    (tmp_path / "rs" / "batched_images_by_zone").mkdir(parents=True)
    ws = Workspace(tmp_path)
    assert ws.batched == tmp_path / "batched_images_by_zone"
    assert ws.layout()["batched_images_by_zone"]["how"] == "flat"


def test_locator_finds_one_nested_tree(tmp_path):
    (tmp_path / "rs" / "batched_images_by_zone").mkdir(parents=True)
    ws = Workspace(tmp_path)
    assert ws.batched == tmp_path / "rs" / "batched_images_by_zone"
    assert ws.layout()["batched_images_by_zone"]["how"] == "nested"


def test_locator_refuses_to_choose_between_two_nested_trees(tmp_path):
    """H2080 carries both rs\\ and rs_cinup\\ aligned trees."""
    (tmp_path / "rs" / "aligned_components").mkdir(parents=True)
    (tmp_path / "rs_cinup" / "aligned_components").mkdir(parents=True)
    ws = Workspace(tmp_path)
    assert not ws.aligned.is_dir()
    rec = ws.layout()["aligned_components"]
    assert rec["how"] == "ambiguous" and len(rec["candidates"]) == 2


def test_locator_never_descends_into_a_retired_copy(tmp_path):
    (tmp_path / "archive" / "batched_images_by_zone").mkdir(parents=True)
    ws = Workspace(tmp_path)
    assert ws.layout()["batched_images_by_zone"]["how"] == "absent"


def test_index_rows_keeps_one_tail_per_key():
    by_full, _by_base, conflicts = index_rows(
        [(("a.jpg",), "1;2"), (("a.jpg",), "9;9")])
    assert conflicts == {("a.jpg",)} and by_full[("a.jpg",)] == "1;2"


def test_pool_absolute_paths_match_by_path_suffix():
    by_full, by_base, _c = index_rows([(nav_provenance.nav_key("wca/D1.JPG"),
                                        "1;2")])
    key = nav_provenance.nav_key(r"C:\pool\wca\D1.JPG")
    got, how = nav_provenance.match_key(key, by_full, by_base)
    assert how == "suffix" and got == ("wca", "d1.jpg")


def test_two_pool_folders_sharing_a_basename_do_not_collide():
    """C:\\poolA\\wca\\D1.JPG and C:\\poolB\\zeuss\\D1.JPG are not one row."""
    by_full, by_base, _c = index_rows([
        (nav_provenance.nav_key("wca/D1.JPG"), "1;1"),
        (nav_provenance.nav_key("zeuss/D1.JPG"), "2;2")])
    key = nav_provenance.nav_key(r"C:\poolB\zeuss\D1.JPG")
    got, how = nav_provenance.match_key(key, by_full, by_base)
    assert how == "suffix" and got == ("zeuss", "d1.jpg")
