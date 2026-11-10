import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path.cwd() / "source"))
import payload


def test_parent_and_child():
    assert payload.parent(True) == "parent true"
    assert payload.parent(False) == "parent false"
    subprocess.run([sys.executable, "coverage_child.py"], check=True, timeout=15)
