# Development notes

This document describes the working development baseline, not a completed end-user
product. The target is this ThinkPad T14 Gen 6 Intel running Arch/Omarchy, using
one `0711:5601` revision `1010` JCD543-family MCT chip and the standalone HDMI port.
The [usability specification](USABILITY_SPEC.md) defines the remaining work and
release gates. It does not authorize installing or loading anything.

## What actually works

On kernel `7.1.9-arch1-2`, Hyprland 0.56.2/Aquamarine 0.14.0, the user confirmed
the HP X27q test image at fixed 1920×1080@60 and its physical return after an
external-only DPMS cycle. The laptop panel/session stayed active. Head 0 uses
raw XRGB8888 with the explicit Aquamarine name shim and active-only raw idle
refresh. A settled 45-second sample sent 44 refreshes with zero errors and no
re-enumeration; the 90-second fault watcher passed. This is narrow supervised
evidence, not a soak, suspend, hotplug, audio, VGA, or dual-head certification.

A later whole-dock detach at 01:04:26 and host hibernation/resume re-enumerated
the chip as device106 at 08:17:01. The resident module refused automatic probe
and remained unbound/refcount0, as designed. The new lifecycle work must support
deliberate recovery without recreating the older repeated-init loop. This later
system-power sequence is not proof that the old static-frame failure recurred.

The later installed DKMS artifact is physically confirmed after two separately
authorized full dock cold resets. Ten external-only software DPMS cycles passed.
An intermediate sleep pre-hook refused cleanup and did not run post. The revised
controller later stopped cleanly, but firmware re-enumeration persisted. An
HP-only AC power cycle restored status1 and a physically confirmed image on the
same device125 after another dock cold reset had left status0. The later
`0.1.0-4` package integrates the tested final-off helper and exact controller
profile. Its installed artifact passed an active stop, 15-second quiet interval,
warm start and 45-second zero-fault sample without changing device125. The user
confirmed the installed image before that cycle. Startup was explicitly enabled
at 15:59:51; the sandboxed watcher adopted the live generation without reload.
Actual reboot/suspend/replug, uninstall/rollback and a one-hour soak remain open. See
[the installation/lifecycle record](INSTALL_TEST_2026-09-06.md) for both failures
and successes; they are not a completed hotplug/suspend acceptance.

The currently approved compressed DKMS artifact is SHA-256
`6eaaacab55b70c1a27b92fdf9cf32c4b1058c7743c33c12ec22cfdf3c5e91f60`,
srcversion `CC62C8A09077D5A5D804316`, for `7.1.9-arch1-2` only. It adds
`final_monitor_off=1` to the head0 shim/raw-refresh profile. DKMS builds never
silently approve a changed artifact or kernel.

The tested kernel source is preserved in this public tree. Its original local
build is SHA-256 `cec6a3429df95e8b3d79ab01e02ff0b7ff96ccee5aa39a11ad30938c09374c35`,
srcversion `F6D5C7316849C7428A83002`. That binary is a private ignored artifact,
not a public download. Rebuilding elsewhere can produce a different hash because
of build paths/toolchain/debug metadata; verify your own artifact and never
edit a wrapper hash merely to bypass its original review boundary.

## The decisive discovery

The inherited 32-byte 1080p mode had sync starts inside the active image area.
MCT's GPL `RESOLUTIONTIMING` definition identified the fields; a public JCD543
USB capture established byte-offset table paging. Two separately guarded
IN-only live reads returned pages identical to that capture. Record 26 also
equals its actual Windows modeset, byte-for-byte.

Only these bytes were corrected:

| Offset | Before | After | Field |
| --- | --- | --- | --- |
| 0x0a | 0x18 | 0xd8 | hsync start 1816→2008 |
| 0x12 | 0xe8 | 0x3c | vsync start low byte |
| 0x13 | 0x03 | 0x04 | vsync start 1000→1084 |
| 0x14 | 0x1d | 0x05 | vsync width 29→5 |

Pixel clock 148.5 MHz, totals 2200×1125, active 1920×1080, hsync width 44,
positive polarities, and PLL bytes were unchanged. The complete corrected record:

```text
144402003c0098088007d8072c00650438043c040500bb02e8031d0101010000
```

The timing-only active change produced the first physically confirmed HP image.
Keep the complete-record regression and exactly-four-byte inherited-diff assertion.
See [TIMING_QUERY.md](TIMING_QUERY.md) for source/capture links and measured hashes.

