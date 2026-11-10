"""Development-only four-reference Flask phase check; no product timing/qualification."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile


REPO = Path('/home/soumya/Downloads/pt')
MATERIALIZATION = Path('/tmp/opencode/pt-flask-offline-49943b5-wuvrrvht/run')
sys.path.insert(0, str(REPO / 'tests/conformance'))
from trace_oracle import read_trace, compare_traces

spec = importlib.util.spec_from_file_location('flask_phase_process_tools', REPO / 'bench/corpus/serial_core/materialize.py')
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)
original = json.loads((MATERIALIZATION / 'result.json').read_text())
assert original['status'] == 'reproduced_pytest_only_observations_unqualified'
assert original['revision'] == '49943b5a94413a530761350f04e896f76e8d620e'
root = Path(tempfile.mkdtemp(prefix='pt-flask-phase-reference-', dir='/tmp/opencode'))
print('Planned four fresh Flask phase references:', root, flush=True)
for name in ('home', 'tmp', 'observer'):
    (root / name).mkdir(mode=0o700)
observer = (REPO / 'tests/conformance/pt_reference_observer.py').read_bytes()
tools._freeze(root / 'observer', {'pt_reference_observer.py': observer})
reader = (REPO / 'tests/conformance/trace_oracle.py').read_bytes()
tools._freeze(root / 'observer', {'trace_oracle.py': reader})
env = {'PATH': os.defpath, 'HOME': str(root / 'home'), 'TMPDIR': str(root / 'tmp'), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
       'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(root / 'observer')}
rows = [{'environment': index, 'repeat': repeat, 'status': 'not_run_prior_failure', 'observation': None}
        for index in (1, 2) for repeat in (1, 2)]
report = {'status': 'aborted', 'planned_references': rows, 'comparisons': [], 'errors': [], 'confirmatory_eligible': False,
          'source_archive_sha256': hashlib.sha256((MATERIALIZATION / 'source.tar').read_bytes()).hexdigest(),
          'observer_sha256': hashlib.sha256(observer).hexdigest(), 'reader_sha256': hashlib.sha256(reader).hexdigest(),
          'profile': 'serial-repository-v1',
          'limitations': ['real-pytest reference only, not a candidate/backend or body-effect proof',
                          'same literal cwd is reset by archiving the owned work copy and creating a fresh copy, never by replay/fallback',
                          'captured output, warning reasons and application paths are not stripped to force a match',
                          'installed-file observations do not establish full environment or immutable-generation assurance'],
          'qualification': {key: None for key in ('semantic_support', 'body_effects', 'environment', 'generation', 'pt_backend', 'release')}}
try:
    assert report['source_archive_sha256'] == original['source_archive_sha256']
    for index in (1, 2):
        site = MATERIALIZATION / f'environment-{index}/lib/python3.12/site-packages'
        installed = tools.tree(site)
        assert installed == original['runtime_environments'][index - 1]['after']
        python = MATERIALIZATION / f'environment-{index}/bin/python'
        for repeat in (1, 2):
            row = next(value for value in rows if value['environment'] == index and value['repeat'] == repeat)
            work = root / 'work'
            work.mkdir(mode=0o700)
            with tarfile.open(MATERIALIZATION / 'source.tar') as archive:
                archive.extractall(work, filter='data')
            inputs = tools.tree(work)
            trace = root / f'trace-{index}-{repeat}.jsonl'
            row['status'] = 'unknown_execution_return'
            argv = [str(python), '-m', 'pytest', '-q', '-p', 'pt_reference_observer',
                    '--pt-reference-profile=serial-repository-v1', '--pt-reference-trace=' + str(trace),
                    '--junitxml=pt-junit.xml', '--basetemp=pt-tmp']
            observation, raw = tools._command(root, f'pytest-{index}-{repeat}', argv, work,
                                             {**env, 'PATH': str(python.parent) + os.pathsep + os.defpath})
            row.update(status='returned_unqualified', observation=observation)
            checked = read_trace(trace, observation['returncode'])
            row.update(trace_sha256=checked['trace_sha256'], selected=len(checked['normalized']['selected']),
                       completed=len(checked['normalized']['completed']), phases=len(checked['normalized']['phases']))
            assert observation['returncode'] == 0 and row['selected'] == row['completed'] == 494 and row['phases'] == 1482
            assert all(tools._read(work / entry['path'])[0]['sha256'] == entry['sha256'] for entry in inputs)
            assert tools.tree(site) == installed
            row['status'] = 'matched_expected_reference_accounting_unqualified'
            work.rename(root / f'retained-work-{index}-{repeat}')
        comparison = compare_traces(root / f'trace-{index}-1.jsonl', root / f'trace-{index}-2.jsonl', baseline_exit=0, candidate_exit=0)
        comparison['environment'] = index
        comparison['stability'] = 'baseline_uncertain' if comparison['status'] == 'mismatch' else 'matched_repeated_reference_contract'
        report['comparisons'].append(comparison)
        print(json.dumps({'environment': index, 'selected_each': 494, 'phase_reports_each': 1482,
                          'reference_stability': comparison['stability'], 'differences': comparison['differences']}, sort_keys=True), flush=True)
    assert (REPO / 'tests/conformance/pt_reference_observer.py').read_bytes() == observer
    assert (REPO / 'tests/conformance/trace_oracle.py').read_bytes() == reader
    report['status'] = 'baseline_uncertain' if any(value['status'] == 'mismatch' for value in report['comparisons']) else 'matched_four_instrumented_references_unqualified'
except (OSError, ValueError, RuntimeError, AssertionError, KeyboardInterrupt) as exc:
    report['errors'].append({'type': type(exc).__name__, 'error': str(exc)})
tools._save(root / 'result.json', report)
print(json.dumps({'root': str(root), 'status': report['status'], 'errors': report['errors'],
                  'rows': [{key: value[key] for key in ('environment', 'repeat', 'status')} for value in rows],
                  'qualification': report['qualification']}, sort_keys=True), flush=True)
raise SystemExit(int(report['status'] == 'aborted'))
