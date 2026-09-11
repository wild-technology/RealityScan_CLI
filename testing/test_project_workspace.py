"""Offline project persistence/lifecycle contract; all artifacts use tmp_path."""
import copy
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from modules.project_workspace import (
    LAYOUT, STAGES, ProjectConflictError, ProjectDocument, ProjectError, settings_stage,
)


@pytest.fixture
def project(tmp_path):
    return ProjectDocument.create("NA171", "H2101", tmp_path / "project",
                                  sources=[tmp_path / "source"])


def finish(project, stage):
    attempt_id = project.start_stage(stage)
    project.complete_stage(stage, attempt_id=attempt_id)
    return attempt_id


def write_document(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_create_and_open_do_not_make_layout_or_write(project):
    assert not project.root.exists()
    assert UUID(project.project_id).version == 4
    assert project.to_dict()["layout"] == LAYOUT
    path = project.save()
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in project.root.iterdir()}
    loaded = ProjectDocument.load(path)
    assert loaded.to_dict() == project.to_dict()
    assert not (project.root / "proc").exists()
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in project.root.iterdir()}


def test_explicit_layout_and_snapshot_isolation(project):
    data = project.to_dict()
    data["stages"]["inventory"]["state"] = "failed"
    assert project.to_dict()["stages"]["inventory"]["state"] == "pending"
    paths = project.create_layout()
    assert set(paths) == set(LAYOUT)
    assert all(p.is_dir() for p in paths.values())
    assert paths["tmp"] == project.root / "proc" / "tmp"
    assert not Path(project.to_dict()["sources"][0]).exists()


@pytest.mark.parametrize("expedition,dive", [("NA17", "H2101"), ("NA1710", "H2101"),
                                               ("na171", "H2101"), ("NA171", "H210"),
                                               ("NA171", "h2101"), ("NA１７１", "H2101")])
def test_identity_rejected(tmp_path, expedition, dive):
    with pytest.raises(ProjectError):
        ProjectDocument.create(expedition, dive, tmp_path / "new")
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("which", ["same", "inside_source", "source_inside"])
def test_overlap_refused(tmp_path, which):
    root = tmp_path / "target"
    source = {"same": root, "inside_source": tmp_path, "source_inside": root / "source"}[which]
    with pytest.raises(ProjectError, match="overlap"):
        ProjectDocument.create("NA171", "H2101", root, [source])
    assert not root.exists()


def test_sibling_with_shared_prefix_allowed(tmp_path):
    p = ProjectDocument.create("NA171", "H2101", tmp_path / "raw_copy", [tmp_path / "raw"])
    assert p.root.name == "raw_copy"


@pytest.mark.parametrize("path", ["../escape", "proc/../escape", "proc//x", "proc/./x",
                                 "C:escape", "\\escape", "proc/a:stream", "proc/NUL.txt",
                                 "proc/trailing.", "proc/trailing ", "proc/bad?", "proc/\x00bad"])
def test_unsafe_relative_paths_refused(project, path):
    with pytest.raises(ProjectError):
        project.resolve_path(path)


def test_document_cannot_save_outside_root(project, tmp_path):
    with pytest.raises(ProjectError):
        project.save(tmp_path / "escape.rovscan")
    assert not project.root.exists()
    assert not (tmp_path / "escape.rovscan").exists()


def test_unsupported_extensions(project):
    with pytest.raises(ProjectError):
        project.save(project.root / "script.py")


def test_backup_keeps_exact_previous_valid_revision(project):
    path = project.save()
    original = path.read_bytes()
    project.set_settings("align", {"answer": 2})
    project.save()
    assert project.backup_path(path).read_bytes() == original
    assert ProjectDocument.load(path).to_dict() == project.to_dict()


def test_corrupt_primary_requires_explicit_read_only_recovery(project):
    path = project.save()
    original = path.read_bytes()
    project.set_settings("align", {"answer": 2})
    project.save()
    path.write_bytes(b'{"broken":')
    with pytest.raises(ProjectError):
        ProjectDocument.load(path)
    recovered = ProjectDocument.load(path, recover_backup=True)
    assert recovered.recovered_from_backup
    assert recovered.to_dict()["settings"] == {}
    assert path.read_bytes() == b'{"broken":'
    recovered.save()
    assert project.backup_path(path).read_bytes() == original
    assert ProjectDocument.load(path).to_dict() == recovered.to_dict()


