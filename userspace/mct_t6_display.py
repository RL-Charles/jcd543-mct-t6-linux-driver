#!/usr/bin/env python3
"""MCT Trigger T6 USB Display Driver for Linux.

First working Linux driver for StarTech USBC2HD4 and similar MCT T6 adapters.
Reverse-engineered from Windows USB packet captures.

Protocol discoveries:
- Pixel format: RBG (byte 0=Red, byte 1=Blue, byte 2=Green)
- Video header format=9, stride in bytes, embedded in first bulk chunk
- Session dest=0x30 for uncompressed raw frames
- Each T6 chip can expose two logical display outputs (0/1)
- VRAM stride may differ from pixel stride (needs per-device calibration)
- Init sequence: 0x1c(0,0) → 0x1c(0x100,0) → 0x31 → 0x23(40B) → 0x24(16B)
  → 0x12(mode,32B) → 0x03(enable) → 0x24(16B) → 0x1c(2,0)
- Commands 0x30/0x31 during frame loop crash the device

Usage:
    sudo pip3 install pyusb Pillow
    sudo python3 tools/drivers/mct_t6_display.py [--daemon] [--mirror]

    --daemon  Run continuously, auto-reconnect on USB disconnect
    --mirror  Mirror the primary display to T6 outputs (requires grim)

Install as service:
    sudo cp tools/drivers/mct-t6-display.service /etc/systemd/system/
    sudo systemctl enable mct-t6-display
    sudo systemctl start mct-t6-display

Based on: https://github.com/cyrozap/mct-usb-display-adapter-re
"""

import argparse
import atexit
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import io
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
import zlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s [mct-t6] %(message)s")
log = logging.getLogger("mct-t6")

try:
    import usb.core
    import usb.util
except ImportError:
    log.error("PyUSB required: sudo pip3 install pyusb")
    sys.exit(1)

# ── Constants ──────────────────────────────────────────────────────
VID, PID = 0x0711, 0x5601
REQ_OUT, REQ_IN = 0x40, 0xC0

# 1080p mode from Windows capture (32 bytes)
MODE_1080P = bytes.fromhex(
    "144402003c009808800718072c0065043804e8031d00bb02e8031d0101010000"
)

# Init data from Windows capture
INIT_0x23 = bytes.fromhex(
    "000000000000001f0000001f0000000f0000000f0000000f0000000f0000000f0000000f00000000"
)
INIT_0x24_PRE = bytes.fromhex("00000000000000008025000000000200")
INIT_0x24_POST = bytes.fromhex("01000000000000008025000000000200")

CHUNK_SIZE = 102400  # Matches Windows driver
BULK_CMD_HEADER_SIZE = 32
VIDEO_HEADER_SIZE = 0x30
FRAME_REFRESH_INTERVAL = 5.0
SECONDARY_REFRESH_INTERVAL = None
SECONDARY_FRAME_INTERVAL = 1.0
STABLE_HEALTH_INTERVAL = 15.0
JPEG_PADDING_SIZE = 1024
JPEG_FB_SLOT_COUNT = 3
JPEG_CMD_BUCKET_SIZES = (
    1024 * 1024,
    2 * 1024 * 1024,
    3 * 1024 * 1024,
)
JPEG_PROFILE_DEFAULTS = {
    "speed": (85, 2),
    "balanced": (95, 2),
    "text": (97, 0),
}
SECONDARY_SAFE_JPEG_QUALITY = 95
SECONDARY_SAFE_JPEG_SUBSAMPLING = 2
JPEG_PROFILE_CHOICES = ("auto",) + tuple(JPEG_PROFILE_DEFAULTS)
JPEG_QUALITY, JPEG_SUBSAMPLING = JPEG_PROFILE_DEFAULTS["balanced"]
VIDEO_CMD_FLIP_PRIMARY = 3
VIDEO_CMD_FLIP_SECONDARY = 4
VIDEO_COLOR_NV12 = 6
VIDEO_COLOR_RGB32 = 8
VIDEO_COLOR_JPEG = 13
_capture_backend = None
_capture_error_logged = False
_COSMIC_APP_ID = "mct-t6-display"
_SYSTEMD_USER_ENV_VARS = (
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
)
_DEFAULT_USER_SERVICE_ARGS = (
    "--mirror",
    "--fps",
    "1",
    "--reconnect-interval",
    "3",
    "--send-workers",
    "2",
    "--quality-profile",
    "balanced",
    "--jpeg-quality",
    "95",
    "--jpeg-subsampling",
    "2",
    "--stats-interval",
    "30",
)
_DEFAULT_USER_SERVICE_NAME = "mct-t6-display.service"


