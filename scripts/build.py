"""Build the HACS release archive: the integration's files at the zip root.

    python3 scripts/build.py

HACS extracts a release asset straight into
`<config>/custom_components/<domain>`, so the archive must contain
`manifest.json` at its root - not a `custom_components/` folder. The manual
install path is therefore the same directory:

    unzip bonbon.zip -d /config/custom_components/bonbon
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
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    expected = ["domain", "name", *sorted(k for k in manifest if k not in ("domain", "name"))]
    if list(manifest) != expected:
        raise SystemExit(f"manifest.json keys must be domain, name, then alphabetical: {list(manifest)}")
    version = manifest["version"]
    files = [
        path
        for path in sorted(COMPONENT.rglob("*"))
        if path.is_file() and not SKIP.intersection(path.parts)
    ]
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(COMPONENT))

    names = zipfile.ZipFile(OUTPUT).namelist()
    if "manifest.json" not in names or any(
        name.startswith("custom_components/") for name in names
    ):
        raise SystemExit("bonbon.zip must have manifest.json at its root")

    print(f"bonbon.zip  v{version}  {len(files)} files  {OUTPUT.stat().st_size} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
