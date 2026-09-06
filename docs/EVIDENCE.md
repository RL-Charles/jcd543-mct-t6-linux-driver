# Evidence and remaining unknowns

Recorded 2026-09-05–06, US/Mountain. Facts below distinguish local observation,
inherited information, source-level reasoning, and physical results.

## Current state — installed rel4 live, startup explicitly enabled

At **15:59:51 September 6**, after the user's explicit opt-in, the installed
watcher adopted the working device125 without reloading the module. Package
`0.1.0-4` and its exact approved DKMS artifact passed installed active stop,
15-second quiet, one warm start and 45-second streaming gates. The user confirmed
the installed image before that cycle. No USB reset, transport fault or new core
occurred during the cycle. Actual reboot, suspend/resume, deliberate replug,
uninstall/rollback and a one-hour soak remain unverified. Earlier status0/firmware
teardown failures and the GTK/Wayland Ghostty SIGSEGV remain recorded, not erased
by this narrow success. The latest dated sections below and
[installation chronology](INSTALL_TEST_2026-09-06.md) separate physical proof,
software results, failures and remaining limitations.

## Original manual result: physical display and DPMS return confirmed

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

## 2026-09-06 09:20 Mountain — offline package/controller gates

Implemented a separate root-owned-helper Arch/DKMS package and bounded controller;
no kernel source change, system installation, module reload, service activation,
or desktop configuration change was performed. The original successful binary
and its preserved copy still both hash to
`cec6a3429df95e8b3d79ab01e02ff0b7ff96ccee5aa39a11ad30938c09374c35`.

- `make check`: 35 source-policy, 40 controller, and 10 setup/manifest Python
  tests pass. Independently rebuilt GCC and Clang ASan/UBSan harnesses each pass
  64 descriptor cases, 128 refresh cases, and 39,475,200 IN tuples plus nine bounds.
- The controller tests include the actual 23-character srcversion format,
  exact artifact metadata/hash and unapproved kernel/compositor refusal,
  descriptor/udev generation, partial enumeration, stale work, budgets, rapid
  re-enumeration, S4 recovery policy, active fault cleanup, and incomplete sleep
  inhibition. These are synthetic policy/adapter tests, not hardware lifecycle proof.
- `systemd-analyze verify` and Bash syntax checks pass. `git diff --check` passes.
  Sparse/shellcheck remain unavailable. No C delta was introduced, so there is
  no new kernel checkpatch delta beyond the previously checked timing fix.
- Ordinary-user `makepkg --nodeps --noconfirm --log` produced the source-only
  `jcd543-trigger6-dkms-0.1.0-1-x86_64.pkg.tar.zst`, SHA-256
  `3c0bf049c6a674f7bbeef853020e853a7aefae22f9958488ae8348d487d35dc3`.
  Its 22 manifest-owned payload files verify after extraction; archive metadata
  records root ownership and intended modes. No `.INSTALL`, enabling hook, udev
  rule, raw runtime artifact, or user configuration is included. Standard local
  makepkg `.BUILDINFO` stays in this ignored archive, not a published release.
- All packaged kernel source bytes match the physically proven checkout.
  A full packaged-source W=1 build against the verified staged headers succeeds,
  with only the already-known missing-pahole version notice (optional BTF off).
  That distinct local build hashes to
  `e873786ea8332ae959a54c17f83355f34fc3a8227072f53ae73a639496931b5d`,
  srcversion `F6D5C7316849C7428A83002`, matching running-kernel vermagic and exact
  alias, empty dependencies. It was not loaded; a future DKMS artifact still
  requires inspection of its own installed hash and explicit approval.
- Read-only adapter check at this stage finds the exact T6 device106, path
  `2-1.4.1`, unbound, and the approved-source old module resident/refcount0.
  Hyprland is present; the idle laptop panel is off, so the new start guard would
  wait. No new physical display result is claimed.

See [INSTALLATION.md](INSTALLATION.md) for staged host installation and rollback.
Service enablement remains behind supervised installation, visible output,
DPMS/replug and sleep/recovery acceptance. New-kernel approval maintenance is an
explicit separate review; the initial approval command refuses overwrite.

