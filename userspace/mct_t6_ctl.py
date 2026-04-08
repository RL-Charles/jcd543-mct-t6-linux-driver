#!/usr/bin/env python3
"""mct-t6-ctl -- companion CLI for the MCT Trigger6 USB display kernel driver."""

import argparse
import glob
import os
import signal
import sys
import time

METRICS_GLOB = "/sys/bus/usb/devices/*/t6_metrics"
METRICS_RESET_GLOB = "/sys/bus/usb/devices/*/t6_metrics_reset"
MODULE_PARAM_DIR = "/sys/module/trigger6/parameters"

SETTABLE_PARAMS = {
    "jpeg-quality": ("jpeg_quality", 1, 100),
    "frame-interval": ("frame_min_interval_ms", 0, 1000),
    "secondary-interval": ("secondary_frame_min_interval_ms", 0, 5000),
}

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
CLEAR = "\033[2J\033[H"


def sysfs_read(path):
    try:
        with open(path) as f:
            return f.read()
    except (OSError, IOError):
        return None


def sysfs_write(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
    except PermissionError:
        print(f"error: permission denied writing {path} (try sudo)", file=sys.stderr)
        sys.exit(1)
    except (OSError, IOError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def discover_devices():
    devices = []
    for path in sorted(glob.glob(METRICS_GLOB)):
        raw = sysfs_read(path)
        if raw is None:
            continue
        devices.append((os.path.dirname(path), parse_metrics(raw)))
    return devices


def parse_metrics(text):
    result = {}
    for line in text.strip().splitlines():
        parts = line.split()
        if not parts:
            continue
        prefix = parts[0]
        kvs = {}
        for token in parts[1:]:
            if "=" in token:
                k, v = token.split("=", 1)
                kvs[k] = v
        if prefix in result:
            result[prefix].update(kvs)
        else:
            result[prefix] = kvs
    return result


def fmt_us(val):
    try:
        us = int(val)
    except (ValueError, TypeError):
        return val or "?"
    if us == 0:
        return "-"
    if us < 1000:
        return f"{us}us"
    if us < 1_000_000:
        return f"{us / 1000:.1f}ms"
    return f"{us / 1_000_000:.2f}s"


def fmt_bytes(val):
    try:
        b = int(val)
    except (ValueError, TypeError):
        return val or "?"
    if b == 0:
        return "-"
    if b < 1024:
        return f"{b}B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f}K"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f}M"
    return f"{b / (1024 * 1024 * 1024):.2f}G"


def g(d, key, default="?"):
    return d.get(key, default)


def cmd_status(_args):
    devices = discover_devices()
    if not devices:
        print("No Trigger6 devices found (is the trigger6 module loaded?)")
        return 1
    for _, dev in devices:
        t6 = dev.get("trigger6", {})
        dv = dev.get("device", {})
        faulted = g(t6, "io_faulted", "0")
        color = GREEN if faulted == "0" else RED
        print(f"{BOLD}Trigger6 {g(t6, 'interface')}{RESET}  "
              f"bus {g(t6, 'bus')} dev {g(t6, 'dev')}  "
              f"[{color}{'OK' if faulted == '0' else 'FAULTED'}{RESET}]")
        print(f"  bulk: {fmt_bytes(g(dv, 'bulk_bytes'))} total  "
              f"errors={g(dv, 'bulk_errors')}  "
              f"last={fmt_us(g(dv, 'last_bulk_us'))}")
        for hi in range(2):
            h = dev.get(f"head{hi}", {})
            if not h:
                continue
            conn = g(h, "connected") == "1"
            conn_str = f"{GREEN}connected{RESET}" if conn else f"{DIM}disconnected{RESET}"
            print(f"  {BOLD}head{hi}{RESET}: {g(h, 'transport'):<10} {conn_str}  "
                  f"{g(h, 'width')}x{g(h, 'height')}")
            print(f"    sent={g(h, 'sent_frames'):>6}  "
                  f"skipped={g(h, 'skipped_frames'):>6}  "
                  f"encode={fmt_us(g(h, 'encode_avg_us'))}  "
                  f"usb={fmt_us(g(h, 'usb_avg_us'))}  "
                  f"payload={fmt_bytes(g(h, 'last_payload_bytes'))}")
        print()
    return 0


def cmd_monitor(_args):
    signal.signal(signal.SIGINT, lambda *_: (print(f"\n{RESET}"), sys.exit(0)))
    while True:
        devices = discover_devices()
        now = time.strftime("%H:%M:%S")
        out = [f"{CLEAR}{BOLD}mct-t6-ctl monitor{RESET}  {now}  "
               f"({len(devices)} device{'s' if len(devices) != 1 else ''})  "
               f"{DIM}Ctrl-C to quit{RESET}\n"]
        for _, dev in devices:
            t6 = dev.get("trigger6", {})
            dv = dev.get("device", {})
            out.append(f"{BOLD}{g(t6, 'interface')}{RESET}  "
                       f"bulk={fmt_bytes(g(dv, 'bulk_bytes'))}")
            for hi in range(2):
                h = dev.get(f"head{hi}", {})
                if not h:
                    continue
                conn = "Y" if g(h, "connected") == "1" else "-"
                out.append(f"  head{hi} {g(h, 'transport'):<10} {conn}  "
                           f"sent={g(h, 'sent_frames'):>6}  "
                           f"enc={fmt_us(g(h, 'encode_avg_us')):>8}  "
                           f"usb={fmt_us(g(h, 'usb_avg_us')):>8}  "
                           f"pay={fmt_bytes(g(h, 'last_payload_bytes')):>8}")
            out.append("")
        if not devices:
            out.append("  No Trigger6 devices found.")
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()
        time.sleep(1.0)


def cmd_set(args):
    if args.param not in SETTABLE_PARAMS:
        print(f"error: unknown parameter '{args.param}'", file=sys.stderr)
        print(f"valid: {', '.join(sorted(SETTABLE_PARAMS))}", file=sys.stderr)
        return 1
    sysfs_name, lo, hi = SETTABLE_PARAMS[args.param]
    try:
        v = int(args.value)
    except ValueError:
        print("error: value must be integer", file=sys.stderr)
        return 1
    if v < lo or v > hi:
        print(f"error: {args.param} range is [{lo}, {hi}]", file=sys.stderr)
        return 1
    path = os.path.join(MODULE_PARAM_DIR, sysfs_name)
    if not os.path.exists(path):
        print(f"error: {path} not found (module loaded?)", file=sys.stderr)
        return 1
    old = (sysfs_read(path) or "").strip()
    sysfs_write(path, str(v))
    new = (sysfs_read(path) or "").strip()
    print(f"{args.param}: {old} -> {new}")
    return 0


def cmd_info(_args):
    import platform
    print(f"{BOLD}Kernel:{RESET}  {platform.release()}")
    if not os.path.isdir("/sys/module/trigger6"):
        print(f"{BOLD}Driver:{RESET}  {RED}not loaded{RESET}")
        return 1
    print(f"{BOLD}Driver:{RESET}  trigger6 (loaded)")
    if os.path.isdir(MODULE_PARAM_DIR):
        print(f"{BOLD}Parameters:{RESET}")
        for f in sorted(os.listdir(MODULE_PARAM_DIR)):
            val = (sysfs_read(os.path.join(MODULE_PARAM_DIR, f)) or "").strip()
            print(f"  {f} = {val}")
    return 0


def cmd_reset(_args):
    paths = sorted(glob.glob(METRICS_RESET_GLOB))
    if not paths:
        print("No Trigger6 devices found.")
        return 1
    for p in paths:
        sysfs_write(p, "1")
        print(f"Reset: {os.path.basename(os.path.dirname(p))}")
    return 0


def main():
    p = argparse.ArgumentParser(prog="mct-t6-ctl",
        description="Companion CLI for the MCT Trigger6 USB display driver")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("status", help="Show connected devices and metrics")
    sub.add_parser("monitor", help="Live dashboard (poll every 1s)")
    sp = sub.add_parser("set", help="Write a module parameter")
    sp.add_argument("param", help=f"({', '.join(sorted(SETTABLE_PARAMS))})")
    sp.add_argument("value", help="Integer value")
    sub.add_parser("info", help="Show driver and kernel info")
    sub.add_parser("reset-metrics", help="Reset all counters")
    args = p.parse_args()
    if not args.command:
        p.print_help()
        return 0
    return {"status": cmd_status, "monitor": cmd_monitor, "set": cmd_set,
            "info": cmd_info, "reset-metrics": cmd_reset}[args.command](args) or 0


if __name__ == "__main__":
    sys.exit(main())
