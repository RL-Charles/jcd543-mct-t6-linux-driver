# MCT Trigger 6 (T6) Linux Display Driver

Linux kernel DRM/KMS driver for MCT Trigger 6 USB display adapters (StarTech USBC2HD4 and similar quad-HDMI USB-C adapters using the MCT T6-688 chipset).

**Beta Release** — fully functional with up to 4 external monitors, multi-resolution support, real-time mode switching, and companion GUI tools.

## Quick Start

```bash
# Prerequisites (Debian/Ubuntu/Pop!_OS)
sudo apt install linux-headers-$(uname -r) dkms build-essential python3-gi gir1.2-gtk-4.0

# Install
sudo ./install.sh

# Verify
lsmod | grep trigger6
mct-t6-ctl status
```

Plug in your T6 adapter — monitors appear automatically in your desktop's display settings.

## Features

- **Up to 4 HDMI outputs** from a single USB-C adapter (2 chips × 2 heads each)
- **9 resolutions**: 1920×1080 (60/30Hz), 1600×900, 1280×1024, 1280×800, 1280×720, 1024×768, 800×600, 640×480
- **Real-time mode switching** — change resolution from display settings, driver sends hardware timing blob
- **Dual transport architecture**:
  - Primary heads: raw XRGB8888 with row-level damage tracking (sub-ms USB, ~60fps capable)
  - Secondary heads: NV12 transport (BGRX→NV12 ~9ms, 3× bandwidth savings, triple-buffered for zero jitter)
- **Damage tracking** — only changed pixel rows sent over USB. Idle screens use zero bandwidth.
- **Bus utilization reduced from 97.5% to ~20%** through damage tracking + NV12 compression
- **Boot keepalive** — dedicated work queue keeps HDMI signal alive during compositor startup
- **DPMS** — monitors properly sleep/wake with your desktop
- **Suspend/resume** — displays recover after laptop sleep with automatic keepalive restart
- **Per-output control** — enable/disable individual outputs via sysfs
- **Adaptive pacing** — raw heads: zero gate (damage tracking is the throttle), NV12/JPEG: encode-time-based
- **USB fault recovery** — auto-reset on timeout, wedge detection after 5 consecutive failures, auto-recovery after 60s
- **Companion tools** — CLI status dashboard, GTK4 settings window, system tray indicator with hotplug notifications

## Hardware

| Feature | Details |
|---------|---------|
| **Adapter** | StarTech USBC2HD4 (USB-C to 4× HDMI) and compatible T6-688 adapters |
| **Chipset** | 2× MCT Trigger 6 (T6-688) per adapter |
| **USB ID** | VID=0x0711 PID=0x5601 |
| **Per chip** | 2 HDMI outputs, 58MB VRAM, USB 3.0 bulk endpoint 0x02 |
| **Total outputs** | 4 HDMI per adapter (tested with 3 monitors, 4th supported) |
| **EDID** | Read per output via vendor request 0x80, physical size parsed for HiDPI |

## System Requirements

- Linux kernel 5.10 or newer (tested on 6.18)
- GCC, make, kernel headers, DKMS
- USB 3.0 port (SuperSpeed required for stable multi-monitor)
- Python 3.8+ with PyGObject (optional, for GUI tools)
- Supported desktops: COSMIC, GNOME, KDE, Sway, any Wayland/X11 compositor

## Installation

### One-Command Install (recommended)

```bash
sudo ./install.sh
```

This builds the kernel module via DKMS, installs udev rules, modprobe defaults, CLI tool, GUI settings app, and system tray indicator. The module auto-rebuilds on kernel upgrades.

### Manual Install

```bash
cd kernel && make && sudo make install
sudo cp ../99-trigger6.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo modprobe trigger6
```

### Uninstall

```bash
sudo ./uninstall.sh
```

## Performance

Measured on StarTech USBC2HD4 with Pop!_OS / COSMIC compositor:

| Metric | Before optimization | After |
|--------|-------------------|-------|
| Raw head USB per frame | 48-54ms | **2-4ms** (damage tracking) |
| NV12 encode time | — | **9ms** (vs 52ms JPEG) |
| USB bus utilization | 97.5% | **~20%** |
| Raw head FPS (active content) | 5-13 | **25-60** |
| Idle screen bandwidth | 8.3MB/frame | **0 bytes** (zero-damage skip) |

## Architecture