### 09:23 follow-up — canonical module path compatibility

Read-only host inspection established that kmod reports `/lib/modules/...` while
this Arch host's `/lib` resolves to `/usr/lib`. Setup now normalizes only that
exact alias/current-kernel layout, then checks protected ownership/no symlinks
before reporting the artifact. It refuses traversal, another kernel/module,
unreviewed alias layouts and symlink escapes. Fixtures cover `.ko`, `.ko.zst`,
`.ko.xz` and `.ko.gz`; the full suite now passes 35+40+13 Python tests (88 total).
This corrects a safe refusal before installation, not a kernel/USB behavior.

The replacement final archive has SHA-256
`e7cce86932d0d9be0349e5e0fe953b8c07c7191a8cd455633edb540e0f2a6ef9`.
Its extracted 22-file manifest and controller/setup/kernel byte equality pass;
the kernel payload is unchanged from the full W=1 packaged-source build above.
The earlier `3c0bf049...` archive is retained privately but superseded. All
archives/build logs remain ignored and uninstalled. Before any actual installed
start, a harmless transient status/capability check must verify the unchanged
systemd sandbox retains CAP_SYS_MODULE with NoNewPrivs enabled; no speculative
sandbox relaxation has been made.

### 09:30 — stop-timeout containment and first prerequisite prompt

Final failure-path review restricted the controller's one cleanup attempt to a
failed **start**. A failed **stop** now immediately preserves its inflight/circuit
markers; it never submits another unbind while the timed-out kernel operation
may still be running. The new regression passes, including a later observer tick
that performs no mutation. Full Python tests now pass 35+41+13 (89 total).

The superseding source/helper archive SHA-256 is
`05b7b8054e8c02b220fb514b095c56e02496bc6af44d3c72654aaf127d3992d6`.
Its 22 manifest-owned extracted files verify, and helper/kernel source equality
passes. The earlier archives remain ignored, uninstalled development artifacts.

After review, one 300-second bounded graphical authentication prompt requested
only `/usr/bin/omarchy pkg add linux-headers dkms`. The Omarchy polkit overlay
was present on eDP, but the laptop stayed idle/locked. At 09:30:22 the command
expired with exit124 and an empty transaction log. No pkexec/pacman process
remained; linux-headers, DKMS and pahole were still absent. No package archive
installation, driver operation, service enablement or other system change ran.
Authentication readiness is the concrete next prerequisite, not a build failure.

## 2026-09-06 12:20 Mountain — prerequisites installed, driver still uninstalled

The user returned and explicitly requested one retry. Fresh read-only checks
confirmed eDP active/unlocked, no stale pkexec/pacman or package DB lock, installed
kernel `7.1.9.arch1-2`, and exact matching sync headers. One bounded graphical
`pkexec /usr/bin/omarchy pkg add linux-headers dkms` authenticated successfully
and completed with exit0. Pacman performed signature/integrity/conflict checks
and installed exactly:

- `linux-headers 7.1.9.arch1-2` — 21,599 package files, zero altered.
- `dkms 3.4.3-2` — 28 package files, zero altered.
- Required dependency `pahole 1:1.31-2` — 50 package files, zero altered.

The package-file results are from `pacman -Qkk`. Prepared headers include the
root-owned Makefile, Module.symvers and generated autoconf; kernel.release is
exactly `7.1.9-arch1-2`. Standard package hooks armed ConditionNeedsUpdate,
updated module dependencies, and scanned DKMS modules. `dkms status` is empty.
No custom driver package, approval file, service, module load/reload, autostart
or desktop configuration change was performed. The old physically proven module
remains resident/refcount0, with the T6 unbound. The reviewed archive still hashes
to `05b7b8054e8c02b220fb514b095c56e02496bc6af44d3c72654aaf127d3992d6`.
Its installation/capability/approval/live-test stages remain separately gated.
The generated transaction log is retained under ignored artifacts.

## 2026-09-06 afternoon — installed image, lifecycle refusal and cold recovery

