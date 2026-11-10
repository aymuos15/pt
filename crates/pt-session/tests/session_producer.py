"""Test-owned synthetic producer. No real-pytest or qualification claim."""
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import time

mode, source = sys.argv[1:3]
os.set_inheritable(3, False)
channel = socket.socket(fileno=3)
with Path('started-once').open('x') as output:
    output.write('one execution effect\n')
if mode == 'cancel_zero':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
rows = json.loads(Path(source).read_bytes())
if mode in ('clean_wait', 'descendant'):
    child = subprocess.Popen([sys.executable, '-I', '-S', '-B', '-c', 'import time;time.sleep(30)'])
    Path('descendant.pid').write_text(str(child.pid))
if mode == 'args':
    Path('arguments.json').write_text(json.dumps([os.fsencode(value).hex() for value in sys.argv[3:]]))
    Path('environment').write_text(os.environ.get('PT_SESSION_TEST_INHERITED', 'absent'))
for row in rows:
    raw = json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    channel.sendall(struct.pack('!I', len(raw)) + raw)
Path('complete-looking.xml').write_text('<testsuite tests="1"><testcase name="looks_complete"/></testsuite>')
if mode in ('clean_wait', 'early_zero', 'close_wait', 'descendant', 'args', 'complete', 'exit_one', 'mismatch', 'exit_17'):
    channel.close()
    if mode == 'close_wait':
        time.sleep(0.2)
        Path('late-finalizer').write_text('after channel EOF, before process return')
    if mode == 'clean_wait':
        time.sleep(30)
    if mode in ('exit_one', 'mismatch'):
        sys.exit(1)
    if mode == 'exit_17':
        os._exit(17)
    sys.exit(0)
if mode == 'oversize':
    channel.sendall(b'\xff\xff\xff\xff')
elif mode == 'bad_json':
    channel.sendall(b'\x00\x00\x00\x03{!?')
elif mode in ('truncated_exit', 'signal_partial', 'timeout_partial'):
    channel.sendall(b'\x00\x00\x00\x64{"partial":')
    if mode == 'truncated_exit':
        os._exit(17)
    if mode == 'signal_partial':
        os.kill(os.getpid(), signal.SIGKILL)
elif mode == 'wait_no_reader':
    pass
elif mode == 'flood':
    for _ in range(10000):
        raw = json.dumps(rows[-1], separators=(',', ':')).encode()
        channel.sendall(struct.pack('!I', len(raw)) + raw)
time.sleep(30)