# ── Color conversion ───────────────────────────────────────────────
def rgb_to_bgrx(data: bytes) -> bytes:
    """Convert RGB pixel data to BGRX 32-bit format for T6.

    T6 VIDEO_COLOR_RGB32 (format=8) uses standard BGRX byte order:
    Blue, Green, Red, pad(0). Confirmed working on QG241Y + K272HL.
    Source: mcttrigger/triggerdm official driver.
    """
    out = bytearray(len(data) // 3 * 4)
    si, di = 0, 0
    while si < len(data):
        out[di] = data[si + 2]     # B
        out[di + 1] = data[si + 1]  # G
        out[di + 2] = data[si]      # R
        out[di + 3] = 0             # pad
        si += 3
        di += 4
    return bytes(out)


def _align(value: int, boundary: int) -> int:
    return ((value + boundary - 1) // boundary) * boundary


def resolve_jpeg_settings(profile: str, fps=None, quality=None, subsampling=None):
    if profile == "auto":
        if fps is None or fps <= 6:
            profile = "balanced"
        else:
            profile = "speed"

    resolved_quality, resolved_subsampling = JPEG_PROFILE_DEFAULTS[profile]
    if quality is not None:
        resolved_quality = quality
    if subsampling is not None:
        resolved_subsampling = subsampling
    return profile, resolved_quality, resolved_subsampling


def stabilize_secondary_jpeg_settings(
    profile: str,
    quality: int,
    subsampling: int,
    allow_unsafe=False,
):
    if allow_unsafe:
        return profile, quality, subsampling, False

    clamped_quality = min(quality, SECONDARY_SAFE_JPEG_QUALITY)
    clamped_subsampling = SECONDARY_SAFE_JPEG_SUBSAMPLING
    clamped = (
        clamped_quality != quality or clamped_subsampling != subsampling
    )
    if clamped:
        return "balanced", clamped_quality, clamped_subsampling, True

    return profile, quality, subsampling, False


def log_jpeg_settings(profile: str, quality: int, subsampling: int, clamped=False):
    if clamped:
        log.warning(
            "Requested secondary JPEG settings exceeded the known-good T6 output-1 envelope; clamped to quality<=%d and subsampling=%d",
            SECONDARY_SAFE_JPEG_QUALITY,
            SECONDARY_SAFE_JPEG_SUBSAMPLING,
        )
    elif subsampling != SECONDARY_SAFE_JPEG_SUBSAMPLING or quality > SECONDARY_SAFE_JPEG_QUALITY:
        log.warning(
            "Secondary JPEG quality=%d subsampling=%d is experimental on T6 output 1 and can blank the screen or misalign chroma; quality<=%d with subsampling=%d remains the known-good envelope",
            quality,
            subsampling,
            SECONDARY_SAFE_JPEG_QUALITY,
            SECONDARY_SAFE_JPEG_SUBSAMPLING,
        )
    log.info(
        "Secondary JPEG profile=%s quality=%d subsampling=%d",
        profile,
        quality,
        subsampling,
    )


@dataclass
class FrameSendResult:
    transport: str
    payload_bytes: int
    encode_ms: float
    usb_ms: float


@dataclass
class BatchSendSummary:
    failed_chips: set
    send_results: list[FrameSendResult]


class IntervalStats:
    def __init__(self, interval_s):
        self.interval_s = interval_s
        self._reset(time.monotonic())

    def _reset(self, now):
        self.window_started_at = now
        self.loop_count = 0
        self.output_samples = 0
        self.capture_count = 0
        self.capture_failures = 0
        self.ready_frames = 0
        self.frames_sent = 0
        self.raw_frames = 0
        self.jpeg_frames = 0
        self.failed_chips = 0
        self.capture_ms = 0.0
        self.prepare_ms = 0.0
        self.send_ms = 0.0
        self.encode_ms = 0.0
        self.usb_ms = 0.0
        self.payload_bytes = 0

    def record_cycle(
        self,
        output_count,
        ready_count,
        capture_ms=0.0,
        prepare_ms=0.0,
        send_ms=0.0,
        capture_ok=True,
        failed_chips=0,
    ):
        self.loop_count += 1
        self.output_samples += output_count
        self.ready_frames += ready_count
        self.capture_ms += capture_ms
        self.prepare_ms += prepare_ms
        self.send_ms += send_ms
        self.failed_chips += failed_chips
        if capture_ok:
            self.capture_count += 1
        else:
            self.capture_failures += 1

    def record_send_summary(self, summary):
        for result in summary.send_results:
            self.frames_sent += 1
            self.encode_ms += result.encode_ms
            self.usb_ms += result.usb_ms
            self.payload_bytes += result.payload_bytes
            if result.transport == "jpeg":
                self.jpeg_frames += 1
            else:
                self.raw_frames += 1

    def maybe_log(self, now):
        if self.interval_s <= 0:
            return

        elapsed = now - self.window_started_at
        if elapsed < self.interval_s:
            return

        avg_outputs = self.output_samples / self.loop_count if self.loop_count else 0.0
        avg_capture = self.capture_ms / self.capture_count if self.capture_count else 0.0
        avg_prepare = self.prepare_ms / self.loop_count if self.loop_count else 0.0
        avg_send = self.send_ms / self.loop_count if self.loop_count else 0.0
        avg_encode = self.encode_ms / self.frames_sent if self.frames_sent else 0.0
        avg_usb = self.usb_ms / self.frames_sent if self.frames_sent else 0.0
        mib_per_s = (self.payload_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0
        fps = self.frames_sent / elapsed if elapsed > 0 else 0.0

        log.info(
            "Stats %.0fs: loops=%d outputs(avg=%.1f) capture_fail=%d ready=%d sent=%d raw=%d jpeg=%d fps=%.2f payload=%.2f MiB/s capture_avg=%.1fms prepare_avg=%.1fms encode_avg=%.1fms usb_avg=%.1fms send_avg=%.1fms failed_chips=%d",
            elapsed,
            self.loop_count,
            avg_outputs,
            self.capture_failures,
            self.ready_frames,
            self.frames_sent,
            self.raw_frames,
            self.jpeg_frames,
            fps,
            mib_per_s,
            avg_capture,
            avg_prepare,
            avg_encode,
            avg_usb,
            avg_send,
            self.failed_chips,
        )
        self._reset(now)


# ── T6 Device ──────────────────────────────────────────────────────
class T6Output:
    """One physical output on an MCT T6 USB display adapter."""

    def __init__(self, dev, output_idx=0, ram_mb=58):
        self.dev = dev
        self.out = output_idx
        self.ram_mb = ram_mb
        self.ep = None
        self.width = 1920
        self.height = 1080
        self.stride = self.width * 4  # RBGX 32-bit
        self.seq = 1
        self.monitor_name = ""
        self._last_frame_crc = None
        self._last_frame_at = 0.0
        self._last_send_at = 0.0
        self._fb_addr = 0
        self._cmd_addr = 0
        self._fb_slots = []
        self._fb_slot_index = 0
        self._cmd_base_addr = 0
        self._cmd_limit_addr = 0
        self._cmd_cursor_addr = 0
        self._init_addressing()
        self._claim()

    def _reset_stream_state(self):
        if len(self._fb_slots) > 1:
            self._fb_slot_index = 1
        else:
            self._fb_slot_index = 0

        self._cmd_cursor_addr = self._cmd_base_addr
        self.seq = 1

    def _init_addressing(self):
        tmp = self.ram_mb - 18
        if self.out == 0:
            self._fb_addr = (tmp - 12) * 1024 * 1024
            self._cmd_addr = 0
            self._fb_slots = [self._fb_addr]
        else:
            self._cmd_addr = tmp * 1024 * 1024
            self._fb_slots = [
                (self.ram_mb - 12) * 1024 * 1024,
                (self.ram_mb - 8) * 1024 * 1024,
                (self.ram_mb - 4) * 1024 * 1024,
            ]
            self._fb_addr = self._fb_slots[0]

        self._cmd_base_addr = self._cmd_addr
        self._cmd_limit_addr = self._fb_slots[0] if self._fb_slots else self._fb_addr
        self._reset_stream_state()

    def _next_jpeg_transfer_addrs(self, total_payload):
        if total_payload <= JPEG_CMD_BUCKET_SIZES[0]:
            cmd_step = JPEG_CMD_BUCKET_SIZES[0]
        elif total_payload <= JPEG_CMD_BUCKET_SIZES[1]:
            cmd_step = JPEG_CMD_BUCKET_SIZES[1]
        elif total_payload <= JPEG_CMD_BUCKET_SIZES[2]:
            cmd_step = JPEG_CMD_BUCKET_SIZES[2]
        else:
            raise ValueError(
                f"JPEG payload {total_payload} exceeds the 3 MiB vendor cmd ring bucket"
            )

        cmd_addr = self._cmd_cursor_addr
        wrapped = False
        if (
            self._cmd_limit_addr > self._cmd_base_addr
            and cmd_addr + cmd_step > self._cmd_limit_addr
        ):
            cmd_addr = self._cmd_base_addr
            wrapped = True

        if len(self._fb_slots) > 1:
            fb_slot_index = (self._fb_slot_index + 1) % len(self._fb_slots)
        else:
            fb_slot_index = 0
        fb_addr = self._fb_slots[fb_slot_index] if self._fb_slots else self._fb_addr
        return cmd_addr, cmd_step, fb_addr, fb_slot_index, wrapped

    def _claim(self):
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
            self.dev.set_configuration()
        except Exception:
            pass
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]
        self.ep = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
        )

    def read_edid(self):
        """Read EDID and extract monitor info."""
        edid = bytearray()
        for off in range(0, 256, 128):
            try:
                edid.extend(
                    self.dev.ctrl_transfer(REQ_IN, 0x80, off, self.out, 128)
                )
            except Exception:
                break
        if len(edid) >= 128:
            self.width = edid[0x38] | ((edid[0x3A] & 0xF0) << 4)
            self.height = edid[0x3B] | ((edid[0x3D] & 0xF0) << 4)
            self.stride = self.width * 4  # RBGX 32-bit
            # Extract monitor name
            for i in range(0x36, 0x7E, 18):
                if (
                    len(edid) > i + 18
                    and edid[i] == 0
                    and edid[i + 1] == 0
                    and edid[i + 3] == 0xFC
                ):
                    self.monitor_name = (
                        bytes(edid[i + 5 : i + 18])
                        .decode("ascii", errors="replace")
                        .strip()
                    )
        return edid

    def is_connected(self):
        try:
            s = self.dev.ctrl_transfer(REQ_IN, 0x87, self.out, 0, 1)
            return s[0] == 1
        except Exception:
            return False

    def init(self):
        """Full Windows-compatible initialization sequence."""
        self.dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0000, 0)
        self.dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0100, 0)
        self.dev.ctrl_transfer(REQ_OUT, 0x23, 0, 0, INIT_0x23)
        self.dev.ctrl_transfer(REQ_OUT, 0x24, 0, 0, INIT_0x24_PRE)
        self.dev.ctrl_transfer(REQ_OUT, 0x12, self.out, 0, MODE_1080P)
        self.dev.ctrl_transfer(REQ_OUT, 0x31, self.out, 0)
        self.dev.ctrl_transfer(REQ_OUT, 0x03, self.out, 1)
        self.dev.ctrl_transfer(REQ_OUT, 0x24, 0, 0, INIT_0x24_POST)
        self.dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0002, 0)
        self._reset_stream_state()
        log.info(
            "Output init: %s (%dx%d)",
            self.monitor_name or "unknown",
            self.width,
            self.height,
        )

    def send_frame(self, rgb_data: bytes):
        if self.out == 1 and _HAS_PILLOW:
            return self._send_jpeg_frame(rgb_data)

        return self._send_raw_frame(rgb_data)

    def _send_raw_frame(self, rgb_data: bytes):
        """Send one frame of RGB data to the display.

        Input: raw RGB (3 bytes/pixel). Converted to BGRX (4 bytes/pixel).

        Protocol (from mcttrigger/triggerdm):
        - BULK_CMD_HEADER (32 bytes): Signature=0, PayloadAddr=fbAddr
        - VIDEO_FLIP_HEADER (48 bytes): Command=3(primary)/4(secondary),
          TargetFormat=8(RGB32), Y_RGB_Pitch=width*4, SourceFormat=8
        - Pixel data in BGRX format (B, G, R, 0)
        """
        bgrx = rgb_to_bgrx(rgb_data)
        frame_size = self.stride * self.height

        # Framebuffer addresses computed from RAM size (queried at init).
        # Formula from triggerdm: tmp = ram_mb - 18
        #   Output 0: fbAddr = (tmp - 12) * 1MB
        #   Output 1: fbAddr = (tmp + 6) * 1MB
        # For 58MB RAM: output 0 = 28MB = 0x01C00000, output 1 = 46MB = 0x02E00000
        fb_addr = self._fb_addr

        # VIDEO_FLIP_HEADER (48 bytes) per triggerdm protocol
        # Command: 3=FLIP_PRIMARY (output 0), 4=FLIP_SECONDARY (output 1)
        cmd = VIDEO_CMD_FLIP_PRIMARY if self.out == 0 else VIDEO_CMD_FLIP_SECONDARY
        pitch = self.stride  # width * 4 for RGB32

        vhdr = bytearray(0x30)
        struct.pack_into("<I", vhdr, 0x00, cmd)          # Command
        struct.pack_into("<I", vhdr, 0x04, frame_size)    # PayloadSize
        struct.pack_into("<I", vhdr, 0x08, 0)             # FenceID
        struct.pack_into("<I", vhdr, 0x0C, VIDEO_COLOR_RGB32)  # TargetFormat = RGB32
        struct.pack_into("<H", vhdr, 0x10, pitch)         # Y_RGB_Pitch (16-bit)
        struct.pack_into("<H", vhdr, 0x12, 0)             # UV_Pitch (16-bit, 0 for RGB)
        # Raw full-block uploads place the flip header at fb_addr and pixel
        # data immediately after it, matching TriggerDM's layout.
        struct.pack_into("<I", vhdr, 0x14, fb_addr + 0x30)  # Y_RGB_Data_FB_Offset
        struct.pack_into("<I", vhdr, 0x18, 0)             # U_UV_Data_Offset
        struct.pack_into("<I", vhdr, 0x1C, 0)             # V_Data_Offset
        struct.pack_into("<I", vhdr, 0x20, VIDEO_COLOR_RGB32)  # SourceFormat = RGB32
        # 0x24-0x2E: padding (zeros)
        # 0x2F: Flag — 0x80 resets JPEG engine (first 10 frames per triggerdm)
        if self.seq <= 10:
            vhdr[0x2F] = 0x80

        total_payload = VIDEO_HEADER_SIZE + frame_size
        video_payload = bytes(vhdr) + bgrx

        # TriggerDM's raw full-block path sends a single BULK_CMD_HEADER followed
        # by the complete video payload buffer.
        usb_started = time.monotonic()
        self.ep.write(
            struct.pack(
                "<IIIIII8x",
                0,              # Signature (display)
                total_payload,  # PayloadLength
                fb_addr,        # PayloadAddress
                total_payload,  # PacketLength
                0,              # Reserved2
                0,              # Reserved3
            ),
            timeout=5000,
        )
        self.ep.write(video_payload, timeout=15000)
        usb_ms = (time.monotonic() - usb_started) * 1000.0

        self.seq += 1
        return FrameSendResult(
            transport="raw",
            payload_bytes=BULK_CMD_HEADER_SIZE + total_payload,
            encode_ms=0.0,
            usb_ms=usb_ms,
        )

    def _send_jpeg_frame(self, rgb_data: bytes):
        """Send output 1 through the vendor-style JPEG command path.

        TriggerDM does not continuously drive 1080p outputs with the raw RGB32
        full-block path. It routes JPEG payloads through a per-output cmdAddr
        ring, adds 1024 bytes of tail padding, rotates across three fbAddr
        slots, and resets the decoder on early frames and cmd ring wrap.
        """
        encode_started = time.monotonic()
        image = _PILImage.frombytes("RGB", (self.width, self.height), rgb_data)
        buffer = io.BytesIO()
        image.save(
            buffer,
            format="JPEG",
            quality=JPEG_QUALITY,
            subsampling=JPEG_SUBSAMPLING,
        )
        jpg_data = buffer.getvalue()
        encode_ms = (time.monotonic() - encode_started) * 1000.0

        total_payload = len(jpg_data) + VIDEO_HEADER_SIZE + JPEG_PADDING_SIZE
        cmd_addr, cmd_step, fb_addr, fb_slot_index, wrapped = self._next_jpeg_transfer_addrs(
            total_payload
        )
        video_payload = bytearray(total_payload)
        y_pitch = _align(self.width, 32)
        y_block_size = y_pitch * _align(self.height, 32) + JPEG_PADDING_SIZE
        cmd = VIDEO_CMD_FLIP_PRIMARY if self.out == 0 else VIDEO_CMD_FLIP_SECONDARY

        struct.pack_into("<I", video_payload, 0x00, cmd)
        struct.pack_into("<I", video_payload, 0x04, total_payload - 0x30)
        struct.pack_into("<I", video_payload, 0x08, 0)
        struct.pack_into("<I", video_payload, 0x0C, VIDEO_COLOR_NV12)
        struct.pack_into("<H", video_payload, 0x10, y_pitch)
        struct.pack_into("<H", video_payload, 0x12, y_pitch)
        struct.pack_into("<I", video_payload, 0x14, fb_addr)
        struct.pack_into("<I", video_payload, 0x18, fb_addr + y_block_size)
        struct.pack_into("<I", video_payload, 0x1C, 0)
        struct.pack_into("<I", video_payload, 0x20, VIDEO_COLOR_JPEG)
        if self.seq <= 10 or wrapped:
            video_payload[0x2F] = 0x80
        video_payload[VIDEO_HEADER_SIZE : VIDEO_HEADER_SIZE + len(jpg_data)] = jpg_data

        usb_started = time.monotonic()
        self.ep.write(
            struct.pack(
                "<IIIIII8x",
                0,
                total_payload,
                cmd_addr,
                total_payload,
                0,
                0,
            ),
            timeout=5000,
        )
        self.ep.write(bytes(video_payload), timeout=5000)
        usb_ms = (time.monotonic() - usb_started) * 1000.0

        self.seq += 1
        self._cmd_cursor_addr = cmd_addr + cmd_step
        self._fb_slot_index = fb_slot_index
        return FrameSendResult(
            transport="jpeg",
            payload_bytes=BULK_CMD_HEADER_SIZE + total_payload,
            encode_ms=encode_ms,
            usb_ms=usb_ms,
        )

    def prime(self, frames=5):
        """Send black frames to stabilize output after init.

        Multi-output chips need a few frames to clear internal buffers
        and lock the HDMI signal before real content is sent.
        """
        black = bytes(self.width * self.height * 3)
        for _ in range(frames):
            try:
                self.send_frame(black)
            except Exception:
                pass

    def needs_frame(self, rgb_data: bytes, refresh_interval=None):
        """Avoid continuously rewriting identical frames.

        The secondary head is noticeably more prone to bleed when the same
        framebuffer is blasted repeatedly. Periodic refreshes keep the output
        from going stale without hammering unchanged content.
        """
        if refresh_interval is None:
            refresh_interval = (
                SECONDARY_REFRESH_INTERVAL if self.out == 1 else FRAME_REFRESH_INTERVAL
            )

        frame_crc = zlib.crc32(rgb_data) & 0xFFFFFFFF
        now = time.monotonic()
        min_frame_interval = SECONDARY_FRAME_INTERVAL if self.out == 1 else 0.0

        if min_frame_interval and now - self._last_send_at < min_frame_interval:
            return False

        if frame_crc == self._last_frame_crc:
            if refresh_interval is None:
                return False
            if now - self._last_frame_at < refresh_interval:
                return False

        self._last_frame_crc = frame_crc
        self._last_frame_at = now
        self._last_send_at = now
        return True

    def disable(self):
        try:
            self.dev.ctrl_transfer(REQ_OUT, 0x03, self.out, 0)
        except Exception:
            pass

    def close(self):
        self.disable()
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass


# ── Discovery ──────────────────────────────────────────────────────
def get_device_ram_mb(dev):
    """Read video RAM size, falling back to the common 58MB default."""
    try:
        ram_data = dev.ctrl_transfer(REQ_IN, 0x88, 0, 0, 4)
        return struct.unpack("<I", ram_data)[0]
    except Exception:
        return 58


def read_output_status(dev, output_idx):
    return dev.ctrl_transfer(REQ_IN, 0x87, output_idx, 0, 1)[0]


def chip_key(target):
    dev = target.dev if hasattr(target, "dev") else target
    return dev.bus, dev.address


def close_outputs(outputs):
    for out in outputs:
        try:
            out.close()
        except Exception:
            pass


def probe_device_outputs(dev, label="Found"):
    ram_mb = get_device_ram_mb(dev)
    outputs = []
    for out_idx in range(2):
        try:
            t6 = T6Output(dev, output_idx=out_idx, ram_mb=ram_mb)
            t6.read_edid()
            if t6.is_connected():
                outputs.append(t6)
                if label:
                    log.info(
                        "%s: %s (%dx%d) bus=%d addr=%d out=%d ram=%dMB fb=0x%08X",
                        label,
                        t6.monitor_name,
                        t6.width,
                        t6.height,
                        dev.bus,
                        dev.address,
                        out_idx,
                        ram_mb,
                        t6._fb_addr,
                    )
            else:
                t6.close()
        except Exception as e:
            log.debug(
                "Failed to probe device bus=%d addr=%d out=%d: %s",
                dev.bus,
                dev.address,
                out_idx,
                e,
            )
    return outputs