The complete sanitized chronology is in
[INSTALL_TEST_2026-09-06.md](INSTALL_TEST_2026-09-06.md). The reviewed package was
installed, its 22-file manifest/41 package files verified, and the current-kernel
DKMS module explicitly approved at SHA-256
`404a3d3755feaabbef9d12ab018b4055ac495e774320dfc3c082945c95890a8e`.
The unchanged service sandbox passed a read-only CAP_SYS_MODULE/NoNewPrivs check.
The host's stock DKMS package hook rebuilt the UKI and updated Limine; a reviewed
read-only audit found the blacklist but no trigger6 payload in its initramfs.
Boot/fallback/signature limits are recorded rather than claiming a tested reboot.

The first packaged start failed before DRM and tripped its circuit. After a true
dock cold reset, device113 produced a user-confirmed physical image at 12:53.
Its 45-second sample and ten software-only DPMS cycles passed with zero faults,
zero off-state transfer and real-frame return on every on. The watcher adopted
the same generation without another insertion. A later sleep pre-hook failed
within about 26ms after unbind, preserved inhibition/inflight state, and never ran
post. The T6 re-enumerated once; a guarded restore saw status0 and refused before
OUT. The first acceptance runner swallowed captured stderr; the exact immediate
refusal cannot be reconstructed and is not labeled a timeout.

Another user-performed true cold reset and one guarded start restored device119
at 13:11:38. The user explicitly confirmed the HP test window again. The working
module remains live, **watcher inactive/startup disabled**. The later user report
of an off screen crossed with sleep cleanup, not a proven DPMS physical failure.

A controller-only follow-up adds bounded 500ms refcount settling within the
shared 2.5s stop deadline, exact persisted phase/errors, stale-state revalidation
and honest unknown-ledger reporting. It changes no kernel/control bytes and is
not installed at that checkpoint. Full offline validation passes 111 Python tests (35+63+13), both
GCC/Clang sanitizer matrices, unit/shell syntax and whitespace checks. Kernel
shutdown ordering remains a separately documented hypothesis. Startup, sleep,
replug, one-hour mixed soak, reboot and actual uninstall gates remain incomplete.

### 13:35 — controller correction committed and archive audited, not installed

Private development commit `95c01830146fb1d6a2c7aae775333111b99d981b`
contains the focused controller correction, 63 controller tests, updated evidence
and explicit package release `0.1.0-2`. Its source/helper archive SHA-256 is
`bad8b9a4c9284e17ea840dc962f85473b93bca795430894beb7fda76df66bc86`.
An ordinary-user extraction verified all 22 manifest files, exact controller/
checkout equality, and every packaged kernel file equal to both the checkout
and installed proven source. Archive ownership/modes are root-owned/non-writable;
there is no symlink or extra activation hook. Standard local `.BUILDINFO` remains
private in the ignored archive; it is not a published release artifact.

This archive has not been installed. The running module remains the approved
`404a3d37...` artifact on device119, service inactive/disabled. A later read-only
sample showed frames8054, refresh1153 and all fault counters zero. Installation
requires another reviewed action, inspection of any stock DKMS/UKI hook effects,
and an independent installed-artifact hash check. Changed artifact approval must
be preserved/reviewed explicitly, never overwritten silently.

### 13:40 — reviewed 0.1.0-2 upgrade installed without live interruption

The exact `bad8b9a4...` archive was approved and installed with one bounded
authenticated pacman transaction. The old compressed module/controller/approval/
manifest were preserved first. Package Qkk again reports 41 files, zero altered;
all 22 installed manifest files verify and the controller equals the reviewed
source. DKMS rebuilt the current-kernel module but its exact SHA remained
`404a3d3755feaabbef9d12ab018b4055ac495e774320dfc3c082945c95890a8e`;
approval was independently verified byte-identical and was not rewritten.

The stock UKI/Limine hook ran; pre/post UKI and config hashes were identical.
The parseable image still has 940 main entries, no trigger6 payload, and the
exact installed blacklist. Temporary extraction was cleaned. The resident
module's sysfs inode and device119 generation/binding were unchanged, with
advancing frames/refresh and zero faults. eDP/HP remain logically active, and
service remains inactive/disabled. Revised authenticated and unprivileged status
now accurately distinguish canonical versus inaccessible private ledger state.
At that checkpoint no sleep/DPMS/watcher action had followed the upgrade; live
cleanup still required review. See [the full audit](INSTALL_TEST_2026-09-06.md).

