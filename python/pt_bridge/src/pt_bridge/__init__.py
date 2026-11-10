"""Development package identity only; no automatic pytest plugin or test runner.

The observational backend/session protocol are not implemented by this skeleton.
Private framing primitives are separately available in ``pt_bridge._wire``;
they are not imported automatically and do not validate complete pytest work.
Importing this module neither imports pytest nor collects or executes a project.
"""

__version__ = "0.0.0"
PROTOCOL_VERSION = 0
