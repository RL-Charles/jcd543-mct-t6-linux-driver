# Preflight, manual test, and recovery

**Reviewed manual procedure, not an automatic loader.** The user has now
authorized temporary tests on this host. A descriptor-only bind/removal and
active head-0 initialization, direct KMS transfer, and Hyprland transport passed.
On September 6, the firmware-verified timing correction also produced a
user-confirmed visible HP test screen and physical return after external-only
DPMS off/on. See the [dated runtime record](RUNTIME_TEST_2026-09-05.md) for exact
hashes, counters, and which steps ran. The same module is still temporarily
resident but unbound after a later detach/hibernation/resume; do not replace it
by replaying historical commands below.
Review the artifact, dependencies, source changes, and
[verified build record](LOCAL_BUILD.md) before each new experiment.
The later active/static-frame instability has a separately reviewed,
default-off [idle-refresh experiment](IDLE_REFRESH_EXPERIMENT.md). Its one-run
wrapper pins a different, freshly checked USB path and artifact; historical
commands below are not authorization to reuse a stale topology or retry a fault.
No persistence has been installed. The [proposed plan](PERSISTENCE_PLAN.md)
requires separate approval and preserves a kernel-specific, fail-closed rollback.

## 1. Prepare and build without loading

Use the laptop's own keyboard and panel. Save work before any later kernel test.
Disconnect dock storage and other nonessential peripherals. Identify the
standalone USB-graphics HDMI port (the MCT HDMI/VGA part of the dock), and use one
powered monitor known to accept 1920×1080 at 60 Hz. Leave VGA and the DP Alt Mode
HDMI/DP pair disconnected for the first experiment. Record the exact port label,
monitor, cable, and whether Windows can drive that same port/cable/monitor.

As the ordinary user:

```sh
cd /path/to/jcd543-mct-t6-linux-driver
REPO=$(pwd -P)
make preflight
make check
make build-staged
```

Build prerequisite: prepared **matching** `linux-headers`, including the build
Makefile, generated configuration, kernel release, and `Module.symvers`. These
remain absent from the system, but an exact signed package has now been verified
and extracted inside this repo. `make build-staged` uses it without installation.
GCC, Clang, make, and `modetest` already exist. The build omits optional module
BTF because `pahole` is absent; see [LOCAL_BUILD.md](LOCAL_BUILD.md).

No package transaction is required for the current staged build. An alternative
future reviewed Arch package transaction for system-installed headers is:

```sh
sudo pacman -Syu linux-headers
```

That alternative is a system update, can upgrade the kernel, and is outside this
repository-local development/test workflow. Coordinate it with the normal Omarchy maintenance
workflow; reboot
into the updated kernel if needed, then rerun preflight and build. Do not pair a
new header package with the old running kernel or copy a `.ko` from another ABI.
DKMS, sparse, and shellcheck were absent; DKMS is unnecessary for manual tests.
The staged build already has matching vermagic and an empty module-dependency
field because this kernel builds the required DRM helpers into `vmlinux`.

After a successful build only:

```sh
uname -r
modinfo kernel/trigger6.ko
modinfo -F vermagic kernel/trigger6.ko
modinfo -F alias kernel/trigger6.ko
modinfo -F depends kernel/trigger6.ko
sha256sum kernel/trigger6.ko
```

Require matching vermagic and the intended USB/interface alias. Record the
compiler, source commit/diff, module hash, and dependency list. If dependency
modules are missing, review the exact listed dependencies before loading them;
never use force flags to bypass version, signature, or unresolved-symbol errors.
Secure Boot was measured disabled on this host, but verify again if firmware
settings change. An out-of-tree module still taints the kernel for diagnostics.

## 2. Descriptor-only insertion

The first kernel test should bind descriptors only. `make preflight` must still
show exactly one matching device and an unbound interface. The path measured
on 2026-09-05 was `2-3.4.1`; recheck it because USB topology can change.

In one user-operated root terminal, monitor the kernel:

```sh
journalctl -kf
```

In another root terminal, after navigating to this repository and confirming
that current preflight still reports this exact path:

