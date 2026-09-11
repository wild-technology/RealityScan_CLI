"""Automatic post-alignment native orphan proof, without a second RS executor.

Controller contract: hold the project operation lease; install RS_SELECTION_MANIFEST,
RS_OCCLUSION_MANIFEST, RS_OCCLUSION_MANIFEST_SHA256 and RS_PROJECT_FILE; pass the
complete current aligned export root (never a selected pair/subdirectory).
assert_approved must raise unless current merge/operating settings are approved
and the alignment stage is verified complete. It is called again before writes,
native stages and publication. Call on the controller worker, not the GUI thread.

Successful return is the published evidence Path consumed by cli_probe_evidence.
InterruptedError means cancellation. EvidenceBlocked carries a structured reason
and a durable diagnostic path, when an attempt was prepared. No incomplete proof
is published. This module does not claim the native feature macro works live.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from uuid import uuid4

from module_base.atomic_io import replace_file
import merge_zones as merge
from modules import orphan_import_probe as probe

VERSION = 'automatic-orphan-evidence-1'


class EvidenceBlocked(ValueError):
    def __init__(self, reason, *, report=None, details=None):
        self.reason = reason
        self.report = str(report) if report is not None else None
        self.details = details
        super().__init__(reason + (': ' + str(details) if details else ''))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _write(path, value):
    probe.checkpoint()
    path.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


def select_probe_pair(census, context, *, max_original_cameras):
    """Stable smallest qualifying pair; every exclusion retains its identity/reason."""
    global_orphans = set(context['images']) - set(census['registered'])
    pairs = sorted(itertools.combinations(range(len(census['components'])), 2),
                   key=lambda ij: (sum(len(census['members'][i]) for i in ij),
                                   tuple(census['paths'][i] for i in ij)))
    rejected = []
    any_offered = False
    unknown_geometry = False
    for indexes in pairs:
        probe.checkpoint()
        paths = [census['paths'][i] for i in indexes]
        members = [census['members'][i] for i in indexes]
        reason = None
        spatial = None
        controls = None
        rejected_controls = {}
        if any(len(m) < 3 for m in members):
            reason = 'insufficient_measured_component_membership'
            unknown_geometry = True
        else:
            try:
                spatial = merge.select_pair_orphans(members, context['navigation'], global_orphans,
                                                     epsg=context['epsg'], policy=context['policy'])
            except ValueError as exc:
                reason = 'component_geometry_unavailable: ' + str(exc)
                unknown_geometry = True
            if spatial is not None:
                any_offered |= bool(spatial['offered_ids'])
                controls, rejected_controls = probe.choose_controls(spatial, context)
            if reason is not None:
                pass
            elif not spatial['offered_ids']:
                reason = 'no_pair_local_orphans'
            elif sum(map(len, members)) > max_original_cameras:
                reason = 'approved_original_camera_budget_exceeded'
            elif any(census['input_paths'][indexes[0]][name] != census['input_paths'][indexes[1]][name]
                     for name in set(members[0]) & set(members[1])):
                reason = 'conflicting_component_image_paths'
            elif spatial.get('refusal'):
                reason = spatial['refusal']
            elif context['policy']['max_offered'] < 2:
                reason = 'insufficient_offered_cap'
            elif controls[0] is None:
                reason = 'missing_inside_control'
            elif controls[1] is None:
                reason = 'missing_corridor_control'
            elif controls[2] is None:
                reason = 'missing_remote_control'
        entry = {'components': paths, 'reason': reason,
                 'controls': controls, 'rejected_controls': rejected_controls,
                 'spatial_reasons': spatial['spatial_reasons'] if spatial else {}}
        if reason is None:
            return paths, dict(selected=entry, rejected_pairs=rejected,
                               any_offered=True, unknown_geometry=unknown_geometry,
                               global_orphans=sorted(global_orphans),
                               globally_registered=census['registered'])
        rejected.append(entry)
    return None, dict(selected=None, rejected_pairs=rejected,
                      any_offered=any_offered, unknown_geometry=unknown_geometry,
                      global_orphans=sorted(global_orphans), globally_registered=census['registered'])


def ensure_orphan_import_evidence(*, project_root, components_root, selection_manifest,
                                  policy_path, policy_sha256, install_dir, instance, reserve_gib,
                                  max_original_cameras, assert_approved, record_executor=None,
                                  environment=None, cache_dir=None, cancelled=None, control=None, progress=None) -> Path | None:
    """Replay or automatically record/publish proof. See module controller contract.

    Callbacks: cancelled() -> bool; progress(dict) -> None; assert_approved() -> None
    (raises on stale/revoked approval or unfinished alignment). All are required to
    be thread-safe. record_executor({path, sha256}) -> integer exit code must
    persist a merge-stage execution plan and use execute_commands with the
    controller's ExecutionControl. Its child must receive the standard parent
    runtime channels plus RS_ORPHAN_EVIDENCE_CHILD=1. Never suppress its
    OwnershipUnconfirmed exception. A passed import-only proof returns Path;
    no global/pair-local offered orphans returns None with an audited reason.
    """
    if not callable(assert_approved):
        raise ValueError('A current controller approval/alignment validator is required')
    if type(max_original_cameras) is not int or max_original_cameras < 1:
        raise ValueError('Original-camera budget must be a positive integer')

    def ready():
        probe.checkpoint()
        assert_approved()
        merge.read_orphan_policy(policy_path, expected_sha256=policy_sha256)

    def report(event):
        ready()
        if progress is not None:
            progress(event)

    with probe.execution_context(cancelled=cancelled, progress=report, control=control, environment=environment):
        ready()
        root = probe.safe(project_root)
        policy, _ = merge.read_orphan_policy(policy_path, expected_sha256=policy_sha256)
        # Validate schema and current approval even when cached evidence exists.
        census = probe.component_census(root, components_root)
        context = merge.load_orphan_context(selection_manifest, policy_path, census['components'],
                                            recording_probe=True, cancelled=cancelled, env=environment)
        if probe.safe(context['project_root']) != root:
            raise EvidenceBlocked('selection_project_mismatch')
        fingerprint = _digest(dict(version=VERSION, census=census,
            max_original_cameras=max_original_cameras, cache_dir=str(cache_dir) if cache_dir else None,
            environment={k: environment[k] for k in ('RS_PROJECT_FILE', 'RS_SELECTION_MANIFEST',
                'RS_OCCLUSION_MANIFEST', 'RS_OCCLUSION_MANIFEST_SHA256', 'RS_CAMERA_PRIORS_FILE')
                if environment is not None and k in environment},
            policy_sha256=policy_sha256, selection=probe.bound(selection_manifest),
            occlusion=context.get('occlusion'), executable=probe.bound(Path(install_dir) / 'RealityScan.exe'),
            helper=probe.bound(__file__), recorder=probe.bound(probe.__file__)))
        target = root / 'metadata/validation/orphan_import.json'
        if not target.resolve().is_relative_to(root):
            raise EvidenceBlocked('redirected_evidence_target')
        if target.is_file():
            try:
                cached = json.loads(target.read_text(encoding='utf-8'))
                if cached.get('automatic_fingerprint') == fingerprint:
                    record = cached['recording_manifest']
                    verdict = probe.verify(record['path'], record['sha256'], policy=policy, epsg=context['epsg'])
                    if verdict.get('status') == 'passed':
                        ready()
                        report({'phase': 'reused', 'evidence_path': str(target)})
                        return target
            except InterruptedError:
                raise
            except (OSError, ValueError, KeyError, TypeError) as exc:
                report({'phase': 'stale_evidence', 'reason': str(exc)})

        if set(context['images']) <= set(census['registered']):
            pair, audit = None, dict(selected=None, rejected_pairs=[], any_offered=False,
                                    unknown_geometry=False, reason='no_global_orphans',
                                    globally_registered=census['registered'], global_orphans=[])
        else:
            pair, audit = select_probe_pair(census, context, max_original_cameras=max_original_cameras)
        ready()
        name = 'auto_' + fingerprint[:16] + '_' + uuid4().hex
        attempt = root / 'proc/validation/orphan_import' / name
        if not attempt.resolve().is_relative_to(root / 'proc/validation/orphan_import'):
            raise EvidenceBlocked('redirected_attempt_directory')
        if pair is None:
            audit_path = attempt / 'selection.json'
            if not audit['any_offered'] and not audit['unknown_geometry']:
                audit.update(status='not_required', reason=audit.get('reason', 'no_pair_local_orphans'))
                _write(audit_path, audit)
                report({'phase': 'not_required', 'reason': audit['reason'], 'report': str(audit_path)})
                return None
            _write(audit_path, audit)
            raise EvidenceBlocked('no_qualifying_pair', report=audit_path, details=audit['rejected_pairs'])
        if not callable(record_executor):
            raise EvidenceBlocked('canonical_executor_callback_required')
        report({'phase': 'preparing', 'components': pair, 'root': str(attempt)})
        plan = probe.build_plan(str(root), str(selection_manifest), str(policy_path), pair,
                                str(install_dir), instance, name, reserve_gib,
                                components_root=components_root, max_original_cameras=max_original_cameras,
                                import_only=True, cache_dir=cache_dir)
        if plan['census'] != census:
            raise EvidenceBlocked('alignment_changed_during_selection')
        # Bind the automatic selector implementation and exact audited choice.
        plan['dependencies'].append(probe.bound(__file__))
        plan['pair_selection'] = audit
        ready()
        manifest = probe.prepare(plan)
        _write(attempt / 'selection.json', audit)
        report({'phase': 'recording', 'root': str(attempt)})
        # The controller binds its command to the real project attempt, persists
        # metadata/plans, and calls execute_commands. OwnershipUnconfirmed must
        # escape unchanged; this helper never treats an unconfirmed child as done.
        code = record_executor(manifest)
        ready()
        if code == 130:
            raise InterruptedError('Native orphan proof cancelled')
        try:
            result = probe.verify(manifest['path'], manifest['sha256'], policy=policy, epsg=context['epsg'])
        except InterruptedError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise EvidenceBlocked('native_proof_unverifiable', report=attempt,
                                  details={'exit_code': code, 'reason': str(exc)}) from exc
        if result.get('status') != 'passed':
            _write(attempt / 'automatic_result.json', result)
            reason = 'native_proof_incomplete' if result.get('status') == 'incomplete' else 'native_proof_verification_failed'
            raise EvidenceBlocked(reason, report=attempt / 'automatic_result.json', details=result)
        if type(code) is not int or code != 0:
            raise EvidenceBlocked('native_probe_execution_failed', report=attempt, details={'exit_code': code})
        # Never trust record's return or a cached pass: replay before publication.
        verdict = probe.verify(manifest['path'], manifest['sha256'], policy=policy, epsg=context['epsg'])
        if verdict.get('status') != 'passed':
            raise EvidenceBlocked('native_proof_verification_failed', report=attempt, details=verdict)
        ready()
        evidence = dict(schema=3, recording_manifest=manifest, automatic_fingerprint=fingerprint)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name('orphan_import.' + uuid4().hex + '.tmp')
        try:
            _write(temporary, evidence)
            # Validate exactly the serialized pointer the merge consumer will read.
            merge.validate_orphan_probe_evidence(temporary, root, policy=policy, epsg=context['epsg'])
            ready()
            replace_file(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        if progress is not None:
            progress({'phase': 'published', 'evidence_path': str(target), 'limits': verdict.get('limits', [])})
        return target
