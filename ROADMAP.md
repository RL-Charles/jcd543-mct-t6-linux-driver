# MCT T6 Linux Roadmap

## Goal

Turn this repository from a machine-specific proof of concept into:

1. a stable community-preview userspace package people can install quickly,
2. a faster and clearer USB display pipeline for mirror and capture-slice modes,
3. a real DRM/KMS driver that can provide proper desktop extension on Linux.

## Current Reality

- The working path today is the Python userspace driver in `userspace/mct_t6_display.py`.
- That path captures the desktop and pushes frames over USB. It is useful, but it is not a compositor-managed display driver.
- `--layout extend-right` is a capture-slicing mode. It does not create a new DRM connector that GNOME, KDE, COSMIC, or Xorg can arrange as a native monitor.
- Proper desktop extension requires the kernel path to mature.
- The kernel driver currently exposes only one head per USB device instance and still uses an older raw transfer model that does not yet reflect the working userspace discoveries for secondary outputs.

## Product Tracks

### Track 1: Community Preview Package

Ship the working userspace path first so other Linux users can install and try it without reading source.

Deliverables:

- Python package with a console entry point.
- User-service install flow for Wayland desktop sessions.
- Udev rule and service template shipped as package data or distro assets.
- Release notes with tested desktops, tested adapters, and known limits.
- Basic troubleshooting guide for PipeWire, portal permissions, and USB access.

Exit criteria:

- `pip install ./userspace` works locally.
- A user can start the driver with one command.
- The package clearly states that mirror and capture-slice modes are preview features.

### Track 2: Faster Userspace Pipeline

Improve the existing userspace path before attempting a public “fast” claim.

Priority changes:

1. Replace Pillow JPEG encoding in the secondary path with libjpeg-turbo or TurboJPEG.
2. Split the pipeline into capture, resize, encode, and USB-send stages so one slow step does not stall the whole frame loop.
3. Move from a single global loop to per-chip workers so the two USB chips can progress independently.
4. Keep the vendor-style JPEG plus `cmdAddr` path for logical output 1 on both chips.
5. Add real performance logging: encode time, transfer time, frame age, dropped frames, and reconnect counts.

Target outcomes:

- Meaningfully higher stable FPS than the current conservative 1 FPS mirror service.
- Lower end-to-end latency.
- Fewer stalls when one chip or one output falls behind.

### Track 3: Better Image Clarity

The current secondary-head JPEG path is stable, but it is not yet tuned as a quality pipeline.

Priority changes:

1. Expose JPEG quality and chroma subsampling as configuration, not hard-coded constants.
2. Default text-oriented modes to 4:4:4 JPEG (`subsampling=0`) when bandwidth allows.
3. Skip resizes when the captured region already matches the target output.
4. Add optional sharpening only after correctness and stability are proven.
5. Measure the tradeoff between clarity and throughput per output, especially on logical output 1.

Target outcomes:

- Clearer text on the secondary head.
- Fewer visible JPEG artifacts on desktop UI.
- Configurable quality/performance profiles instead of one fixed compromise.

### Track 4: Proper DRM/KMS Driver

This is the work required for native desktop extension.

Required milestones:

1. Stop the current modeset freeze in the kernel path.
2. Redesign the kernel driver around both logical outputs per chip, not only the primary path.
3. Port the working protocol facts from userspace into the kernel path:
   - per-output `0x31` readiness,
   - chip-scoped init,
   - raw full-block layout for primary,
   - vendor-style JPEG plus `cmdAddr` routing for secondary 1080p.
4. Expose connectors, CRTCs, and frame delivery in a way compositors can use as real displays.
5. Add hotplug handling that supports partially populated chips and later-added second outputs.

Exit criteria:

- GNOME/KDE/COSMIC can see the displays through DRM/KMS.
- The adapter can be arranged in the desktop display settings as a native extended monitor.
- The driver survives suspend/resume, unplug/replug, and monitor hotplug without full session loss.

## Packaging Strategy

### Near Term

Package only the userspace path.

Recommended artifacts:

- Python wheel and source distribution for the userspace app.
- GitHub release tarball with install docs.
- Optional distro packaging later for Fedora, Ubuntu, and Arch once the dependency story is clean.

### Later

Package the kernel path only after modeset stability is proven.

Recommended artifacts:

- DKMS package for the DRM driver.
- Distro-native packages after multiple kernel versions are validated.

## Recommended Immediate Backlog

1. Ship the userspace app as an installable package.
2. Add performance instrumentation and benchmark scripts.
3. Add configurable JPEG quality and subsampling for the secondary path.
4. Prototype per-chip worker threads in the userspace path.
5. Debug the current USB/IP data-path failure (`usbip-host` `-71` on busid `6-1.1`) or move guest hardware validation to a host with IOMMU-backed controller passthrough; QEMU `usb-host` and current USB/IP both still stop short of stable real frame traffic.
6. Rework the kernel driver to model both outputs per chip before attempting another public “proper driver” milestone.