def test_missing_primary_recovery_and_invalid_backup(project):
    path = project.save()
    project.set_settings("inventory", {"mode": "test"})
    project.save()
    path.unlink()
    recovered = ProjectDocument.load(path, recover_backup=True)
    assert not path.exists()
    recovered.save()
    assert path.exists()
    path.write_bytes(b"invalid")
    project.backup_path(path).write_bytes(b"invalid too")
    with pytest.raises(ProjectError, match="Primary and backup"):
        ProjectDocument.load(path, recover_backup=True)


def test_stale_writer_and_unrelated_save_as_refused(project, tmp_path):
    path = project.save()
    stale = ProjectDocument.load(path)
    project.set_settings("inventory", {"name": "new"})
    project.save()
    latest = path.read_bytes()
    with pytest.raises(ProjectConflictError):
        stale.save()
    other = ProjectDocument.create("NA171", "H2101", project.root)
    with pytest.raises(ProjectConflictError):
        other.save(path)
    assert path.read_bytes() == latest


def test_atomic_failure_preserves_primary_and_recovery(project, monkeypatch):
    path = project.save()
    original = path.read_bytes()
    project.set_settings("science", {"frame": "test"})
    replace = os.replace

    def fail_primary(src, dest):
        if Path(dest) == path:
            raise OSError("simulated rename failure")
        replace(src, dest)

    monkeypatch.setattr(os, "replace", fail_primary)
    with pytest.raises(OSError, match="simulated"):
        project.save()
    assert path.read_bytes() == original
    assert project.backup_path(path).read_bytes() == original
    assert not list(project.root.glob("*.tmp"))
    monkeypatch.setattr(os, "replace", replace)
    project.save()
    assert path.read_bytes() != original


def test_backup_write_failure_leaves_primary(project, monkeypatch):
    path = project.save()
    original = path.read_bytes()
    project.set_settings("science", {"frame": "test"})

    def fail(*args):
        raise OSError("no space")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="no space"):
        project.save()
    assert path.read_bytes() == original
    assert not list(project.root.glob("*.tmp"))


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema=True),
    lambda d: d.update(schema=2),
    lambda d: d.update(id="wrong"),
    lambda d: d.update(extra="unexpected"),
    lambda d: d.update(layout={"raw": "../outside"}),
    lambda d: d.update(sources="not a list"),
    lambda d: d.update(created_at="2026-09-11"),
    lambda d: d["stages"]["inventory"].update(state="succeeded"),
    lambda d: d["stages"]["inventory"].update(attempts="bad"),
    lambda d: d.update(settings={"block": {"values": [], "approval": None}}),
    lambda d: d.update(settings={"block": {"values": {"bad": float("nan")}, "approval": None}}),
])
def test_malformed_schema_refused_without_disk_edits(project, mutate):
    path = project.save()
    data = project.to_dict()
    mutate(data)
    write_document(path, data)
    original = path.read_bytes()
    with pytest.raises(ProjectError):
        ProjectDocument.load(path)
    assert path.read_bytes() == original


def test_duplicate_json_keys_and_executable_text_are_refused(project):
    path = project.save()
    for raw in [b'{"schema":1,"schema":1}', b'__import__("os").system("anything")']:
        path.write_bytes(raw)
        with pytest.raises(ProjectError):
            ProjectDocument.load(path)
        assert path.read_bytes() == raw


def test_approval_hash_bound_to_its_block_and_detached(project):
    values = {"frame": "test", "nested": {"x": 1}}
    project.set_settings("science", values)
    values["nested"]["x"] = 2
    assert project.to_dict()["settings"]["science"]["values"]["nested"]["x"] == 1
    with pytest.raises(ProjectError, match="approval"):
        project.start_stage("inventory")
    approved = project.approve_settings("science", "Owner")
    project.set_settings("science", {"nested": {"x": 1}, "frame": "test"})
    assert project.settings_approved() and project.settings_signature(['science']) == approved
    project.set_settings("align", {"mode": "test"})
    assert not project.settings_approved()
    assert project.to_dict()["settings"]["science"]["approval"]["content_hash"] == approved
    project.approve_settings("align", "Owner")
    assert project.settings_approved()


