"""Offline independent *shape* control, not a real-work or qualification oracle.

Loads only the two repository schema documents; imports no PT product/test code.
Coordinator-only diagnostic records are not a complete merged qualified trace.
"""
import importlib.metadata
import json
from pathlib import Path
import sys

import jsonschema
from referencing import Registry, Resource

if sys.version_info[:3] != (3, 12, 12) or importlib.metadata.version('jsonschema') != '4.25.1':
    raise RuntimeError('record controls pin CPython 3.12.12 and jsonschema 4.25.1')
schemas = [json.loads(Path(name).read_bytes()) for name in sys.argv[1:3]]
registry = Registry().with_resources([(value['$id'], Resource.from_contents(value)) for value in schemas])
event, result = [jsonschema.Draft202012Validator(value, registry=registry) for value in schemas]
source, output = map(Path, sys.argv[3:5])
if source.stat().st_size > 16 * 1024 * 1024:
    raise ValueError('explicit test record bound')
document = json.loads(source.read_bytes())
for record in document['coordinator_records']:
    event.validate(record)
result.validate(document['final_result'])
final = document['final_result']
native = document.get('native_process')
if native is not None:
    leader = native['leader_status']
    code = leader['code'] if leader and leader['kind'] == 'exited' else None
    signal = leader['signal'] if leader and leader['kind'] == 'signaled' else None
    if final['backend_exit_code'] != code or final['backend_signal'] != signal:
        raise ValueError('final record changed the retained raw process status')
    cause = native['termination']['kind']
    stop = cause if cause in ('timeout', 'interrupted') else 'none'
    if final['stop_cause'] != stop:
        raise ValueError('final record erased or invented a native stop cause')
    if stop == 'interrupted' and final['interruption_signal'] != native['termination']['signal']:
        raise ValueError('final record changed the actual cancellation signal')
    cleanup = {'not_launched': 'not_started', 'complete': 'complete', 'uncertain': 'uncertain'}[native['cleanup']['kind']]
    if final['cleanup']['status'] != cleanup:
        raise ValueError('final record changed native cleanup uncertainty')
if document['final_result']['current_full_success'] or document['final_result']['environment_verified']:
    raise ValueError('development controls may not certify those gates')
with output.open('x') as destination:
    json.dump({'mode': 'offline_record_shape_and_raw_process_projection', 'events': len(document['coordinator_records']),
               'raw_process_projection_checked': native is not None,
               'qualified': False, 'artifact_bytes_checked': False, 'generation_evidence_checked': False,
               'environment_evidence_checked': False}, destination, sort_keys=True)