## Code map and safety invariants

| File | Responsibility |
| --- | --- |
| `kernel/trigger6_drv.c` | USB matching/probe, controls, active initialization, frame transport, timers/work, DRM atomic callbacks, lifecycle and fault latches |
| `kernel/trigger6_connector.c` | Fixed validated 1080p60 mode and connector behavior |
| `kernel/trigger6_match.h` | Pure exact-descriptor/single-output policy shared with host tests |
| `kernel/trigger6_refresh.h` | Pure active-only last-frame replay eligibility shared with host tests |
| `kernel/trigger6_query.h` | Pure bounded display-IN allowlist and count bounds shared with host tests |
| `tools/preflight.py` | Cached sysfs inspection only; no USB/DRM device-node access |
| `tools/decode_timings.py`, `tools/inspect_timing_capture.py` | Offline bounded record/capture parsing; no traffic replay |
| `tools/*.sh` | Explicitly reviewed historical one-session experiments or local display content; inert without the appropriate invocation |
| `control/controller.py` | Root-owned installed-helper boundary, exact generation/artifact selection, bounded start/stop/watch/sleep policy; fake adapters for tests |
| `control/setup.py`, `packaging/` | Local source-only Arch/DKMS package, hash/mode manifest, explicit setup/removal; no implicit activation |

Keep default `manual_only=1`, empty `device_path`, `output_mask=0`, and every
experimental/query switch off. The descriptor-only branch must precede I/O,
allocations, workqueues and DRM registration. Active operation requires exact
descriptors/path, one selected head, valid sink/EDID and 58 MB layout. One active
attempt per module insertion includes failures. No reconnect loop, automatic
USB reset, force unload, writable fault-clear parameter, or broad device alias.

Timer/worker/send paths must remain quiescent with an inactive CRTC, disconnect,
suspend, or fault. DPMS-off invalidates the raw cache; a real full frame must
prime it after on. A successful USB transfer proves transport completion, not
visible pixels. Preserve the distinction in code comments, tests, and reports.

## Known misleading names and unresolved protocol behavior

The donor's 0x23 "color" and 0x24 "timing" requests are MCT audio node values and
audio engine state. Their blobs/call counts were intentionally unchanged for the
timing-only experiment and are regression-tested. Their removal is future work,
not an implemented cleanup. Likewise, 0x1c is undocumented in the inspected GPL
definitions; no new reset was introduced. The raw first-frame 0x80 flag is named
as JPEG reset in the lineage, another isolated question. Do not change all three
while diagnosing one defect. Public capture analysis is a behavioral oracle;
never run/replay proprietary binaries or full captured traffic as a shortcut.

Earlier T6-only disconnects correlated with static active frames. The opt-in
last-frame refresh coincided with stable short runs, but the firmware watchdog
explanation remains a hypothesis. Repeating valid video costs about 8.3 MB per
idle second; power/bandwidth impact needs measurement. The current one-attempt
latch prevents a failed experiment from becoming repeated reinitialization.

## Local edit/verify workflow

1. Read `AGENTS.md`, `SAFETY.md`, and the current evidence before a change. Check
   for a resident module; building never replaces it. Preserve the last working
   binary and logs in ignored artifacts without overwriting them.
2. Change one bounded behavior and add a regression for the failure being fixed.
   Use pure shared policy functions for exhaustive host tests when practical.
3. Run `make check`: 35 source-policy, 63 controller and 13 setup Python checks;
   64 descriptor cases, 128 refresh
   combinations, 39,475,200 IN tuples plus nine count/overflow bounds. C harnesses
   use warning-as-error plus ASan/UBSan. These do not emulate USB/DRM or prove
   scheduling/lifetime correctness.
4. Run `make build-staged` only with an already verified matching header tree.
   The kernel target uses `W=1`. Record compiler, kernel/config, warnings,
   vermagic/alias/dependencies, source diff and artifact SHA-256. Optional BTF was
   omitted on the original host because pahole was absent; do not hide warnings.
5. Run kernel checkpatch on the relevant delta and `git diff --check`. Compile
   host harnesses with both GCC and Clang in separate ignored output paths when
   either header/policy changes. Missing sparse/shellcheck must be reported,
   not represented as passes.