### 13:50–14:17 — clean STOP, persistent teardown issue, HP-only physical PASS

The separately authorized isolated pre-hook exited zero in 119.897ms, with
14.371ms to the exact-unbind event and 25.271ms reference settling. The module
was removed normally; no stuck task, circuit or inflight work remained. Sleep
inhibition was retained, eDP stayed active and no post/reload ran. Firmware
nevertheless disconnected 4.362s after its disconnect callback and re-enumerated
as device120. A further whole-dock cold reset produced device125. One later
post-hook rearmed state only; the explicit start then received status0 and
refused before initialization OUT/DRM/frames, with clean removal and latched
circuit. The earlier immediate-refcount defect and firmware teardown are thus
separate findings.

After an explicitly reported **HP-only AC power cycle of about 20 seconds**, with
HDMI and dock USB/power left connected, the same device125 returned status1 and
valid HP EDID at **14:15:11**. One approved clear/start restored active 1080p60.
The user subsequently confirmed a stable, visible test window: **physical PASS**.
The compressed installed artifact remains
`404a3d3755feaabbef9d12ab018b4055ac495e774320dfc3c082945c95890a8e`, with controller
`88d442054be2ad3e003b0a7fe78bd7e1676aefbc4f449f220a79edbcc97767e2` and unchanged
approval. Canonical state records one managed attempt and no circuit/inflight;
service remains inactive/disabled. The 14:16:49–54 raw sample sent four frames/
refreshes and 33,177,920 bulk bytes; every fault and head1 traffic counter stayed
zero, with no disconnect or warning through 14:17:13.

Two wrapper issues are preserved separately: a mixed-clock cooldown assertion
refused before any mutation, and late authentication outlasted the user-owned
outer timeout while the privileged single start completed normally. Its final
log and independent state checks prove completion; outer exit137 alone did not.
No second kernel attempt was launched. Future runners need matching ledger
clocks and a privileged execution deadline separate from authentication.

A separately symbolized main Ghostty singleton SIGSEGV occurred at
14:15:11.921, within about 20ms of DRM ready. Independent core analysis traced
GTK4 4.22.4 `dmabuf_formats_free` called by `linux_dmabuf_done` in Wayland feedback
handling; no OOM or kernel/driver fault was found. The dedicated non-singleton
test terminal survived. This external GTK/Wayland hotplug bug remains a client
safety gate: preserve user work and minimize singleton exposure before separately
reviewed output cycling. The physically working display is preserved; only
offline design continues. No Ghostty/system configuration changed. Raw logs,
ledger backups and metrics remain ignored/private; this update changes docs only.

### Later offline work — default-off final monitor-off branch

After evidence commit `31b2df0006d3a20f914b7d0751caa14328629cb3`, an explicitly
reviewed offline implementation adds `final_monitor_off=0`. It preserves unplug
and complete work drain before one private disconnect-owned EP0 `40/03` head0
off, guarded by exact profile/path, cached sink/EDID, prior active scanout,
configured/unbinding USB and no existing fault. Deadline250ms; no reset, retry,
head1 traffic or global/head fault-latch mutation. Existing atomic-disable
protection, timing record and all initialization/audio calls remain unchanged.

The isolated W=1 build passes on matching system headers, including both USB
state gates, with no warnings. Module SHA-256
`d54cf17bd604629be0dd39d1c21c18eefaa135366ae0010467f3d30d3d7a480b`, srcversion
`CC62C8A09077D5A5D804316`, matching vermagic/exact alias/no dependencies. New flag
is readonly and zero-initialized. Strict checkpatch passes; 114 Python checks
and fresh GCC/Clang sanitizer matrices pass, including 40,960 final-off policy
combinations and 8,193 result cases. See the
[design and detailed gates](QUIESCE_EXPERIMENT.md).

This branch has **not been installed or hardware-tested**. Only the prospective
source package release/header list changes (`0.1.0-3`); no new package transaction
or approval happened. Current proven manual/installed artifact hashes remain
`cec6a342...`/`404a3d37...`. The physically confirmed live module, installed
controller, service inactivity/startup-disabled state and desktop config are
untouched. Preserve the Ghostty client-hotplug safety gate before any further
separately reviewed transition.

