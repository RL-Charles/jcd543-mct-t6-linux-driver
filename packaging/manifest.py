#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build-only manifest generation inside makepkg's staging root."""

import hashlib
import json
from pathlib import Path
import re
import sys

MANIFEST = "usr/share/jcd543-trigger6/files.json"


def collect(root, release):
    if not isinstance(release, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*-[1-9][0-9]{0,5}", release):
        raise ValueError("invalid explicit package release")
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("package payload must not contain symlinks")
        if path.is_file() and path.relative_to(root).as_posix() != MANIFEST:
            files.append({"path": path.relative_to(root).as_posix(),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "mode": path.stat().st_mode & 0o777})
    return {"schema": 1, "package": "jcd543-trigger6-dkms", "version": release, "files": files}


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: manifest.py MAKEPKG-STAGING-ROOT PACKAGE-VERSION-RELEASE")
    root = Path(sys.argv[1]).resolve(strict=True)
    if root == Path("/") or not (root / "usr/lib/jcd543-trigger6/controller.py").is_file():
        raise SystemExit("not a prepared package staging root")
    manifest = collect(root, sys.argv[2])
    destination = root / MANIFEST
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
