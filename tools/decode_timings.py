#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline MCT RESOLUTIONTIMING decoder; never opens hardware or changes modes.

Layout: mcttrigger/triggerdm t6.h (_ResolutionTiming), commit 63cecc7ef330.
The independent cyrozap T6 dissector agrees on geometry field offsets.
PLL bytes are reported without calculation or modification.
"""

import argparse
import json
from pathlib import Path
import re
import struct

TIMING = struct.Struct("<IBB10H6B")
FIELDS = (
    "pixel_clock_khz", "frequency_hz", "reserved", "h_total", "h_active",
    "h_sync_start", "h_sync_width", "v_total", "v_active", "v_sync_start",
    "v_sync_width", "pll_fnum", "pll_fden", "pll_idiv", "output_select",
    "h_polarity", "v_polarity", "reduced", "flag",
)
CEA_1080P60 = {
    "pixel_clock_khz": 148500, "frequency_hz": 60,
    "h_total": 2200, "h_active": 1920, "h_sync_start": 2008, "h_sync_width": 44,
    "v_total": 1125, "v_active": 1080, "v_sync_start": 1084, "v_sync_width": 5,
    "h_polarity": 1, "v_polarity": 1,
}
HEADER = re.compile(
    r"Timing query head 0: total=(\d+) captured=(\d+) bytes=(\d+) start=(\d+); raw diagnostic only$"
)
RECORD = re.compile(r"T6 timing\[(\d+)\]: ([0-9a-fA-F]{64})$")


def decode_record(data):
    if len(data) != TIMING.size:
        raise ValueError(f"a timing record must be exactly {TIMING.size} bytes")
    result = dict(zip(FIELDS, TIMING.unpack(data), strict=True))
    errors = []
    if not result["pixel_clock_khz"] or not result["frequency_hz"]:
        errors.append("pixel clock and frequency must be nonzero")
    for axis in ("h", "v"):
        active, start, width, total = (
            result[f"{axis}_{field}"] for field in ("active", "sync_start", "sync_width", "total")
        )
        if not (0 < active <= start < start + width <= total):
            errors.append(f"{axis}: require 0 < active <= sync_start < sync_end <= total")
        if result[f"{axis}_polarity"] not in (0, 1):
            errors.append(f"{axis}: documented sync polarity must be 0 or 1")
    result["raw_hex"] = data.hex()
    result["geometry_errors"] = errors
    result["cea_1080p60_differences"] = {
        key: {"observed": result[key], "expected": value}
        for key, value in CEA_1080P60.items() if result[key] != value
    }
    denominator = result["h_total"] * result["v_total"]
    result["calculated_refresh_hz"] = (
        result["pixel_clock_khz"] * 1000 / denominator if denominator else None
    )
    # Geometry validity does not establish usable PLL values or transmitter setup.
    return result


def parse_kernel_log(text):
    if len(text) > 1024 * 1024:
        raise ValueError("use a scoped log of at most 1 MiB")
    headers, records = [], {}
    for line in text.splitlines():
        if "Timing query head 0:" in line:
            match = HEADER.search(line)
            if not match:
                raise ValueError("malformed timing count/header line")
            headers.append(tuple(map(int, match.groups())))
        if "T6 timing[" in line:
            match = RECORD.search(line)
            if not match:
                raise ValueError("malformed timing record line")
            index = int(match[1])
            if index in records:
                raise ValueError("duplicate timing record index")
            records[index] = decode_record(bytes.fromhex(match[2]))
    if len(headers) != 1:
        raise ValueError("require exactly one timing query header")
    total, captured, size, start = headers[0]
    if not (start in (0, 16) and start < total <= 0xFFFFFFFF and
            captured == min(total - start, 16) and size == captured * 32):
        raise ValueError("invalid count, capture bound, or byte length")
    if start == 16 and total != 36:
        raise ValueError("continuation requires the measured 36-record table")
    if set(records) != set(range(start, start + captured)):
        raise ValueError("missing, extra, or out-of-order-range record indices")
    return {
        "head": 0, "total": total, "captured": captured, "bytes": size, "start": start,
        "truncated": total > captured,
        "records": [records[index] for index in range(start, start + captured)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--hex", help="exactly one 32-byte hexadecimal timing record")
    source.add_argument("--log", type=Path, help="scoped kernel log from one query, at most 1 MiB")
    args = parser.parse_args()
    try:
        if args.hex is not None:
            result = {"records": [decode_record(bytes.fromhex(args.hex))]}
        else:
            if args.log.stat().st_size > 1024 * 1024:
                raise ValueError("use a scoped log of at most 1 MiB")
            result = parse_kernel_log(args.log.read_text())
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    result["geometry_valid"] = all(not item["geometry_errors"] for item in result["records"])
    result["cea_1080p60_indices"] = [
        result.get("start", 0) + index for index, item in enumerate(result["records"])
        if not item["geometry_errors"] and not item["cea_1080p60_differences"]
    ]
    print(json.dumps(result, indent=2))
    return 0 if result["geometry_valid"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