The focused implementation was committed as `5679130425430f41b8dc9e71f0bb6d24a709c3b5`.
Normal-user package build `0.1.0-3` and its 45-entry/23-payload SHA/mode/scope audit
passed; archive SHA-256 is
`b4c992a4bd558be1e92eda437d0d0d39faeaf5a7f6671881c203b502451020a6`.
The inherited manifest compatibility-version field remains `0.1.0-1`, while
pacman metadata correctly records `0.1.0-3`; resolving that metadata discrepancy
is a separate packaging gate. The archive is not approved for installation.
At 14:53–54, read-only checks found device125 still bound/active with zero faults,
both displays on, installed artifacts/approval unchanged and service inactive/
disabled. The next separately reviewed test is the old-module DPMS-off/stop
bridge only, not a new-artifact load. Detailed archive and phase gates are in
[QUIESCE_EXPERIMENT.md](QUIESCE_EXPERIMENT.md).

### Supervised quiesce Phase A/B — September 6, 15:02–15:09

Phase A used the **old installed module**: scoped external DPMS-off, a two-second
zero-traffic sample, then exactly one ordinary installed stop at15:02:04.405.
Stop returned0 in116.885ms (reference settle25.252ms); eDP stayed on. Unlike the
earlier active teardown, device125 stayed enumerated and unbound through the
15-second quiet observation. No new kernel fault/core or process leftover was
found. A preceding Lua syntax refusal changed nothing and was preserved before
the separately authorized corrected attempt. One incidental controller bytecode
cache created by a diagnostic import was disclosed and retained for final
reviewed cleanup; subsequent privileged runners use Python `-B`.

Phase B separately loaded the isolated `d54cf17b...` artifact once from a fresh,
sealed root-owned0600 `/run` copy with `final_monitor_off=1`. At15:08:45–46, the
same device125 returned status1/valid HP EDID and active HDMI-A-2 at1080p60. The
existing test window/workspace returned automatically. A45-second sample advanced
87 frames, 42 idle refreshes and638,984,336 bulk bytes with zero errors, head1
traffic, USB reconnects, kernel warnings or new cores. Root/coordinator exited0.
The module stays live pending explicit physical confirmation; its new final-off
helper has not run yet. Installed package/artifact/approval and controller ledger
remain unchanged, service inactive/disabled. The installed controller correctly
does not own this differently hashed temporary module. Detailed gates/log names
are in [QUIESCE_EXPERIMENT.md](QUIESCE_EXPERIMENT.md).

The user then explicitly confirmed the Phase B test window was physically visible
on the HP: **physical PASS**. A separately approved Phase C performed an active
stop at15:15:05, without prior DPMS-off. The new helper issued exactly one
`40/03 value=0 index=0 length=0 timeout_ms=250`, returning **ret0/error0 in1576us**
with no skip. Unbind4.327ms, reference settle0.202ms and ordinary rmmod completed
in31.867ms total. Device125 stayed enumerated/unbound for15 seconds with eDP on,
no reconnect, kernel warning, new core or privileged process leftover. No
recovery/load followed. Installed package/approval/ledger stayed unchanged and
service inactive/disabled; sealed recovery artifact remains protected in `/run`.
This is a successful isolated active quiesce trial, not full lifecycle acceptance.

### Offline rel4 integration and archive audit — September 6

After physical/active-stop evidence commit `ed4419d19ddcef2230cbd954ce9b1eaf19b12ff4`,
integration commit `61cf78d` requires `final_monitor_off=Y` in the controller's
exact insertion/ownership profile. Missing/off/malformed values remain unowned.
PKGBUILD release `0.1.0-4` is passed explicitly into the payload manifest;
verification checks the installed release via bounded read-only `pacman -Q`.
No runtime release override exists. Old rel3 archive, installed rel2, installed
approval and sealed recovery artifact are preserved; no transaction occurred.

