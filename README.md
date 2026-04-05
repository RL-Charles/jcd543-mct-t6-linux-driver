# MCT Trigger 6 (T6) Linux Display Driver

First Linux driver for MCT Trigger 6 USB display adapters (StarTech USBC2HD4, and similar quad-HDMI USB-C adapters using the MCT T6-688 chipset).

## Status

| Component | Status | Details |
|-----------|--------|---------|
| **Userspace Python driver** | **Working** | 3 monitors at 1920x1080, correct colors, stable output 1 via vendor-style JPEG routing |
| **Kernel DRM driver** | **Experimental but live** | Loads on Pop!_OS/COSMIC, exports real DRM connectors, and COSMIC can enable extended T6 heads |
| **3rd monitor (output 1)** | **Hybrid DRM path in progress** | The stable transport is still JPEG plus `cmdAddr`; `secondary_userspace_jpeg=1` now exposes the DRM head while userspace feeds `/dev/trigger6-*-out1-jpeg`. `experimental_secondary_raw=1` remains diagnostic-only after a host freeze during live testing |

See `ROADMAP.md` for the plan from the current userspace preview to a proper DRM/KMS driver.

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

There are two relevant working paths:

- **Output 0 / stable raw path**: single bulk command header followed by one full RGB32 flip buffer
- **Output 1 / vendor 1080p path**: JPEG payload routed through a separate `cmdAddr` work area with `JPEG_PADDING_SIZE=1024`

#### 1. Bulk Command Header (32 bytes)

```c
struct bulk_cmd_header {
    uint32_t signature;        // 0 = display
    uint32_t payload_length;   // total: video_header + pixel_data
    uint32_t payload_address;  // framebuffer address in T6 VRAM
    uint32_t packet_length;    // full payload length
    uint32_t reserved2;        // 0
    uint32_t reserved3;        // 0
    uint8_t  padding[8];       // 0
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

#### 3. Payload Data

- **Raw path**: 48-byte flip header followed by full BGRX pixel data
- **JPEG path**: 48-byte flip header followed by JPEG data and 1024 bytes of tail padding

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

For dual-1080p chips, TriggerDM routes 1080p video for the secondary path through `cmd_addr=0x02800000` with JPEG source data and `JPEG_PADDING_SIZE=1024`. Using the same raw RGB32 full-frame path for output 1 was the main cause of the persistent flicker.

Hotplug is chip-scoped: if a chip is already driving one screen and its second HDMI port is connected later, the userspace driver re-probes and reinitializes that whole chip so the newly added output gets the same vendor-style routing and init sequence.

Both outputs initialized in one sequence (steps 5a-5c above for each). Bulk transfers must be serialized (mutex) — interleaving corrupts the stream.

### Known Issues

1. **T6 chip state corruption**: Sending wrong pixel format or bad init sequence can corrupt chip state badly enough that a physical unplug/replug is needed.

2. **Kernel DRM driver freezes**: The DRM framework on kernel 6.17 calls connector callbacks (detect, get_modes, fill_modes) from contexts that deadlock with USB control transfers. Even with all USB removed from callbacks, `drm_dev_register` triggers atomic flushes that dereference stale plane state pointers.

3. **Performance is still limited**: The userspace path is stable, but mirror mode is intentionally conservative to protect output 1 from flicker.

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

Community packaging:

```bash
python -m pip install ./userspace
mct-t6-display --mirror --fps 1 --reconnect-interval 3 --send-workers 2 --quality-profile balanced --jpeg-quality 95 --jpeg-subsampling 2 --stats-interval 30
mct-t6-install-user-service
mct-t6-benchmark-output1 --source synthetic --repeats 3
mct-t6-recover-output1 --bus 6 --address 13 --case stable --case 444-experimental --allow-unsafe-secondary-jpeg
```

Important limitation: `--layout extend-right` is currently a capture-slice mode in the userspace app. It is useful for experimentation, but it is not the same thing as a compositor-managed extended desktop. Native display extension requires the kernel DRM path to mature.

Userspace tuning controls now include:

- `--send-workers` to parallelize USB transfers across both T6 chips
- `--quality-profile auto|speed|balanced|text` for output-1 JPEG tuning
- `--jpeg-quality` and `--jpeg-subsampling` for manual clarity/performance tuning
- `--allow-unsafe-secondary-jpeg` to intentionally test settings outside the known-good output-1 envelope
- `--stats-interval` to log capture, prepare, encode, and USB throughput summaries while the service runs
- `mct-t6-recover-output1` to run output-1 hardware experiments and then restore the stable `balanced/95/2` state automatically

For output 1, quality values above 95 and `jpeg-subsampling` values other than `2` remain outside the known-good envelope. Those settings are still available for deliberate experiments, but they can blank the screen or shift the color planes even when luminance looks correct.

## Pop!_OS / GNOME Setup

The userspace driver is still the safe path for daily work on Pop!_OS. For native extension experiments on kernel 6.17, prefer the hybrid kernel path with `secondary_userspace_jpeg=1`; do not persist `experimental_secondary_raw=1` as your default configuration.

Why the old service did not work:

- It was a system service running as `root`, so it could not see your logged-in Wayland session.
- It hard-coded `/opt/authentra/...`, which does not match this repo.
- Mirror mode only used `grim`, which is a wlroots tool and is not the right backend for GNOME/Pop!_OS.

Use a user service instead:

```bash
# Installed package
mct-t6-install-user-service

