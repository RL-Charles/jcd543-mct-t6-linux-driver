#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read an existing little-endian pcapng USB capture; never replay USB traffic.

Only report captured vendor timing-table INs and video-mode OUT data.
USBPcap layout: https://desowin.org/usbpcap/captureformat.html
Linux usbmon layout: https://docs.kernel.org/usb/usbmon.html
This intentionally small parser refuses unsupported/truncated containers.
"""

import argparse
import gzip
import json
from pathlib import Path
import struct


def packets(stream):
    links = []
    while True:
        prefix = stream.read(8)
        if not prefix:
            return
        if len(prefix) != 8:
            raise ValueError("truncated block header")
        kind, length = struct.unpack("<II", prefix)
        if length < 12 or length > 16 * 1024 * 1024 or length % 4:
            raise ValueError("unsupported block length or byte order")
        rest = stream.read(length - 8)
        if len(rest) != length - 8 or struct.unpack("<I", rest[-4:])[0] != length:
            raise ValueError("truncated block or mismatching trailer")
        body = rest[:-4]
        if kind == 0x0A0D0D0A:
            if len(body) < 16 or body[:4] != b"\x4d\x3c\x2b\x1a":
                raise ValueError("only little-endian pcapng sections are supported")
            links = []
        elif kind == 1:
            if len(body) < 8:
                raise ValueError("short interface descriptor")
            links.append(struct.unpack_from("<H", body)[0])
        elif kind == 6:
            if len(body) < 20:
                raise ValueError("short enhanced packet")
            interface, high, low, captured, original = struct.unpack_from("<IIIII", body)
            if interface >= len(links) or captured > original or captured > len(body) - 20:
                raise ValueError("invalid enhanced packet bounds")
            if links[interface] in (220, 249):
                yield links[interface], body[20:20 + captured]


def inspect(stream):
    pending = {}
    records = []
    for sequence, (link, data) in enumerate(packets(stream)):
        if link == 220:
            if len(data) < 64:
                raise ValueError("truncated usbmon header")
            irp, event, transfer, endpoint, device, bus, setup_flag, data_flag = (
                struct.unpack_from("<QBBBBHBB", data)
            )
            status, length, captured = struct.unpack_from("<iII", data, 28)
            if captured > len(data) - 64:
                raise ValueError("invalid usbmon capture length")
            if transfer != 2:
                continue
            key = (bus, device, irp)
            payload = data[64:64 + captured]
            if event == ord("S") and setup_flag == 0:
                pending.pop(key, None)
                direction, request, value, index, expected = struct.unpack_from("<BBHHH", data, 40)
                if (direction, request) not in ((0xC0, 0x89), (0x40, 0x12)):
                    continue
                record = {"packet": sequence, "bus": bus, "device": device,
                          "type": direction, "request": request, "value": value,
                          "index": index, "expected": expected}
                if direction == 0x40:
                    record.update(data_hex=payload.hex(), captured=len(payload))
                    records.append(record)
                else:
                    pending[key] = record
            elif event == ord("C") and key in pending:
                record = pending.pop(key)
                record.update(status=status, captured=len(payload), data_hex=payload.hex())
                records.append(record)
            continue
        if len(data) < 27:
            raise ValueError("truncated USBPcap header")
        size, irp, status, function, info, bus, device, endpoint, transfer, length = (
            struct.unpack_from("<HQIHBHHBBI", data)
        )
        if size < 27 or size > len(data) or length > len(data) - size:
            raise ValueError("invalid USBPcap payload bounds")
        if transfer != 2:
            continue
        if size < 28:
            raise ValueError("short control header")
        stage, payload = data[27], data[size:size + length]
        key = (bus, device, irp)
        if stage == 0:
            pending.pop(key, None)
            if len(payload) < 8:
                raise ValueError("short USB setup packet")
            direction, request, value, index, expected = struct.unpack_from("<BBHHH", payload)
            if (direction, request) not in ((0xC0, 0x89), (0x40, 0x12)):
                continue
            record = {"packet": sequence, "bus": bus, "device": device,
                      "type": direction, "request": request, "value": value,
                      "index": index, "expected": expected}
            if direction == 0x40:
                record.update(data_hex=payload[8:].hex(), captured=len(payload) - 8)
                records.append(record)
            else:
                pending[key] = record
        elif stage in (1, 3) and info & 1 and key in pending:
            record = pending.pop(key)
            record.update(status=status, captured=len(payload), data_hex=payload.hex())
            records.append(record)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    if not args.capture.is_file():
        parser.error("capture must be an existing regular file, never a device node")
    opener = gzip.open if args.capture.suffix == ".gz" else open
    try:
        with opener(args.capture, "rb") as stream:
            print(json.dumps(inspect(stream), indent=2))
    except (OSError, ValueError, struct.error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
