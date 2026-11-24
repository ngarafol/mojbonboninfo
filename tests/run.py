"""Run the test suite without pytest: `python3 tests/run.py`.

pytest collects the same functions, so CI can use either.
"""

from __future__ import annotations

import importlib
import sys
import traceback

import conftest  # noqa: F401  (registers the synthetic package)

MODULES = ("test_models", "test_session_import")


def main() -> int:
    failures = 0
    total = 0
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            total += 1
            try:
                getattr(module, name)()
            except Exception:  # noqa: BLE001 - a runner reports, it does not crash
                failures += 1
                print(f"FAIL {module_name}.{name}")
                traceback.print_exc()
    print(f"{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
