# Evidence and remaining unknowns

Recorded 2026-09-05–06, US/Mountain. Facts below distinguish local observation,
inherited information, source-level reasoning, and physical results.

## Latest result: physical display and DPMS return confirmed

On September 6 around **00:45 Mountain**, the user confirmed that the HP X27q
physically displayed the test screen through the standalone MCT HDMI port.
The user subsequently confirmed that the HP visibly turned off and came back on
during the **00:46:33–00:46:43 external-only DPMS test**. These are manual physical
observations, distinct from successful USB transfers or compositor screenshots.

The successful module was built from source commit `f79493e`:

- SHA-256: `cec6a3429df95e8b3d79ab01e02ff0b7ff96ccee5aa39a11ad30938c09374c35`.
- srcversion: `F6D5C7316849C7428A83002`.
- vermagic: `7.1.9-arch1-2 SMP preempt mod_unload `; no extra dependencies.
- Head 0, fixed 1920×1080@60, `aquamarine_evdi_name=1`,
  `raw_idle_refresh=1`, `serialize_usb_bus=1`; all query switches off.
- At 00:52:12: still loaded/refcount 1 and bound to exact device 102 at
  `2-1.4.1:1.0`; active head-0 CRTC, head 1 inactive, healthy eDP/VT2.
- No re-enumeration since insertion at 00:44:48, zero USB/send/short-write/
  keepalive/transport faults; kernel taint remains 12288 (out-of-tree/unsigned).

The 45-second settled sample sent 44 idle refreshes, adding 364,957,120 bulk
bytes; the 90-second root fault watcher exited 0. Ten settled DPMS-off seconds
held all bulk/frame/refresh counters unchanged. Re-enable sent fresh real full
frames before idle refresh resumed. Detailed timestamps/counters are in the
[runtime chronology](RUNTIME_TEST_2026-09-05.md).

The decisive source change was only four data bytes in the inherited 32-byte
mode. Live firmware record 26 and a public JCD543 Windows modeset are identical;
the original differed in horizontal sync start and vertical sync start/width.
The complete second 512-byte page also matches the public capture. The corrected
record fixed the physical blank screen in the supervised test. Audio requests
0x23/0x24 and all other initialization/stream behavior were held unchanged; their
necessity and safety remain separate open issues. See [TIMING_QUERY.md](TIMING_QUERY.md).

The exact working binary is preserved in ignored runtime artifacts. Nothing was
permanently installed, no config changed, and no boot/hotplug/suspend support is
claimed. The [persistence plan](PERSISTENCE_PLAN.md) is a proposal, not execution.

**Later state, 08:26:** at 01:04:26 both dock hub trees, card reader, Ethernet and
T6 detached together; T6 latched `-19`. Host hibernation entry followed at
01:04:32, then S4 resume/root-hub power loss at 08:17:00. T6 re-enumerated as
device106 at 08:17:01. The module-global latch refused one automatic probe and
left it unbound/refcount0, without a reinitialization loop. Only eDP is present
in Hyprland (idle/locked, DPMS off). No agent-issued runtime action caused this
sequence. It is not evidence of the earlier T6-only seven-second failure; it
demonstrates the intentionally missing reconnect/hibernate recovery. The reason
for the initial whole-dock detach is not established by these logs.

Current native Ethernet is a separate `0b95:1790` AX88179B entity bound to
`cdc_ncm`; the coordinating inventory reports NetworkManager Ethernet unavailable
and no separate dock USB audio entity. Neither Ethernet readiness nor audio
support is provided or proven by trigger6. They require separate diagnostics.

## Initial local host/device observation, before module insertion

