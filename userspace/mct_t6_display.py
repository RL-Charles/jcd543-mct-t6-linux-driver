#!/usr/bin/env python3
"""MCT Trigger T6 USB Display Driver for Linux.

First working Linux driver for StarTech USBC2HD4 and similar MCT T6 adapters.
Reverse-engineered from Windows USB packet captures.

Protocol discoveries:
- Pixel format: RBG (byte 0=Red, byte 1=Blue, byte 2=Green)
- Video header format=9, stride in bytes, embedded in first bulk chunk
- Session dest=0x30 for uncompressed raw frames
- Each T6 chip = 1 physical HDMI output (logical outputs 0/1 share same display)
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
import logging
import os
import signal
import struct
import subprocess
import sys
import time

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


# ── T6 Device ──────────────────────────────────────────────────────
class T6Output:
    """One physical output on an MCT T6 USB display adapter."""

    def __init__(self, dev, output_idx=0, ram_mb=58):
        self.dev = dev
        self.out = output_idx
        self.ep = None
        self.width = 1920
        self.height = 1080
        self.stride = self.width * 4  # RBGX 32-bit
        self.seq = 1
        self.monitor_name = ""
        # Framebuffer address from RAM size (triggerdm formula)
        tmp = ram_mb - 18
        if output_idx == 0:
            self._fb_addr = (tmp - 12) * 1024 * 1024
        else:
            self._fb_addr = (tmp + 6) * 1024 * 1024
        self._claim()

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
        self.dev.ctrl_transfer(REQ_OUT, 0x31, 0x0000, 0)
        self.dev.ctrl_transfer(REQ_OUT, 0x23, 0, 0, INIT_0x23)
        self.dev.ctrl_transfer(REQ_OUT, 0x24, 0, 0, INIT_0x24_PRE)
        self.dev.ctrl_transfer(REQ_OUT, 0x12, self.out, 0, MODE_1080P)
        self.dev.ctrl_transfer(REQ_OUT, 0x03, self.out, 1)
        self.dev.ctrl_transfer(REQ_OUT, 0x24, 0, 0, INIT_0x24_POST)
        self.dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0002, 0)
        self.seq = 1
        log.info(
            "Output init: %s (%dx%d)",
            self.monitor_name or "unknown",
            self.width,
            self.height,
        )

    def send_frame(self, rgb_data: bytes):
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
        cmd = 3 if self.out == 0 else 4
        pitch = self.stride  # width * 4 for RGB32

        vhdr = bytearray(0x30)
        struct.pack_into("<I", vhdr, 0x00, cmd)          # Command
        struct.pack_into("<I", vhdr, 0x04, frame_size)    # PayloadSize
        struct.pack_into("<I", vhdr, 0x08, 0)             # FenceID
        struct.pack_into("<I", vhdr, 0x0C, 8)             # TargetFormat = RGB32
        struct.pack_into("<H", vhdr, 0x10, pitch)         # Y_RGB_Pitch (16-bit)
        struct.pack_into("<H", vhdr, 0x12, 0)             # UV_Pitch (16-bit, 0 for RGB)
        struct.pack_into("<I", vhdr, 0x14, fb_addr)         # Y_RGB_Data_FB_Offset
        struct.pack_into("<I", vhdr, 0x18, 0)             # U_UV_Data_Offset
        struct.pack_into("<I", vhdr, 0x1C, 0)             # V_Data_Offset
        struct.pack_into("<I", vhdr, 0x20, 8)             # SourceFormat = RGB32
        # 0x24-0x2E: padding (zeros)
        # 0x2F: Flag — 0x80 resets JPEG engine (first 10 frames per triggerdm)
        if self.seq <= 10:
            vhdr[0x2F] = 0x80

        total_payload = 0x30 + frame_size

        # BULK_CMD_HEADER (32 bytes)
        # Signature=0 (display), PayloadLength, PayloadAddress=fbAddr,
        # PacketLength for first chunk
        first_data = CHUNK_SIZE - 0x30
        self.ep.write(
            struct.pack(
                "<IIIIIIII",
                0,              # Signature (display)
                total_payload,  # PayloadLength
                fb_addr,        # PayloadAddress (framebuffer, not 0x30)
                CHUNK_SIZE,     # PacketLength (this fragment)
                0,              # bytes written so far
                self.out,       # output index
                0, 0,           # padding
            )
        )
        self.ep.write(bytes(vhdr) + bgrx[:first_data])

        # Remaining chunks
        off, written = first_data, CHUNK_SIZE
        while off < frame_size:
            cs = min(CHUNK_SIZE, frame_size - off)
            self.ep.write(
                struct.pack(
                    "<IIIIIIII",
                    0,              # Signature
                    total_payload,  # PayloadLength
                    fb_addr,        # PayloadAddress
                    cs,             # PacketLength
                    written,        # bytes written
                    self.out,       # output index
                    0, 0,
                )
            )
            self.ep.write(bgrx[off : off + cs])
            off += cs
            written += cs

        self.seq += 1

    def prime(self, frames=5):
        """Send black frames to stabilize output after init.

        Multi-output chips need a few frames to clear internal buffers
        and lock the HDMI signal before real content is sent.
        """
        black = bytes(self.width * self.height * 4)
        for _ in range(frames):
            try:
                self.send_frame(black)
            except Exception:
                pass

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
def find_outputs():
    """Find all T6 devices and create output objects."""
    devices = sorted(
        usb.core.find(find_all=True, idVendor=VID, idProduct=PID),
        key=lambda d: (d.bus, d.address),
    )
    outputs = []
    for dev in devices:
        # Query RAM size per chip
        ram_mb = 58  # default
        try:
            ram_data = dev.ctrl_transfer(REQ_IN, 0x88, 0, 0, 4)
            ram_mb = struct.unpack('<I', ram_data)[0]
        except Exception:
            pass
        for out_idx in range(2):
            t6 = T6Output(dev, output_idx=out_idx, ram_mb=ram_mb)
            t6.read_edid()
            if t6.is_connected():
                outputs.append(t6)
                log.info(
                    "Found: %s (%dx%d) bus=%d addr=%d out=%d ram=%dMB fb=0x%08X",
                    t6.monitor_name,
                    t6.width,
                    t6.height,
                    dev.bus,
                    dev.address,
                    out_idx,
                    ram_mb,
                    t6._fb_addr,
                )
    return outputs


# ── Optional Pillow ────────────────────────────────────────────────
try:
    from PIL import Image as _PILImage

    _HAS_PILLOW = True
except ImportError:
    _HAS_PILLOW = False


# ── Screen capture ─────────────────────────────────────────────────
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


def capture_screen(target_w=None, target_h=None, region=None):
    """Capture the primary display (or a region) as RGB bytes.

    Args:
        target_w: Desired output width. If capture differs, will resize.
        target_h: Desired output height. If capture differs, will resize.
        region: Optional (x, y, w, h) tuple for grim -g region capture.

    Returns:
        RGB bytes sized to target_w x target_h, or None on failure.
    """
    cmd = ["grim", "-t", "ppm"]
    if region:
        x, y, w, h = region
        cmd += ["-g", f"{x},{y} {w}x{h}"]
    cmd.append("-")

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=2)
        if proc.returncode != 0:
            return None
        cap_w, cap_h, rgb = _parse_ppm(proc.stdout)
        # If no target specified, use captured size
        if target_w is None:
            target_w = cap_w
        if target_h is None:
            target_h = cap_h
        return _resize_rgb(rgb, cap_w, cap_h, target_w, target_h)
    except FileNotFoundError:
        log.error("grim not found — install grim for screen capture")
        return None
    except Exception as e:
        log.debug("Screen capture failed: %s", e)
        return None


# ── Hotplug / Reconnect ───────────────────────────────────────────
def check_outputs_alive(outputs):
    """Remove dead outputs from the list. Returns list of still-alive outputs."""
    alive = []
    for out in outputs:
        try:
            # Quick probe — if the USB device is gone this will throw
            out.dev.ctrl_transfer(REQ_IN, 0x87, out.out, 0, 1)
            alive.append(out)
        except Exception:
            log.warning(
                "Output lost: %s (bus=%d addr=%d)",
                out.monitor_name or "unknown",
                out.dev.bus,
                out.dev.address,
            )
            try:
                out.close()
            except Exception:
                pass
    return alive


def refresh_outputs(existing):
    """Re-scan USB bus and add any new T6 devices. Returns merged list."""
    # Build set of (bus, address) for existing live outputs
    known = {(o.dev.bus, o.dev.address) for o in existing}
    new_devs = sorted(
        usb.core.find(find_all=True, idVendor=VID, idProduct=PID),
        key=lambda d: (d.bus, d.address),
    )
    added = []
    for dev in new_devs:
        if (dev.bus, dev.address) not in known:
            try:
                t6 = T6Output(dev, output_idx=0)
                t6.read_edid()
                if t6.is_connected():
                    t6.init()
                    added.append(t6)
                    log.info(
                        "Hotplug: %s (%dx%d) bus=%d addr=%d",
                        t6.monitor_name,
                        t6.width,
                        t6.height,
                        dev.bus,
                        dev.address,
                    )
            except Exception as e:
                log.debug("Failed to init new device bus=%d addr=%d: %s", dev.bus, dev.address, e)
    return existing + added


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


# ── Main ───────────────────────────────────────────────────────────
def main():
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
    args = parser.parse_args()

    log.info("MCT Trigger T6 USB Display Driver v2.0")
    outputs = find_outputs()
    if not outputs:
        log.error("No T6 displays found")
        sys.exit(1)

    log.info("Found %d display(s). Initializing...", len(outputs))
    # Group by chip and init all outputs per chip in one sequence
    # (device reset kills other outputs, so reset once per chip)
    from collections import defaultdict as _dd
    chips: dict[tuple, list] = _dd(list)
    for out in outputs:
        chips[(out.dev.bus, out.dev.address)].append(out)
    for chip_key, chip_outs in chips.items():
        dev = chip_outs[0].dev
        dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0000, 0)
        dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0100, 0)
        dev.ctrl_transfer(REQ_OUT, 0x31, 0x0000, 0)
        dev.ctrl_transfer(REQ_OUT, 0x23, 0, 0, INIT_0x23)
        dev.ctrl_transfer(REQ_OUT, 0x24, 0, 0, INIT_0x24_PRE)
        for out in chip_outs:
            dev.ctrl_transfer(REQ_OUT, 0x12, out.out, 0, MODE_1080P)
            dev.ctrl_transfer(REQ_OUT, 0x03, out.out, 1)
            out.seq = 1
            log.info("  Output %d: %s (%dx%d) fb=0x%08X",
                     out.out, out.monitor_name, out.width, out.height, out._fb_addr)
        dev.ctrl_transfer(REQ_OUT, 0x24, 0, 0, INIT_0x24_POST)
        dev.ctrl_transfer(REQ_OUT, 0x1C, 0x0002, 0)

    if args.mirror:
        log.info("Mirror mode (%s layout) at %d FPS", args.layout, args.fps)
        frame_time = 1.0 / args.fps
        last_health = time.monotonic()
        regions = compute_regions(outputs, args.layout)
        try:
            while True:
                start = time.monotonic()

                # Periodic health check and reconnect
                if start - last_health >= args.reconnect_interval:
                    outputs = check_outputs_alive(outputs)
                    outputs = refresh_outputs(outputs)
                    regions = compute_regions(outputs, args.layout)
                    last_health = start
                    if not outputs:
                        log.warning("No outputs — waiting for reconnect...")
                        time.sleep(args.reconnect_interval)
                        continue

                for out, region in zip(outputs, regions):
                    screen = capture_screen(
                        target_w=out.width, target_h=out.height, region=region
                    )
                    if screen:
                        try:
                            out.send_frame(screen)
                        except usb.core.USBError as e:
                            log.warning("USB error on %s: %s — will reconnect", out.monitor_name, e)
                            # Force health check next iteration
                            last_health = 0
                        except Exception as e:
                            log.warning("Frame send failed on %s: %s", out.monitor_name, e)

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
            _chip_groups = _dd(list)
            for idx, out in enumerate(outputs):
                _chip_groups[(out.dev.bus, out.dev.address)].append((idx, out))

            last_health = time.monotonic()
            last_render = time.monotonic()
            while True:
                now = time.monotonic()

                # Periodic health check
                if now - last_health >= args.reconnect_interval:
                    outputs = check_outputs_alive(outputs)
                    outputs = refresh_outputs(outputs)
                    last_health = now
                    if not outputs:
                        log.warning("No outputs — waiting...")
                        time.sleep(args.reconnect_interval)
                        continue
                    # Rebuild chip groups and re-render
                    _chip_groups = _dd(list)
                    for idx, out in enumerate(outputs):
                        _chip_groups[(out.dev.bus, out.dev.address)].append((idx, out))
                    _frames = _render_frames()

                # Re-render every 10s for clock update
                if now - last_render >= 10:
                    _frames = _render_frames()
                    last_render = now

                # Send per-chip: all outputs on same chip together
                for _ckey, _couts in _chip_groups.items():
                    for idx, out in _couts:
                        try:
                            out.send_frame(_frames[idx])
                        except usb.core.USBError as e:
                            log.warning("USB error on %s: %s", out.monitor_name, e)
                            last_health = 0
                        except Exception:
                            pass
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
    for out in outputs:
        out.close()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    main()
