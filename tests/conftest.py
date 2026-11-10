import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_ROBDEF_DIR = Path(__file__).resolve().parent / "robdef"
STANDARD_ROBDEF_DIR = Path(
    os.environ.get("ROBDEF_STANDARD_DIR", ROOT / ".deps" / "robotraconteur_standard_robdef")
)


def standard_robdef_files():
    files = []
    for group in ("group1", "group2"):
        files.extend(sorted((STANDARD_ROBDEF_DIR / group).glob("*.robdef")))
    return files


def local_robdef_files():
    return sorted(TEST_ROBDEF_DIR.glob("*.robdef"))


def all_robdef_files():
    return standard_robdef_files() + local_robdef_files()


requires_standard = pytest.mark.skipif(
    not (STANDARD_ROBDEF_DIR / "group1").is_dir(),
    reason="robotraconteur_standard_robdef not found; set ROBDEF_STANDARD_DIR",
)