| Item | Measured state |
| --- | --- |
| Host | Lenovo ThinkPad T14 Gen 6 Intel; Windows/Omarchy dual boot |
| OS/session | Omarchy 4.0.2, Arch Linux, Wayland/Hyprland |
| Kernel | `7.1.9-arch1-2`, x86_64 |
| GPU | Intel i915 |
| DRM | `card1-eDP-1` connected; `card1-DP-1` through `DP-4` and `card1-HDMI-A-1` disconnected |
| Hyprland | Only eDP-1 was observed by the coordinating host investigation |
| USB video device | One `0711:5601`, MCT Corp., T6 USB Station |
| Device revision | `bcdDevice=1010` (lsusb displays 10.10) |
| USB protocol/speed | bcdUSB 3.20; negotiated SuperSpeed, 5000 Mbit/s |
| Topology at report time | USB device `2-3.4.1`, interface `2-3.4.1:1.0`; bus 002/device 016 at inspection |
| Identity caveat | No USB serial number; port/device numbers can change |
| Device/interface class | Device ff/00/00; interface ff/00/00 |
| Configuration | One configuration, value 1; one interface; interface 0, alternate 0; three endpoints |
| Bulk IN | 0x81, attributes 2, max packet 1024, interval 0; max burst 1 |
| Bulk OUT | 0x02, attributes 2, max packet 1024, interval 0; max burst 1 |
| Interrupt IN | 0x83, attributes 3, max packet 64, interval 5; max burst 0 |
| Binding | T6 interface unbound; `trigger6` absent from `/sys/module` |
| Other dock functions | Genesys USB hubs, AX88179 Ethernet, card reader, `040b:f301` Billboard observed by host investigation |
| Build tools | GNU make 4.4.1, GCC 16.2.1, Clang 22.1.8, Git, Python 3, modinfo, modetest present |
| System prerequisites | System headers remain absent; exact verified headers staged locally; pahole/DKMS/sparse/shellcheck absent |
| Secure Boot | EFI value 0, disabled, measured by coordinating host investigation |
| Recovery environment | Btrfs root subvolume `/@`; snapper/btrfs commands present; no snapshot created in this work |

Commands used here were read-only `uname`, `lsusb -v`, cached sysfs reads,
`modetest -h`, local tool/package-file inspection, and the repo preflight. An
unprivileged `lsusb -v` said it could not open the device; available descriptors
and their matching sysfs values were still reported. No vendor USB requests,
USB captures, module actions, or kernel debug changes were performed during that
initial inspection. Later authorized runtime actions are recorded separately below.

`python3 tools/preflight.py --json` reproduces a fresh report from cached sysfs.
It prints to stdout, opens no `/dev/bus/usb` or `/dev/dri` device node, and requires
no third-party Python package. It does not certify a device or authorize loading.

## Source/build verification

| Check | Result |
| --- | --- |
| Import equivalence | `git diff upstream/master 2e15c5c -- kernel LICENSE` was empty |
| Upstream provenance | Pinned `e2aca2ca89650a68df3184918f93e37fce933f2e`; 22 commits fetched; no push |
| `make check` | 34 Python checks, 64 descriptor cases, 128 refresh cases, 39,475,200 query tuples plus nine count/overflow bounds pass |
| GCC C policy harness | `-Wall -Wextra -Werror`, AddressSanitizer and UndefinedBehaviorSanitizer; pass |
| Clang C policy harnesses | Same warning/sanitizer flags; 64 descriptor and 128 refresh cases pass |
| Initial `make preflight` | One matching unbound 5000 Mbit/s device; system headers missing, matching staged headers available; no module loaded at that stage |
| Initial `make build` | Stopped at absent system headers; this motivated verified local header staging |
| Exact-header `W=1` build | Passed after local extraction; no C warnings, expected missing-pahole version warning; optional module BTF omitted |
| Missing header files | `Makefile`, `include/generated/autoconf.h`, `Module.symvers`, `include/config/kernel.release` under `/usr/lib/modules/7.1.9-arch1-2/build` |
| `git diff --check` | Passed during validation |
| Generic Tree-sitter C parse | Connector, codec, codec header, and match header parsed; main driver/header hit unsupported kernel macro syntax (`__stringify`/type arguments). Not treated as a compiler pass |
| Kernel `.ko` | `kernel/trigger6.ko` produced; matching `7.1.9-arch1-2 SMP preempt mod_unload` vermagic; later insertion results below |
| Artifact SHA-256 | First KMS artifact `9fc97547029ebcd91bb1876f28b1d62f144110374a4af4849e3503840567fc14`; shim/status artifact `6eff96df530353d1a6e296616990c72c5b90881439a4552b81f9f867cf515c04`; prepared one-probe/idle-refresh artifact `71c43fee30514153bdda59a1ed20a08b9b7c35f43550652c3d3ee75d4c47a064` |
| Kernel checkpatch | Initial adaptation: 0 errors, 1 informational new-file/MAINTAINERS warning, 1,485 lines; latest kernel delta: 0 errors/warnings, 230 lines; new refresh-policy header: 0/0 |
| Hardware/display test | Corrected head-0 build: user confirms physical HP test screen and DPMS off/on return; earlier blank-screen failures remain in the chronology |

