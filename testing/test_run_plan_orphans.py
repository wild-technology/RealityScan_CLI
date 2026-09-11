"""The existing planner carries approved pair-local orphan settings end to end."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import merge_zones
from modules.run_charter import parse_charter
from modules.run_plan import Session, build_commands, build_plan, session_from_charter


POLICY = dict(horizontal_margin_m=0.5, vertical_margin_m=1.0,
              footprint_link_m=6.0, max_corridor_m=15.0, max_offered=20,
              vertical_datum='ellipsoidal_m', component_features=1)


def charter(tmp_path, science, signed=True, stages=None):
    data = dict(schema=1, campaign='TEST', dive='DIVE',
        locations=dict(results_root=str(tmp_path / 'project/proc/workflows/run'),
                       originals=[], nav=[], protected=[]),
        ownership=dict(rs_instance='TEST_OWNED', rs_cache_dir=str(tmp_path / 'project/proc/tmp/cache'),
                       user_instances=[]),
        pipeline=dict(stages=stages or ['merge'], answers={}), science=science,
        signed_off=dict(by='owner', date='2026-09-11') if signed else {})
    return parse_charter(data, tmp_path / 'charter.json')


@pytest.fixture
def policy(tmp_path):
    path = tmp_path / 'project/proc/policies/orphan policy.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(POLICY))
    return path


def value(argv, flag):
    return argv[argv.index(flag) + 1]


def test_approved_science_reaches_one_merge_command_with_content_pin(tmp_path, policy, monkeypatch):
    manifest = str(tmp_path / 'project/proc/selections/current/selection.json')
    monkeypatch.setenv('RS_SELECTION_MANIFEST', manifest)
    occlusion = str(tmp_path / 'project/proc/occlusion/approved.json')
    monkeypatch.setenv('RS_OCCLUSION_MANIFEST', occlusion)
    monkeypatch.setenv('RS_OCCLUSION_MANIFEST_SHA256', 'a' * 64)
    monkeypatch.setenv('RS_PROJECT_FILE', str(tmp_path / 'project/active.rovscan'))
    contract = charter(tmp_path, dict(orphan_policy=str(policy)))
    session = session_from_charter(contract)
    plan = build_plan(session, contract)
    assert not plan['warnings'] and len(plan['commands']) == 1
    command = plan['commands'][0]
    assert command['stage'] == 'Merge Components'
    assert Path(command['argv'][1]).name == 'merge_zones.py'
    assert value(command['argv'], '--orphan_policy') == str(policy)
    assert value(command['argv'], '--orphan_policy_sha256') == hashlib.sha256(policy.read_bytes()).hexdigest()
    assert value(command['argv'], '--merge_scope') == 'neighbour'
    assert command['env']['RS_SELECTION_MANIFEST'] == manifest
    assert command['env']['RS_OCCLUSION_MANIFEST'] == occlusion
    assert command['env']['RS_OCCLUSION_MANIFEST_SHA256'] == 'a' * 64
    assert command['env']['RS_PROJECT_FILE'].endswith('active.rovscan')
    assert command['required_env'] == ['RS_SELECTION_MANIFEST', 'RS_OCCLUSION_MANIFEST',
                                        'RS_OCCLUSION_MANIFEST_SHA256']
    assert '--orphan_selection_manifest' not in command['argv']


def test_controller_can_bind_authoritative_manifest_after_planning(tmp_path, policy, monkeypatch):
    monkeypatch.delenv('RS_SELECTION_MANIFEST', raising=False)
    contract = charter(tmp_path, dict(orphan_policy=str(policy)))
    plan = build_plan(session_from_charter(contract), contract)
    command = plan['commands'][0]
    assert '--orphan_policy' in command['argv']
    assert 'RS_SELECTION_MANIFEST' not in command['env']
    # This is the existing ProjectController late binding, not a second planner.
    command['env']['RS_SELECTION_MANIFEST'] = str(tmp_path / 'current-selection.json')
    assert '--orphan_selection_manifest' not in command['argv']


@pytest.mark.parametrize('science', [{}, {'orphan_policy': None}])
def test_absent_policy_leaves_legacy_lane_component_only(tmp_path, science):
    contract = charter(tmp_path, science)
    command = build_plan(session_from_charter(contract), contract)['commands'][0]
    assert '--orphan_policy' not in command['argv']
    assert 'required_env' not in command


def test_unapproved_or_revoked_policy_cannot_silently_downgrade(tmp_path, policy):
    contract = charter(tmp_path, dict(orphan_policy=str(policy)), signed=False)
    with pytest.raises(ValueError, match='approval'):
        build_plan(session_from_charter(contract), contract)
    contract = charter(tmp_path, dict(orphan_policy=str(policy)))
    session = session_from_charter(contract)
    contract.signed_off = {}
    with pytest.raises(ValueError, match='approval'):
        build_plan(session, contract)
    with pytest.raises(ValueError, match='approval'):
        build_commands(Session(results_root=str(tmp_path), enabled=['merge'], orphan_policy=str(policy)))


@pytest.mark.parametrize('supplied', ['', 'relative.json', POLICY, True])
def test_science_policy_must_be_materialized_absolute_path(tmp_path, supplied):
    with pytest.raises(ValueError, match='materialized JSON path'):
        session_from_charter(charter(tmp_path, dict(orphan_policy=supplied)))


@pytest.mark.parametrize('change', ['missing', 'malformed', 'negative', 'nan', 'missing_bound', 'unknown_key'])
def test_invalid_policy_refuses_plan_before_commands(tmp_path, policy, change):
    payload = dict(POLICY)
    if change == 'missing':
        policy.unlink()
    elif change == 'malformed':
        policy.write_text('{')
    else:
        if change == 'negative':
            payload['horizontal_margin_m'] = -1
        elif change == 'nan':
            payload['vertical_margin_m'] = float('nan')
        elif change == 'missing_bound':
            del payload['footprint_link_m']
        elif change == 'unknown_key':
            payload['enabled'] = True
        policy.write_text(json.dumps(payload))
    contract = charter(tmp_path, dict(orphan_policy=str(policy)))
    with pytest.raises((ValueError, FileNotFoundError)):
        build_plan(session_from_charter(contract), contract)


def test_policy_pin_detects_changed_bounds_at_runtime(tmp_path, policy):
    contract = charter(tmp_path, dict(orphan_policy=str(policy)))
    command = build_plan(session_from_charter(contract), contract)['commands'][0]
    expected = value(command['argv'], '--orphan_policy_sha256')
    parsed, actual = merge_zones.read_orphan_policy(policy, expected_sha256=expected)
    assert parsed == POLICY and actual == expected
    policy.write_text(json.dumps(dict(POLICY, horizontal_margin_m=2.0)))
    with pytest.raises(ValueError, match='changed since planning'):
        merge_zones.read_orphan_policy(policy, expected_sha256=expected)


def test_nonmerge_stages_do_not_read_policy_artifacts(tmp_path, policy):
    contract = charter(tmp_path, dict(orphan_policy=str(policy)), stages=['export'])
    policy.unlink()
    command = build_plan(session_from_charter(contract), contract)['commands'][0]
    assert '--orphan_policy' not in command['argv']


def test_shared_schema_has_no_unapproved_spatial_defaults():
    schema = merge_zones.ORPHAN_POLICY_SCHEMA
    assert set(schema['required']) == set(POLICY)
    assert schema['additionalProperties'] is False
    assert all('default' not in field for field in schema['properties'].values())
    assert schema['properties']['component_features']['enum'] == [0, 1, 2]
    assert 'cli_probe_evidence' not in schema['required']


@pytest.mark.parametrize('tampered', [False, True])
def test_real_merge_parser_accepts_planner_flags_and_checks_pin_before_writes(
        tmp_path, policy, monkeypatch, caplog, tampered):
    contract = charter(tmp_path, dict(orphan_policy=str(policy)))
    command = build_plan(session_from_charter(contract), contract)['commands'][0]
    class ParsedAndValidated(Exception):
        pass
    def first_settings_access(*args, **kwargs):
        raise ParsedAndValidated()
    monkeypatch.setattr(merge_zones, 'SettingsStore', lambda: SimpleNamespace(ask=first_settings_access))
    monkeypatch.setattr(merge_zones, 'assert_safe_merge_harvest', lambda *args: None)
    monkeypatch.setattr(merge_zones.sys, 'argv', command['argv'][1:])
    monkeypatch.setattr(merge_zones, 'RealityScanCLI', lambda *a, **k: pytest.fail('live workflow reached'))
    if tampered:
        policy.write_text(json.dumps(dict(POLICY, max_offered=21)))
        assert merge_zones.main() == 1
        assert 'changed since planning' in caplog.text
    else:
        with pytest.raises(ParsedAndValidated):
            merge_zones.main()
    assert not (tmp_path / 'project/proc/workflows').exists()
