"""Load helper scripts by path (skill folders contain hyphens, so they are not packages)."""

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(skill: str, script: str):
    path = REPO / "skills" / skill / script
    name = "rescue_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
