"""Test-only pinned-image ELF projection via independent GNU readelf/struct.

Never executes/imports the target image or PT code; no loader/library resolution
or environment/startup/provenance qualification is supplied by this control.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys


target, expected, output = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
if sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 12, 12) or sys.platform != "linux":
    raise ValueError("positive metadata controls pin Linux CPython 3.12.12")
fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
with os.fdopen(fd, "rb") as stream:
    before = os.fstat(stream.fileno())
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 64 <= before.st_size <= 128*1024*1024:
        raise ValueError("bounded regular declared ELF input required")
    raw = stream.read(128*1024*1024+1)
    after = os.fstat(stream.fileno())
named = target.stat(follow_symlinks=False)
stamp = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
if stamp(before) != stamp(after) or stamp(before) != stamp(named) or len(raw) != before.st_size or hashlib.sha256(raw).hexdigest() != expected:
    raise ValueError("declared ELF bytes/binding changed or differ from the prior archive pin")
if raw[:9] != b"\x7fELF\x02\x01\x01\x00\x00":
    raise ValueError("this positive control pins the exact observed ELF64LE SysV image")
phoff = struct.unpack_from("<Q", raw, 32)[0]
entsize, count = struct.unpack_from("<HH", raw, 54)
if entsize != 56 or not 1 <= count <= 128 or phoff + count*entsize > len(raw):
    raise ValueError("independent ELF program-header bound")
headers = [struct.unpack_from("<IIQQQQQQ", raw, phoff+index*entsize) for index in range(count)]
dynamic = [row for row in headers if row[0] == 2]
if len(dynamic) != 1 or dynamic[0][5] % 16 or not 16 <= dynamic[0][5] <= 65536:
    raise ValueError("pinned positive dynamic segment required")
offset, size = dynamic[0][2], dynamic[0][5]
if offset + size > len(raw):
    raise ValueError("independent ELF dynamic range")
tags = [struct.unpack_from("<QQ", raw, offset+index) for index in range(0, size, 16)]
used = next(index+1 for index, (tag, _) in enumerate(tags) if tag == 0)
if any(tag or value for tag, value in tags[used:]):
    raise ValueError("the selected image's declared dynamic padding changed")
argv = ["/usr/bin/readelf", "--wide", "--file-header", "--program-headers", "--dynamic", str(target)]
stdout, stderr = output.with_suffix(".readelf.stdout"), output.with_suffix(".readelf.stderr")
with stdout.open("xb") as out, stderr.open("xb") as err:
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=5,
                            env={**os.environ, "LC_ALL": "C"})
if result.returncode or stdout.stat().st_size > 1024*1024 or stderr.stat().st_size > 1024*1024:
    raise ValueError("independent readelf failed or exceeded the positive control's output bound")
text = stdout.read_text(encoding="utf-8", errors="strict")
interpreters = re.findall(r"Requesting program interpreter: ([^\]]+)\]", text)
needed = re.findall(r"\(NEEDED\)[^\n]*Shared library: \[([^\]]*)\]", text)
search = re.findall(r"\((RPATH|RUNPATH)\)[^\n]*Library (?:rpath|runpath): \[([^\]]*)\]", text)
if len(interpreters) != 1 or len(needed) != 6 or search != [("RPATH", "$ORIGIN/../lib")]:
    raise ValueError("the selected positive image's independent loader/library projection changed")
report = {"mode": "readelf_and_struct_positive_metadata_control", "image_sha256": expected,
          "image_bytes": len(raw), "interpreter": interpreters[0], "needed": needed, "search": search,
          "program_headers": headers, "dynamic_entries": tags, "used_dynamic_entries": used,
          "object_type": struct.unpack_from("<H", raw, 16)[0], "os_abi": raw[7],
          "entry_point": struct.unpack_from("<Q", raw, 24)[0], "readelf_argv": argv,
          "readelf_returncode": result.returncode, "readelf_locale": "C", "readelf_sha256": hashlib.sha256(Path(argv[0]).read_bytes()).hexdigest(),
          "target_executed": False, "dependency_resolution_verified": False, "environment_verified": False, "qualified": False}
with output.open("x") as stream:
    json.dump(report, stream, sort_keys=True, indent=2)
    stream.write("\n")
