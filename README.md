# MCT Trigger 6 (T6) Linux Display Driver

Linux kernel DRM/KMS driver for MCT Trigger 6 USB display adapters (StarTech USBC2HD4 and similar quad-HDMI USB-C adapters using the MCT T6-688 chipset).

**Beta Release** — fully functional with multi-resolution support, companion GUI tools, and DKMS packaging.

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

- **Up to 4 HDMI outputs** from a single USB-C adapter (2 chips × 2 heads)
- **9 resolutions**: 1920×1080 (60/30Hz), 1600×900, 1280×1024, 1280×800, 1280×720, 1024×768, 800×600, 640×480
- **Real-time mode switching** — change resolution from display settings without reloading
- **Damage tracking** — only changed pixels sent over USB (sub-ms for idle screens)
- **NV12 secondary transport** — 3× bandwidth savings vs raw RGB on secondary heads
- **Boot keepalive** — monitors stay lit during compositor startup
- **DPMS** — monitors properly sleep/wake with your desktop
- **Suspend/resume** — displays recover after laptop sleep
- **Per-output control** — enable/disable individual outputs via sysfs
- **Companion tools** — CLI status, GTK4 settings window, system tray indicator

## Hardware

| Feature | Details |
|---------|---------|
| **Adapter** | StarTech USBC2HD4 (USB-C to 4× HDMI) |
| **Chipset** | 2× MCT Trigger 6 (T6-688) |
| **USB ID** | VID=0x0711 PID=0x5601 |
| **Per chip** | 2 HDMI outputs, 58MB VRAM, USB 3.0 bulk |
| **EDID** | Read per output via vendor request 0x80 |

## System Requirements

- Linux kernel 5.10 or newer
- GCC, make, kernel headers, DKMS
- USB 3.0 port (SuperSpeed)
- Python 3.8+ with PyGObject (optional, for GUI tools)

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

## Companion Tools

### mct-t6-ctl (CLI)

```bash
mct-t6-ctl status          # Show connected devices and metrics
mct-t6-ctl monitor         # Live-updating dashboard
mct-t6-ctl set jpeg-quality 80  # Adjust JPEG quality (1-100)
mct-t6-ctl info            # Driver and kernel info
mct-t6-ctl reset-metrics   # Reset all counters
```

### mct-t6-settings (GUI)

Launch from the application menu ("MCT Trigger6 Settings") or run `mct-t6-settings`. Shows:
- Connected devices with per-head metrics (FPS, encode time, USB time)
- DRM connector status and available modes
- Quality sliders (JPEG quality, frame intervals)

### mct-t6-tray (System Tray)

Auto-starts on login. Shows connection status in the system tray with:
- Desktop notifications on monitor connect/disconnect
- Quick access to settings and terminal monitor

## Module Parameters

All parameters are runtime-writable via `/sys/module/trigger6/parameters/`.

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| `jpeg_quality` | 1-100 | 40 | JPEG quality for in-kernel encoder |
| `frame_min_interval_ms` | 0-1000 | 5 | Per-head pacing gate (ms) |
| `secondary_frame_min_interval_ms` | 0-5000 | 250 | Secondary head adaptive pacing cap |
| `manual_only` | 0/1 | 0 | Keep connectors disconnected (safe mode) |
| `serialize_usb_bus` | 0/1 | 1 | Serialize USB across all adapters |
| `experimental_secondary_raw` | 0/1 | 0 | Force raw XRGB on secondary head |

## Architecture

```
Primary head (output 0):   Raw XRGB8888 + row-level damage tracking
Secondary head (output 1): NV12 transport + triple-buffered VRAM slots

Compositor → tx_back (staging) → tx_front (send) → USB bulk → T6 VRAM → HDMI
```

- **Primary**: sends only changed rows (~100KB vs 8.3MB full frame)
- **Secondary**: BGRX→NV12 conversion (~9ms) into 3.1MB payload, triple-buffered for zero jitter
- **Idle monitors**: zero USB traffic (damage tracking skips unchanged frames)

## Per-Output Control

```bash
# Show head enable status
cat /sys/bus/usb/devices/6-1.1:1.0/t6_head_enable

# Disable head 1 (secondary) on chip 1
echo "1 0" | sudo tee /sys/bus/usb/devices/6-1.1:1.0/t6_head_enable

# Re-enable
echo "1 1" | sudo tee /sys/bus/usb/devices/6-1.1:1.0/t6_head_enable
```

## Troubleshooting

### No display output
```bash
lsmod | grep trigger6        # Module loaded?
dmesg | grep trigger6        # Init messages?
mct-t6-ctl status            # Device connected?
```

### Wrong resolution
Open your desktop's Display Settings — select from the available modes (9 validated resolutions). The driver sends the correct hardware timing blob on mode change.

### Monitor flickers or goes blank periodically
Check if the keepalive is working: `mct-t6-ctl status` should show `keepalive_sent` incrementing. If not, the boot keepalive may not be running.

### Slow startup (monitors take >5s)
The driver primes monitors with black frames and maintains signal via boot keepalive. HDMI lock time varies by monitor — some take 2-3 seconds.

### Display settings show only 1920×1080
The hardware resolution table query (vendor requests 0x84/0x89) may not be supported by your firmware revision. The driver falls back to 9 built-in modes with validated timing blobs.

## Known Limitations

- **Resolution**: Limited to 9 validated modes. Additional resolutions require hardware-validated timing blobs.
- **Refresh rate**: 60Hz and 30Hz (1080p only). Other refresh rates need PLL validation.
- **No hardware cursor**: Cursor rendered in software by compositor.
- **No HDCP/audio**: USB transport doesn't support protected content or audio passthrough.
- **No night light**: Gamma LUT not yet implemented (requires CRTC refactoring).
- **Secondary head quality**: NV12 uses 4:2:0 chroma subsampling — slight color loss vs primary head's full RGB.
- **Multi-adapter**: Each adapter creates a separate DRM device. Window spanning works via compositor display arrangement.

## Credits

- Protocol decoded from [mcttrigger/triggerdm](https://github.com/mcttrigger/triggerdm) (GPL, MCT's ChromeOS driver)
- Reverse engineering docs from [cyrozap/mct-usb-display-adapter-re](https://github.com/cyrozap/mct-usb-display-adapter-re)
- Driver architecture follows the Linux UDL (USB DisplayLink) pattern

## License

- Kernel driver: GPL-2.0-only
- Userspace tools: MIT
- Copyright (C) 2026 Authentra / Ralph Friedman
