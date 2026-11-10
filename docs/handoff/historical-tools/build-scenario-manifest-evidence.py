"""Offline functional controls for manifest associations; never execute source campaigns."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml

REPO = Path('/home/soumya/Downloads/pt')
HARNESS = REPO / 'bench/harness'
sys.path.insert(0, str(HARNESS))
import scenario_manifest as bindings
import paired_scenarios as pairs

SOURCES = Path('/tmp/opencode/pt-paired-scenario-evidence-cl3bevoq')
ROOT = Path(tempfile.mkdtemp(prefix='pt-scenario-manifest-evidence-', dir='/tmp/opencode'))
TEMPLATE = yaml.safe_load((REPO / 'bench/benchmark-campaign.template.yaml').read_text())


def invoke(*arguments):
    return subprocess.run([sys.executable, str(HARNESS / 'scenario_manifest.py'), *map(str, arguments)],
                          cwd=REPO, capture_output=True, text=True, timeout=90)


def retain(directory, name, result):
    (directory / (name + '.stdout')).write_text(result.stdout)
    (directory / (name + '.stderr')).write_text(result.stderr)
    assert 'Traceback' not in result.stderr, (name, result.stderr)


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True))


def read(path):
    return json.loads(path.read_text())


def declaration(run):
    plan = read(run / 'schedule.json')
    data = copy.deepcopy(TEMPLATE)
    data['scenario']['id'] = plan['sessions']['baseline']['scenario']['id']
    data['experiment'].update(paired_blocks=len(plan['schedule']), random_seed=plan['seed'], sample_unit='complete_session_replay',
                              analysis_unit='independent_paired_session', timeout_seconds=plan['sessions']['baseline']['execution_timeout_seconds'])
    data['analysis']['resampling_unit'] = 'independent_paired_session'
    for arm in pairs.ARMS:
        data[arm]['cwd'] = plan['sessions'][arm]['cwd']
    return data


def freeze_fake_pins(data, plan):
    data.update(status='frozen', campaign_id='test-only-not-preregistered')
    for arm in pairs.ARMS:
        data[arm].update(revision='a' * 40, binary_sha256='a' * 64, environment_lock_sha256='a' * 64, interpreter_sha256='a' * 64,
                          reset_script_sha256='a' * 64, state_probe_sha256='a' * 64, argv=plan['sessions'][arm]['requests'][0]['command']['argv'])
    data['scenario'].update(repository='test-owned', source_revision='a' * 40, expected_inventory_sha256='a' * 64,
                            expected_outcome_artifact_sha256='a' * 64, output_profile='test', reset_policy_document_sha256='a' * 64)
    data['machine'].update(profile_sha256='a' * 64, memory_budget_bytes=1, memory_metric='test')
    data['experiment'].update(exclusion_policy_sha256='a' * 64, pilot_report_sha256='a' * 64)
    data['analysis'].update(practical_absolute_gain_seconds=0.1, analysis_code_sha256='a' * 64)


source_names = read(SOURCES / 'index.json')['cases']
extra_names = ['wrong-planned-count', 'wrong-scenario-id', 'matching-first-argv-only', 'original-declaration-conflict', 'fake-frozen-pins']
CASES = [(name, name) for name in source_names] + [(name, 'complete') for name in extra_names]
print('Offline test-owned evidence associations, not benchmarks or qualification:', ROOT, flush=True)
for name, source in CASES:
    directory = ROOT / name
    directory.mkdir()
    run = SOURCES / source / 'run'
    before = pairs._snapshot(run)
    plan = read(run / 'schedule.json')
    data = declaration(run)
    if name == 'wrong-planned-count':
        data['experiment']['paired_blocks'] = 1
    elif name == 'wrong-scenario-id':
        data['scenario']['id'] = 'S4'
    elif name == 'matching-first-argv-only':
        for arm in pairs.ARMS:
            data[arm]['argv'] = plan['sessions'][arm]['requests'][0]['command']['argv']
    elif name == 'original-declaration-conflict':
        data['scenario']['scope'] = 'affected'
    elif name == 'fake-frozen-pins':
        freeze_fake_pins(data, plan)
    manifest = directory / 'campaign.yaml'
    manifest.write_text(yaml.safe_dump(data))
    original_bytes = manifest.read_bytes()
    result = invoke('bind', '--manifest', manifest, '--run', run, '--output', directory / 'binding.json')
    retain(directory, 'generation', result)
    assert result.returncode in (0, 1), (name, result.stderr)
    value = read(directory / 'binding.json')
    expected_exit = int(value['declaration_consistency'] == 'conflicts_found')
    assert result.returncode == expected_exit
    assert value['manifest']['declaration'] == data and value['manifest']['sha256'] == hashlib.sha256(original_bytes).hexdigest()
    assert value['status'] == 'blocked' and not value['confirmatory_eligible']
    assert len(value['qualification']) == 14 and all(item is None for item in value['qualification'].values())
    assert all(item is None for item in value['statistics'].values())
    counts = value['denominators']
    assert counts['planned_session_count'] == 4 == sum(counts['session_status_counts'].values())
    assert len(value['session_observations']) == 4
    for noun, total in (('request', 8), ('phase', 24), ('file_effect', 48)):
        assert counts[f'planned_{noun}_count'] == total == sum(counts[f'{noun}_status_counts'].values())
    inspected = invoke('inspect', '--manifest', manifest, '--run', run, '--binding', directory / 'binding.json')
    retain(directory, 'inspection', inspected)
    assert inspected.returncode == 0, (name, inspected.stderr)
    repeated = bindings.generate_binding(manifest, run)
    assert repeated == value and manifest.read_bytes() == original_bytes and pairs._snapshot(run) == before
    if name == 'whole-return-lost-after-commit':
        assert value['session_observations'][0]['reset_evidence'] is None
        assert counts['file_effect_status_counts'] == {'not_run': 36, 'unknown_unobserved': 12}
    print(json.dumps({'case': name, 'bind_exit': result.returncode, 'inspect_exit': 0, 'declaration_consistency': value['declaration_consistency'],
                      'sessions': counts['session_status_counts'], 'unknown_requests': counts['unknown_request_invocations'],
                      'effects': counts['file_effect_status_counts'], 'null_qualifications': 14, 'subjects_rerun': False,
                      'repeat_identical': True, 'sources_unchanged': True}, sort_keys=True), flush=True)

FORGED = ['drop-session', 'reverse-sessions', 'duplicate-session', 'drop-request', 'drop-reset', 'shrink-denominator', 'invent-matched-check',
          'drop-check', 'drop-payload-inventory', 'change-manifest-pin', 'invent-frozen-readiness', 'change-runtime', 'change-reader-inventory',
          'qualify-reset', 'drop-qualification', 'promote-eligibility', 'latency-ratio', 'wrong-kind', 'recover-lost-reset', 'recover-lost-request',
          'hide-publication-uncertainty', 'hide-original-conflict']
for name in FORGED:
    directory = ROOT / ('forged-' + name)
    directory.mkdir()
    source = ('whole-return-lost-after-commit' if name in ('recover-lost-reset', 'recover-lost-request') else
              'receipt-publication-unconfirmed' if name == 'hide-publication-uncertainty' else
              'original-declaration-conflict' if name == 'hide-original-conflict' else 'complete')
    run = SOURCES / (source if source in source_names else 'complete') / 'run'
    manifest = ROOT / source / 'campaign.yaml'
    value = read(ROOT / source / 'binding.json')
    if name == 'drop-session':
        value['session_observations'].pop()
    elif name == 'reverse-sessions':
        value['session_observations'].reverse()
    elif name == 'duplicate-session':
        value['session_observations'][1] = copy.deepcopy(value['session_observations'][0])
    elif name == 'drop-request':
        value['session_observations'][0]['request_observations'].pop()
    elif name == 'drop-reset':
        value['session_observations'][0]['reset_evidence'] = None
    elif name == 'shrink-denominator':
        value['denominators']['planned_request_count'] -= 1
    elif name == 'invent-matched-check':
        value['declaration_checks'][0]['status'] = 'matched_declaration'
    elif name == 'drop-check':
        value['declaration_checks'].pop()
    elif name == 'drop-payload-inventory':
        value['evidence']['files'] = [item for item in value['evidence']['files'] if not item['path'].startswith('payloads/')]
    elif name == 'change-manifest-pin':
        value['manifest']['declaration']['candidate']['binary_sha256'] = 'a' * 64
    elif name == 'invent-frozen-readiness':
        value['manifest']['frozen_structure_error_paths'] = []
    elif name == 'change-runtime':
        value['generator']['runtime']['python_version'] = '0.0.0'
    elif name == 'change-reader-inventory':
        value['generator']['implementation']['files'].pop()
    elif name == 'qualify-reset':
        value['qualification']['reset_equivalence'] = True
    elif name == 'drop-qualification':
        value['qualification'].pop('manifest_preregistration')
    elif name == 'promote-eligibility':
        value['confirmatory_eligible'] = True
    elif name == 'latency-ratio':
        value['statistics']['ratio'] = 1.1
    elif name == 'wrong-kind':
        value['kind'] = 'paired_replay_exploratory_result_card'
    elif name == 'recover-lost-reset':
        complete = read(ROOT / 'complete/binding.json')
        value['session_observations'][0]['reset_evidence'] = complete['session_observations'][0]['reset_evidence']
    elif name == 'recover-lost-request':
        complete = read(ROOT / 'complete/binding.json')
        value['session_observations'][0]['request_observations'][0] = complete['session_observations'][0]['request_observations'][0]
    elif name == 'hide-publication-uncertainty':
        value['session_observations'][0]['receipt_record_committed'] = True
    elif name == 'hide-original-conflict':
        value['manifest']['declaration_conflicts'] = []
        value['declaration_consistency'] = 'checked_unqualified'
    value['reconstruction_sha256'] = bindings._reconstruction(value)
    path = directory / 'binding.json'
    save(path, value)
    result = invoke('inspect', '--manifest', manifest, '--run', run, '--binding', path)
    retain(directory, 'inspection', result)
    assert result.returncode == 2, (name, result.stdout, result.stderr)
    print(json.dumps({'forged': name, 'inspect_exit': 2, 'rejection': result.stderr.strip()}, sort_keys=True), flush=True)

MALFORMED = ['omit-reset', 'omit-shutdown', 'wrong-pre-input', 'corrupt-frozen-payload', 'later-session-after-abort', 'lost-diagnostic-changed']
for name in MALFORMED:
    directory = ROOT / ('malformed-source-' + name)
    directory.mkdir()
    manifest = ROOT / 'complete/campaign.yaml'
    run = SOURCES / ('malformed-' + name) / 'run'
    result = invoke('bind', '--manifest', manifest, '--run', run, '--output', directory / 'binding.json')
    retain(directory, 'generation', result)
    assert result.returncode == 2 and not (directory / 'binding.json').exists(), (name, result.stderr)
    print(json.dumps({'malformed_source': name, 'bind_exit': 2, 'report_published': False}, sort_keys=True), flush=True)

marker = ROOT / 'must-not-execute'
data = declaration(SOURCES / 'complete/run')
data['candidate']['argv'] = [sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).touch()']
path = ROOT / 'must-not-execute.yaml'
path.write_text(yaml.safe_dump(data))
result = invoke('bind', '--manifest', path, '--run', SOURCES / 'complete/run', '--output', ROOT / 'marker-binding.json')
retain(ROOT, 'executable-marker', result)
assert result.returncode == 1 and not marker.exists()
save(ROOT / 'index.json', {'sources': [name for name, _ in CASES], 'forged': FORGED, 'malformed_sources': MALFORMED,
                          'qualification': 'not_established', 'subjects_rerun': False, 'reader_base': 'c2ffd37'})
print(json.dumps({'root': str(ROOT), 'retained_associations': len(CASES), 'forged_rejected': len(FORGED), 'malformed_sources_rejected': len(MALFORMED),
                  'executable_marker_absent': True, 'subjects_rerun': False}, sort_keys=True), flush=True)
