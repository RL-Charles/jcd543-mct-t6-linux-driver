# Safety boundary

This is experimental kernel code. After the successful local build, the user
explicitly authorized temporary descriptor-only and single-head active tests.
After earlier blank-screen tests, a four-byte firmware-verified timing correction
produced a user-confirmed visible HP X27q test screen on September 6 around
00:45 Mountain. The user also confirmed physical return after external-only
DPMS off/on. The 45-second static sample and 90-second fault watcher passed;
the original manual artifact was then preserved. A later whole-dock detach/S4
resume left it unbound behind the one-attempt latch. The user subsequently
authorized package installation and supervised lifecycle tests. The approved
DKMS artifact now has user-confirmed HP output after a full dock cold reset;
ten software DPMS cycles passed. A sleep-hook cleanup refused, followed by
status0 on a guarded restore. A second cold reset restored a physically confirmed
image. The later rel4 module is live; the user explicitly enabled startup at
15:59:51 after installed active-stop/warm-restart and short stability gates.
The bounded-reference-settle/error-reporting correction was installed as
`0.1.0-2`; its isolated pre-sleep stop passed in 120ms, including 25ms reference
settling. The T6 still disconnected/re-enumerated 4.36s after logical teardown.
Another dock cold reset did not restore head0 status; an HP-only AC power cycle
did, and the unchanged device125/artifact produced another physically confirmed
image at the 14:15 recovery. Successful module cleanup is therefore distinct
from firmware quiescence and warm recovery. Rel4 adds the separately tested
final-off helper; its one-attempt latch is unchanged. The enabled watcher adopted
the live module without reload. Actual reboot, suspend/resume, deliberate replug,
uninstall/rollback and one-hour soak remain unverified; see the
[dated record](docs/INSTALL_TEST_2026-09-06.md).
This narrow supervised success leaves
kernel crashes, session loss,
corrupted display output, and USB-controller stalls possible. Upstream history explicitly records
xHCI freezes and unreliable USB passthrough tests on other hardware.
An earlier run on this dock produced repeated T6-only USB disconnects after
initialization, without a transport error or host warning beforehand. This
demonstrates why zero transfer-error counters do not establish device stability.

During the 14:15 output hotplug, the main Ghostty singleton crashed in GTK4's
Wayland DMA-BUF feedback handling. Independent core analysis found a userspace
SIGSEGV, not an OOM or kernel/driver fault; the separate display-test terminal
survived. This remains a desktop-integration acceptance issue. Preserve user
terminal work and minimize exposed clients before any separately reviewed
output cycling; do not change terminal/system configuration implicitly.

## Enforced defaults

The optional package blacklists USB modalias autoload and ships its service
disabled. The installed root-owned controller additionally requires an explicit
per-kernel artifact hash approval, measured descriptors, fresh device generation,
active i915/eDP, and the reviewed Hyprland/Aquamarine package versions. It never
executes a loader from this user-writable checkout. Three attempts/hour, six/boot,
120-second cooldown, and a manual circuit breaker contain reconnect failures;
these are offline-tested policies, not a promise of firmware stability. The
bounded sleep hook may fail closed and require manual recovery. See
[the package review and rollback procedure](docs/INSTALLATION.md).

The USB alias targets only `0711:5601`, interface `ff/00/00`. Before allocation
or I/O, the probe additionally checks revision `0x1010`, one configuration and
interface, configuration 1, interface/alternate 0, one alternate, SuperSpeed,
and the exact three observed endpoint descriptors. Missing, duplicate, extra,
wrong-direction, wrong-transfer-type, or wrong-packet-size endpoints are refused.

Even a matching device is refused without its exact USB port path. With the
default `manual_only=1`, a selected matching interface is bound using cached
descriptors, but no vendor control/bulk request, DRM registration, worker,
timer, chip initialization, or scanout is started. Disconnect/suspend callbacks
handle this state without using an allocated driver object.

Active mode requires an explicit `manual_only=0` and exactly one output bit.
Current source consumes a module-global atomic permission latch before the first
active allocation/I/O. Even a failed probe consumes it. USB-core re-enumeration
cannot repeat initialization until a deliberate normal module unload/reload;
there is no writable parameter or fault-clearing path for this latch.
The disabled output receives no per-head status, EDID, readiness, resolution,
or monitor-control request. Chip-scoped setup is still shared hardware activity;
the output mask cannot isolate a transmitter from chip resets or global timing.
The donor RAM layout is accepted only at 58 MB. The first test exposes only a
fixed 1080p60 mode and rejects scaling/cropping, avoiding the donor's unbounded
resolution-table path and mismatched fixed-size buffers.

EDID requires its standard header and checksum. Only the fetched base block is
published; the unfetched extension count is zeroed with a corrected checksum.
Errors and short USB transfers stop further traffic; subsequent chunks check
the fault latch. Automatic USB resets, fault clearing, background head probes,
startup frame bursts, and resume reinitialization are absent. Transport switches
and bus-serialization changes are rejected for an active experiment. The JPEG
injection code remains inherited but cannot be enabled in this profile.

## What the guards cannot establish

Descriptors and port paths are not cryptographic identity. This dock has no USB
serial number, a different device may be plugged into the same path, and devices
can imitate descriptors. These checks reduce accidental matches; they cannot
prove the exact IC, transmitter wiring, firmware behavior, or physical model.
The 58 MB response was measured during the first active test. It agrees with the
inherited RAM layout; it does not validate every address or protocol operation.

