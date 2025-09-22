#!/usr/bin/env python3
"""
Build a single repository-level resources.zip from per-package asset folders.

Layout:
  assets/
    com.github.ebastler.marbastlib/
      icon.png
      screenshots/one.png
    com.zeroping.jal_powerpole/
      icon.png
      screenshot.png

Result:
  resources.zip containing:
    com.github.ebastler.marbastlib/icon.png
    com.github.ebastler.marbastlib/screenshots/one.png
    com.zeroping.jal_powerpole/icon.png
    com.zeroping.jal_powerpole/screenshot.png
"""

import os
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
OUT_ZIP = ROOT / "resources.zip"


def add_dir_to_zip(z: zipfile.ZipFile, base_dir: Path, arc_prefix: str):
    for path in base_dir.rglob("*"):
        if path.is_file():
            arcname = f"{arc_prefix}/{path.relative_to(base_dir).as_posix()}"
            z.write(path, arcname)


def main():
    # If no assets/ directory, remove resources.zip if present and exit cleanly
    if not ASSETS.exists():
        if OUT_ZIP.exists():
            OUT_ZIP.unlink()
            print("Removed stale resources.zip (no assets/ found).")
        else:
            print("No assets/ directory; nothing to build.")
        return

    # Gather package folders under assets/
    pkg_dirs = [p for p in ASSETS.iterdir() if p.is_dir()]
    if not pkg_dirs:
        if OUT_ZIP.exists():
            OUT_ZIP.unlink()
            print("Removed stale resources.zip (assets/ empty).")
        else:
            print("assets/ has no package folders; nothing to build.")
        return

    # Create/overwrite resources.zip
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for pkg_dir in sorted(pkg_dirs, key=lambda p: p.name.lower()):
            # namespace contents under the package identifier folder
            add_dir_to_zip(z, pkg_dir, pkg_dir.name)

    size = OUT_ZIP.stat().st_size
    print(
        f"Built {OUT_ZIP.name} ({size} bytes) from {len(pkg_dirs)} package folder(s)."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Don’t fail the whole build just because resources couldn’t be packed
        print(f"[update_resources] warning: {e}", file=sys.stderr)
        sys.exit(0)
