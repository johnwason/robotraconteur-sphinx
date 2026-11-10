"""Sphinx project that documents the Robot Raconteur standard service definitions.

Set ROBDEF_STANDARD_DIR to a robotraconteur_standard_robdef checkout
(default: ../.deps/robotraconteur_standard_robdef).
"""

import os
from pathlib import Path

_here = Path(__file__).resolve().parent
_standard = Path(os.environ.get("ROBDEF_STANDARD_DIR", _here.parent / ".deps" / "robotraconteur_standard_robdef"))

project = "Robot Raconteur Service Definitions"
extensions = ["robotraconteur_sphinx"]
primary_domain = "robdef"
nitpicky = True
exclude_patterns = ["_build"]

robdef_files = [
    str(_standard / "group1"),
    str(_standard / "group2"),
    "../tests/robdef",
]
# Upstream bug: group2/com.robotraconteur.a1.robotics.scene.robdef declares
# "service com.robotraconteur.robotics.scene", but the planning service imports
# com.robotraconteur.a1.robotics.scene, so those references cannot resolve.
nitpick_ignore_regex = [(r"robdef:.*", r"com\.robotraconteur\.a1\.robotics\.scene(\..*)?")]

robdef_output_dir = "robdef"
robdef_index = "index"