```sh
insmod kernel/trigger6.ko device_path=2-3.4.1 manual_only=1 output_mask=0
readlink /sys/bus/usb/devices/2-3.4.1:1.0/driver
ls /sys/class/drm
```

Expected: the log reports a descriptor-only match and the interface binds to
`trigger6`. There is **no new T6 DRM card/connector**, no vendor initialization,
and no change to the monitor signal. Module insertion alone is not evidence
of video support. If the driver is already loaded, stop and determine its source
and parameters; this procedure must not replace an unrelated installation.

Stop on a kernel warning, oops, USB error, panel disruption, or controller stall.
Use the recovery steps below. After a clean descriptor test, remove the temporary
module from the same root terminal:

```sh
rmmod trigger6
```

Do not continue until removal succeeds and the interface is unbound again.

## 3. One active output, with exclusive KMS ownership

This stage sends experimental reverse-engineered commands. Arrange a supervised test window.
Hyprland can automatically discover the card when it appears, so insertion while
the desktop is running may trigger compositor modesets before a manual pattern.
The first run exposed a userspace renderer failure and sent no frames.

For isolated KMS, use a Linux text console with the graphical session inactive.
A supervised VT switch can preserve the running desktop and its unsaved work;
logging out is not inherently required. Record the original VT first with
`head -c 32 /sys/class/tty/tty0/active` and plan the return key combination.
Do not perform an unattended VT switch or restart the controlling session. Keep
the journal follower available. Never test the laptop's i915 card or unload i915.
The explicitly reviewed `tools/vt_pattern_test.sh` records this host's one-time
12-second VT3 experiment and automatic return to VT2. It refuses stale selectors
and default/unprivileged invocations; it is not a general-purpose VT launcher.

After verifying the current USB path, an explicit logical-head-0 test is:

```sh
insmod kernel/trigger6.ko device_path=2-3.4.1 manual_only=0 output_mask=1
modetest -M trigger6 -a -c -p -e
```

The driver reads RAM, status, and a base EDID, then initializes only the selected
logical output with the inherited chip-wide setup sequence. It requires the
donor's 58 MB usable-RAM report and a connected monitor with valid base EDID;
otherwise the active probe fails. Record the returned value instead of bypassing
the guard. It does not prime black frames at probe time.
The current source permits one active attempt per module insertion. A failed
probe or subsequent USB reconnect requires clean removal and a freshly reviewed
insertion; writing `bind` repeatedly will not authorize another attempt.
Stop on a device disconnect/re-enumeration loop even if error counters are zero.

From `modetest` output, identify the connected connector ID and its compatible
CRTC ID and primary-plane ID on the **trigger6** device. The following example
uses the first run's IDs `35`, `38`, and `36`; replace them with the IDs actually
reported for the current insertion:

```sh
modetest -M trigger6 -a -s 35@38:1920x1080-60@XR24 -P 36@38:1920x1080+0+0@XR24
```

`-M trigger6` selects the experimental DRM driver and `-a` uses atomic KMS.
libdrm 2.4.134 requires both `-s` and `-P` in this atomic mode. The `-s`-only form
can exit successfully without submitting a framebuffer. Require an active CRTC,
increasing `sent_frames`/`bulk_bytes`, zero fault/error counters in the read-only
`t6_metrics` attribute, and visible confirmation. A permission failure while
Hyprland owns DRM master is not a USB failure; privilege does not safely steal
master from a running compositor. Stop and arrange exclusive ownership.

The displayed pattern, readable colors/text, and clean kernel logs are the
evidence sought. End the pattern with Enter when prompted (or Ctrl-C), record
the result, and physically disconnect the dock before the cleanup below.

If no monitor is detected, do not repeatedly retry the same failure. The port
may map to logical head 1. After full cleanup and review of the first result,
a separate head-1 experiment can use `output_mask=2`, with the same single
physical monitor and otherwise identical steps. `output_mask=3` is rejected.
HDMI-A connector naming is inherited and does not prove physical HDMI/VGA mapping.

## 4. Hyprland integration, only after a clean KMS pattern

After a clean `modetest` result, examine the existing Hyprland session first.
A fresh session is a separately coordinated experiment if actually needed;
it can terminate control and lose unsaved work. Keep i915 as the renderer and the
laptop panel enabled. Check the actual new connector with:

