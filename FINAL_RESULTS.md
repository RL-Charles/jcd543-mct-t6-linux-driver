# Final Results

Date: 2026-04-05

This file captures the latest end-to-end status of the Trigger 6 Linux work after the VM pivot and the follow-up USB/IP guest path.

## What Worked

- The userspace output-1 transport was validated on the real host before the VM pivot: the vendor-style JPEG plus `cmdAddr` ring produced visible color bars on monitor 3 during direct userspace testing.
- The disposable Ubuntu 24.04 smoke VM workflow is functional:
  - cloud image boot works,
  - SSH works,
  - the repo mounts read-write inside the guest,
  - guest-side kernel builds can run against the shared source tree.
- The repo now has a working USB/IP helper path:
  - `tools/trigger6-usbip-host.sh` builds repo-local `usbip` and `usbipd` from matching upstream Linux sources,
  - it exports both attached T6 adapters from the host,
  - `tools/trigger6-vm-usbip.sh` launches the guest without direct `usb-host` passthrough, installs the repo's T6 udev rule in the guest, and auto-attaches those adapters over USB/IP.
- Guest kernel compatibility is fixed for Ubuntu `6.8.0-106-generic`:
  - `kernel/trigger6_drv.c` now gates `drm_dev_set_dma_dev()` to kernels `>= 6.16`,
  - `kernel/trigger6_connector.c` now uses the older mutable `mode_valid` callback signature expected by the guest DRM headers.
- After those compatibility fixes, the guest can:
  - build `kernel/trigger6.ko`,
  - load `trigger6` with `secondary_userspace_jpeg=1`,
  - enumerate both passed-through T6 adapters,
  - create the hybrid JPEG feeder device node for output 1.
- The live host safety story is better than before even though the transport bug is still open:
  - `kernel/trigger6_drv.c` now trips a chip-level circuit breaker on the first fatal USB transport error and stops queueing further frame traffic for that adapter,
  - `kernel/trigger6_drv.c` also supports `manual_only=1`, which keeps DRM connectors disconnected and blocks automatic compositor scanout while still allowing guarded `/dev/trigger6-*-out1-jpeg` tests,
  - `tools/trigger6-host-guard.sh` now defaults to `secondary_userspace_jpeg=1 manual_only=1` for the guarded host path,
  - `tools/trigger6-dry-check.sh` can validate the guard wiring, kernel build, and offline output-1 JPEG path without loading the module or touching live scanout.
- The guarded host hybrid path now reaches a real one-shot feed on Pop!_OS:
  - after rebuilding the driver cleanly with `make W=1 -j1`, `tools/trigger6-host-guard.sh arm` plus `unquarantine` loaded `trigger6` with `secondary_userspace_jpeg=1 manual_only=1`,
  - both attached adapters reprobed cleanly and `/dev/trigger6-006-003-out1-jpeg` appeared while no `trigger6` DRM outputs were exposed to COSMIC,
  - a host-side `--test-pattern --frames 3` feed to that hybrid node completed with `feed_rc=0`, and the collected host report is `tools/trigger6-host-report-20260405-124625-manual-only.log`.
- The guarded host hybrid path now has visible post-reboot confirmation:
  - after reboot, the staged module was loaded again through the guarded `manual_only=1` path,
  - `/dev/trigger6-006-003-out1-jpeg` came up world-writable as expected,
  - both short unprivileged feeder batches and a 12-frame animated test-pattern run completed with `feed_rc=0`,
  - the user confirmed that the third monitor visibly showed several changing frames during the animated run, which is the first confirmed live kernel hybrid output success on the real host.
- The hybrid JPEG node permission issue is now fixed and verified live:
  - `kernel/trigger6_drv.c` now sets `head->jpeg_miscdev.mode = 0666` during hybrid-node registration,
  - after a clean reboot and guarded reload, `/dev/trigger6-006-003-out1-jpeg` came up as `crw-rw-rw-`,
  - an unprivileged host-side `userspace/feed_output1_jpeg.py --test-pattern --frames 3` run completed with `feed_rc=0`,
  - the post-reboot host report is `tools/trigger6-host-report-20260405-133258-manual-only-post-reboot.log`.
- Under USB/IP, the guest can also:
  - auto-install `linux-modules-extra-$(uname -r)` when `vhci-hcd` is missing,
  - attach both exported T6 adapters as SuperSpeed USB devices,
  - enumerate the expected three logical heads in userspace discovery.

## Final VM Findings

The remaining blocker is not the driver build or module load path. The blocker is guest USB transport.

### QEMU xHCI guest

- Both T6 adapters enumerate correctly in the guest.
- The kernel hybrid feeder device appears as expected.
- Real frame traffic still fails:
  - the hybrid kernel feeder stalls or fails on the first JPEG write,
  - the known-good direct PyUSB output-1 sender also fails on the first bulk write,
  - observed failures were `ETIMEDOUT`, `EPROTO`, and libusb `Input/Output Error`.

Conclusion: QEMU `usb-host` passthrough under xHCI is good enough for probe and module smoke tests, but not good enough for real T6 frame traffic on this machine.

### QEMU EHCI guest

- The adapters enumerate under EHCI, but the guest kernel logs show:
  - `bulk endpoint ... has invalid maxpacket 1024`
