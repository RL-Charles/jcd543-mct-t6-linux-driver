#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only install/removal plan; installed root helper requires --apply."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys

PACKAGE = "jcd543-trigger6-dkms"
VERSION = "0.1.0"
SELF = Path("/usr/lib/jcd543-trigger6/setup.py")
MANIFEST = "usr/share/jcd543-trigger6/files.json"
CONFIG = Path("/etc/jcd543-trigger6/approved.json")
ALLOWED_PREFIXES = ("usr/src/jcd543-trigger6-0.1.0/", "usr/lib/jcd543-trigger6/",
                    "usr/share/doc/jcd543-trigger6/", "usr/share/licenses/jcd543-trigger6-dkms/")
ALLOWED_FILES = {"usr/bin/jcd543-trigger6", "usr/bin/jcd543-trigger6-setup",
                 "usr/lib/systemd/system/jcd543-trigger6.service",
                 "usr/lib/systemd/system-sleep/jcd543-trigger6",
                 "etc/modprobe.d/jcd543-trigger6.conf"}


class Refusal(RuntimeError):
    pass


def safe_relative(name):
    if (not isinstance(name, str) or not name or name.startswith("/") or
            ".." in Path(name).parts or not re.fullmatch(r"[A-Za-z0-9_./+-]+", name)):
        raise Refusal("invalid package manifest path")
    if name not in ALLOWED_FILES and not name.startswith(ALLOWED_PREFIXES):
        raise Refusal("package manifest path outside owned scope")


def trusted(path, root, owner):
    if not path.is_relative_to(root):
        raise Refusal("path escaped installation root")
    for part in (path, *path.parents):
        info = part.lstat()
        if info.st_uid != owner or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise Refusal(f"untrusted owner/mode/link: {part.name}")
        if part == root:
            break
    if not path.is_file():
        raise Refusal("manifest item is not a regular file")


def verify(root=Path("/"), owner=0, *, release_reader=None):
    manifest_path = root / MANIFEST
    trusted(manifest_path, root, owner)
    if manifest_path.stat().st_size > 65536:
        raise Refusal("oversized installation manifest")
    document = json.loads(manifest_path.read_text())
    # Runtime truth comes from pacman's installed record, not a second pinned
    # pkgrel literal. The injected reader is for synthetic archive/root tests;
    # no CLI option or environment override can replace this runtime check.
    expected_release = (release_reader or installed_package_release)()
    if (document.get("schema") != 1 or document.get("package") != PACKAGE or
            not isinstance(expected_release, str) or
            not re.fullmatch(re.escape(VERSION) + r"-[1-9][0-9]{0,5}", expected_release) or
            document.get("version") != expected_release or not isinstance(document.get("files"), list) or
            not 10 <= len(document["files"]) <= 64):
        raise Refusal("invalid installation manifest")
    seen = set()
    for item in document["files"]:
        name = item["path"]
        safe_relative(name)
        if name in seen:
            raise Refusal("duplicate manifest entry")
        seen.add(name)
        path = root / name
        trusted(path, root, owner)
        if (path.stat().st_mode & 0o777 != item["mode"] or
                hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]):
            raise Refusal(f"installed file changed; preserve and review: {name}")
    required = ALLOWED_FILES | {"usr/lib/jcd543-trigger6/controller.py", "usr/lib/jcd543-trigger6/setup.py",
                                "usr/src/jcd543-trigger6-0.1.0/dkms.conf"}
    if not required <= seen:
        raise Refusal("incomplete installation manifest")
    return document


def run(argv, timeout=30):
    if argv[0] not in {"/usr/bin/systemctl", "/usr/bin/dkms", "/usr/bin/pacman",
                       "/usr/bin/jcd543-trigger6", "/usr/bin/modinfo"}:
        raise Refusal("setup command not allowed")
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=timeout, check=False, env={"PATH": "/usr/bin", "LC_ALL": "C"})
    if result.returncode != 0:
        raise Refusal(f"{Path(argv[0]).name} failed (exit {result.returncode}); activation remains blocked")
    return result.stdout.strip()


def installed_package_release(runner=None):
    result = (runner or run)(["/usr/bin/pacman", "-Q", PACKAGE], timeout=5)
    match = re.fullmatch(re.escape(PACKAGE + " " + VERSION) + r"-([1-9][0-9]{0,5})", result)
    if not match:
        raise Refusal("installed package release unavailable or outside supported version")
    return VERSION + "-" + match[1]


