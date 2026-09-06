#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read cached sysfs descriptors and local state; never open USB/DRM devices."""

import argparse
import json
import os
from pathlib import Path
import platform
import shutil

ROOT = Path(__file__).resolve().parents[1]


def read_text(path):
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return None


def parse_descriptors(data):
    """Parse cached USB descriptors with strict length and boundary checks."""
    records = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 2:
            raise ValueError("truncated descriptor header")
        length, kind = data[offset : offset + 2]
        if length < 2 or offset + length > len(data):
            raise ValueError("invalid descriptor length")
        record = data[offset : offset + length]
        item = {"type": kind, "length": length}
        if kind == 1:
            if length != 18:
                raise ValueError("unexpected device descriptor length")
            item.update(vid=f"{int.from_bytes(record[8:10], 'little'):04x}",
                        pid=f"{int.from_bytes(record[10:12], 'little'):04x}",
                        revision=f"{int.from_bytes(record[12:14], 'little'):04x}",
                        device_class=record[4], configurations=record[17])
        elif kind == 2:
            if length != 9:
                raise ValueError("unexpected configuration descriptor length")
            item.update(interfaces=record[4], configuration=record[5])
        elif kind == 4:
            if length != 9:
                raise ValueError("unexpected interface descriptor length")
            item.update(number=record[2], alternate=record[3], endpoints=record[4],
                        interface_class=record[5], subclass=record[6], protocol=record[7])
        elif kind == 5:
            if length < 7:
                raise ValueError("truncated endpoint descriptor")
            item.update(address=f"0x{record[2]:02x}", attributes=record[3],
                        max_packet=int.from_bytes(record[4:6], "little"), interval=record[6])
        records.append(item)
        offset += length
    return records


def inspect_usb(path):
    result = {"path": path.name}
    for key in ("idVendor", "idProduct", "bcdDevice", "speed", "manufacturer", "product"):
        result[key] = read_text(path / key)
    interface = path.parent / (path.name + ":1.0")
    driver = interface / "driver"
    result["driver"] = driver.resolve().name if driver.is_symlink() else None
    try:
        result["cached_descriptors"] = parse_descriptors((path / "descriptors").read_bytes())
    except (OSError, ValueError) as error:
        result["descriptor_error"] = str(error)
    return result


def collect():
    release = platform.release()
    headers = Path("/usr/lib/modules") / release / "build"
    devices = []
    for path in sorted(Path("/sys/bus/usb/devices").glob("*")):
        if read_text(path / "idVendor") == "0711" and read_text(path / "idProduct") == "5601":
            devices.append(inspect_usb(path))
    drm = {}
    for path in sorted(Path("/sys/class/drm").glob("card*-*/status")):
        drm[path.parent.name] = read_text(path)
    required = ("Makefile", "include/generated/autoconf.h", "Module.symvers",
                "include/config/kernel.release")
    missing = [name for name in required if not (headers / name).is_file()]
    staged = ROOT / "artifacts" / f"headers-{release}" / "root/usr/lib/modules" / release / "build"
    staged_ready = (all((staged / name).is_file() for name in required)
                    and read_text(staged / "include/config/kernel.release") == release)
    tools = {name: shutil.which(name) for name in ("make", "gcc", "clang", "modinfo", "modetest")}
    return {"kernel": release, "uid": os.geteuid(), "headers_path": str(headers),
            "missing_header_files": missing,
            "header_release": read_text(headers / "include/config/kernel.release"),
            "staged_headers_path": str(staged), "staged_headers_ready": staged_ready,
            "local_module_exists": (ROOT / "kernel/trigger6.ko").is_file(),
            "tools": tools, "t6_devices": devices, "drm_connectors": drm,
            "trigger6_loaded": Path("/sys/module/trigger6").is_dir(),
            "note": "Cached sysfs data only. This is neither a build nor a hardware validation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the read-only report as JSON")
    args = parser.parse_args()
    report = collect()
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print(f"Kernel: {report['kernel']}")
    if report["missing_header_files"]:
        print("System-header build BLOCKED: matching linux-headers are absent/incomplete.")
        print("  Missing: " + ", ".join(report["missing_header_files"]))
    elif report["header_release"] != report["kernel"]:
        print("Build BLOCKED: the header release differs from the running kernel.")
    else:
        print("Prepared matching headers found; compilation remains a separate check.")
    if report["staged_headers_ready"]:
        print("Matching repo-local headers found: make build-staged is available.")
        print("  Staging does not install headers or certify their provenance; see docs/LOCAL_BUILD.md.")
    print(f"Local .ko exists: {report['local_module_exists']} (does not mean loaded/tested)")
    print(f"trigger6 loaded: {report['trigger6_loaded']}")
    for device in report["t6_devices"]:
        print(f"T6 {device['path']}: revision={device['bcdDevice']} "
              f"speed={device['speed']} Mbit/s driver={device['driver'] or 'unbound'}")
        print(f"  Candidate selector for later review: device_path={device['path']}")
        for descriptor in device.get("cached_descriptors", []):
            if descriptor["type"] == 5:
                print(f"  Endpoint {descriptor['address']} attrs={descriptor['attributes']} "
                      f"packet={descriptor['max_packet']} interval={descriptor['interval']}")
        if "descriptor_error" in device:
            print("  Descriptor read failed: " + device["descriptor_error"])
    if len(report["t6_devices"]) != 1:
        print("Physical test BLOCKED: expected exactly one 0711:5601 device.")
    for name, status in report["drm_connectors"].items():
        print(f"DRM {name}: {status}")
    print(report["note"])


if __name__ == "__main__":
    main()