- That makes EHCI unusable for this hardware.

Conclusion: EHCI is useful only for descriptor/debugging experiments. The T6 adapters need SuperSpeed-class behavior for real traffic.

### USB/IP guest

- The host helper successfully exports both adapters by busid (`6-1.1`, `6-1.2`).
- The guest helper successfully:
  - boots without direct QEMU USB passthrough,
  - installs `linux-modules-extra-6.8.0-106-generic` when needed,
  - loads `vhci-hcd`,
  - imports both adapters over USB/IP,
  - enumerates them in the guest as SuperSpeed devices.
- Real frame traffic still fails under USB/IP:
  - guest `vhci_hcd` logs `urb->status -104` after real traffic starts,
  - host `usbip-host` logs repeated `urb completion with non-zero status -71` on `6-1.1`,
  - the one-shot userspace sender and the known-good output-1 JPEG recovery path both end in libusb `Input/Output Error`.
- One-device-only isolation does not clear the problem:
  - with only busid `6-1.1` attached, the guest still finds both logical heads and the one-shot userspace sender still ends in libusb `Input/Output Error`; host `usbip-host` still reports repeated `-71` completions and guest `vhci_hcd` still reports `urb->status -104`,
  - with only busid `6-1.2` attached, the guest finds the single output-0 head but the one-shot raw sender still fails, this time on the large payload write with libusb `Insufficient memory` (`Errno 12`) rather than the same immediate `-71` signature.
- Host-side `usbmon` on bus 6 / device 3 (`6-1.1`) narrows the failure further:
  - the setup control traffic completes cleanly,
  - repeated 32-byte bulk command headers complete successfully on endpoint 2,
  - the full raw payload transfer never appears in that capture before the failure propagates back to userspace.
- Cleaner output-0-only chunked replays on both chips reduce the ambiguity further:
  - with isolated `6-1.1` or `6-1.2`, a minimal `out.init()` plus manual raw output-0 send still succeeds through the 32-byte bulk command header,
  - host `usbmon` shows the first 102400-byte payload chunk reach bus 6 on both device 3 (`6-1.1`) and device 4 (`6-1.2`),
  - that first payload chunk never completes before guest timeout, so the guest reports `USBTimeoutError` with `sent=0` even though the host saw the transfer submission,
  - this means the current blocker is no longer just “large write allocation” in guest libusb: the first real payload chunk is reaching the host USB/IP path and then hanging there.

Conclusion: USB/IP solves guest device import and enumeration on this machine, but it does not yet solve real output-1 bulk frame traffic.

## Host Hardware Constraint

- Both T6 adapters sit under host USB controller `0000:6c:00.0`.
- This host does not expose an `iommu_group` for that PCI function.

Conclusion: full-controller VFIO passthrough is not available in the current host configuration.

## Practical Outcome

- Safe VM-only development is now partially solved:
  - build,
  - probe,
  - load,
  - dmesg inspection,
  - connector and device-node validation,
  - USB/IP guest attach and enumeration
  can all happen in the guest.
- The guarded real-host manual-only path is now materially better than before:
  - it can load without exposing live `trigger6` scanout to COSMIC,
  - it can expose the hybrid JPEG node for deliberate tests,
  - both privileged and unprivileged feeder batches now complete without immediately tripping the old transport-fault loop,
  - and the manual-only animated test pattern is now visibly confirmed on the real third monitor.
- QEMU `usb-host` passthrough is still insufficient for real frame traffic.
- USB/IP improved the guest position from descriptor-only to full device import, but the current output-1 data path still collapses under real bulk writes.
- A fully isolated guest path for stable output-1 frame traffic still likely requires either:
  - deeper USB/IP transport debugging on this host, or
  - a machine with proper IOMMU-backed controller passthrough.

## Final Status By Goal

- Provision disposable VM: complete
- Verify guest SSH access: complete
- Diagnose VM USB issue: complete
- Implement USB/IP guest workflow: complete
- Run longer stable test: blocked by USB/IP bulk-transfer failures on output 1
- Send desktop-like frame: blocked by USB/IP bulk-transfer failures on output 1
- Retest kernel hybrid feed: manual-only guarded host success confirmed; the third monitor visibly updates during the animated feeder test, but compositor-driven DRM scanout is still intentionally disabled and unproven
- Restore safe host state: complete

## Files Changed To Reach This State

- `kernel/trigger6_drv.c`
- `kernel/trigger6_connector.c`
- `tools/trigger6-vm-smoke.sh`
- `tools/trigger6-usbip-host.sh`
- `tools/trigger6-vm-usbip.sh`
- `README.md`

## Recommended Next Step

The next concrete step is to debug the USB/IP bulk-transfer failure itself before spending more time on guest-side DRM behavior.

1. Explain why the first 102400-byte raw payload chunk reaches host usbmon on both isolated chips but never completes before guest timeout.
2. Explain the extra `usbip-host` `-71` protocol failures that still appear on `6-1.1` once the connection starts collapsing, even though the simpler clean replay on both chips first presents as a hung payload chunk.
3. If USB/IP remains unstable, move the pending longer-run, desktop-frame, and hybrid-feeder validations to a host with IOMMU-backed controller passthrough.