def init_outputs(outputs):
    """Initialize every connected output, grouped per T6 chip."""
    if not outputs:
        return

    chips: dict[tuple, list] = defaultdict(list)
    for out in outputs:
        chips[(out.dev.bus, out.dev.address)].append(out)

    for chip_outs in chips.values():
        chip_outs.sort(key=lambda out: out.out)
        dev = chip_outs[0].dev

        dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0000, 0)
        dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0100, 0)
        dev.ctrl_transfer(REQ_OUT, 0x23, 0, 0, INIT_0x23)
        dev.ctrl_transfer(REQ_OUT, 0x24, 0, 0, INIT_0x24_PRE)
        for out in chip_outs:
            dev.ctrl_transfer(REQ_OUT, 0x12, out.out, 0, MODE_1080P)
            dev.ctrl_transfer(REQ_OUT, 0x31, out.out, 0)
            dev.ctrl_transfer(REQ_OUT, 0x03, out.out, 1)
            out.seq = 1
            log.info(
                "  Output %d: %s (%dx%d) fb=0x%08X",
                out.out,
                out.monitor_name,
                out.width,
                out.height,
                out._fb_addr,
            )
        dev.ctrl_transfer(REQ_OUT, 0x24, 0, 0, INIT_0x24_POST)
        dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0002, 0)
        for out in chip_outs:
            out.prime(frames=8)


def find_outputs():
    """Find all T6 devices and create output objects."""
    devices = sorted(
        usb.core.find(find_all=True, idVendor=VID, idProduct=PID),
        key=lambda d: (d.bus, d.address),
    )
    outputs = []
    for dev in devices:
        outputs.extend(probe_device_outputs(dev, label="Found"))
    return outputs


# ── Optional Pillow ────────────────────────────────────────────────
try:
    from PIL import Image as _PILImage

    _HAS_PILLOW = True
except ImportError:
    _HAS_PILLOW = False

try:
    import gi

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    gi.require_version("Gst", "1.0")
    gi.require_version("GstVideo", "1.0")

    from gi.repository import Gio, GLib, Gst, GstVideo

    Gst.init(None)
    _HAS_PORTAL_CAPTURE = True
except Exception:
    Gio = GLib = Gst = GstVideo = None
    _HAS_PORTAL_CAPTURE = False

_portal_capture = None
_portal_retry_after = 0.0


