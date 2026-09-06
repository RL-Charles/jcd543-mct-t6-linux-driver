# Upstream audit and provenance

Reviewed 2026-09-05. This is a focused source review, not a certification or
exhaustive concurrency/security audit.

## Baseline selection

The imported files are exactly the donor's `kernel/` subtree and root `LICENSE`
at commit `e2aca2ca89650a68df3184918f93e37fce933f2e`, dated 2026-04-08:
<https://github.com/ramifriedman/mct-t6-linux/tree/e2aca2ca89650a68df3184918f93e37fce933f2e>.
The unmodified local import is commit `2e15c5c`; comparison against the upstream
tree returned no difference for those paths before adaptation.

The fetched history contains 22 commits, dated 2026-04-04 through 2026-04-08.
The sequence progresses from initial release through USB serialization, hybrid
JPEG, fault handling, NV12, a beta snapshot, then a full CRTC/plane/encoder
rewrite in `911abc2`, hardening in `8ed8765`, and probe cleanup in `e2aca2c`.
The final three commits postdate the beta README. Selecting the latest source
retains the relevant DRM work and its history; it does not establish that the
latest rewrite received the same physical tests claimed for earlier paths.

The root README advertises beta operation on kernel 6.18 and Wayland, but
`FINAL_RESULTS.md`, `ROADMAP.md`, and the repository description contain older
or narrower results, including earlier freezes and USB/IP transport failures.
Treat those as historical evidence with different dates, not a unified test
report for this revision. The one open issue when inspected asks about
[`0711:560b`](https://github.com/ramifriedman/mct-t6-linux/issues/1); that ID is
outside this fork and was not added.

## Hardware fit

The donor's StarTech USBC2HD4 uses two T6 chips and four HDMI outputs; the local
dock enumerates one `0711:5601` device with the expected bulk endpoint. A shared
VID/PID makes it a useful protocol baseline but does not establish transmitter
compatibility. This dock has USB-graphics HDMI/VGA plus a separate DP Alt Mode
HDMI/DP pair. The latter cannot be enabled by this driver.

[cyrozap's hardware notes](https://github.com/cyrozap/mct-usb-display-adapter-re)
identify JCD543 in the Trigger VI family and list USB-graphics HDMI and VGA.
They also describe different transmitter arrangements among related T6 products.
This fork leaves the inherited two logical heads intact while permitting only
one selected head per active test. Physical port mapping is explicitly unknown.

## Findings addressed in this fork

| Donor behavior | Local change |
| --- | --- |
| Broad device-only USB alias; no endpoint validation | Interface-scoped alias, exact descriptor policy, and required port selector |
| `manual_only=0`; manual mode still queries/initializes, primes, and schedules activity | `manual_only=1` exits the probe before allocation or USB I/O |
| Multiple active heads and configurable risky transports | Exactly one selected head; default raw/NV12 transports only |
| Mode table and dynamic timing can exceed fixed frame buffers; refresh fallback can mismatch requested mode | One exact DRM 1080p60 mode; a separate bounded IN-only diagnostic never publishes or applies firmware records |
| EDID base checksum alone accepts all-zero data; unfetched extension count reaches DRM EDID validation | Header validation and a bounded base-only EDID representation |
| Control failures/timeouts can queue USB resets; delayed work can recover faults | First error/short transfer latches traffic off; no automatic reset/reprobe/recovery |
| Resume reinitializes hardware and resumes keepalive | Suspend/resume leaves active traffic stopped for deliberate re-test |
| Probe error loop cleans every encoder/CRTC/plane, including objects not initialized yet | Managed mode-config cleanup owns successfully initialized objects; early error clears interface data |
| Runtime sysfs controls issue USB writes independently of selected experiment | Read-only metrics only; all load parameters read-only after insertion |
| Plane preparation omits explicit GEM framebuffer fence preparation | Uses `drm_gem_plane_helper_prepare_fb` with shadow-plane helpers |

The cleanup change follows the Linux DRM implementation of
[`drmm_mode_config_init`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_mode_config.c),
which registers managed cleanup of created mode objects. A later exact-header
7.1.9 build verified the API signatures used here; runtime cleanup behavior still
requires a supervised kernel test. See [LOCAL_BUILD.md](LOCAL_BUILD.md).

## Integration and installation audit

The donor `install.sh` is aimed at Debian/Ubuntu. It removes/replaces a DKMS
source directory, installs a module, copies udev and modprobe configuration,
installs GUI/CLI files, and creates a global tray autostart entry. Its
`uninstall.sh` unloads a module and deletes global paths. The separate
`REMOVE_KERNEL_MODULE.sh` also writes a blacklist. `dkms.conf` has automatic
installation enabled. The udev rule grants raw USB access. Older VM and host
guard helpers can install packages, load modules, export USB devices, or change
host configuration. None is imported into the active working tree or executed.

The local Makefiles use an explicit prepared kernel build tree, validate its
release and `Module.symvers`, use recursive `$(MAKE)`, build with `W=1`, and
provide no installation target. `make build-staged` now reuses a verified Arch
header package extracted inside the repo, omitting optional module BTF because
pahole is absent. No DKMS dependency is needed for this workflow.

Hyprland's initial generic secondary-renderer path failed because this USB DRM
card does not provide a replacement renderer for i915. A subsequent explicit,
default-off DRM-name shim entered Aquamarine 0.14.0's generic renderless branch
and enabled real buffer import/atomic commits and USB frames. This is a temporary
compatibility experiment, not evdi private-ABI support. No EVDI/DisplayLink
software, Xorg configuration, compositor environment override, or monitor rule
is installed. See the [runtime evidence](RUNTIME_TEST_2026-09-05.md).
See Hyprland's [multi-GPU documentation](https://wiki.hypr.land/configuring/extra/multi-gpu/)
for the distinction between renderer priority and an additional display device.

## Licensing and protocol research

All imported kernel C/header files carry `GPL-2.0-only` and retain Authentra /
Ralph Friedman's copyright. The original root `LICENSE` separately describes
MIT terms for donor userspace code; that subtree is not imported. A complete
GPL v2 text from <https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt> is added
under `LICENSES/`. New local source, tests, scripts, and documentation are offered
under GPL-2.0-only. The root LICENSE is retained verbatim for provenance.

The donor credits [MCT's `triggerdm`](https://github.com/mcttrigger/triggerdm)
(GPL-2.0 ChromeOS userspace code using EVDI/libusb) and
[cyrozap's protocol research](https://github.com/cyrozap/mct-usb-display-adapter-re)
(software under 0BSD; copyrightable non-software notes under CC BY-SA 4.0).
These are references, not copied subtrees. The donor identifies its static
initialization/timing arrays as captured USB behavior; those inherited arrays
remain GPL source. No Windows/macOS binary or proprietary driver source was
downloaded, executed, disassembled, or imported during this work.

If protocol gaps remain after a reviewed first test, future Windows USB captures
can serve as a behavioral oracle: use synthetic color patterns, record exact
hardware/driver versions and setup packet direction/value/index/length, then
document each inferred operation independently. Keep captures private until
screen pixels and unrelated device traffic are removed. Do not distribute or
translate proprietary implementation code, replay unexplained writes blindly,
or treat a capture from another product as proof for this dock.

## Remaining limits

An exact kernel 7.1.9 build succeeds. Subsequent supervised tests passed module
binding, head-0 control initialization, a direct KMS frame, and short Hyprland
buffer-import/atomic-commit/USB transport with a default-off compatibility shim;
see [the runtime record](RUNTIME_TEST_2026-09-05.md). Other per-port mapping,
real monitor hotplug, long-run transport, and suspend/resume recovery remain
untested. There is no 4K, audio, HDCP,
hardware cursor, or color-management
implementation in the selected test profile. The fixed mode is a display timing;
it is not a measured 60-frame-per-second USB delivery rate. Long-term deployment
and multi-output support require further review and physical evidence.
