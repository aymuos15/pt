"""Retain test-owned paired file/process cases and explicitly injected adverse controls."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest import mock


REPO = Path('/home/soumya/Downloads/pt')
HARNESS = REPO / 'bench/harness'
sys.path[:0] = [str(HARNESS), str(HARNESS / 'tests')]
import test_scenario_replay as controls
import paired_scenarios as pairs
import scenario_replay as scenario
import scenario_inputs as inputs
import pt_bench as timer


ROOT = Path(tempfile.mkdtemp(prefix='pt-paired-scenario-evidence-', dir='/tmp/opencode'))


def invoke(*arguments):
    return subprocess.run([sys.executable, *map(str, arguments)], cwd=REPO, capture_output=True, text=True, timeout=60)


def retain(directory, label, result):
    (directory / (label + '.stdout')).write_text(result.stdout)
    (directory / (label + '.stderr')).write_text(result.stderr)
    assert 'Traceback' not in result.stderr, (label, result.stderr)


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    return {'name': path.name, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def read(path):
    return json.loads(path.read_text())


def assert_counts(report, sessions=4):
    assert report['planned_session_count'] == sessions == sum(report['session_status_counts'].values())
    assert report['attempted_unit_calls'] + report['known_not_called_units'] == sessions
    assert report['observed_session_count'] + report['unconfirmed_unit_calls'] == report['attempted_unit_calls']
    for noun, count in (('request', 2), ('phase', 6), ('file_effect', 12)):
        assert report[f'planned_{noun}_count'] == sessions * count == sum(report[f'{noun}_status_counts'].values())
    assert sum(report[key] for key in ('known_request_invocations', 'unknown_request_invocations', 'known_not_invoked_requests')) == 2 * sessions
    assert sum(report[key] for key in ('known_shutdown_invocations', 'unknown_shutdown_invocations', 'known_not_invoked_shutdowns')) == sessions
    assert report['qualification'] == {key: None for key in scenario.QUALIFICATION}
    assert not report['confirmatory_eligible']
    assert all(report[key] is None for key in ('ratio', 'absolute_latency_ns', 'bootstrap', 'resource_observation'))


CASES = ['complete', 'failed-request', 'candidate-failure', 'expected-nonzero', 'failed-shutdown', 'deadline',
         'unsupported-environment', 'unsupported-watch', 'unsupported-os-cold', 'partial-reset', 'partial-edit',
         'inner-return-lost-after-commit', 'whole-return-lost-before', 'whole-return-lost-after-commit',
         'receipt-publication-unconfirmed', 'metadata-publication-unconfirmed', 'frozen-payload-identity-changed']
print('Test-owned real file/process controls, not PT conformance or benchmark:', ROOT, flush=True)
for name in CASES:
    directory = ROOT / name
    directory.mkdir()
    fixture = controls.ScenarioReplayTests('runTest')
    fixture.setUp()
    try:
        plans = {arm: copy.deepcopy(fixture.plan) for arm in pairs.ARMS}
        shutil.copytree(fixture.payloads, directory / 'inputs')
        for arm, plan in plans.items():
            shutil.copytree(fixture.cwd, directory / arm)
            plan['cwd'] = str(directory / arm)
    finally:
        fixture.doCleanups()
    output, payloads = directory / 'run', directory / 'inputs'
    if name in ('failed-request', 'candidate-failure', 'expected-nonzero'):
        arms = pairs.ARMS if name == 'expected-nonzero' else ('candidate',) if name == 'candidate-failure' else ('baseline',)
        for arm in arms:
            command = plans[arm]['requests'][0]['command']
            command['argv'][-1] = 'fail'
            if name == 'expected-nonzero':
                command['guard_expectations']['expected_exit_code'] = command['required_finalization']['expected_exit_code'] = 7
    elif name == 'failed-shutdown':
        plans['baseline']['shutdown']['argv'][-1] = 'unreleased'
    elif name == 'deadline':
        for plan in plans.values():
            plan['execution_timeout_seconds'] = 0.001
    elif name.startswith('unsupported-'):
        for plan in plans.values():
            plan['scenario']['id'] = {'unsupported-environment': 'S6', 'unsupported-watch': 'S7', 'unsupported-os-cold': 'S9'}[name]
    for arm, plan in plans.items():
        save(directory / (arm + '.json'), plan)

    def produce():
        return pairs.run_pairs(output, plans['baseline'], plans['candidate'], payloads, 2, 0, apply=True)

    injected = name in CASES[9:]
    if name in ('partial-reset', 'partial-edit'):
        original, calls = inputs.mutate, []

        def fault(root, observed, desired, bundle):
            result = original(root, observed, desired, bundle)
            calls.append(observed['path'])
            if observed['path'] == 'source.txt' and (name == 'partial-reset' or len(calls) > 4):
                raise OSError('explicit fixture-only file-effect return loss after installation')
            return result

        with mock.patch.object(inputs, 'mutate', side_effect=fault):
            report = produce()
    elif name == 'inner-return-lost-after-commit':
        original, calls = timer.measure_and_publish, []

        def fault(*args, **kwargs):
            receipt = original(*args, **kwargs)
            calls.append(1)
            if len(calls) == 1:
                raise OSError('explicit fixture-only inner command-return loss after commit')
            return receipt

        with mock.patch.object(timer, 'measure_and_publish', side_effect=fault):
            report = produce()
    elif name.startswith('whole-return-lost-'):
        original = scenario.run_scenario

        def fault(*args, **kwargs):
            if name.endswith('after-commit'):
                original(*args, **kwargs)
            raise OSError('explicit fixture-only whole-session API-return loss')

        with mock.patch.object(scenario, 'run_scenario', side_effect=fault) as invoked:
            report = produce()
            invoked.assert_called_once()
    elif name in ('receipt-publication-unconfirmed', 'metadata-publication-unconfirmed'):
        original = timer.write_record
        target = output / ('receipt-000001-baseline.json' if name.startswith('receipt-') else 'block-000001-baseline.json')

        def fault(path, value):
            original(path, value)
            if Path(path) == target:
                raise OSError('explicit fixture-only paired publication return loss after commit')

        with mock.patch.object(timer, 'write_record', side_effect=fault):
            report = produce()
    elif name == 'frozen-payload-identity-changed':
        original, calls = scenario.run_scenario, []

        def fault(*args, **kwargs):
            receipt = original(*args, **kwargs)
            calls.append(1)
            if len(calls) == 1:
                path = next((output / 'payloads').iterdir())
                raw = path.read_bytes()
                path.unlink()
                path.write_bytes(raw)
            return receipt

        with mock.patch.object(scenario, 'run_scenario', side_effect=fault):
            report = produce()
        assert len(calls) == 1
    else:
        result = invoke(HARNESS / 'paired_scenarios.py', '--baseline-plan', directory / 'baseline.json',
                        '--candidate-plan', directory / 'candidate.json', '--payloads', payloads,
                        '--output', output, '--blocks', '2', '--seed', '0', '--apply')
        retain(directory, 'generation', result)
        expected_exit = 3 if name.startswith('unsupported-') else 0 if name in ('complete', 'expected-nonzero') else 2
        assert result.returncode == expected_exit, (name, result.stderr)
        report = json.loads(result.stdout)
    if injected:
        save(directory / 'api-inspection.json', report)
    before = pairs._snapshot(output)
    inspected = invoke(HARNESS / 'inspect_run.py', output)
    summarized = invoke(HARNESS / 'summarize_run.py', output)
    retain(directory, 'inspection', inspected)
    retain(directory, 'summary', summarized)
    assert inspected.returncode == 0, (name, inspected.stderr)
    summary = json.loads(summarized.stdout)
    assert summarized.returncode == (0 if name in ('complete', 'expected-nonzero') else 1), (name, summarized.stderr)
    assert_counts(summary)
    repeated = invoke(HARNESS / 'summarize_run.py', output)
    assert repeated.stdout == summarized.stdout and repeated.returncode == summarized.returncode
    assert pairs._snapshot(output) == before
    if name.startswith('whole-return-lost-'):
        row = summary['session_observations'][0]
        assert row['reset_evidence'] is None and row['scenario_summary'] is None
        assert row['file_effect_status_counts'] == {'unknown_unobserved': 12}
        assert all(request['observed_input'] is None for request in row['request_observations'])
    save(directory / 'evidence-class.json', {'evidence_class': 'test-owned-real-file-and-process-controls',
                                           'faults': 'explicit-api-injection' if injected else None, 'qualification': 'not_established'})
    print(json.dumps({'case': name, 'generation': 'injected API' if injected else 'CLI', 'inspection_exit': 0,
                      'summary_exit': summarized.returncode, **{key: summary[key] for key in ('session_status_counts', 'request_status_counts',
                       'file_effect_status_counts', 'unknown_request_invocations', 'unconfirmed_unit_calls')},
                      'repeated_summary_identical': True, 'source_unchanged': True}, sort_keys=True), flush=True)


def rebind_unit(directory, unit):
    root = directory / 'run'
    nested = root / 'session-000001-baseline'
    unit['retained_inputs'] = scenario._inputs(nested)[0]
    receipt = read(root / 'receipt-000001-baseline.json')
    receipt['unit'] = save(nested / 'unit.json', unit)
    record = read(root / 'block-000001-baseline.json')
    record['receipt'] = save(root / 'receipt-000001-baseline.json', receipt)
    save(root / 'block-000001-baseline.json', record)


MALFORMED = ['omit-reset', 'omit-transition', 'omit-shutdown', 'omit-request-input', 'wrong-pre-input', 'operation-order',
             'early-clock', 'arm-relabel', 'call-overlap', 'missing-receipt', 'lost-diagnostic-changed', 'later-session-after-abort',
             'missing-abort', 'qualification-promotion', 'corrupt-frozen-payload', 'false-failure']
for name in MALFORMED:
    directory = ROOT / ('malformed-' + name)
    directory.mkdir()
    source = 'whole-return-lost-after-commit' if name == 'lost-diagnostic-changed' else 'failed-request' if name in ('later-session-after-abort', 'missing-abort') else 'complete'
    output = directory / 'run'
    shutil.copytree(ROOT / source / 'run', output)
    if name in ('omit-reset', 'omit-transition', 'omit-shutdown', 'omit-request-input', 'wrong-pre-input', 'operation-order', 'early-clock'):
        unit = read(output / 'session-000001-baseline/unit.json')
        if name.startswith('omit-') and name != 'omit-request-input':
            unit['phases'].pop({'omit-reset': 0, 'omit-transition': 1, 'omit-shutdown': 5}[name])
        elif name == 'omit-request-input':
            unit['phases'][2]['before']['files'].pop()
        elif name == 'wrong-pre-input':
            unit['phases'][2]['before']['files'][-1]['value'] = read(ROOT / 'complete/baseline.json')['reset'][-1]['value']
        elif name == 'operation-order':
            unit['phases'][1]['operations'].reverse()
        else:
            unit['phases'][2]['after']['clock'].update(monotonic_start_ns=0, monotonic_end_ns=0, elapsed_ns=0)
        rebind_unit(directory, unit)
    elif name in ('arm-relabel', 'call-overlap'):
        path = output / ('block-000001-baseline.json' if name == 'arm-relabel' else 'block-000001-candidate.json')
        record = read(path)
        if name == 'arm-relabel':
            record['context']['arm'] = 'candidate'
        else:
            record['call_clock']['monotonic_start_ns'] = read(output / 'block-000001-baseline.json')['call_clock']['monotonic_start_ns']
            record['call_clock']['elapsed_ns'] = record['call_clock']['monotonic_end_ns'] - record['call_clock']['monotonic_start_ns']
        save(path, record)
    elif name == 'missing-receipt':
        (output / 'receipt-000001-baseline.json').unlink()
    elif name == 'lost-diagnostic-changed':
        (output / 'session-000001-baseline/extra.json').write_text('{}')
    elif name == 'later-session-after-abort':
        shutil.copytree(output / 'session-000001-baseline', output / 'session-000001-candidate')
    elif name == 'missing-abort':
        (output / 'abort.json').unlink()
    elif name == 'qualification-promotion':
        path = output / 'receipt-000001-baseline.json'
        receipt = read(path)
        receipt['qualification']['reset_equivalence'] = True
        record = read(output / 'block-000001-baseline.json')
        record['receipt'] = save(path, receipt)
        save(output / 'block-000001-baseline.json', record)
    elif name == 'corrupt-frozen-payload':
        next((output / 'payloads').iterdir()).write_bytes(b'corrupt')
    elif name == 'false-failure':
        record = read(output / 'block-000002-baseline.json')
        save(output / 'abort.json', {'schema_version': 1, 'kind': 'paired_scenario_abort', 'mode': 'exploratory_unqualified',
                                    'context': record['context'], 'campaign_plan': record['campaign_plan'], 'reason': 'session_failed',
                                    'error': 'unjustified exclusion fixture', 'call_clock': None, 'diagnostic_receipt': None,
                                    'diagnostic_session': None, 'diagnostic_inputs': None})
    result = invoke(HARNESS / 'inspect_run.py', output)
    retain(directory, 'inspection', result)
    assert result.returncode == 2, (name, result.stdout, result.stderr)
    print(json.dumps({'malformed': name, 'inspection_exit': 2, 'rejection': result.stderr.strip()}, sort_keys=True), flush=True)

refused = ROOT / 'missing-apply'
refused.mkdir()
result = invoke(HARNESS / 'paired_scenarios.py', '--baseline-plan', ROOT / 'complete/baseline.json', '--candidate-plan', ROOT / 'complete/candidate.json',
                '--payloads', ROOT / 'complete/inputs', '--output', refused / 'run', '--blocks', '2', '--seed', '0')
retain(refused, 'generation', result)
assert result.returncode == 2 and not (refused / 'run').exists()
save(ROOT / 'index.json', {'cases': CASES, 'malformed': MALFORMED, 'qualification': 'not_established', 'reader_base': 'a7f76e8'})
print(json.dumps({'evidence_root': str(ROOT), 'cases': len(CASES), 'malformed_rejected': len(MALFORMED),
                  'missing_apply_exit': 2, 'output_created_without_apply': False}, sort_keys=True), flush=True)