# Repo checkout
cd userspace/
./install_user_service.sh
```

The installer writes a per-user systemd unit, imports your current session environment, and starts the mirror daemon from this checkout.
The installed user unit now pins output 1 to the known-good tuple: `--mirror --fps 1 --reconnect-interval 3 --send-workers 2 --quality-profile balanced --jpeg-quality 95 --jpeg-subsampling 2 --stats-interval 30`.

Capture backends:

- `grim` for wlroots compositors
- `gnome-screenshot` for GNOME / Pop!_OS
- `Pillow` is required when using the `gnome-screenshot` backend

On COSMIC, the first screencast request may still ask you to choose the desktop and press Share. The userspace driver now uses the standard XDG desktop portal screencast flow, stores the returned `restore_token`, and reuses that approval on later restarts instead of prompting every time.

## Kernel Driver (Experimental DRM/KMS Path)

```bash
cd kernel/
make
sudo mkdir -p /lib/modules/$(uname -r)/extra
sudo cp trigger6.ko /lib/modules/$(uname -r)/extra/
sudo depmod -a

# Test manually first. Do not persist raw-secondary options in modprobe.d.
sudo modprobe -r trigger6 2>/dev/null || true
sudo modprobe trigger6 secondary_userspace_jpeg=1 manual_only=1

# Disable the old userspace mirror service so it does not reclaim the USB devices
systemctl --user disable --now mct-t6-display.service

# Output 1 stays black until a feeder writes JPEG frames into the hybrid device node
mct-t6-feed-output1 --list-devices
mct-t6-feed-output1 --list-streams
mct-t6-feed-output1 --device /dev/trigger6-006-013-out1-jpeg --stream-index 2 --fps 2

# Animated manual-only visibility test with obvious frame numbers
mct-t6-feed-output1 --device /dev/trigger6-006-013-out1-jpeg --test-pattern --animate-test-pattern --frames 16 --fps 1

# Keepalive-style test: hold each logical frame for ~1s while still sending
# 5 writes per second so the monitor does not drop signal between updates
mct-t6-feed-output1 --device /dev/trigger6-006-013-out1-jpeg --test-pattern --animate-test-pattern --frames 16 --repeat-each-frame 5 --fps 5

# Only drop manual_only=1 when you intentionally want live DRM scanout risk
# from the compositor:
# sudo modprobe trigger6 secondary_userspace_jpeg=1 manual_only=0
```

Safer host workflow:

```bash
# Dry-run validation only: syntax-check the guard, inspect current host state,
# rebuild the module, and run the offline output-1 JPEG benchmark.
tools/trigger6-dry-check.sh

# Check for known host-side conflicts like stale DisplayLink rules or loaded
# evdi/udl modules before any live probe.
tools/trigger6-host-guard.sh conflicts

# Inspect the live host state without touching the driver
tools/trigger6-host-guard.sh status

# Build and stage the next module on the real host
tools/trigger6-host-guard.sh stage

