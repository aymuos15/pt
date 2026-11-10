"""Development package identity only; no automatic pytest plugin or test runner.

The explicit observational hook module and private framing primitives are
separately available in ``pt_bridge.pytest_observer`` and ``pt_bridge._wire``;
they are not imported automatically and cannot certify a full run result.
Importing this module neither imports pytest nor collects or executes a project.
"""

__version__ = "0.0.0"
PROTOCOL_VERSION = 0
