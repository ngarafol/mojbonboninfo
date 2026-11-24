"""Build the HACS release archive: bonbon.zip with custom_components/bonbon.

    python3 scripts/build.py

The archive root is `custom_components/`, so unzipping it into /config is
exactly what HACS does and what a manual install needs.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
COMPONENT = ROOT / "custom_components" / "bonbon"
OUTPUT = ROOT / "bonbon.zip"
SKIP = {"__pycache__", ".DS_Store"}


def main() -> int:
    version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
    files = [
        path
        for path in sorted(COMPONENT.rglob("*"))
        if path.is_file() and not SKIP.intersection(path.parts)
    ]
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT))
    print(f"bonbon.zip  v{version}  {len(files)} files  {OUTPUT.stat().st_size} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