The compiled host harness exercises the actual `trigger6_match.h` function used
by the probe: observed descriptor acceptance, rejection of each changed identity
field, endpoint direction/type/size/interval mismatch, duplicate endpoints,
reordered valid endpoints, and single-output masks. It does not link the DRM or
USB driver, execute transport code, or emulate a kernel.
The refresh harness exercises all 128 combinations of the actual shared
seven-boolean eligibility function. Only explicitly enabled primary raw scanout
with a connected monitor, valid prior frame, and clear manual/fault state passes.
It does not exercise timer scheduling, locking, or hardware.

Source regression checks cover the early descriptor-only branch, default
parameters, exact alias, absence of automatic reset/recovery and writable control
attributes, managed cleanup, fault-latch wiring, bounded EDID exposure, fixed
mode selection, installer exclusions, Python syntax, and malformed descriptor
length rejection. These are guard regressions, not proof of full C correctness.

## Exact-header build follow-up

The trusted Arch archive supplied `linux-headers-7.1.9.arch1-2-x86_64.pkg.tar.zst`.
Its SHA-256 matched the unchanged local sync database, and its signature verified
with the installed Arch keyring using a local dearmored copy. Extraction and
all outputs stayed in this repo; the original system header path remains absent.
The successful build used GCC 16.2.1 with `W=1` and
`CONFIG_DEBUG_INFO_BTF_MODULES=` because pahole is missing. No kernel C API change
was needed after commit `e6d79cf`. The module is unsigned and has no additional
module dependencies because the DRM helpers are built into this kernel.
See [LOCAL_BUILD.md](LOCAL_BUILD.md) for URLs, hashes, signing fingerprint,
commands, artifact metadata, and the BTF limitation. Nothing was installed or
loaded; the T6 interface remained unbound after compilation.

## Supervised runtime follow-up

After explicit user authorization, descriptor-only insertion/removal passed at
18:15 Mountain time on 2026-09-05. Active head 0 then returned 58 MB RAM and a
valid HP X27q EDID, with clean control transfers and a connected trigger6 DRM
connector. Hyprland initially failed secondary EGL renderer creation before
sending a frame. The corrected atomic `modetest` command includes both `-s` and
`-P`; a supervised bounded VT3 test then transferred one full frame, returning
to the preserved VT2 desktop. An explicit default-off DRM-name shim entered
Aquamarine 0.14.0's generic renderless-KMS branch. A later sample showed an active
CRTC and 6,181 successful Hyprland frames with zero USB/send errors. Readable
visible output awaits user confirmation. Full commands, hashes, counters,
transient non-connected reload result, current module state, and recovery are in
[RUNTIME_TEST_2026-09-05.md](RUNTIME_TEST_2026-09-05.md).
At 18:55, two further physical-level USB disconnect/re-enumerations were observed
without any agent-issued reset. The first reprobe succeeded; the second returned
raw head-0 status `0x00`, so the connection guard refused probe before chip setup.
At 18:58 the module remained resident but unbound, with refcount zero and no T6
DRM card. Laptop VT2/i915 remained healthy; a user port/power check was requested.
The user completed that check and reported the standalone HDMI port between DP
and VGA. At 21:16 the dock reappeared at new path `2-1.4.1`; the resident module
correctly refused it because its readonly selection was still `2-3.4.1`.
The new-path supervised test and its exact authentication/result are recorded
in the runtime log; no path guard was removed to accommodate the port move.
Authentication completed at 21:24:16 and the same artifact initialized HP/head 0.
Shortly afterward, the T6 alone began repeatedly disconnecting/re-enumerating
roughly 7–12 seconds after each successful probe. USB-core reprobes reused the
resident parameters, exposing a gap in the earlier per-device fault latch.
The new module-global one-active-attempt guard has been built and source-tested;
that build is SHA-256 `27987c90ebf62670cfffd7cf68e2d59b21fc01c69b9ccb77daa9c21301145fd1`,
srcversion `57CD0FF21972DE205D7C134`. It has not yet been loaded. The earlier
`6eff96df…` artifact is preserved under ignored runtime artifacts. This guard
prevents repeated initialization, but does not establish why the chip disconnects.