An explicitly active test executes reverse-engineered control sequences and
frame transfers. Initial control transfers and short direct-KMS/Hyprland frame
tests passed on this dock; long-run reliability and unselected outputs remain
unverified. A software fault latch cannot cancel a USB transaction already executing in the
host controller, recover a kernel panic, or guarantee that other devices on the
controller stay available. Keep the laptop keyboard/screen available and detach
dock storage before testing. See the [recovery procedure](docs/MANUAL_TEST.md).

The default-off `aquamarine_evdi_name` switch changes only the DRM-reported name
to enter Aquamarine 0.14.0's existing generic renderless-KMS path. It does not
implement evdi's private ABI and must not be used with DisplayLink-specific
software or an unreviewed compositor. Module/USB names, descriptor checks, path
selection, raw head-0-only operation, and fault latches remain unchanged. The
proper long-term solution is compositor capability support, not this name shim.

The separate default-off `raw_idle_refresh` experiment replays only a successfully
sent real head-0 frame after one idle second, through the ordinary raw sender.
It adds no vendor command or boot primer. Timer and worker both require an active
CRTC, a valid cache, connected state, and clear fault latches. Disable cancels
activity and invalidates the cache before monitor-off; no refresh is permitted
while DPMS-off, suspended, disconnected, or faulted. This costs roughly 8.3 MB
per idle refresh and is a diagnostic hypothesis, not evidence of a firmware fix.
See the [experiment design and test gates](docs/IDLE_REFRESH_EXPERIMENT.md).

The successful mode fix changes only four bytes in the 32-byte 1080p record,
matching both the live firmware and a public JCD543 Windows modeset capture.
It does not certify every inherited setup request. In particular, donor names
`T6_REQ_SET_COLOR` (0x23) and `T6_REQ_SET_TIMING` (0x24) refer to MCT audio node
values and audio engine state, respectively. Their unchanged 40/16/16-byte
blobs and call counts are regression-tested to isolate the timing experiment;
their necessity and audio-side effects remain unverified. Request 0x1c also
remains undocumented in the inspected MCT definitions. No new reset or request
was added for the correction. Any removal of these calls requires a separate
bounded experiment, not an assumption based on the visible screen.

The separate default-off `query_only` stage retains every descriptor/path,
single-head, and one-attempt guard. With `manual_only=0`, it performs only the
existing RAM and selected-head status/base-EDID IN requests, then releases USB/DMA
references and binds with NULL driver data (the descriptor-only teardown path).
It allocates no frame buffers/workqueue and never initializes the chip or DRM.
An IN/EDID failure refuses binding. Its reviewed head-1 wrapper restores the saved
head-0 artifact only after a clean query; a USB/query fault stops the sequence.
It never sends blind frames or activates both logical heads.
That historical query returned no head-1 sink. Immediate head-0 restoration
failed its EDID guard before initialization, then the device re-enumerated once.
The one-attempt latch kept it unbound/quiet. Historical wrappers refuse the new
device number and must not be replayed blindly.

`query_timings=1` adds only documented head-0 timing count/table IN requests,
after raw status 1 and valid EDID, with query-only mode and disabled shim/refresh.
The count is capped before multiplication: at most 16 records/512 bytes, no
paging or retries. All query-mode IN requests pass a shared tuple allowlist;
OUT/bulk helpers independently refuse query mode. No audio or video initialization
can be reached. The new wrapper restores quiet/unbound state rather than active
video, including bounded failure cleanup. Treat malformed/short data or a
disconnect as failure. Documented IN purpose cannot guarantee firmware side-effect
safety. See [TIMING_QUERY.md](docs/TIMING_QUERY.md).
The separately opt-in `query_timing_page1` continuation permits only the observed
JCD543 tuple 0xc0/0x89, value 0, byte offset 512, length 512, and requires the
measured count 36. It replaces the first-page read, not an automatic paging loop.
Its wrapper starts with no module and ends unbound/module-absent. The public
JCD543 capture corroborates byte-offset units; a sentinel query is unnecessary.

## Reviewable scope

Development targets never install or activate anything. The separately authorized
[package/controller installation](docs/INSTALLATION.md) is now present on this
host, with exact artifact approval and separately user-authorized startup. Its stock host package
hooks rebuilt the UKI; read-only inspection found the blacklist but no trigger6
payload inside. Future package update/removal may invoke those hooks too; boot
and fallback validation remain distinct acceptance gates. Kernel builds stay in `kernel/`, host
test programs in `tests/build/`, and optional user-captured reports in ignored
`artifacts/`. Explicitly authorized runtime tests may temporarily bind this exact
device and expose its DRM connectors. They neither install nor enable autoload.
The out-of-tree/unsigned module taints the current kernel even after removal;
only reboot clears that diagnostic state. See the dated runtime record for the
actual module state and commands, rather than inferring it from a successful build.
Earlier runtime artifacts allowed the USB core to initialize a newly enumerated
matching device using resident parameters. The added one-attempt latch closes
that gap in the current source. Check the artifact hash: rebuilding does not
replace an already loaded module. The approved installed artifact is currently
live after the installed rel4 warm restart; its source and saved manual rollback
binary remain preserved. Ending resident authorization first requires stopping
the enabled watcher, then its guarded normal removal. Earlier sleep-stop failure
and incomplete real-sleep testing mean unattended cleanup is not proven.

For a safety bug, prepare a minimal source diff or synthetic reproduction and
remove private paths, monitor serials, screen pixels, and USB captures before
sharing. No automatic report or message is sent by this project.
