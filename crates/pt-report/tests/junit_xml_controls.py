"""Independent stdlib XML adversaries for one literal pinned pass projection.

No product/runtime module is imported. All controls are explicitly synthetic.
"""
import datetime
import itertools
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

if sys.version_info[:3] != (3, 12, 12):
    raise RuntimeError("XML controls pin CPython 3.12.12")
declaration = '<?xml version="1.0" encoding="utf-8"?>'
case = '<testcase classname="test_x" name="test_first" time="0.000" />'
suite = '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="1" time="0.001" timestamp="2026-11-10T12:34:56.123456+00:00" hostname="test-host">'
valid = declaration + '<testsuites name="pytest tests">' + suite + case + '</testsuite></testsuites>'
space = ' \t\r\n'
duration = re.compile(r'(?:0|[1-9][0-9]*)\.[0-9]{3}\Z')


def accepted(raw):
    if not raw.startswith(declaration) or '<!' in raw or raw.count('<?') != 1:
        return False
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError):
        return False
    if root.tag != 'testsuites' or root.attrib != {'name': 'pytest tests'} or len(root) != 1:
        return False
    suite = root[0]
    fixed = {'name': 'pytest', 'errors': '0', 'failures': '0', 'skipped': '0', 'tests': '1'}
    if suite.tag != 'testsuite' or set(suite.attrib) != {*fixed, 'time', 'timestamp', 'hostname'} or len(suite) != 1:
        return False
    if any(suite.get(key) != value for key, value in fixed.items()):
        return False
    item = suite[0]
    if item.tag != 'testcase' or set(item.attrib) != {'classname', 'name', 'time'} or len(item):
        return False
    if item.get('classname') != 'test_x' or item.get('name') != 'test_first':
        return False
    if not all(duration.fullmatch(element.get('time', '')) for element in (suite, item)):
        return False
    timestamp = suite.get('timestamp', '')
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?[+-][0-9]{2}:[0-9]{2}', timestamp):
        return False
    try:
        datetime.datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    return all(not (element.text or '').strip(space) and not (element.tail or '').strip(space)
               for element in (root, suite, item))


cases = []
seen = set()


def add(label, raw):
    if raw not in seen:
        seen.add(raw)
        cases.append({'label': label, 'raw': raw, 'accepted': accepted(raw)})


add('literal pass', valid)
for index in range(len(valid)):
    add(f'character deletion {index}', valid[:index] + valid[index+1:])
    for replacement in ('<', '>', '&', '"', '/', '\x01'):
        add(f'character replacement {index} {ord(replacement)}', valid[:index] + replacement + valid[index+1:])
for attributes in itertools.permutations(('classname="test_x"', 'name="test_first"', 'time="0.000"')):
    for separator in (' ', '  ', '\t', ''):
        add('attribute order and separation', valid.replace(case, '<testcase ' + separator.join(attributes) + ' />'))
for reference in ('&amp;', '&#32;', '&#x20;', '&unknown;', '&amp', '&#1;', '&#0;', '&#xFFFF;', '&#xD800;'):
    add('attribute reference', valid.replace('test-host', reference))
for extra in ('<!--comment-->', '<![CDATA[text]]>', '<properties />', '<system-out>text</system-out>', '<x />'):
    add('extra data', valid.replace(case, case + extra))
for count in ('0', '01', '+1', '-1', '1e0', 'true', str(2**64), '1.0'):
    add('counter lexical form', valid.replace('tests="1"', f'tests="{count}"'))
for value in ('1.000', '0.000', 'NaN', 'inf', '-0.000', '1e0', '0.00', '00.000'):
    add('duration lexical form', valid.replace('time="0.001"', f'time="{value}"'))
add('explicit paired testcase', valid.replace(case, case.replace(' />', '></testcase>')))
add('entity matching identity', valid.replace('name="test_first"', 'name="test_&#102;irst"'))
add('trailing XML whitespace', valid + '\n\t ')
output = {'mode': 'independent_literal_junit_xml_mutations', 'qualified': False, 'cases': cases}
raw = json.dumps(output, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
if len(raw) > 8*1024*1024:
    raise RuntimeError('XML adversaries exceed their explicit retained bound')
with Path(sys.argv[1]).open('xb') as destination:
    destination.write(raw)