6. Any hardware follow-up needs fresh exact-device review, one explicit auth
   prompt, a bounded watcher/normal cleanup, eDP recovery, and user-visible
   confirmation. Historical shell selectors/hashes are not portable. No new
   hardware test is implied by a code or documentation task.

No test, build, or proposed roadmap step installs packages, DKMS, udev, a service,
or desktop config by default. Keep generated artifacts out of Git. Preserve GPL
notices and use source-level primary references when changing protocol behavior.

## Current setup implementation boundary

The rel4 package/controller is installed with explicitly opted-in startup.
It preserves the verified timing correction and one-probe latch. New udev
generations can be handled only by a separately approved installed helper, after
debounce/cooldown/budget/health checks. Rapid loss or fault never causes blind
reinitialization. Exact installed-kernel SHA approval is independent from DKMS
compilation; package installation never opts the user into startup. The bounded
sleep hook preserves inhibition after incomplete cleanup. See
[INSTALLATION.md](INSTALLATION.md) for the manifest, staging, acceptance and
rollback procedure, including current one-kernel approval maintenance limits.

The follow-up controller correction passed offline tests and an isolated live
pre-hook test: a 500ms reference-settle
window within a shared 2.5s stop deadline, unchanged outer sleep-hook ceiling,
fresh identity/generation checks before one ordinary removal, persisted precise
errors, and truthful inaccessible-ledger status. Kernel/control bytes remain
unchanged. The measured hook completed in 120ms, including a 25ms reference wait;
module removal was clean. Firmware nevertheless disconnected/re-enumerated
4.36s after logical teardown. This fixes an immediate-refcount assumption, not
the separate firmware state or a complete suspend/resume cycle. The official
[DRM lifetime documentation](https://docs.kernel.org/gpu/drm-internals.html)
allows open users after unplug and documents that unplug before protected
shutdown can leave hardware enabled. Any kernel quiesce-order experiment needs
separate review, exact guards and a preserved known-working artifact.
The [final monitor-off experiment](QUIESCE_EXPERIMENT.md) implements a
default-off, single-request disconnect-owned helper after unplug/drain. Its
isolated warm load produced a user-confirmed HP image; an active stop then sent
one successful final-off in 1.576 ms, with a quiet same-generation observation.
The module was then removed. This isolated result preceded the later installed
warm-restart pass; neither establishes full lifecycle approval.

The installed `0.1.0-4` integration makes `final_monitor_off=Y` part of the
controller's exact profile: insertion explicitly supplies it, and a resident
module with an absent/disabled/malformed parameter is unowned. Kernel defaults,
descriptor/probe guards, controller budgets, stop deadlines and service sandbox
remain unchanged. No timing/init/audio/frame code changed after the proven
isolated artifact. New package installation must preserve the old approval and
separately review the actual new DKMS hash; it cannot reuse old source identity.

The payload manifest now receives its release directly from PKGBUILD, and setup
verification compares it with a bounded read-only `pacman -Q` record. There is no
second pinned pkgrel or runtime override. Synthetic tests inject the package
record without consulting the host. Legacy rel1/rel2 manifests contain a known
stale revision field; a new-checkout verifier correctly refuses that mismatch.
Use the existing installed helper for pre-upgrade checks and the newly installed
one only after the reviewed package transaction completes.

The supervised recovery wrappers also exposed two distinct orchestration defects:
a cooldown check mixed `CLOCK_MONOTONIC` with the controller's `CLOCK_BOOTTIME`
ledger (it refused before mutation), and a user-owned outer timeout did not
contain the privileged runner after late authentication. That runner completed
its one internally bounded start and read-only checks, with clear canonical
state. Future wrappers must use the ledger's clock, separate authentication and
execution deadlines, and put the execution bound inside the privileged process.
Do not infer that an outer timeout means the privileged action did not run, or
launch another action until live state and remaining processes are checked.

## Upstream contribution plan

Prepare independently reviewable changes: first the four-byte mode correction
with the public capture and documented struct evidence; separately descriptor/
fault/lifetime hardening; separately compositor renderless-device support. Do
not submit the evdi-name shim as evdi ABI compatibility. Include clean synthetic
tests, exact supported hardware/profile, and sanitized results; offer private
captures only with explicit owner permission. Opening an issue/PR or pushing to
an upstream remote is a separate action, not performed by this development note.
