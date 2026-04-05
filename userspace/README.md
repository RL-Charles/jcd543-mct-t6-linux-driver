# MCT T6 Userspace Driver Package

This directory contains the installable userspace preview for MCT Trigger 6 adapters.

What this package is today:

- A working userspace USB display driver for mirror mode.
- A capture-slice `extend-right` mode for experimentation.
- A practical way to use the adapter on desktops where the kernel DRM path is not ready.

What this package is not yet:

- A native DRM/KMS display driver.
- A compositor-managed extended desktop implementation.

## Install

```bash
python -m pip install ./userspace
```

This installs the `mct-t6-display`, `mct-t6-install-user-service`, `mct-t6-recover-output1`, `mct-t6-benchmark-output1`, and `mct-t6-feed-output1` commands.

## Run

```bash
mct-t6-display --mirror --fps 1 --reconnect-interval 3 --send-workers 2 --quality-profile balanced --jpeg-quality 95 --jpeg-subsampling 2 --stats-interval 30
```

## Install As User Service

For a pip-installed package:

```bash
mct-t6-install-user-service
```

For a repo checkout, `./install_user_service.sh` still works.

## Output 1 Tools

Direct recovery on the chip that owns logical output 1:

```bash
mct-t6-recover-output1 --bus 6 --address 13
```

Run deliberate hardware experiments and automatically roll back to the known-good state before exit:

```bash
mct-t6-recover-output1 --bus 6 --address 13 --case stable --case 444-experimental --allow-unsafe-secondary-jpeg
```

Offline JPEG research without touching the device:

```bash
mct-t6-benchmark-output1 --source synthetic --repeats 3
```

Hybrid DRM output-1 feeder for the kernel path:

```bash
# Load the kernel driver manually with the hybrid secondary transport enabled
sudo modprobe trigger6 secondary_userspace_jpeg=1

mct-t6-feed-output1 --list-devices
mct-t6-feed-output1 --list-streams
mct-t6-feed-output1 --device /dev/trigger6-006-013-out1-jpeg --stream-index 2 --fps 2
```

## Notes

- `PyUSB` and `Pillow` are installed through Python packaging.
- Portal capture on Wayland desktops also needs system GObject Introspection and GStreamer components.
- The included user-service installer remains the easiest way to run the driver as a logged-in desktop user, and it now pins output 1 to the known-good tuple: `--quality-profile balanced --jpeg-quality 95 --jpeg-subsampling 2 --stats-interval 30 --send-workers 2`.
- `--layout extend-right` currently slices the captured desktop image; it does not create a native extended desktop output in the compositor.
- `--send-workers` parallelizes frame sends across chips; this is the first throughput improvement in the packaged userspace path.
- `--quality-profile auto` now resolves only to settings inside the known-good output-1 envelope.
- Manual JPEG overrides are available with `--jpeg-quality` and `--jpeg-subsampling`.
- Use `--allow-unsafe-secondary-jpeg` if you intentionally want to test settings outside the known-good output-1 envelope.
- `mct-t6-recover-output1` now restores output 1 back to the known-good `balanced/95/2` state by default after any experiment run.
- `mct-t6-feed-output1` is for the hybrid DRM path: the kernel owns the connector, and userspace injects stable JPEG frames into `/dev/trigger6-*-out1-jpeg` after the module is loaded with `secondary_userspace_jpeg=1`.
- `--stats-interval` emits rolling summaries for capture, frame preparation, encode time, USB send time, and payload throughput.
