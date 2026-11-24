"""Load the integration's HA-free modules without importing Home Assistant."""

from __future__ import annotations

import sys
import types
from pathlib import Path

COMPONENT_DIR = Path(__file__).parents[1] / "custom_components" / "bonbon"

# The package __init__ imports homeassistant; tests only need the pure modules,
# so a synthetic package rooted at the component directory is enough.
_pkg = types.ModuleType("bonbon_under_test")
_pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules.setdefault("bonbon_under_test", _pkg)