# Lowest-risk prep: logically detach the T6 devices, then load the module without probing them yet
tools/trigger6-host-guard.sh arm

# Reattach the quarantined T6 devices only when you're ready for a real live probe
tools/trigger6-host-guard.sh unquarantine

# Only reload when the dongle is already detached; the wrapper refuses the unsafe live path
tools/trigger6-host-guard.sh safe-reload

# Capture a post-failure report without guessing at ad-hoc commands
tools/trigger6-host-guard.sh collect
```

The wrapper is intentionally conservative. It can quarantine the attached T6 USB devices through sysfs authorization, disables any COSMIC outputs backed by `trigger6`, refuses to unload the module while a T6 USB device is still attached, and tells you to reboot if the module is already wedged in teardown. That is deliberate: repeated live reloads with the adapter attached were the main pattern that preceded the desktop freezes.

The driver now also fails closed after a fatal USB transport error on a T6 chip: it stops queueing further frame traffic for that adapter and lets its connectors fall back to disconnected until you reload the module or unplug/replug the dongle. That does not fix the underlying transport fault, but it does avoid sitting in the repeated `Frame send failed ... -71` loop after the first bad write.

For the safest guarded host workflow, keep `manual_only=1` enabled. That lets the module probe the adapters and register `/dev/trigger6-*-out1-jpeg` for deliberate one-shot tests while keeping the DRM connectors disconnected so COSMIC cannot auto-enable them.

The current driver source also registers those hybrid JPEG miscdevices with mode `0666`, and that behavior is now verified on the live host after reboot and guarded reload, so the manual-only feeder test no longer needs a separate udev rule or `sudo` just to open `/dev/trigger6-*-out1-jpeg`.

The current live behavior also suggests the panel needs a steady stream to stay awake: slow one-shot frame changes can be visible but still let the monitor drop signal between updates, while a higher write cadence with repeated logical frames is more stable. `mct-t6-feed-output1` now supports `--animate-test-pattern` plus `--repeat-each-frame` specifically to test that keepalive hypothesis.

`tools/trigger6-host-guard.sh` now defaults to that safe mode and refuses `manual_only=0` unless you also set `TRIGGER6_ALLOW_LIVE_SCANOUT=1` for the command. That keeps an accidental environment override from silently re-enabling the risky compositor path.

As of the latest hardening pass, the old host-side `99-displaylink-mct.rules` hotplug rule was found to still match the T6 VID/PID and call a missing `/opt/displaylink/udev.sh`. That stale rule has been disabled and purged from package state, and `tools/trigger6-host-guard.sh conflicts` now flags that class of issue explicitly.

VM note: a VM with USB passthrough can isolate basic probe/load/unload smoke tests, but it will not reproduce the real Pop!_OS/COSMIC host compositor interactions that have been triggering the freezes here. Use the wrapper as the default live workflow and treat a VM as a secondary smoke-test environment, not a substitute for host validation.

Latest VM and guest-validation summary: see `FINAL_RESULTS.md`.

Optional VM smoke harness:

```bash
# Boot a disposable QEMU/KVM guest with both attached T6 USB devices passed through
tools/trigger6-vm-smoke.sh --disk ~/vm/ubuntu-24.04.qcow2

# Print the generated QEMU command without starting the guest
tools/trigger6-vm-smoke.sh --disk ~/vm/ubuntu-24.04.qcow2 --dry-run

# Fresh-machine path: install the host VM deps, fetch Ubuntu 24.04 cloud image,
# create a cloud-init seed, and print the exact launch command
tools/trigger6-vm-fresh-ubuntu.sh --install-host-deps

# Or do the prep and launch in one shot
tools/trigger6-vm-fresh-ubuntu.sh --install-host-deps --launch

# Export the attached T6 devices over USB/IP from the host
tools/trigger6-usbip-host.sh ready