Read-only follow-up found that the cleanup password prompt expired without any
removal. Quiet intervals instead correlated with continuously animated
screensavers, followed by inactive/DPMS-off CRTCs. User activity was followed by
another reconnect sequence; device 81 then stayed stable from 21:39, first while
animated and later while off. The user reported a black HP screen with a white
power LED: signal presence is distinct from readable scanout. This evidence
motivated the contained, default-off [idle-refresh experiment](IDLE_REFRESH_EXPERIMENT.md).
Its prepared build is SHA-256 `71c43fee30514153bdda59a1ed20a08b9b7c35f43550652c3d3ee75d4c47a064`,
srcversion `3C037EE0098BDEC7A3211D5`, preserving the one-attempt guard. The dated
runtime log records whether its separately authorized replacement actually ran;
building it does not replace the old resident module.

At 23:33:17 user authentication succeeded and the `71c43fee…` module actually
replaced the old one. Device 101 stayed enumerated. A static 45-second sample
sent 42 full idle refreshes (296→338 frames, 152→194 keepalives), with zero faults
and 348,368,160 additional bulk bytes. A later ten-second external-only DPMS-off
sample held all frame/bulk/keepalive counters unchanged; re-enable sent fresh
real frames and resumed refreshes. eDP remained active throughout. The user
confirmed the HP was still blank. A compositor screenshot of the test window
is readable but is not physical-pixel evidence.

A separately reviewed default-off `query_only` build now stops after the
existing selected-head RAM/status/valid-base-EDID IN requests. Its SHA-256 is
`3564df8fc611461d252483dcaaf5c751c72bfe2651e8353d167e1e2dfd8ed802`, srcversion
`DE5C92E23618EE9D77CE6F7`; W=1 and all 18/64/128 checks pass, kernel delta
checkpatch 0 errors/warnings (29 lines). The query/restore wrapper never enables
head-1 frames and restores saved `71c43fee…` only after clean query completion.
Its actual invocation/result is separate in the dated runtime chronology.

At 23:49:07 the head-1 IN query actually returned raw status 0/no sink, EDID bytes
0; no frames were sent to it. Immediate saved-head0 restoration returned status
1 but invalid full-length EDID, so its guard refused before initialization/OUT.
Device 101 disconnected at 23:49:12; device 102 appeared at 23:49:13 and the
one-attempt latch refused automatic probe. At 00:06 on September 6, saved
`71c43fee…` remained resident/refcount 0, interface unbound, no T6 DRM, eDP on,
and no further disconnect or host warning. Restoration to active video failed.
This single sequence cannot distinguish a query side effect, idle/watchdog
behavior, or an immediate-restoration readiness race.

The user confirmed workspace 5 and the test window migrated to eDP after the
external connector vanished. That window and its capture demonstrate compositor
content, not physical output on the HP.

The new [timing diagnostic](TIMING_QUERY.md) is prepared offline. W=1 and the
expanded Python/GCC/Clang sanitizer checks pass. Checkpatch: 0 errors/warnings
on the 162-line kernel delta and 59-line query header. Artifact SHA-256 is
`ee5d9402b5a1ff65c1100c36e3229a0e9f1b5ad4d165f5e3cdcb2fc31418481c`,
srcversion `DE73E2F323EF05B0DD600AF`; vermagic/alias match, extra dependencies
empty. Its runtime result is not yet established at this preparation point.
The inherited active timing bytes/stream are unchanged; the decoder reports
their sync-start/width disagreement with advertised CEA 1080p60.

