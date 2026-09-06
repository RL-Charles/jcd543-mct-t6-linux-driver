# Contained raw idle-refresh experiment

Prepared 2026-09-05. This is a default-off diagnostic experiment, not an asserted
fix or permanent deployment path. Physical readable output remains the goal.

## Evidence and interpretation

The T6 repeatedly disconnected/re-enumerated approximately 7–12 seconds after
active initialization, despite successful USB frames and zero transfer-error
counters. At 21:30:36 the last device instance initialized; Omarchy launched its
normal per-monitor screensaver at 21:30:38.619. That instance then sent 6,914
frames without a disconnect before the idle lock at 21:33:08.620. At 21:35 both
monitors were DPMS-off and the T6 CRTC inactive. The cleanup password prompts had
timed out; no module removal caused this quiet interval.

User activity at 21:35:43 preceded another series of T6-only reconnects. The final
instance, USB device 81, appeared at 21:39:07, alongside another screensaver launch
at 21:39:07.579. It sent 6,071 frames without USB errors before the 21:41:37 lock.
These timings support an active/static-frame or idle-sensitive firmware issue;
they do not prove a particular watchdog register or exclude another cause.
The user reported a black HP screen with a white power LED, not readable pixels.

The GPL donor source gives two useful constraints:

- Its boot path sends and caches black priming frames, then replays them until
  the compositor takes over. That automatic priming was deliberately removed
  from this fork. The donor's regular raw path skips unchanged content and
  does not arm a recurring keepalive. JPEG/NV12 paths do arm one. Restoring a
  cached black primer would not solve readable static desktop delivery.
- Its DPMS changes cancel timers/work before monitor-off. MCT's own GPL source
  defines vendor request `0x03`, `wValue=head`, `wIndex=0/off,1/on`, matching this
  driver's power request. There is no evidence supporting an inverted request.

## Narrow code change

`raw_idle_refresh=0` remains the default. With explicit `=1`, only raw head 0
is accepted. After a real framebuffer has been successfully sent, one second
without another real USB frame queues a replay through the **existing full-frame
raw sender**, using the last-sent pixels and existing staging buffer. There is
no new vendor command, startup black frame, additional buffer allocation, USB
reset, device-ID expansion, or retry after a USB error.

The timer and worker both check opt-in, head/transport, manual mode, connected
state, valid cached frame, CRTC activity, and both device/head fault latches.
The worker rechecks activity/deadline under the USB I/O mutex. Real USB frames
postpone the deadline; unchanged compositor updates do not. A full refresh is
about 8.3 MB, at most once per idle second, with one queued worker per head.
`keepalive_sent` counts these successful refreshes; they are also included in
`sent_frames` because the same normal sender is used.

CRTC disable marks inactive before cancelling work, deletes a possibly rearmed
timer after cancellation, and invalidates the last-frame cache before sending
monitor-off. The first subsequent real update therefore cannot be skipped merely
because its pixels match pre-DPMS content. Suspend/disconnect/fault handling also
prevents refresh. The existing `commit_tail_rpm` helper enables the CRTC before
committing active planes; refresh is never used to prime an inactive CRTC.

The module-global one-active-probe latch is retained. Any physical/firmware USB
re-enumeration after this insertion is refused before hardware I/O, even if the
first probe failed. A new attempt requires a normal reviewed unload/reload.

## Build and proposed supervised test

Prepared artifact SHA-256:
`71c43fee30514153bdda59a1ed20a08b9b7c35f43550652c3d3ee75d4c47a064`.
Srcversion `3C037EE0098BDEC7A3211D5`; vermagic
`7.1.9-arch1-2 SMP preempt mod_unload`. It builds with exact verified staged
headers and `W=1`; only the expected missing-pahole warning remains. Fifteen
Python checks, 64 descriptor cases, and all 128 refresh-policy boolean
combinations pass. Both C harnesses pass under GCC and Clang with ASan/UBSan.
Kernel delta checkpatch: 0 errors/warnings (230 lines); new policy header: 0/0.

The user authorized one exact-interface replacement and this sequence:

1. Revalidate current topology, cached descriptors, old loaded source/parameters,
   new artifact hash, kernel, healthy panel/VT, and taint. The reviewed wrapper
   unbinds only the exact T6 interface, requires DRM removal/refcount zero, and
   uses normal removal/insertion. No force or permanent installation.
2. Use `manual_only=0 output_mask=1 aquamarine_evdi_name=1 raw_idle_refresh=1
   serialize_usb_bus=1`, with the freshly checked exact `device_path`.
3. Present static high-contrast text with the terminal cursor hidden. Observe
   roughly 45 seconds: unchanged USB device number, active CRTC, about one idle
   refresh per second, and no USB/driver errors. Confirm actual readable output.
4. If clean, disable only the external output briefly. Confirm inactive CRTC and
   non-increasing bulk/frame/keepalive counters after disable completes. Restore
   only that output, and check a fresh image/refresh and physical readability.
5. Stop on any disconnect, fault, warning, or corruption. The one-attempt guard
   prevents an automatic initialization loop. Never mistake a screenshot of the
   compositor's framebuffer for confirmation of pixels on the physical monitor.

The wrapper is `tools/test_idle_refresh.sh`, inert without its explicit root
review token. Like earlier one-run tools, its pinned state is not portable to a
different host, kernel, artifact, or USB path. Actual execution and outcomes are
recorded in [the runtime chronology](RUNTIME_TEST_2026-09-05.md).

## Source references

- [Pinned donor driver](https://github.com/ramifriedman/mct-t6-linux/blob/e2aca2ca89650a68df3184918f93e37fce933f2e/kernel/trigger6_drv.c),
  raw send, keepalive, CRTC callbacks, and boot priming.
- [Donor DPMS commit](https://github.com/ramifriedman/mct-t6-linux/commit/a3e4752c10ba174a515d7799b38795816c3a68a3).
- [MCT GPL protocol header](https://github.com/mcttrigger/triggerdm/blob/63cecc7ef3308bcd4ad213e1ebd3139d804ffb8a/t6.h)
  and `t6usbdongle.c` monitor-power helper. No donor executable was run.
- [Linux 7.1 atomic helpers](https://github.com/torvalds/linux/blob/v7.1/drivers/gpu/drm/drm_atomic_helper.c),
  `drm_atomic_helper_commit_tail_rpm` ordering.

Screensaver/lock times came from read-only local user-journal entries. Installed
idle settings were 150/300 seconds. No idle setting, screen-lock behavior,
Hyprland configuration, or packaged Omarchy file was changed.