@pytest.mark.parametrize("field", ["root", "id", "sources", "values"])
def test_edited_document_invalidates_approval_in_memory(project, tmp_path, field):
    project.set_settings("science", {"scale": 1})
    project.approve_settings("science", "Owner")
    data = project.to_dict()
    if field == "root":
        data["root"] = str(tmp_path / "elsewhere")
    elif field == "id":
        data["id"] = str(uuid4())
    elif field == "sources":
        data["sources"] = [str(tmp_path / "other-source")]
    else:
        data["settings"]["science"]["values"]["scale"] = 2
    assert not ProjectDocument(data).settings_approved()


def test_stage_lifecycle_attempts_and_stale_callback(project):
    with pytest.raises(ProjectError, match="Predecessor"):
        project.start_stage("navigation")
    first = project.start_stage("inventory")
    with pytest.raises(ProjectError, match="running"):
        project.restart_stage("inventory")
    with pytest.raises(ProjectError):
        project.set_settings("science", {})
    project.fail_stage("inventory", "I/O unavailable", attempt_id=first)
    with pytest.raises(ProjectError, match="Restart"):
        project.start_stage("inventory")
    project.restart_stage("inventory")
    second = project.start_stage("inventory")
    with pytest.raises(ProjectError, match="Stale"):
        project.complete_stage("inventory", attempt_id=first)
    project.complete_stage("inventory", attempt_id=second)
    attempts = project.to_dict()["stages"]["inventory"]["attempts"]
    assert [a["state"] for a in attempts] == ["failed", "succeeded"]
    assert [a["number"] for a in attempts] == [1, 2]
    assert all(a["ended_at"] for a in attempts)


def test_restart_invalidates_downstream_and_preserves_artifacts(project):
    project.create_layout()
    for stage in STAGES:
        attempt = project.start_stage(stage)
        artifact = project.root / "proc" / f"{stage}.dat"
        artifact.write_bytes(stage.encode())
        project.record_output(stage, artifact, attempt_id=attempt)
        project.complete_stage(stage, attempt_id=attempt)
    original = project.to_dict()
    project.restart_stage("align", "Owner changed alignment scope")
    updated = project.to_dict()
    align_index = STAGES.index("align")
    for name in STAGES[:align_index]:
        assert updated["stages"][name] == original["stages"][name]
    for name in STAGES[align_index:]:
        assert updated["stages"][name]["state"] == "invalidated"
        assert updated["stages"][name]["attempts"] == original["stages"][name]["attempts"]
    assert all(r["status"] == "ok" for r in project.verify_outputs())
    assert [o["valid"] for o in updated["outputs"]] == [True] * align_index + [False] * 4
    project.save()
    assert ProjectDocument.load(project.path).to_dict() == project.to_dict()


def test_load_running_requires_explicit_recovery(project):
    attempt = project.start_stage("inventory")
    path = project.save()
    before = path.read_bytes()
    loaded = ProjectDocument.load(path)
    assert loaded.to_dict()["stages"]["inventory"]["state"] == "running"
    assert loaded.recover_interrupted() == ["inventory"]
    assert loaded.to_dict()["stages"]["inventory"]["state"] == "interrupted"
    assert loaded.recover_interrupted() == []
    assert path.read_bytes() == before
    with pytest.raises(ProjectError):
        loaded.complete_stage("inventory", attempt_id=attempt)
    loaded.restart_stage("inventory")
    finish(loaded, "inventory")
    assert len(loaded.to_dict()["stages"]["inventory"]["attempts"]) == 2


def test_explicit_skip_with_reason(project):
    project.skip_stage("inventory", "Imported inventory verified by operator")
    finish(project, "navigation")
    project.restart_stage("inventory")
    assert project.to_dict()["stages"]["navigation"]["state"] == "invalidated"
    with pytest.raises(ProjectError):
        project.skip_stage("inventory", "")