# ── Screen capture ─────────────────────────────────────────────────
def _variant_to_python(value):
    if _HAS_PORTAL_CAPTURE and isinstance(value, GLib.Variant):
        return _variant_to_python(value.unpack())
    if isinstance(value, dict):
        return {k: _variant_to_python(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_variant_to_python(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_variant_to_python(v) for v in value)
    return value


def _cosmic_restore_path():
    state_home = os.environ.get("XDG_STATE_HOME")
    if not state_home:
        state_home = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state_home, "mct-t6-display", "cosmic-restore.json")


def _normalize_cosmic_restore_data(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None

    vendor, version, payload = value
    if not isinstance(vendor, str) or not isinstance(version, int):
        return None
    if not isinstance(payload, (list, tuple)) or len(payload) != 2:
        return None

    outputs, toplevels = payload
    if not isinstance(outputs, (list, tuple)) or not isinstance(toplevels, (list, tuple)):
        return None
    if not all(isinstance(name, str) for name in outputs):
        return None
    if not all(isinstance(name, str) for name in toplevels):
        return None

    return vendor, version, (list(outputs), list(toplevels))


def _normalize_cosmic_restore_token(value):
    if not isinstance(value, str) or not value:
        return None
    return value


def _normalize_cosmic_restore_state(value):
    if isinstance(value, dict):
        restore_data = _normalize_cosmic_restore_data(value.get("restore_data"))
        restore_token = _normalize_cosmic_restore_token(value.get("restore_token"))
        if not restore_data and not restore_token:
            return None
        return {
            "restore_data": restore_data,
            "restore_token": restore_token,
        }

    restore_data = _normalize_cosmic_restore_data(value)
    if not restore_data:
        return None
    return {
        "restore_data": restore_data,
        "restore_token": None,
    }


def _load_cosmic_restore_state():
    path = _cosmic_restore_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        log.debug("Failed to load COSMIC restore data: %s", e)
        return None

    data = _normalize_cosmic_restore_state(data)
    if not data:
        log.debug("Ignoring invalid COSMIC restore data at %s", path)
    return data


def _save_cosmic_restore_state(value):
    value = _normalize_cosmic_restore_state(value)
    if not value:
        return

    path = _cosmic_restore_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            payload = {}
            if value["restore_data"]:
                restore_data = value["restore_data"]
                payload["restore_data"] = [
                    restore_data[0],
                    restore_data[1],
                    [restore_data[2][0], restore_data[2][1]],
                ]
            if value["restore_token"]:
                payload["restore_token"] = value["restore_token"]
            json.dump(payload, f)
    except OSError as e:
        log.debug("Failed to save COSMIC restore data: %s", e)


def _clear_cosmic_restore_data():
    path = _cosmic_restore_path()
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as e:
        log.debug("Failed to clear COSMIC restore data: %s", e)


def _cosmic_restore_data_variant(value):
    value = _normalize_cosmic_restore_data(value)
    if not value:
        return None

    vendor, version, payload = value
    outputs, toplevels = payload
    return GLib.Variant(
        "(suv)",
        (vendor, version, GLib.Variant("(asas)", (outputs, toplevels))),
    )


class PortalScreenCastCapture:
    """Capture the desktop through xdg-desktop-portal and PipeWire."""

    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.session_handle = None
        self.pipeline = None
        self.appsink = None
        self.node_id = None
        self.latest_frame = None
        self.failed = False
        restore_state = _load_cosmic_restore_state() or {}
        self.restore_data = restore_state.get("restore_data")
        self.restore_token = restore_state.get("restore_token")

    def _sender_path(self):
        return self.bus.get_unique_name().lstrip(":").replace(".", "_")

    def _request_path(self, token):
        return f"/org/freedesktop/portal/desktop/request/{self._sender_path()}/{token}"

    def _session_path(self, token):
        return f"/org/freedesktop/portal/desktop/session/{self._sender_path()}/{token}"

    def _call_portal_request(self, method, params, timeout_ms=120000):
        request_token = f"mct{uuid.uuid4().hex}"
        request_path = self._request_path(request_token)
        response = {}
        loop = GLib.MainLoop()

        def on_response(_conn, _sender, _path, _interface, _signal, parameters, _data):
            response["payload"] = _variant_to_python(parameters)
            loop.quit()

        sub_id = self.bus.signal_subscribe(
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Request",
            "Response",
            request_path,
            None,
            Gio.DBusSignalFlags.NONE,
            on_response,
            None,
        )

        def on_timeout():
            response["timed_out"] = True
            loop.quit()
            return False

        timeout_source = GLib.timeout_add(timeout_ms, on_timeout)
        try:
            self.bus.call_sync(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.ScreenCast",
                method,
                params(request_token),
                GLib.VariantType("(o)"),
                Gio.DBusCallFlags.NONE,
                timeout_ms,
                None,
            )
            loop.run()
        finally:
            GLib.source_remove(timeout_source)
            self.bus.signal_unsubscribe(sub_id)

        if response.get("timed_out"):
            raise RuntimeError(f"Portal screencast request {method} timed out")

        code, results = response.get("payload", (2, {}))
        if code != 0:
            raise RuntimeError(f"Portal screencast request {method} failed with response={code}")
        return _variant_to_python(results)

    def _persist_restore_state(self):
        state = {
            "restore_data": self.restore_data,
            "restore_token": self.restore_token,
        }
        if state["restore_data"] or state["restore_token"]:
            _save_cosmic_restore_state(state)
        else:
            _clear_cosmic_restore_data()

    def _update_restore_state(self, results):
        restore_token = _normalize_cosmic_restore_token(results.get("restore_token"))
        restore_data = _normalize_cosmic_restore_data(results.get("restore_data"))
        changed = False

        if restore_token and restore_token != self.restore_token:
            self.restore_token = restore_token
            changed = True
        if restore_data and restore_data != self.restore_data:
            self.restore_data = restore_data
            changed = True

        if changed:
            self._persist_restore_state()

    def _start_session(self, restore_token=None, restore_data=None):
        session_token = f"mct{uuid.uuid4().hex}"
        create_results = self._call_portal_request(
            "CreateSession",
            lambda request_token: GLib.Variant(
                "(a{sv})",
                (
                    {
                        "handle_token": GLib.Variant("s", request_token),
                        "session_handle_token": GLib.Variant("s", session_token),
                    },
                ),
            ),
        )
        self.session_handle = create_results.get("session_handle") or self._session_path(session_token)

        select_results = self._call_portal_request(
            "SelectSources",
            lambda request_token: GLib.Variant(
                "(oa{sv})",
                (
                    self.session_handle,
                    {
                        "handle_token": GLib.Variant("s", request_token),
                        "types": GLib.Variant("u", 1),
                        "multiple": GLib.Variant("b", False),
                        "cursor_mode": GLib.Variant("u", 2),
                        "persist_mode": GLib.Variant("u", 2),
                        **(
                            {"restore_token": GLib.Variant("s", restore_token)}
                            if restore_token
                            else {}
                        ),
                    },
                ),
            ),
        )
        self._update_restore_state(select_results)

        start_results = self._call_portal_request(
            "Start",
            lambda request_token: GLib.Variant(
                "(osa{sv})",
                (
                    self.session_handle,
                    "",
                    {"handle_token": GLib.Variant("s", request_token)},
                ),
            ),
        )
        self._update_restore_state(start_results)
        streams = start_results.get("streams") or []
        if not streams:
            raise RuntimeError("Portal screencast started without returning a stream")
        self.node_id = streams[0][0]

    def _ensure_pipeline(self):
        if self.pipeline or self.failed:
            return

        startup_error = None
        attempts = []
        if self.restore_token:
            attempts.append(
                {
                    "restore_token": self.restore_token,
                    "restore_data": None,
                }
            )
        attempts.append({"restore_token": None, "restore_data": None})
        fresh_retry_used = False
        for restore_state in attempts:
            try:
                self._start_session(
                    restore_token=restore_state["restore_token"],
                    restore_data=restore_state["restore_data"],
                )
                break
            except Exception as e:
                startup_error = e
                self.session_handle = None
                self.node_id = None
                used_restore_state = (
                    restore_state["restore_token"] is not None
                    or restore_state["restore_data"] is not None
                )
                if (
                    not used_restore_state
                    and not fresh_retry_used
                    and "Timeout was reached" in str(e)
                ):
                    fresh_retry_used = True
                    time.sleep(0.2)
                    continue
                if not used_restore_state:
                    raise

                log.warning(
                    "Persisted portal share could not be restored; requesting a fresh desktop share"
                )
                self.restore_data = None
                self.restore_token = None
                _clear_cosmic_restore_data()
        else:
            raise startup_error

        pipeline = Gst.parse_launch(
            "pipewiresrc path={path} do-timestamp=true keepalive-time=1000 "
            "on-disconnect=error ! videoconvert ! video/x-raw,format=RGB ! "
            "appsink name=sink emit-signals=false max-buffers=1 drop=true sync=false"
            .format(path=self.node_id)
        )
        sink = pipeline.get_by_name("sink")
        if not sink:
            raise RuntimeError("Failed to create GStreamer appsink for COSMIC capture")

        pipeline.set_state(Gst.State.PLAYING)
        state_change, _state, _pending = pipeline.get_state(5 * Gst.SECOND)
        if state_change == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("PipeWire capture pipeline failed to start for COSMIC")

        self.pipeline = pipeline
        self.appsink = sink

    def _check_pipeline(self):
        if not self.pipeline:
            return
        msg = self.pipeline.get_bus().timed_pop_filtered(
            0,
            Gst.MessageType.ERROR | Gst.MessageType.EOS,
        )
        if not msg:
            return
        if msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            raise RuntimeError(f"PipeWire capture error: {err}; {debug}")
        raise RuntimeError("PipeWire capture stream ended")

    def get_frame(self):
        self._ensure_pipeline()
        self._check_pipeline()

        sample = self.appsink.emit("try-pull-sample", 500 * Gst.MSECOND)
        if sample is None:
            return self.latest_frame

        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")
        if not width or not height:
            raise RuntimeError("Failed to parse GStreamer caps for COSMIC capture")

        buffer = sample.get_buffer()
        ok, map_info = buffer.map(Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError("Failed to map GStreamer buffer for COSMIC capture")

        try:
            row_len = width * 3
            row_stride = len(map_info.data) // height
            raw = memoryview(map_info.data)
            if row_stride == row_len:
                rgb = bytes(raw[: row_stride * height])
            else:
                out = bytearray(row_len * height)
                for row in range(height):
                    src = row * row_stride
                    dst = row * row_len
                    out[dst : dst + row_len] = raw[src : src + row_len]
                rgb = bytes(out)
        finally:
            buffer.unmap(map_info)

        self.latest_frame = (width, height, rgb)
        return self.latest_frame

    def close(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.appsink = None
        if self.session_handle:
            try:
                self.bus.call_sync(
                    "org.freedesktop.portal.Desktop",
                    self.session_handle,
                    "org.freedesktop.portal.Session",
                    "Close",
                    None,
                    None,
                    Gio.DBusCallFlags.NONE,
                    5000,
                    None,
                )
            except Exception:
                pass
        self.session_handle = None


def _capture_with_portal_screencast():
    global _portal_capture, _portal_retry_after

    if not _HAS_PORTAL_CAPTURE:
        return None

    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        return None

    if _portal_retry_after and time.monotonic() < _portal_retry_after:
        return None

    if _portal_capture is None:
        _portal_capture = PortalScreenCastCapture()

    try:
        frame = _portal_capture.get_frame()
        if frame:
            _portal_retry_after = 0.0
            _log_capture_backend("portal-screencast")
        return frame
    except Exception as e:
        log.error("Portal screencast failed: %s", e)
        if isinstance(_portal_capture, PortalScreenCastCapture):
            _portal_capture.close()
        _portal_capture = None
        _portal_retry_after = time.monotonic() + 5.0
        return None


def close_capture_backend():
    global _portal_capture

    if isinstance(_portal_capture, PortalScreenCastCapture):
        _portal_capture.close()
    _portal_capture = None


atexit.register(close_capture_backend)


def _parse_ppm(data: bytes):
    """Parse PPM binary data. Returns (width, height, rgb_bytes)."""
    # PPM P6 format: "P6\nWIDTH HEIGHT\n255\n<data>"
    # Handle optional comments (lines starting with #)
    idx = data.index(b"\n") + 1  # skip "P6"
    while data[idx : idx + 1] == b"#":
        idx = data.index(b"\n", idx) + 1
    dim_end = data.index(b"\n", idx)
    parts = data[idx:dim_end].split()
    cap_w, cap_h = int(parts[0]), int(parts[1])
    # Skip maxval line ("255")
    pixel_start = data.index(b"\n", dim_end + 1) + 1
    rgb = data[pixel_start : pixel_start + cap_w * cap_h * 3]
    return cap_w, cap_h, rgb


def _resize_rgb(rgb: bytes, src_w: int, src_h: int, dst_w: int, dst_h: int) -> bytes:
    """Resize RGB data to target resolution. Uses Pillow if available, else truncates."""
    if src_w == dst_w and src_h == dst_h:
        return rgb
    if _HAS_PILLOW:
        img = _PILImage.frombytes("RGB", (src_w, src_h), rgb)
        img = img.resize((dst_w, dst_h), _PILImage.LANCZOS)
        return img.tobytes()
    # Fallback: nearest-neighbor crop/pad without Pillow
    log.debug("Pillow unavailable — falling back to raw truncation for resize")
    src_stride = src_w * 3
    dst_stride = dst_w * 3
    out = bytearray(dst_w * dst_h * 3)
    copy_w = min(src_stride, dst_stride)
    for y in range(min(src_h, dst_h)):
        out[y * dst_stride : y * dst_stride + copy_w] = rgb[
            y * src_stride : y * src_stride + copy_w
        ]
    return bytes(out)


def _log_capture_backend(name):
    global _capture_backend

    if _capture_backend != name:
        _capture_backend = name
        log.info("Using screen capture backend: %s", name)


def _capture_with_grim():
    proc = subprocess.run(["grim", "-t", "ppm", "-"], capture_output=True, timeout=2)
    if proc.returncode != 0:
        return None
    _log_capture_backend("grim")
    return _parse_ppm(proc.stdout)


def _capture_with_gnome_screenshot():
    if not _HAS_PILLOW:
        return None

    fd, path = tempfile.mkstemp(prefix="mct-t6-", suffix=".png")
    os.close(fd)
    try:
        proc = subprocess.run(
            ["gnome-screenshot", "-f", path], capture_output=True, timeout=5
        )
        if proc.returncode != 0:
            if proc.stderr:
                log.debug("gnome-screenshot failed: %s", proc.stderr.decode("utf-8", errors="replace").strip())
            return None

        with _PILImage.open(path) as img:
            img = img.convert("RGB")
            _log_capture_backend("gnome-screenshot")
            return img.width, img.height, img.tobytes()
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def capture_desktop():
    """Capture the full desktop layout using the best backend available."""
    global _capture_error_logged

    desktop_name = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

    if "COSMIC" in desktop_name:
        data = _capture_with_portal_screencast()
        if data:
            _capture_error_logged = False
            return data

        if not _capture_error_logged:
            log.error(
                "COSMIC requires the portal screencast backend for non-disruptive capture. On first run, approve the share prompt once; later runs should reuse the saved portal permission."
            )
            _capture_error_logged = True
        return None

    for backend, runner in (
        ("grim", _capture_with_grim),
        ("portal-screencast", _capture_with_portal_screencast),
        ("gnome-screenshot", _capture_with_gnome_screenshot),
    ):
        if backend == "portal-screencast" or shutil.which(backend):
            try:
                data = runner()
                if data:
                    _capture_error_logged = False
                    return data
            except Exception as e:
                log.debug("%s capture failed: %s", backend, e)

    if not _capture_error_logged:
        log.error(
            "No supported screen capture backend found. Install grim for wlroots or gnome-screenshot for GNOME/Pop!_OS."
        )
        if not _HAS_PILLOW:
            log.error("Pillow is required when using the gnome-screenshot backend.")
        _capture_error_logged = True
    return None


def crop_rgb(rgb: bytes, src_w: int, src_h: int, region):
    """Crop a region from raw RGB data, padding out-of-bounds with black."""
    if region is None:
        return src_w, src_h, rgb

    x, y, width, height = region
    out = bytearray(width * height * 3)

    for row in range(height):
        src_y = y + row
        if src_y < 0 or src_y >= src_h:
            continue

        src_x0 = max(x, 0)
        src_x1 = min(x + width, src_w)
        if src_x0 >= src_x1:
            continue

        row_width = src_x1 - src_x0
        dst_x = src_x0 - x
        src_start = (src_y * src_w + src_x0) * 3
        dst_start = (row * width + dst_x) * 3
        out[dst_start : dst_start + row_width * 3] = rgb[
            src_start : src_start + row_width * 3
        ]

    return width, height, bytes(out)


def extract_screen_region(
    rgb: bytes,
    src_w: int,
    src_h: int,
    region,
    target_w: int,
    target_h: int,
):
    """Crop and resize the captured desktop for one T6 output."""
    crop_w, crop_h, crop = crop_rgb(rgb, src_w, src_h, region)
    return _resize_rgb(crop, crop_w, crop_h, target_w, target_h)


def capture_screen(target_w=None, target_h=None, region=None):
    """Capture the primary display (or a region) as RGB bytes.

    Args:
        target_w: Desired output width. If capture differs, will resize.
        target_h: Desired output height. If capture differs, will resize.
        region: Optional (x, y, w, h) tuple for grim -g region capture.

    Returns:
        RGB bytes sized to target_w x target_h, or None on failure.
    """
    desktop = capture_desktop()
    if not desktop:
        return None

    cap_w, cap_h, rgb = desktop
    if target_w is None:
        target_w = cap_w
    if target_h is None:
        target_h = cap_h

    try:
        return extract_screen_region(rgb, cap_w, cap_h, region, target_w, target_h)
    except Exception as e:
        log.debug("Screen capture failed: %s", e)
        return None


# ── Hotplug / Reconnect ───────────────────────────────────────────
def check_outputs_alive(outputs):
    """Remove failed chips from the live set. Returns still-usable outputs."""
    alive = []
    chips = defaultdict(list)
    for out in outputs:
        chips[chip_key(out)].append(out)

    for (bus, address), chip_outputs in chips.items():
        chip_failed = False
        reason = None
        for out in chip_outputs:
            try:
                status = read_output_status(out.dev, out.out)
                if status != 1:
                    chip_failed = True
                    reason = f"output {out.out} disconnected"
                    break
            except Exception as e:
                chip_failed = True
                reason = str(e)
                break

        if chip_failed:
            log.warning(
                "Chip lost: bus=%d addr=%d (%s) — dropping all outputs on that chip",
                bus,
                address,
                reason or "probe failed",
            )
            close_outputs(chip_outputs)
            continue

        alive.extend(chip_outputs)

    return alive


def drop_failed_chips(outputs, failed_chips):
    if not failed_chips:
        return outputs

    kept = []
    for out in outputs:
        if chip_key(out) in failed_chips:
            continue
        kept.append(out)

    close_outputs([out for out in outputs if chip_key(out) in failed_chips])
    return kept


def refresh_outputs(existing):
    """Re-scan USB bus, add new chips, and pick up new outputs on live chips."""
    known_outputs = defaultdict(list)
    for out in existing:
        known_outputs[chip_key(out)].append(out)

    devices = sorted(
        usb.core.find(find_all=True, idVendor=VID, idProduct=PID),
        key=lambda d: (d.bus, d.address),
    )
    refreshed = []
    for dev in devices:
        ckey = chip_key(dev)
        chip_outputs = known_outputs.pop(ckey, [])

        if not chip_outputs:
            added = probe_device_outputs(dev, label="Hotplug")
            if added:
                init_outputs(added)
                refreshed.extend(added)
            continue

        chip_outputs.sort(key=lambda out: out.out)
        missing_outputs = [out_idx for out_idx in range(2) if out_idx not in {out.out for out in chip_outputs}]
        if not missing_outputs:
            refreshed.extend(chip_outputs)
            continue

        detected_outputs = []
        probe_dev = chip_outputs[0].dev
        for out_idx in missing_outputs:
            try:
                if read_output_status(probe_dev, out_idx) == 1:
                    detected_outputs.append(out_idx)
            except Exception as e:
                log.debug(
                    "Failed to probe missing output on bus=%d addr=%d out=%d: %s",
                    probe_dev.bus,
                    probe_dev.address,
                    out_idx,
                    e,
                )

        if not detected_outputs:
            refreshed.extend(chip_outputs)
            continue

        log.info(
            "Hotplug: chip bus=%d addr=%d gained output(s) %s — reinitializing chip",
            probe_dev.bus,
            probe_dev.address,
            ",".join(str(out_idx) for out_idx in detected_outputs),
        )
        close_outputs(chip_outputs)

        reprobed_outputs = probe_device_outputs(dev, label="Hotplug")
        if reprobed_outputs:
            init_outputs(reprobed_outputs)
            refreshed.extend(reprobed_outputs)

    for chip_outputs in known_outputs.values():
        refreshed.extend(chip_outputs)

    return refreshed


def send_chip_batch(batch):
    batch = sorted(batch, key=lambda item: item[0].out)
    send_results = []
    for out, frame in batch:
        send_results.append(out.send_frame(frame))
    return send_results


def send_frame_batches(send_executor, output_frames):
    chip_batches = defaultdict(list)
    for out, frame in output_frames:
        chip_batches[chip_key(out)].append((out, frame))

    summary = BatchSendSummary(failed_chips=set(), send_results=[])
    futures = {}
    for ckey, batch in chip_batches.items():
        futures[send_executor.submit(send_chip_batch, batch)] = (ckey, batch)

    for future, (ckey, batch) in futures.items():
        out = batch[0][0]
        try:
            summary.send_results.extend(future.result())
        except usb.core.USBError as e:
            summary.failed_chips.add(ckey)
            log.warning(
                "USB error on chip bus=%d addr=%d via %s: %s",
                out.dev.bus,
                out.dev.address,
                out.monitor_name,
                e,
            )
        except Exception as e:
            summary.failed_chips.add(ckey)
            log.warning(
                "Frame send failed on chip bus=%d addr=%d via %s: %s",
                out.dev.bus,
                out.dev.address,
                out.monitor_name,
                e,
            )

    return summary


def compute_regions(outputs, layout):
    """Compute capture regions for each output based on layout.

    For "mirror": all outputs get None (full screen capture).
    For "extend-right": outputs are arranged left-to-right,
        each capturing its own horizontal slice of the virtual desktop.
    """
    if layout == "mirror" or len(outputs) <= 1:
        return [None] * len(outputs)

    # extend-right: place outputs side by side
    regions = []
    x_offset = 0
    for out in outputs:
        regions.append((x_offset, 0, out.width, out.height))
        x_offset += out.width
    return regions


def health_check_interval(outputs, retry_interval):
    if not outputs:
        return retry_interval
    return max(retry_interval, STABLE_HEALTH_INTERVAL)


def _systemd_quote(arg):
    if not arg:
        return '""'
    if any(ch.isspace() or ch in {'"', "\\"} for ch in arg):
        escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return arg


def render_user_service_unit(python_executable=None):
    if python_executable is None:
        python_executable = sys.executable

    exec_args = [python_executable, "-m", "mct_t6_display", *_DEFAULT_USER_SERVICE_ARGS]
    exec_start = " ".join(_systemd_quote(arg) for arg in exec_args)
    pass_environment = " ".join(_SYSTEMD_USER_ENV_VARS)

    return textwrap.dedent(
        f"""\
        [Unit]
        Description=MCT Trigger T6 USB Display Driver
        After=graphical-session.target
        PartOf=graphical-session.target

        [Service]
        Type=simple
        ExecStart={exec_start}
        Restart=always
        RestartSec=3
        Environment=PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
        PassEnvironment={pass_environment}

        [Install]
        WantedBy=default.target
        """
    )


def _run_optional_command(command):
    if shutil.which(command[0]) is None:
        return None

    return subprocess.run(command, check=False, text=True, capture_output=True)


def install_user_service_main():
    parser = argparse.ArgumentParser(description="Install the mct-t6-display user systemd service")
    parser.add_argument(
        "--unit-path",
        help="Override the output unit path (default: ~/.config/systemd/user/mct-t6-display.service)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated systemd unit instead of installing it",
    )
    args = parser.parse_args()

    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    unit_path = Path(args.unit_path) if args.unit_path else config_home / "systemd" / "user" / _DEFAULT_USER_SERVICE_NAME
    unit_text = render_user_service_unit()

    if args.dry_run:
        print(unit_text, end="")
        return 0

    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(unit_text, encoding="utf-8")
    log.info("Installed %s", unit_path)

    _run_optional_command(["systemctl", "--user", "import-environment", *_SYSTEMD_USER_ENV_VARS])
    _run_optional_command(["dbus-update-activation-environment", "--systemd", *_SYSTEMD_USER_ENV_VARS])

    daemon_reload = _run_optional_command(["systemctl", "--user", "daemon-reload"])
    if daemon_reload is None:
        log.error("systemctl not found; the user service file was written but could not be enabled")
        return 1
    if daemon_reload.returncode != 0:
        log.error("systemctl --user daemon-reload failed: %s", (daemon_reload.stderr or daemon_reload.stdout or "").strip())
        return daemon_reload.returncode

    enable = _run_optional_command(["systemctl", "--user", "enable", "--now", _DEFAULT_USER_SERVICE_NAME])
    if enable is None:
        log.error("systemctl not found; the user service file was written but could not be enabled")
        return 1
    if enable.returncode != 0:
        log.error("systemctl --user enable --now failed: %s", (enable.stderr or enable.stdout or "").strip())
        return enable.returncode

    status = _run_optional_command(["systemctl", "--user", "--no-pager", "--full", "status", _DEFAULT_USER_SERVICE_NAME])
    if status and status.stdout:
        print(status.stdout, end="")
    elif status and status.stderr:
        print(status.stderr, end="", file=sys.stderr)

    return 0


# ── Main ───────────────────────────────────────────────────────────
def main():
    global JPEG_QUALITY, JPEG_SUBSAMPLING

    parser = argparse.ArgumentParser(description="MCT T6 USB Display Driver")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument(
        "--mirror", action="store_true", help="Mirror primary display"
    )
    parser.add_argument("--fps", type=int, default=10, help="Target FPS (default: 10)")
    parser.add_argument(
        "--layout",
        default="mirror",
        help='Display layout: "mirror" (default) or "extend-right"',
    )
    parser.add_argument(
        "--reconnect-interval",
        type=int,
        default=10,
        help="Seconds between reconnect checks in daemon/mirror mode (default: 10)",
    )
    parser.add_argument(
        "--send-workers",
        type=int,
        default=2,
        help="Parallel USB send workers across chips (default: 2)",
    )
    parser.add_argument(
        "--quality-profile",
        choices=JPEG_PROFILE_CHOICES,
        default="auto",
        help="Secondary JPEG quality profile: auto, speed, balanced, or text",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        help="Override secondary JPEG quality (1-100)",
    )
    parser.add_argument(
        "--jpeg-subsampling",
        type=int,
        choices=(0, 1, 2),
        help="Override secondary JPEG subsampling: 0=4:4:4, 1=4:2:2, 2=4:2:0",
    )
    parser.add_argument(
        "--allow-unsafe-secondary-jpeg",
        action="store_true",
        help="Allow experimental output-1 JPEG settings outside the known-good quality<=95 and subsampling=2 envelope",
    )
    parser.add_argument(
        "--stats-interval",
        type=int,
        default=30,
        help="Seconds between performance summaries (0 disables, default: 30)",
    )
    args = parser.parse_args()

    if args.send_workers < 1:
        parser.error("--send-workers must be at least 1")
    if args.jpeg_quality is not None and not 1 <= args.jpeg_quality <= 100:
        parser.error("--jpeg-quality must be between 1 and 100")
    if args.stats_interval < 0:
        parser.error("--stats-interval must be 0 or greater")

    resolved_profile, JPEG_QUALITY, JPEG_SUBSAMPLING = resolve_jpeg_settings(
        args.quality_profile,
        fps=args.fps if args.mirror else 1,
        quality=args.jpeg_quality,
        subsampling=args.jpeg_subsampling,
    )
    resolved_profile, JPEG_QUALITY, JPEG_SUBSAMPLING, jpeg_clamped = stabilize_secondary_jpeg_settings(
        resolved_profile,
        JPEG_QUALITY,
        JPEG_SUBSAMPLING,
        allow_unsafe=args.allow_unsafe_secondary_jpeg,
    )
    stats = IntervalStats(args.stats_interval)

    log.info("MCT Trigger T6 USB Display Driver v2.0")
    log.info(
        "USB send workers=%d, stats interval=%ss",
        args.send_workers,
        args.stats_interval,
    )
    log_jpeg_settings(
        resolved_profile,
        JPEG_QUALITY,
        JPEG_SUBSAMPLING,
        clamped=jpeg_clamped,
    )
    outputs = find_outputs()
    if not outputs and not (args.daemon or args.mirror):
        log.error("No T6 displays found")
        sys.exit(1)

    if outputs:
        log.info("Found %d display(s). Initializing...", len(outputs))
        init_outputs(outputs)
    else:
        log.warning("No T6 displays found yet — waiting for hotplug")

    if args.mirror:
        log.info("Mirror mode (%s layout) at %d FPS", args.layout, args.fps)
        frame_time = 1.0 / args.fps
        last_health = time.monotonic() if outputs else 0
        regions = compute_regions(outputs, args.layout)
        try:
            with ThreadPoolExecutor(
                max_workers=args.send_workers,
                thread_name_prefix="mct-t6-send",
            ) as send_executor:
                while True:
                    start = time.monotonic()

                    # Periodic health check and reconnect
                    if start - last_health >= health_check_interval(outputs, args.reconnect_interval):
                        outputs = check_outputs_alive(outputs)
                        outputs = refresh_outputs(outputs)
                        regions = compute_regions(outputs, args.layout)
                        last_health = start
                        if not outputs:
                            log.warning("No outputs — waiting for reconnect...")
                            time.sleep(args.reconnect_interval)
                            continue

                    capture_started = time.monotonic()
                    desktop = capture_desktop()
                    capture_ms = (time.monotonic() - capture_started) * 1000.0
                    if not desktop:
                        stats.record_cycle(
                            output_count=len(outputs),
                            ready_count=0,
                            capture_ms=capture_ms,
                            capture_ok=False,
                        )
                        stats.maybe_log(time.monotonic())
                        time.sleep(min(frame_time, 1.0))
                        continue

                    cap_w, cap_h, desktop_rgb = desktop
                    prepare_started = time.monotonic()
                    ready_frames = []
                    for out, region in zip(outputs, regions):
                        screen = extract_screen_region(
                            desktop_rgb,
                            cap_w,
                            cap_h,
                            region,
                            out.width,
                            out.height,
                        )
                        if screen and out.needs_frame(screen):
                            ready_frames.append((out, screen))
                    prepare_ms = (time.monotonic() - prepare_started) * 1000.0

                    send_started = time.monotonic()
                    send_summary = send_frame_batches(send_executor, ready_frames)
                    send_ms = (time.monotonic() - send_started) * 1000.0
                    stats.record_send_summary(send_summary)
                    stats.record_cycle(
                        output_count=len(outputs),
                        ready_count=len(ready_frames),
                        capture_ms=capture_ms,
                        prepare_ms=prepare_ms,
                        send_ms=send_ms,
                        failed_chips=len(send_summary.failed_chips),
                    )
                    stats.maybe_log(time.monotonic())

                    if send_summary.failed_chips:
                        outputs = drop_failed_chips(outputs, send_summary.failed_chips)
                        regions = compute_regions(outputs, args.layout)
                        last_health = 0

                    elapsed = time.monotonic() - start
                    if elapsed < frame_time:
                        time.sleep(frame_time - elapsed)
        except KeyboardInterrupt:
            pass
    elif args.daemon:
        log.info("Daemon mode — showing workspace (reconnect every %ds)", args.reconnect_interval)
        try:
            from PIL import Image, ImageDraw, ImageFont

            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80
                )
                sfont = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30
                )
            except Exception:
                font = sfont = ImageFont.load_default()

            # Pre-render frames once (update every 10s for clock)
            def _render_frames():
                _f = []
                for idx, out in enumerate(outputs):
                    img = Image.new("RGB", (out.width, out.height), (15, 20, 35))
                    d = ImageDraw.Draw(img)
                    d.rectangle(
                        [(0, 0), (out.width - 1, out.height - 1)],
                        outline=(60, 80, 120),
                        width=2,
                    )
                    d.text(
                        (out.width // 2, out.height // 2),
                        out.monitor_name or f"Display {idx + 1}",
                        fill=(255, 255, 255),
                        font=font,
                        anchor="mm",
                    )
                    d.text(
                        (out.width // 2, out.height // 2 + 80),
                        f"{out.width}x{out.height} | Authentra MCT T6",
                        fill=(100, 120, 160),
                        font=sfont,
                        anchor="mm",
                    )
                    d.text(
                        (20, 10),
                        time.strftime("%H:%M:%S"),
                        fill=(80, 80, 100),
                        font=sfont,
                    )
                    _f.append(img.tobytes())
                return _f

            _frames = _render_frames()
            log.info("Frames pre-rendered for %d outputs", len(_frames))

            # Group outputs by chip for sequential sending
            _chip_groups = defaultdict(list)
            for idx, out in enumerate(outputs):
                _chip_groups[(out.dev.bus, out.dev.address)].append((idx, out))

            last_health = time.monotonic() if outputs else 0
            last_render = time.monotonic()
            with ThreadPoolExecutor(
                max_workers=args.send_workers,
                thread_name_prefix="mct-t6-send",
            ) as send_executor:
                while True:
                    now = time.monotonic()
                    prepare_ms = 0.0

                    # Periodic health check
                    if now - last_health >= health_check_interval(outputs, args.reconnect_interval):
                        outputs = check_outputs_alive(outputs)
                        outputs = refresh_outputs(outputs)
                        last_health = now
                        if not outputs:
                            log.warning("No outputs — waiting...")
                            time.sleep(args.reconnect_interval)
                            continue
                        # Rebuild chip groups and re-render
                        _chip_groups = defaultdict(list)
                        for idx, out in enumerate(outputs):
                            _chip_groups[(out.dev.bus, out.dev.address)].append((idx, out))
                        render_started = time.monotonic()
                        _frames = _render_frames()
                        prepare_ms += (time.monotonic() - render_started) * 1000.0

                    # Re-render every 10s for clock update
                    if now - last_render >= 10:
                        render_started = time.monotonic()
                        _frames = _render_frames()
                        prepare_ms += (time.monotonic() - render_started) * 1000.0
                        last_render = now

                    prepare_started = time.monotonic()
                    ready_frames = []
                    for _ckey, _couts in _chip_groups.items():
                        for idx, out in _couts:
                            if not out.needs_frame(_frames[idx]):
                                continue
                            ready_frames.append((out, _frames[idx]))
                    prepare_ms += (time.monotonic() - prepare_started) * 1000.0

                    send_started = time.monotonic()
                    send_summary = send_frame_batches(send_executor, ready_frames)
                    send_ms = (time.monotonic() - send_started) * 1000.0
                    stats.record_send_summary(send_summary)
                    stats.record_cycle(
                        output_count=len(outputs),
                        ready_count=len(ready_frames),
                        prepare_ms=prepare_ms,
                        send_ms=send_ms,
                        failed_chips=len(send_summary.failed_chips),
                    )
                    stats.maybe_log(time.monotonic())

                    if send_summary.failed_chips:
                        outputs = drop_failed_chips(outputs, send_summary.failed_chips)
                        _chip_groups = defaultdict(list)
                        for idx, out in enumerate(outputs):
                            _chip_groups[(out.dev.bus, out.dev.address)].append((idx, out))
                        _frames = _render_frames() if outputs else []
                        last_health = 0

                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    else:
        # One-shot: show test pattern and exit
        try:
            from PIL import Image, ImageDraw, ImageFont

            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120
                )
            except Exception:
                font = ImageFont.load_default()
            for idx, out in enumerate(outputs):
                img = Image.new("RGB", (out.width, out.height), (30, 50, 80))
                d = ImageDraw.Draw(img)
                d.rectangle(
                    [(0, 0), (out.width - 1, out.height - 1)],
                    outline=(255, 255, 255),
                    width=5,
                )
                d.text(
                    (out.width // 2, out.height // 2),
                    out.monitor_name,
                    fill=(255, 255, 255),
                    font=font,
                    anchor="mm",
                )
                out.send_frame(img.tobytes())
                log.info("Test pattern sent to %s", out.monitor_name)
        except ImportError:
            log.info("Pillow not available — sending solid white")
            for out in outputs:
                out.send_frame(bytes([255, 255, 255] * out.width * out.height))

    log.info("Shutting down")
    close_capture_backend()
    for out in outputs:
        out.close()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    main()