# Launch the guest without direct QEMU USB passthrough and auto-attach the
# exported T6 devices over USB/IP
tools/trigger6-vm-usbip.sh --disk tools/.vm-images/noble-server-cloudimg-amd64.img --seed-disk tools/.vm-seeds/trigger6-smoke-seed.img --pass-arg -display --pass-arg none
```

What the VM harness is for:

- Isolating USB passthrough, module probe, bind, and unload smoke tests from the live COSMIC session
- Testing guest-kernel behavior with the real T6 hardware attached
- Capturing guest serial logs without risking the host desktop

What it is not for:

- Reproducing the exact host compositor behavior of Pop!_OS/COSMIC
- Declaring the DRM path host-safe just because the guest survives

Important current limitation: on this machine, QEMU `usb-host` passthrough is sufficient for probe/load smoke tests but not for real T6 frame traffic. USB/IP improves that to full guest attach and SuperSpeed enumeration, but real output-1 bulk writes still fail with guest `vhci_hcd` `-104` and host `usbip-host` `-71` errors on busid `6-1.1`. The latest validated state and blocker details are captured in `FINAL_RESULTS.md`.

The helper auto-discovers the currently attached T6 devices, creates a disposable qcow2 overlay by default, forwards guest ssh to `127.0.0.1:2222`, and shares this repo into the guest as mount tag `repo` so the guest can inspect the same source tree. On a fresh machine, `tools/trigger6-vm-fresh-ubuntu.sh` downloads the official Ubuntu 24.04 cloud image, verifies its SHA256, generates a cloud-init seed with SSH access, and then hands that image and seed to the main launcher. The USB/IP helper builds matching `usbip` userspace tools locally under `tools/.host-tools/usbip/`, and the VM USB/IP wrapper installs `linux-modules-extra-$(uname -r)` in the guest when `vhci-hcd` is missing. Inside the guest, mount the share with:

```bash
sudo mkdir -p /mnt/repo
sudo mount -t 9p -o trans=virtio,version=9p2000.L repo /mnt/repo
```

The kernel driver successfully:
- Probes both T6 chips
- Caches both logical heads per chip and reads EDID for each connected output
- Registers DRM cards for the T6 USB chips
- Exposes real COSMIC-visible HDMI connectors through DRM/KMS
- Supports raw-capable heads directly and can expose secondary heads with `secondary_userspace_jpeg=1` while a userspace feeder injects stable JPEG frames into `/dev/trigger6-*-out1-jpeg`

The current kernel refactor keeps chip-scoped init and per-head framebuffer metadata in sync with the working userspace discoveries, and the code now models one DRM connector/pipe per logical head. The missing piece is still the proper in-kernel JPEG plus `cmdAddr` transport for logical output 1, so the hybrid bridge is the safer way to exercise native extension without reusing the unstable raw-secondary stopgap.

The immediate atomic-commit freeze was addressed by moving USB I/O off the pipe update path and wiring the DRM mode-config atomic hooks correctly. On the Pop!_OS/COSMIC host, this now produces real extended heads instead of only mirror-mode userspace output.

Current limitations:

- `secondary_userspace_jpeg=1` still depends on a userspace feeder; output 1 will stay black until `mct-t6-feed-output1` is running.
- `experimental_secondary_raw=1` is still available for controlled diagnostics, but it is no longer the recommended live path because the vendor's stable 1080p secondary transport is JPEG-routed, not raw RGB, and a host freeze was observed during live testing.

## Contributing

The biggest unsolved problems:

1. **Replace both current stopgaps with a proper in-kernel secondary transport** — logical output 1 should use the vendor-style JPEG plus `cmdAddr` path without relying on either `experimental_secondary_raw` or the current `/dev/trigger6-*-out1-jpeg` bridge.

2. **Harden the kernel DRM path** — hotplug, suspend/resume, and repeated compositor reconfiguration still need broader validation on kernel 6.17.

3. **Optimize userspace throughput** — the userspace driver is still the quality/stability reference path for output 1 and remains tuned conservatively.

## References

- [mcttrigger/triggerdm](https://github.com/mcttrigger/triggerdm) — Official MCT ChromeOS driver (GPL)
- [cyrozap/mct-usb-display-adapter-re](https://github.com/cyrozap/mct-usb-display-adapter-re) — Reverse engineering docs
- [rhgndf/trigger5](https://github.com/rhgndf/trigger5) — Linux kernel driver for Trigger 5 (older chip)

## License

GPL-2.0-only (kernel driver), MIT (userspace driver)

## Credits

Protocol reverse engineering and driver development by Claude (Anthropic) + Ralph Friedman (Authentra), April 2026.