def test_output_hash_detects_same_size_same_mtime_edit(project):
    project.create_layout()
    path = project.root / "proc" / "artifact"
    path.write_bytes(b"abc")
    attempt = project.start_stage("inventory")
    recorded = project.record_output("inventory", path, attempt_id=attempt)
    assert project.verify_outputs()[0]["status"] == "ok"
    old_stat = path.stat()
    path.write_bytes(b"xyz")
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert project.verify_outputs()[0]["status"] == "changed"
    assert project.to_dict()["outputs"][0] == recorded
    path.unlink()
    assert project.verify_outputs()[0]["status"] == "missing"


def test_record_output_no_aliasing_and_no_reusing_deliverable(project):
    project.create_layout()
    path = project.root / "proc" / "artifact"
    path.write_bytes(b"ok")
    attempt = project.start_stage("inventory")
    recorded = project.record_output("inventory", path, attempt_id=attempt)
    recorded["sha256"] = "bad"
    assert project.verify_outputs()[0]["status"] == "ok"
    project.complete_stage("inventory", attempt_id=attempt)
    project.restart_stage("inventory")
    second = project.start_stage("inventory")
    with pytest.raises(ProjectError, match="already recorded"):
        project.record_output("inventory", path, attempt_id=second)
    assert path.read_bytes() == b"ok"


def test_adapter_uses_existing_session_and_charter_without_writes(project):
    from modules.run_plan import Session
    project.set_settings("pipeline", {"stages": ["batch", "align"],
                                      "answers": {"b_flag": False, "b_count": 3, "missing": None}})
    project.set_settings("science", {"min_component_size": 45})
    session = project.to_session()
    assert type(session) is Session
    assert session.enabled == ["batch", "align"]
    assert session.answers == {"b_flag": "false", "b_count": "3", "r_min_component_size": "45"}
    assert session.min_component_size == 45
    assert Path(session.results_root) == project.root / "proc"
    assert not session.continue_automatically
    assert not project.to_charter().is_signed()
    assert project.to_session([]).enabled == []
    with pytest.raises(ProjectError):
        project.to_session(["navigation"])
    assert not project.root.exists()


def test_resolved_directory_link_escape_refused(project, tmp_path):
    project.root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (project.root / "proc").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlink privilege unavailable: {exc}")
    with pytest.raises(ProjectError, match="outside"):
        project.resolve_path("proc/result")
    with pytest.raises(ProjectError):
        project.create_layout()
    assert list(outside.iterdir()) == []


def test_hardlinked_document_refused(project, tmp_path):
    path = project.save()
    alias = tmp_path / "alias"
    os.link(path, alias)
    original = alias.read_bytes()
    project.set_settings("inventory", {})
    with pytest.raises(ProjectError, match="unlinked"):
        project.save()
    assert alias.read_bytes() == original


def test_required_blocks_allow_inventory_without_future_science(project):
    project.set_settings("operations", {"instance": "fixture"})
    project.set_settings("science", {"frame": "fixture"})
    project.approve_settings("operations", "Operator")
    assert not project.settings_approved()
    with pytest.raises(ProjectError, match="approval"):
        project.start_stage("inventory")
    attempt = project.start_stage("inventory", required_blocks=("operations",))
    project.complete_stage("inventory", attempt_id=attempt)
    with pytest.raises(ProjectError, match="approval"):
        project.start_stage("navigation", required_blocks=("absent",))


def test_explicit_settings_scope_preserves_inventory_and_retires_later(project):
    for name in STAGES:
        finish(project, name)
    before = project.to_dict()["stages"]["inventory"]
    project.set_settings("camera", {"fixture": True}, affects_stage="georeference")
    assert project.to_dict()["stages"]["inventory"] == before
    assert project.to_dict()["stages"]["navigation"]["state"] == "succeeded"
    assert project.to_dict()["stages"]["georeference"]["state"] == "invalidated"
    with pytest.raises(ProjectError):
        project.set_settings("camera", {}, affects_stage="unknown")


def test_complete_refuses_changed_current_outputs(project):
    project.create_layout()
    path = project.root / "proc" / "artifact"
    path.write_bytes(b"original")
    attempt = project.start_stage("inventory")
    project.record_output("inventory", path, attempt_id=attempt)
    path.write_bytes(b"changed")
    with pytest.raises(ProjectError, match="missing, changed"):
        project.complete_stage("inventory", attempt_id=attempt)
    assert project.to_dict()["stages"]["inventory"]["state"] == "running"