At 00:13:59 the first timing query succeeded, returning exactly 16/36 records
in 512 bytes. All decode as valid modes; none is 1080p. After ten passive seconds,
normal cleanup completed at 00:14:09, device 102 unchanged, module absent, eDP on.
The public JCD543 capture's first page matches all 512 bytes and proves byte
offsets 0/512/1024. Its record 26 and actual captured modeset both use correct
CEA1080p60 timings, differing from the donor in four bytes/three sync fields.
The precise [continuation design](TIMING_QUERY.md) reads only offset 512/512
bytes, after fresh count36/validEDID, then removes itself. Build
`debce8f3f8b2409dbe3de5502bb9f16a7309314132565ae59c0773a4ea817edf`, srcversion
`0DA9B2181DC790C77E8B79F`, and expanded checks pass offline. No active timing
correction or physical display success is implied.

At 00:27:33 the continuation attempt authenticated, but raw head0 status was 0.
The guard stopped before EDID/count/page512; normal cleanup left module absent,
device102 unchanged/unbound. A user-requested single retry prompt was visible
on active eDP at 00:29:04, then timed out124 around 00:31:03 with an empty log.
No second probe ran. The live record26 remains unread. HP connection restoration
and successful authentication are prerequisites; no active correction is loaded.

After HP power-cycle, the next authenticated query at00:34:23 returned valid
head0/HP/count36 and the complete second512-byte page. All16 geometries are valid;
the page and record26 match the public JCD543 table/Windows modeset exactly.
Cleanup passed00:34:33, module absent, device102 unchanged, eDP on, no faults.
The four confirmed timing bytes were then corrected in source; all other active
code/data, including audio0x23/0x24, are unchanged. Corrected artifact
`cec6a3429df95e8b3d79ab01e02ff0b7ff96ccee5aa39a11ad30938c09374c35`,
srcversion `F6D5C7316849C7428A83002`, passed W=1/checkpatch/full tests. The subsequent
successful physical test and still-live state are summarized at the top.

## Unknown until further evidence

- Whether this physical dock is labeled JCD543 or JCD543P and which firmware/IC
  revision its enclosure contains; USB identity alone does not establish that.
- Head-1/VGA wiring and operation; head 0 is now physically confirmed on this
  dock's standalone HDMI port. The unconnected head-1 path was never streamed.
- Whether the measured 58 MB RAM report implies every inherited address is safe.
- Detailed color/image accuracy, sustained throughput, and long-run USB behavior
  beyond the successful short visible-screen and static-refresh tests.
- Runtime behavior beyond the short head-0 desktop experiment, including the
  reason one intermediate reload returned a non-connected status.
- A durable capability-based Hyprland/Aquamarine integration. The explicit name
  shim permits buffer import/atomic commits, but implements no evdi private ABI.
- Simultaneous outputs, long-run behavior, hotplug, and suspend/resume. The
  current profile intentionally permits only one output. One external DPMS cycle
  passed physically; suspend still stops traffic until a fresh deliberate test.
- Why the separate DP Alt Mode path is disconnected; this repository neither
  diagnoses nor changes that path.

## Next supervised step

Preserve the exact working artifact and review the lifecycle/setup specification
before any installation or new authenticated reload. The later whole-dock detach
and hibernation left the module resident/unbound; historical device102 wrappers
must refuse current device106. Longer reliability tests and kernel-lifecycle/
hotplug work remain future steps.
Head 1 remains unused. Recovery is in the runtime record and
[MANUAL_TEST.md](MANUAL_TEST.md).

For every later stage append: date, source commit and diff, kernel/module hash,
USB topology, selected logical/physical output, monitor/cable, exact command,
kernel log result, visible result, and recovery result. A successful build,
bind, test pattern, and Hyprland desktop are four separate milestones.
