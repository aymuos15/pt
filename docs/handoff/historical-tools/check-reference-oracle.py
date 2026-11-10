import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

repo = Path('/home/soumya/Downloads/pt')
sys.path.insert(0, str(repo / 'tests/conformance'))
from trace_oracle import read_trace, compare_traces

profile = repo / 'bench/corpus/serial_core'
data = json.loads((profile / 'corpus.json').read_text())
root = Path(tempfile.mkdtemp(prefix='pt-reference-oracle-check-', dir='/tmp/opencode'))
print('Instrumented reference evidence:', root, flush=True)
checks = []
for index in (1, 2):
    python = Path('/tmp/opencode/pt-serial-core-materialize-dptvq6o5/run') / f'environment-{index}/bin/python'
    for case in data['cases']:
        name = case['id']
        cwd = root / f'work-{index}' / name
        shutil.copytree(profile / 'fixtures' / name, cwd)
        trace = root / f'trace-{index}-{name}.jsonl'
        events = root / f'events-{index}-{name}.txt'
        environment = {'PATH': os.defpath, 'HOME': str(root), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                       'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                       'PYTHONPATH': str(repo / 'tests/conformance'), 'PT_CORE_EVENTS': str(events)}
        command = [str(python), '-m', 'pytest', '-q', '-p', 'pt_reference_observer', '--pt-reference-trace=' + str(trace), *case['argv']]
        result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, timeout=30)
        (root / f'{index}-{name}.stdout').write_text(result.stdout)
        (root / f'{index}-{name}.stderr').write_text(result.stderr)
        assert result.returncode == case['expected_exit_code'], (index, name, result.returncode, result.stdout, result.stderr)
        checked = read_trace(trace, result.returncode)
        assert len(checked['normalized']['selected']) == (0 if name == 'collection_error' else len(case['junit'])), name
        effects = events.read_text().splitlines() if events.exists() else None
        assert effects == case['expected_events'], (name, effects)
        checks.append({'environment': index, 'case': name, 'exit': result.returncode,
                       'selected': len(checked['normalized']['selected']), 'phases': len(checked['normalized']['phases']),
                       'trace_sha256': checked['trace_sha256']})
        if index == 2:
            baseline_events = root / f'events-1-{name}.txt'
            report = compare_traces(root / f'trace-1-{name}.jsonl', trace, baseline_exit=case['expected_exit_code'],
                                    candidate_exit=case['expected_exit_code'],
                                    baseline_effects=baseline_events.read_text().splitlines() if baseline_events.exists() else None,
                                    candidate_effects=effects)
            assert report['status'] == 'matched_instrumented_trace_contract', (name, report)
            print(json.dumps({'case': name, 'comparison': report['status'], 'selected_occurrences': len(checked['normalized']['selected']),
                              'phase_reports': len(checked['normalized']['phases']), 'expected_exit': case['expected_exit_code'],
                              'backend_qualified': False}, sort_keys=True), flush=True)
(root / 'index.json').write_text(json.dumps({'observations': checks, 'qualification': 'not_established',
                                            'profile': 'instrumented_same-session_reference_core'}, indent=2))
print(json.dumps({'root': str(root), 'fresh_pytest_requests': 20, 'comparisons': 10, 'backend_qualified': False}, sort_keys=True), flush=True)