def test_preprocess_review_cannot_be_skipped(project):
    for name in ("inventory", "navigation", "georeference"):
        finish(project, name)
    with pytest.raises(ProjectError, match="mandatory"):
        project.skip_stage("preprocess", "Try to bypass review")
    with pytest.raises(ProjectError, match="Predecessor"):
        project.start_stage("batch")


def approved_blocks(project):
    for block in ('operating', 'budget', 'navigation', 'cameras', 'georeference', 'align', 'science'):
        project.set_settings(block, {'value': 1})
    for block in project.to_dict()['settings']:
        project.approve_settings(block, 'Original operator')
    return project


def legacy_approved_data(project):
    data = project.to_dict()
    for block in data['settings'].values():
        if block['approval']:
            block['approval']['content_hash'] = project.settings_hash
    return data


@pytest.mark.parametrize('block,stage', [('operating', None), ('budget', None), ('science', 'align'),
    ('navigation', 'navigation'), ('cameras', 'georeference'), ('unknown-setting', 'inventory'),
    *[(stage, stage) for stage in STAGES if stage != 'navigation']])
def test_shared_settings_stage_dependency_map(block, stage):
    assert settings_stage(block) == stage


@pytest.mark.parametrize('block', ['operating', 'budget'])
def test_execution_only_edits_preserve_completed_science_and_other_approvals(project, block):
    approved_blocks(project)
    for stage in STAGES:
        finish(project, stage)
    before = project.to_dict()
    old_global = project.settings_hash
    geo_signature = project.settings_signature(['navigation', 'cameras', 'georeference'])
    project.set_settings(block, {'value': 2})
    after = project.to_dict()
    assert after['stages'] == before['stages']
    assert after['outputs'] == before['outputs']
    assert after['settings'][block]['approval'] is None
    for name in after['settings']:
        if name != block:
            assert after['settings'][name] == before['settings'][name]
            assert project.settings_approved([name])
    assert not project.settings_approved([block])
    assert project.settings_hash != old_global
    assert project.settings_signature(['navigation', 'cameras', 'georeference']) == geo_signature
    assert all(entry['attempts'][0]['settings_hash'] == old_global for entry in after['stages'].values())


@pytest.mark.parametrize('block,earliest', [('align', 'align'), ('science', 'align'),
    ('navigation', 'navigation'), ('cameras', 'georeference'), ('new_unknown', 'inventory')])
def test_settings_edit_invalidates_only_dependency_suffix(project, block, earliest):
    approved_blocks(project)
    for stage in STAGES:
        finish(project, stage)
    before = project.to_dict()
    project.set_settings(block, {'value': 2})
    after = project.to_dict()
    for stage in STAGES[:STAGES.index(earliest)]:
        assert after['stages'][stage] == before['stages'][stage]
    for stage in STAGES[STAGES.index(earliest):]:
        assert after['stages'][stage]['state'] == 'invalidated'
        assert after['stages'][stage]['attempts'] == before['stages'][stage]['attempts']
    for name in before['settings']:
        if name != block:
            assert after['settings'][name]['approval'] == before['settings'][name]['approval']


def test_valid_legacy_approvals_migrate_without_signoff_or_file_writes(project):
    approved_blocks(project)
    finish(project, 'inventory')
    data = legacy_approved_data(project)
    path = project.save()
    path.write_text(json.dumps(data), encoding='utf-8')
    before = path.read_bytes()
    loaded = ProjectDocument.load(path)
    assert path.read_bytes() == before
    assert loaded.settings_hash == project.settings_hash
    assert loaded.to_dict()['stages'] == data['stages']
    assert loaded.to_dict()['updated_at'] == data['updated_at']
    for name, block in data['settings'].items():
        migrated = loaded.to_dict()['settings'][name]['approval']
        assert migrated['content_hash'] == loaded.settings_signature([name])
        assert migrated['by'] == block['approval']['by'] and migrated['at'] == block['approval']['at']
    assert loaded.settings_approved()
    assert ProjectDocument(loaded.to_dict()).to_dict() == loaded.to_dict()