def prepare(runner=run):
    """A partial DKMS failure never approves, enables, or loads a module."""
    release = platform.release()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,95}", release):
        raise Refusal("invalid running kernel release")
    runner(["/usr/bin/dkms", "install", f"jcd543-trigger6/{VERSION}", "-k", release], timeout=180)
    module = runner(["/usr/bin/modinfo", "-n", "trigger6"])
    if module.startswith(f"/lib/modules/{release}/"):
        if Path("/lib").resolve(strict=True) != Path("/usr/lib"):
            raise Refusal("unreviewed /lib layout; canonical module path requires review")
        module = "/usr" + module
    if (not module.startswith(f"/usr/lib/modules/{release}/") or ".." in Path(module).parts or
            not re.fullmatch(r"[A-Za-z0-9_./+-]+/trigger6\.ko(?:\.(?:zst|xz|gz))?", module)):
        raise Refusal("DKMS artifact was not installed into current kernel tree")
    return module


def uninstall(runner=run):
    # Stop before deleting helper files; unknown/in-use modules abort normally.
    runner(["/usr/bin/systemctl", "disable", "--now", "jcd543-trigger6.service"], timeout=20)
    if CONFIG.exists():
        runner(["/usr/bin/jcd543-trigger6", "stop", "--apply"], timeout=10)
    elif Path("/sys/module/trigger6").exists():
        raise Refusal("resident module has no approval: remove it through reviewed recovery first")
    current = runner(["/usr/bin/dkms", "status", f"jcd543-trigger6/{VERSION}"])
    if current:
        runner(["/usr/bin/dkms", "remove", f"jcd543-trigger6/{VERSION}", "--all"], timeout=60)
    runner(["/usr/bin/pacman", "-R", "--noconfirm", PACKAGE], timeout=60)
    runner(["/usr/bin/systemctl", "daemon-reload"])
    # Keep an approval recovery copy; no startup entry remains to act on it.
    if CONFIG.exists():
        trusted(CONFIG, Path("/"), 0)
        data = CONFIG.read_bytes()
        destination = Path("/var/lib/jcd543-trigger6")
        destination.mkdir(mode=0o700, exist_ok=True)
        info = destination.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise Refusal("unsafe approval recovery directory; original approval preserved")
        saved = destination / ("retired-approval-" + hashlib.sha256(data).hexdigest() + ".json")
        if saved.exists():
            trusted(saved, Path("/"), 0)
            if saved.read_bytes() != data:
                raise Refusal("recovery copy differs; original approval preserved")
        else:
            descriptor = os.open(saved, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        CONFIG.unlink()
    print("Project package/DKMS entries removed; headers/DKMS tools and user source preserved.")
    print("Approval recovery copy is retained under /var/lib/jcd543-trigger6 when present; /run state expires at reboot.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "verify", "prepare", "uninstall"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.command in ("plan", "verify") or not args.apply:
        report = {"read_only": True, "package": PACKAGE, "activation": "disabled unless separately enabled",
                  "prerequisites": ["matching linux-headers", "dkms"],
                  "first_install": "review local package; install via pacman -U after Omarchy prerequisite flow",
                  "prepare": "verify owned files; build/install current-kernel DKMS artifact; no approval/load/enable",
                  "uninstall": "verify manifest; disable/stop only project unit; remove exact DKMS version and package; preserve prerequisites/source"}
        if Path("/" + MANIFEST).exists():
            report["verified_file_count"] = len(verify()["files"])
        elif args.command == "verify":
            raise Refusal("project is not installed")
        print(json.dumps(report, indent=2))
        return
    if os.geteuid() != 0 or Path(__file__).absolute() != SELF:
        raise Refusal("mutations require the root-owned installed setup helper and explicit --apply")
    trusted(SELF, Path("/"), 0)
    document = verify()
    print(f"Verified {len(document['files'])} manifest-owned files; no foreign file will be removed.", flush=True)
    if args.command == "prepare":
        module = prepare()
        trusted(Path(module), Path("/"), 0)
        print(json.dumps({"installed_module": module, "sha256": hashlib.sha256(Path(module).read_bytes()).hexdigest(),
                          "srcversion": run(["/usr/bin/modinfo", "-F", "srcversion", module]),
                          "vermagic": run(["/usr/bin/modinfo", "-F", "vermagic", module]),
                          "activation": "not approved/loaded/enabled"}, indent=2))
    else:
        uninstall()


if __name__ == "__main__":
    try:
        main()
    except (Refusal, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(f"Refused: {error}", file=sys.stderr)
        sys.exit(1)