All **122 Python tests** pass (38 source, 66 controller, 18 setup), including eight
new ownership/argument/release/mismatch/failure regressions. Fresh GCC/Clang
ASan/UBSan each pass all four C matrices. Fresh W=1 build and strict kernel
checkpatch pass without warnings; shell/unit syntax and diff checks pass.
Kernel source is byte-identical to the physically tested isolated build.
Fresh module SHA-256 `b4fb3c15ed8df2cc271ba7750ffbc05297d9de58110f5c110031d50ea6b663a6`,
srcversion `CC62C8A09077D5A5D804316`, exact vermagic/USB alias/no dependencies.
All 48 loaded code/data/relocation sections match the tested `d54cf17b...` artifact;
the GNU build-ID note differs. Debug/BTF sections are outside this comparison.
The fresh binary itself was not loaded. Sparse/ShellCheck remain unavailable.

Normal-user makepkg completed in ignored `artifacts/rel4-package-nYx2Xh/`.
Archive `jcd543-trigger6-dkms-0.1.0-4-x86_64.pkg.tar.zst` SHA-256:
`a55d62f6501a93dfa96dd078929edfad3bf587eb2aad464e3ce92f1ece7ba90d`.
All 46 archive entries have safe root ownership/modes and no links, special
files or path escapes; all 24 payload files match their SHA/mode manifest.
Manifest release equals `.PKGINFO` release0.1.0-4. Extracted synthetic-root setup
verification passes with that archive package record. No `.INSTALL`, enable
link, udev rule or module-autoload entry exists; blacklist/service/sleep hook
are unchanged. The quiesce experiment document is included in the package.

Payload controller SHA-256:
`47ee89b3e7b749ec228be3fa50cf5ef41dc75d6fbd42081f8935eb92624bf454`;
setup `de9ca247e103b4f8d52472bc83b3966dcb5fd4d6ee8ffe053ed4d63e2edcd34e`;
manifest `b17f30fb973c1f6fd74ed05db2d811e68e5441af22ee547119e7d0a36a58aa84`.
Private archive build metadata and raw audit/runtime artifacts remain ignored.

At the last read-only check, device125 remained unbound/module absent after
Phase C, eDP on, service inactive/disabled and installed hashes unchanged.
Another received display confirmation cannot establish a new live module while
this state persists; the explicit earlier Phase B physical PASS is retained.
Next gate is review of one exact package transaction and its standard DKMS/UKI
effects, then independent new-artifact/approval review. No load, approval change
or service enable is part of this offline completion.

### 15:41–15:59 — installed rel4 lifecycle and explicit startup opt-in

The audited rel4 archive was subsequently installed and the resulting DKMS
artifact independently approved, preserving the old approval and rollback
artifact. Package Qkk reports43 files/0 altered; setup verifies24 payload files.
Installed compressed module SHA-256:
`6eaaacab55b70c1a27b92fdf9cf32c4b1058c7743c33c12ec22cfdf3c5e91f60`,
srcversion `CC62C8A09077D5A5D804316`. The exact current profile requires head0,
shim, raw refresh, serialized USB and final-off; query/secondary switches stay off.

One separately authorized installed active-stop/warm-start test at15:41 kept
device125 unchanged. Final-off was exactly `40/03 v0 i0 len0 timeout250ms`,
ret0/error0 in1866us; ordinary installed stop completed in100.758ms. After15s
quiet, one start completed in550.922ms with status1/valid HP EDID. The45s sample
added83 frames,41 idle refreshes and614,024,400 bulk bytes, with zero faults,
head1 traffic, reconnects, new cores or privileged leftovers. No retry, circuit
clear, DPMS manipulation or service activation occurred in this cycle.

At15:59:51 the user separately authorized automatic startup. The service became
active/enabled and adopted the existing managed generation without reinitializing;
frames1622→1638 advanced. Effective/bounding capabilities contained only
CAP_SYS_MODULE, NoNewPrivs=1, seccomp mode2 with14 filters, ProtectSystem=strict,
ProtectHome=yes and PrivateTmp=yes. The exact
[installation chronology](INSTALL_TEST_2026-09-06.md) records approval, commands,
private evidence hashes and acceptance limitations. No source, desktop settings
or other dock-interface configuration changed during these actions.