def test_legacy_migration_occurs_against_pre_mutation_global_hash(project):
    approved_blocks(project)
    # Emulate a still-live v1 in-memory document, rather than construction
    # (which already migrates). Mutation itself must migrate before editing.
    project._data = legacy_approved_data(project)
    before = project.to_dict()
    project.set_settings('budget', {'value': 9})
    for name in before['settings']:
        if name != 'budget':
            assert project.settings_approved([name])
            assert project.to_dict()['settings'][name]['approval']['at'] == before['settings'][name]['approval']['at']
    assert not project.settings_approved(['budget'])


@pytest.mark.parametrize('tamper', ['values', 'root', 'source', 'id', 'hash'])
def test_stale_legacy_approval_never_migrated_or_blessed(project, tmp_path, tamper):
    approved_blocks(project)
    data = legacy_approved_data(project)
    if tamper == 'values':
        data['settings']['cameras']['values']['value'] = 99
    elif tamper == 'root':
        data['root'] = str(tmp_path / 'other-project')
    elif tamper == 'source':
        data['sources'] = [str(tmp_path / 'new-source')]
    elif tamper == 'id':
        data['id'] = str(uuid4())
    else:
        for block in data['settings'].values():
            block['approval']['content_hash'] = '0' * 64
    loaded = ProjectDocument(data)
    assert all(block['approval'] is None for block in loaded.to_dict()['settings'].values())
    assert not loaded.settings_approved()


def test_mixed_legacy_and_block_proofs_preserve_only_valid_approvals(project):
    approved_blocks(project)
    data = legacy_approved_data(project)
    data['settings']['navigation']['approval']['content_hash'] = project.settings_signature(['navigation'])
    data['settings']['science']['approval']['content_hash'] = '0' * 64
    data['settings']['budget']['approval'] = None
    loaded = ProjectDocument(data)
    assert loaded.settings_approved(['operating', 'navigation', 'cameras'])
    assert not loaded.settings_approved(['science', 'budget'])
    assert loaded.to_dict()['settings']['science']['approval'] is None
    assert loaded.to_dict()['settings']['budget']['approval'] is None


def test_scoped_signature_order_optional_blocks_save_as_and_approval_independence(project):
    project.set_settings('navigation', {'z': 1, 'nested': {'b': 2, 'a': 1}})
    names = ['navigation', 'cameras', 'georeference']
    signature = project.settings_signature(names)
    assert signature == project.settings_signature(reversed(names))
    project.approve_settings('navigation', 'Owner')
    project.set_settings('align', {'r_min_component_size': 20})
    project.set_settings('budget', {'cache_delta': 200})
    project.save()
    project.save(project.root / 'renamed.rovscan')
    assert project.settings_signature(names) == signature
    project.set_settings('cameras', {})
    assert project.settings_signature(names) != signature  # absent != present empty


@pytest.mark.parametrize('names', ['navigation', None, ['navigation', 'navigation'], [1], [''], 1])
def test_signature_refuses_ambiguous_block_arguments(project, names):
    with pytest.raises(ProjectError):
        project.settings_signature(names)


def test_global_attempt_provenance_algorithm_remains_legacy_exact(project):
    approved_blocks(project)
    data = project.to_dict()
    original_payload = {key: data[key] for key in ('schema', 'id', 'expedition', 'dive', 'root', 'sources', 'layout')} | {
        'settings': {key: block['values'] for key, block in data['settings'].items()}}
    expected = hashlib.sha256(json.dumps(original_payload, sort_keys=True, separators=(',', ':'),
                                        ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    assert project.settings_hash == expected
    attempt = project.start_stage('inventory')
    project.complete_stage('inventory', attempt_id=attempt)
    project.set_settings('budget', {'new': 3})
    assert project.to_dict()['stages']['inventory']['attempts'][0]['settings_hash'] == expected


def test_explicit_scope_override_for_execution_block_is_preserved(project):
    approved_blocks(project)
    for stage in STAGES:
        finish(project, stage)
    project.set_settings('budget', {'value': 2}, affects_stage='georeference')
    assert project.to_dict()['stages']['navigation']['state'] == 'succeeded'
    assert project.to_dict()['stages']['georeference']['state'] == 'invalidated'