```sh
hyprctl monitors all
python3 tools/preflight.py --json
```

Do not assume the DRM card number or connector name persists between boots.
If DRM sees the connected monitor but Hyprland omits it or reports DMA-BUF import
errors, save those logs and stop at that integration boundary. The existing
multi-GPU buffer path needs investigation; setting a USB card as the primary GPU
does not fix a protocol or framebuffer bug. This repository makes no Hyprland
configuration changes. The first run on Hyprland 0.56.2/Aquamarine 0.14.0 reached
an EGL-renderer failure before any frame was sent: Aquamarine's renderless-KMS
exception explicitly recognizes `evdi`, not `trigger6`. A monitor rule, changing
GPU order, or disabling explicit synchronization does not address that code path.
The default-off `aquamarine_evdi_name=1` experiment changes only the DRM-reported
name to take Aquamarine 0.14.0's existing generic renderless-KMS branch. This is
not evdi ABI support. It is limited to head 0, must not be used with DisplayLink
software, and is not a permanent integration recommendation. With this switch,
`modetest -M evdi` matches the reported DRM name; `-M trigger6` does not. First
verify the exact T6 is the only matching DRM device and that no real evdi module
or DisplayLink service is present. In libdrm 2.4.134, `-D` means a DRM bus ID,
not a device path; this driver reports an empty bus ID. Do not use a pathname
passed to `-D` as a device-identity guard. The current shim test did achieve
an active CRTC and thousands of successful Hyprland frames without a restart.

Consult the installed-version syntax and
[Hyprland multi-GPU documentation](https://wiki.hypr.land/configuring/extra/multi-gpu/)
before any separately reviewed compositor adjustment.

Record stable static output first, then a short scrolling/window-motion test.
No sustained frame rate is claimed. Do not test simultaneous outputs, suspend,
hotplug loops, or automatic startup in this initial window. Suspend deliberately
leaves traffic stopped and requires a fresh deliberate test.

## Recovery and removal

1. End `modetest` or close the temporary test window normally. A logout is not
   required when unplugging the T6 lets the running compositor release it.
2. Physically unplug the dock's USB connection. This removes the selected device
   and stops new host traffic; it also disconnects dock Ethernet/storage, which
   should already be idle and detached from the experiment.
3. In the root terminal, run `rmmod trigger6` once. If it reports the module is in
   use, inspect the remaining test/display process and close it normally. Never
   use `rmmod -f`. If a command hangs, avoid stacking additional unload/reset calls.
4. If the console or USB controller is unresponsive, disconnect the dock and
   reboot through the normal system control if available. A forced power-off is
   a last resort when the host is frozen and can lose unsaved data.
5. Leave the dock disconnected for the reboot. No installed module, DKMS entry,
   udev rule, service, or autostart exists in this workflow, so reboot does not
   reload this repository's module. Reconnect only after the normal desktop is
   healthy and the experiment has been reviewed.

During this supervised development run, the user also authorized one exact
T6-interface unbind for a compatibility reload. `tools/reload_name_shim.sh`
records that bounded experiment, verifies current path/artifact/session identity,
requires DRM disappearance/refcount zero/clean removal, and leaves every other
dock interface and i915 alone. It is not a generic recovery or hotplug loop.
Physical unplug remains the preferred recovery after a transport/kernel fault.

Verify after recovery:

```sh
lsmod | rg '^trigger6\b'
python3 tools/preflight.py
journalctl -k -b --no-pager | rg -i 'trigger6|xhci|usb.*(error|reset|timeout)'
```

Expected: no `trigger6` module line, an unbound T6 interface when reconnected,
and the laptop display operating normally. If the previous boot crashed,
`journalctl -k -b -1 --no-pager` may contain its final messages if persistent
journaling retained them.

There is no permanent installation to uninstall from the OS after this work.
After a manual insertion, unplugging and successful `rmmod`, or a reboot with
the dock disconnected, removes the temporary runtime driver. Keep this repo for
review, or move it to an archive/trash through your normal file manager; no
recursive deletion command is needed. Do not use the donor uninstall scripts.
