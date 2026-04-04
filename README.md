# MCT Trigger 6 (T6) Linux Display Driver

First Linux driver for MCT Trigger 6 USB display adapters (StarTech USBC2HD4, and similar quad-HDMI USB-C adapters using the MCT T6-688 chipset).

## Status

| Component | Status | Details |
|-----------|--------|---------|
| **Userspace Python driver** | **Working** | 2 monitors at 1920x1080, correct colors, ~2 FPS |
| **Kernel DRM driver** | **WIP — crashes** | Probes correctly, registers DRM cards, but freezes system on modeset |
| **3rd monitor (output 1)** | **Not working** | HDMI link establishes but no frames displayed |

## Hardware

- **Adapter**: StarTech USBC2HD4 (USB-C to 4x HDMI)
- **Chipset**: 2x MCT Trigger 6 (T6-688), VID=0x0711 PID=0x5601
- **Each chip**: 2 HDMI outputs, 58MB video RAM, USB 3.0 bulk endpoint 0x02
- **EDID**: Readable per output via vendor request 0x80

## Protocol Discovery

Decoded from [mcttrigger/triggerdm](https://github.com/mcttrigger/triggerdm) (GPL official ChromeOS driver), [cyrozap/mct-usb-display-adapter-re](https://github.com/cyrozap/mct-usb-display-adapter-re) (reverse engineering), and extensive USB packet analysis.

### Pixel Format

**BGRX 32-bit** (4 bytes per pixel, format=8 `VIDEO_COLOR_RGB32`):
- Byte 0: Blue
- Byte 1: Green  
- Byte 2: Red
- Byte 3: Padding (0)

This was discovered through trial-and-error. Format=9 (RGB24, 3bpp) also works but produces a ~16% horizontal offset due to VRAM stride mismatch. Format=8 (RGB32, 4bpp) is perfectly centered.

### Frame Transfer Protocol

Each frame is sent as chunked USB bulk transfers:

#### 1. Bulk Command Header (32 bytes)

```c
struct bulk_cmd_header {
    uint32_t signature;        // 0 = display
    uint32_t payload_length;   // total: video_header + pixel_data
    uint32_t payload_address;  // framebuffer address in T6 VRAM
    uint32_t packet_length;    // size of this chunk
    uint32_t bytes_written;    // cumulative bytes sent
    uint32_t output_index;     // 0 or 1
    uint32_t reserved[2];      // 0
};
```

#### 2. Video Flip Header (48 bytes, first chunk only)

```c
struct video_flip_header {
    uint32_t command;          // 3=FLIP_PRIMARY (output 0), 4=FLIP_SECONDARY (output 1)
    uint32_t payload_size;     // stride * height
    uint32_t fence_id;         // 0
    uint32_t target_format;    // 8 = RGB32
    uint16_t y_rgb_pitch;      // stride in bytes (width * 4)  ← 16-BIT!
    uint16_t uv_pitch;         // 0 for RGB
    uint32_t y_fb_offset;      // framebuffer address
    uint32_t u_offset;         // 0
    uint32_t v_offset;         // 0
    uint32_t source_format;    // 8 = RGB32
    uint8_t  padding[7];       // 0
    uint8_t  flag;             // 0x80 = reset JPEG engine (first 10 frames)
};
```

**Important**: `y_rgb_pitch` is 16-bit, NOT 32-bit. Getting this wrong causes garbage output.

#### 3. Pixel Data

Raw BGRX pixels, chunked at 102400 bytes per bulk transfer. Each chunk is preceded by a bulk command header.

### Memory Layout (58MB RAM)

```
tmp = ram_mb - 18 = 40

Output 0:
  fb_addr = (tmp - 12) * 1MB = 0x01C00000 (28MB)

Output 1:  
  fb_addr = (tmp + 6) * 1MB  = 0x02E00000 (46MB)
  cmd_addr = tmp * 1MB        = 0x02800000 (40MB)
```

### Initialization Sequence

```
1. Vendor OUT 0x1C wValue=0x0000        // Device reset low
2. Vendor OUT 0x1C wValue=0x0100        // Device reset high
3. Vendor OUT 0x23 data=init_color      // Color/gamma config (40 bytes)
4. Vendor OUT 0x24 data=init_timing_pre // Timing pre-config (16 bytes)
5. For each output:
   a. Vendor OUT 0x12 wValue=output_idx data=mode_1080p  // Set resolution (32 bytes)
   b. Vendor OUT 0x31 wValue=output_idx                   // SOFTWARE_READY ← CRITICAL
   c. Vendor OUT 0x03 wValue=output_idx wIndex=1          // Enable monitor
6. Vendor OUT 0x24 data=init_timing_post // Timing post-config (16 bytes)  
7. Vendor OUT 0x1C wValue=0x0002        // Finalize
```

**SOFTWARE_READY (0x31) is per-output** — each output needs its own 0x31 call. Without it, output 1 never displays.

### Vendor Requests

| Request | Direction | wValue | wIndex | Description |
|---------|-----------|--------|--------|-------------|
| 0x03 | OUT | output_idx | 0/1 (off/on) | Enable/disable monitor |
| 0x12 | OUT | output_idx | 0 | Set resolution timing (32B) |
| 0x23 | OUT | 0 | 0 | Color/gamma config (40B) |
| 0x24 | OUT | 0 | 0 | Timing config (16B) |
| 0x31 | OUT | output_idx | 0 | Software ready signal |
| 0x1C | OUT | varies | 0 | Device reset/finalize |
| 0x80 | IN | offset | output_idx | Read EDID (128B) |
| 0x84 | IN | output_idx | 0 | Get resolution count |
| 0x87 | IN | output_idx | 0 | Monitor status (1B: 0=disconnected, 1=connected) |
| 0x88 | IN | 0 | 0 | Video RAM size (4B LE, in MB) |
| 0x89 | IN | output_idx | 0 | Resolution timing table (512B) |
| 0xB0 | IN | 0 | 0 | Firmware version (64B) |
| 0xB3 | IN | 0 | 0 | Display section header (512B) |

### Multi-Output

Each T6 chip has 2 HDMI outputs sharing one USB bulk endpoint (0x02):

- **Output 0**: Command=3 (`FLIP_PRIMARY`), fb_addr=0x01C00000
- **Output 1**: Command=4 (`FLIP_SECONDARY`), fb_addr=0x02E00000

Both outputs initialized in one sequence (steps 5a-5c above for each). Bulk transfers must be serialized (mutex) — interleaving corrupts the stream.

### Known Issues

1. **Output 1 doesn't display**: HDMI link establishes, T6 chip accepts frames without USB errors, but nothing appears on screen. Tried: different commands, fb addresses, JPEG reset flags, staged init, separate processes. Once worked briefly during rapid testing then never reproduced reliably.

2. **T6 chip state corruption**: Sending wrong pixel format or bad init sequence permanently corrupts the chip. USB reset doesn't fix it — requires physical unplug/replug of the adapter.

3. **Kernel DRM driver freezes**: The DRM framework on kernel 6.17 calls connector callbacks (detect, get_modes, fill_modes) from contexts that deadlock with USB control transfers. Even with all USB removed from callbacks, `drm_dev_register` triggers atomic flushes that dereference stale plane state pointers.

## Userspace Driver (Working)

```bash
# Install dependencies
sudo pip3 install pyusb Pillow

# Test pattern (one-shot)
sudo python3 userspace/mct_t6_display.py

# Daemon mode (continuous workspace display)
sudo python3 userspace/mct_t6_display.py --daemon

# Mirror primary screen
sudo python3 userspace/mct_t6_display.py --mirror --fps 10
```

## Kernel Driver (WIP — Do Not Use in Production)

```bash
cd kernel/
make
sudo insmod trigger6.ko

# To remove (may require reboot if DRM holds reference)
sudo rmmod trigger6
```

The kernel driver successfully:
- Probes both T6 chips
- Reads EDID and detects monitors
- Registers DRM cards (card1, card2)
- Reports connectors as "connected"

But freezes the system when the compositor tries to use the displays. The issue is in the DRM atomic commit path interacting with USB bulk transfers.

## Contributing

The biggest unsolved problems:

1. **Fix the kernel DRM driver** — needs someone with kernel DRM debugging experience (KGDB, lockdep, ftrace). The `drm_simple_display_pipe` + USB combination has locking issues on kernel 6.17.

2. **Get output 1 working** — the second HDMI port on each chip. Protocol is correct per triggerdm source, but frames don't display. May need USB packet capture comparison with Windows driver.

3. **Optimize frame rate** — the userspace driver manages ~2 FPS. JPEG compression (format=13) would dramatically increase throughput, as the Windows driver uses JPEG for 1080p.

## References

- [mcttrigger/triggerdm](https://github.com/mcttrigger/triggerdm) — Official MCT ChromeOS driver (GPL)
- [cyrozap/mct-usb-display-adapter-re](https://github.com/cyrozap/mct-usb-display-adapter-re) — Reverse engineering docs
- [rhgndf/trigger5](https://github.com/rhgndf/trigger5) — Linux kernel driver for Trigger 5 (older chip)

## License

GPL-2.0-only (kernel driver), MIT (userspace driver)

## Credits

Protocol reverse engineering and driver development by Claude (Anthropic) + Ralph Friedman (Authentra), April 2026.