```
Primary head (output 0):   Raw XRGB8888 → row-level damage → multi-write partial USB
Secondary head (output 1): XRGB8888 → NV12 conversion → triple-buffered VRAM slots

Compositor → shadow plane → damage detect → encode/convert → USB bulk → T6 VRAM → HDMI
```

- **Primary (raw)**: compares each row against last-sent frame; sends only dirty rows via separate USB bulk writes. Full 1920×1080 frame = 8.3MB, typical desktop update = 100-200KB.
- **Secondary (NV12)**: converts BGRX to NV12 (BT.601, ~3.1MB per frame), rotates through 3 VRAM slots so the display reads from one while the driver writes another — zero tearing.
- **Mode switching**: sends full chip timing sequence (SET_TIMING pre → SET_RESOLUTION for all heads → SET_TIMING post → FINALIZE) to prevent sibling head crashes.

## Companion Tools

### mct-t6-ctl (CLI)

```bash
mct-t6-ctl status          # Show connected devices and metrics
mct-t6-ctl monitor         # Live-updating dashboard (FPS, encode, USB time)
mct-t6-ctl set jpeg-quality 80  # Adjust JPEG quality (1-100)
mct-t6-ctl info            # Driver and kernel info
mct-t6-ctl reset-metrics   # Reset all counters
```

### mct-t6-settings (GUI)

Launch from the application menu ("MCT Trigger6 Settings") or run `mct-t6-settings`. Shows:
- Connected devices with per-head live metrics (FPS, encode time, USB time, payload size)
- DRM connector status and available modes
- Quality sliders (JPEG quality, frame intervals)
- Driver version and kernel info

### mct-t6-tray (System Tray)

Auto-starts on login. Shows connection status with:
- Desktop notifications on monitor connect/disconnect
- Quick access to settings and terminal monitor

## Module Parameters

All parameters are runtime-writable via `/sys/module/trigger6/parameters/`.

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| `jpeg_quality` | 1-100 | 40 | JPEG quality for in-kernel encoder (fallback path) |
| `frame_min_interval_ms` | 0-1000 | 5 | Per-head pacing gate (ignored for raw heads with damage tracking) |
| `secondary_frame_min_interval_ms` | 0-5000 | 250 | Secondary head adaptive pacing cap |
| `manual_only` | 0/1 | 0 | Keep connectors disconnected (safe testing mode) |
| `serialize_usb_bus` | 0/1 | 1 | Serialize USB writes across all adapters |
| `experimental_secondary_raw` | 0/1 | 0 | Force raw XRGB on secondary head (causes tearing) |

## Troubleshooting

### No display output
```bash
lsmod | grep trigger6        # Module loaded?
dmesg | grep trigger6        # Init messages?
mct-t6-ctl status            # Device connected?
```

### Wrong resolution
Open your desktop's Display Settings — the driver offers 9 validated resolutions. Selecting a mode sends the correct hardware timing blob to the T6 chip.

### Slow startup
The driver primes monitors with black frames and maintains signal via boot keepalive. HDMI lock time varies by monitor (typically 2-5 seconds).

### Monitor power cycling (on/off/on)
If monitors cycle power during sleep, the DPMS fix ensures all keepalive activity stops when the compositor blanks the display. Check that your desktop power settings are configured for your use case.

## Known Limitations

- **Resolution**: 9 validated modes. Additional resolutions require hardware-tested timing blobs or firmware support for vendor request 0x84/0x89.
- **Refresh rate**: 60Hz and 30Hz (1080p). Other rates need PLL parameter validation.
- **No hardware cursor**: Cursor rendered by compositor (software).
- **No HDCP/audio**: USB transport limitation.
- **No night light**: Gamma LUT not yet implemented (requires CRTC architecture change).
- **NV12 chroma**: Secondary heads use 4:2:0 subsampling — slight color difference vs primary head's full RGB.
- **Multi-adapter**: Each chip creates a separate DRM device. Window spanning works via compositor display arrangement (Settings → Displays).

## Credits

- Protocol decoded from [mcttrigger/triggerdm](https://github.com/mcttrigger/triggerdm) (GPL, MCT's ChromeOS driver)
- Reverse engineering docs from [cyrozap/mct-usb-display-adapter-re](https://github.com/cyrozap/mct-usb-display-adapter-re)
- Driver architecture follows the Linux UDL (USB DisplayLink) pattern

### Contributors
- Authentra
- Claude Opus 4.6 (Anthropic)
- Codex 5.4 (OpenAI)
- Gemini (Google)

## License

- Kernel driver: GPL-2.0-only
- Userspace tools: MIT
- Copyright (C) 2026 Authentra
