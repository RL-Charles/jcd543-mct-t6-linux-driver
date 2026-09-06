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
and remains unbound/refcount0, as designed. The new lifecycle work must support
deliberate recovery without recreating the older repeated-init loop. This later
system-power sequence is not proof that the old static-frame failure recurred.

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
3. Run `make check`: presently 35 Python checks, 64 descriptor cases, 128 refresh
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

## Upstream contribution plan

Prepare independently reviewable changes: first the four-byte mode correction
with the public capture and documented struct evidence; separately descriptor/
fault/lifetime hardening; separately compositor renderless-device support. Do
not submit the evdi-name shim as evdi ABI compatibility. Include clean synthetic
tests, exact supported hardware/profile, and sanitized results; offer private
captures only with explicit owner permission. Opening an issue/PR or pushing to
an upstream remote is a separate action, not performed by this development note.
