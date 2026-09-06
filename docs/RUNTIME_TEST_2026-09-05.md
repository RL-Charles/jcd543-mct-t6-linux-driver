# Supervised runtime test — 2026-09-05

Successful test, **2026-09-06 00:45–00:52 Mountain**: the user physically confirmed the
HP X27q test screen after the four-byte timing correction and separately confirmed
the HP visibly went off and returned during external-only DPMS off/on. A settled
45-second static sample, 90-second fault watcher, and ten-second DPMS-off gating
test passed with zero USB faults or re-enumeration. The corrected `cec6a342…`
module was left temporarily loaded on device 102 at `2-1.4.1:1.0`, head 0 only,
with eDP/VT2 preserved. **Latest 08:26 state:** later whole-dock detach/host
hibernation/resume produced device106; the resident one-attempt module correctly
refused reinitialization and is unbound/refcount0. See stage40. No permanent
installation or config change was made.
Earlier blank-screen/reconnect failures below are historical evidence, not the
current result. Short supervised success does not establish unattended, suspend,
hotplug, or general dock support. See the [unexecuted persistence plan](PERSISTENCE_PLAN.md).

Publication note: personal checkout prefixes in historical commands are
normalized to `"$REPO"` (the reviewed checkout's absolute path). USB paths/device
numbers are session-specific selectors, not portable commands. Original local
development commit IDs remain evidence identifiers; private development history
and raw artifacts are not published. See [PUBLICATION.md](PUBLICATION.md).

## Authority and unchanged boundaries

The user explicitly authorized temporary module insertion/removal and guarded
USB/DRM communication on this laptop. Direct background privileged commands used
`pkexec`. When graphical authentication stalled, the explicitly authorized
visible-terminal path used `sudo` with the user's password entered in that
terminal, as the Omarchy skill requires for interactive commands. The agent
neither received nor recorded the password. No packages, DKMS, udev rules, services, autoload entries,
system headers, or desktop configuration were installed/changed. i915 and the
laptop panel remain active. No USB-controller reset, force operation, firmware
update, or proprietary driver execution was performed.

## Initial artifact and device (historical stages 1–10)

- Source: `ee552a1`, clean at insertion; unchanged for chronology stages 1–10.
- Kernel/vermagic: `7.1.9-arch1-2 SMP preempt mod_unload`.
- Module: `kernel/trigger6.ko`, SHA-256
  `9fc97547029ebcd91bb1876f28b1d62f144110374a4af4849e3503840567fc14`.
- Fresh preflight: one unbound `0711:5601` revision `1010`, 5000 Mbit/s,
  path `2-3.4.1`, interface `2-3.4.1:1.0`, exact guarded descriptors.
- Laptop: i915 `card1`, eDP-1 at 1920×1200@60; Hyprland session VT2.
- Monitor: HP X27q, user-attached HDMI cable; physical dock port label still not
  independently observed. Its valid EDID answered on logical head 0.
- No dock block device was mounted. Monitor serial and network identifiers are
  omitted from this tracked record; raw local logs are ignored artifacts.

Those are the first-stage artifact details. Later source changes add a default-off
Aquamarine name shim, raw connection-status logging, and accurate native-mode
diagnostics; they do not change the USB protocol or device-match policy. The final
tested build is SHA-256
`6eff96df530353d1a6e296616990c72c5b90881439a4552b81f9f867cf515c04`,
srcversion `DC2FAAE96B693A6F3C47599`, with the same vermagic. The first KMS-proven
binary is retained as ignored `artifacts/runtime-2026-09-05/trigger6-kms-proven.ko`.

## Command chronology

All paths below were checked against current preflight before use. They are
historical commands, not stable device selectors for a later boot/replug.

1. At 18:11, descriptor-only `pkexec insmod` was dismissed during authentication,
   exit 126. The module remained absent and the interface unbound. After the
   user was explicitly alerted, the same operation was retried once.
2. At 18:15:06, this command completed successfully (45-second outer timeout):

   ```sh
   /usr/bin/timeout --signal=TERM 45s /usr/bin/pkexec /usr/bin/insmod "$REPO/kernel/trigger6.ko" device_path=2-3.4.1 manual_only=1 output_mask=0
   ```

   The log explicitly reported descriptor-only binding with no vendor USB I/O,
   DRM registration, or scanout. Sysfs confirmed the exact driver binding and
   parameters `manual_only=Y`, `output_mask=0`, `device_path=2-3.4.1`. No new DRM
   card appeared. Expected out-of-tree/unsigned module taint messages occurred;
   there was no T6 warning stack, oops, USB error, timeout, or controller stall.
3. At 18:15:24, cleanup succeeded:

   ```sh
   /usr/bin/timeout --signal=TERM 45s /usr/bin/pkexec /usr/bin/rmmod trigger6
   ```

   `/sys/module/trigger6` was absent, the interface was unbound again, and the
   laptop panel was unchanged. Kernel diagnostic taint persists until reboot.
4. At 18:16:13, the first active insertion succeeded:

   ```sh
   /usr/bin/timeout --signal=TERM 45s /usr/bin/pkexec /usr/bin/insmod "$REPO/kernel/trigger6.ko" device_path=2-3.4.1 manual_only=0 output_mask=1
   ```

   RAM query returned 58 MB. Head 0 returned status 1 and a valid HP X27q EDID.
   All initial control transfers completed; `io_faulted=0`, `io_last_error=0`.
   No bulk frames had been sent. Head 1 was not queried or activated.
5. Read-only `modetest -M trigger6 -D /dev/dri/card0 -a -c -p -e` exposed:

   | Object | Observed ID/state |
   | --- | --- |
   | Driver/card | trigger6 `/dev/dri/card0` |
   | Selected connector | 35, HDMI-A-2, connected, one fixed 1080p60 mode |
   | Encoder | 39, compatible with CRTC 38 |
   | CRTC | 38, inactive, framebuffer 0 |
   | Primary plane | 36, XR24 LINEAR, compatible with CRTC 38 |
   | Disabled logical head | connector 40 HDMI-A-3, disconnected |

6. Hyprland automatically discovered HDMI-A-2, assigned workspace 5, and listed
   it at 1920×1080@60 to the right of the panel. That did **not** establish
   scanout: metrics stayed at zero frames/zero bulk bytes and CRTC 38 inactive.
7. The initial `modetest -a -s 35@38:1920x1080-60@XR24` exited 0 without a frame.
   Inspection of the official libdrm 2.4.134 source explained this: its atomic
   main path requires both `count` and `plane_count`, unless `-r` is used. The
   manual procedure has been corrected to include `-P`; exit status alone was
   not accepted as a pattern result.
8. The corrected bounded command was attempted once:

   ```sh
   /usr/bin/timeout --signal=TERM 30s /usr/bin/modetest -M trigger6 -D /dev/dri/card0 -a -s 35@38:1920x1080-60@XR24 -P 36@38:1920x1080+0+0@XR24
   ```

   It reported the intended mode/plane, `failed to set gamma: Permission denied`,
   then `Atomic Commit failed [1]`, exit 1. Hyprland still owned DRM master.
   There were no USB transfers or new kernel errors. No privilege escalation
   or force operation was used to try to steal DRM master.

Kernel logs also contained unrelated Wi-Fi/firewall messages and resets of USB
device `3-7` (`06cb:00f9`) around authentication, before driver insertion. These
are a different device/path from T6 `2-3.4.1`; no T6 reset was observed.

## Direct KMS proof and compatibility follow-up

9. A bounded `pkexec` VT wrapper attempt timed out after 55 seconds waiting for
   authentication, before its first command or VT switch. It was not counted as
   a KMS test. The next attempt opened a visible terminal using the inspected
   `omarchy launch terminal` route; the user confirmed entering their password.
10. At 18:30:09–18:30:22, `tools/vt_pattern_test.sh` verified the exact live
    USB/card/connector/parameter state and original VT2, switched to VT3, ran the
    selected atomic mode+plane for 12 seconds with a two-second kill grace, and
    returned to VT2 using its EXIT/INT/TERM trap. The planned timeout returned
    124. More importantly, the driver recorded one completed raw frame:

    | Counter | Observed value |
    | --- | --- |
    | Successful raw frames | 1 |
    | Bulk bytes/chunks | 8,294,480 / 83 |
    | Bulk errors / short writes / send errors | 0 / 0 / 0 |
    | Fault latch / last error | 0 / 0 |

    There was no T6 warning/oops/USB timeout. The laptop's running desktop and
    panel were preserved; no logout or compositor restart occurred.
11. Source inspection of all Aquamarine 0.14.0 `src/` and `include/` found the
    `evdi` special case only in its generic DRM backend, with no evdi-private
    ioctl. This supported a deliberately temporary, default-off name shim after
    direct KMS proof. `aquamarine_evdi_name=1` changes only the DRM name/description
    and is allowed only with head 0; module name, USB driver, guards, generic DRM
    operations, and fault handling remain `trigger6` behavior.
12. At 18:37:17, the explicitly authorized exact-interface reload wrapper detached
    only `2-3.4.1:1.0`. Its DRM card disappeared, Hyprland released both references,
    refcount reached zero, and ordinary `rmmod trigger6` succeeded. No other dock
    interface or controller was touched. The first shim build
    (`0c6760d875394b7850c866059cdf4d7bf0cd1a6fd7253a762af6e95d4f4c1e7b`)
    then read RAM 58 MB but did not receive status 1 for head 0. Probe stopped
    with `-ENODEV` before chip setup/DRM registration. Its raw status byte was
    not logged, so its exact value is unknown. No connection guard was bypassed.
13. A diagnostic-only source change added raw status logging. At 18:43:28, one
    reviewed reload of the unbound, refcount-zero module used the final `6eff96df…`
    artifact and the same active/head-0/shim parameters. This time status was
    `0x01`, the same HP EDID was valid, and initialization completed. The agent
    initiated no physical or USB reset. Why the earlier status differed remains
    an unresolved transient observation, not proof of a fixed hotplug bug.
14. Hyprland then submitted real frames automatically without configuration
    changes. Read-only DRM inspection confirmed connector 35 → encoder 39 →
    CRTC 38 (`ACTIVE=1`, 1920×1080), primary plane 36, framebuffer 45, XR24 LINEAR.
    The HP output stayed on workspace 5 at 1920×0, scale 1; eDP-1 stayed enabled
    and the session remained on VT2.
15. At 18:49:19, after about six minutes including normal screensaver animation,
    counters showed 6,181 successful frames, 22,939,240,336 bulk bytes, 260,213
    chunks, and zero bulk/send/short-write/transport errors. Fault latch and last
    error remained zero. This is a short transport observation, not a sustained
    frame-rate benchmark or long-run reliability claim.
16. An unprivileged temporary Ghostty window titled `JCD543-display-check` was
    placed on the HP's workspace 5, with readable text, RGB bars, and ten timed
    updates from `tools/display_check.sh`. No existing window was moved. A first
    legacy-syntax IPC attempt was rejected before execution; the current Lua
    dispatch syntax was verified from the installed Omarchy helpers and official
    wiki, then used successfully. No configuration file or persistent window
    rule was written. The user can press Enter in that window to close it.
17. At 18:55:04 the T6 disconnected and re-enumerated as USB device 17 at 18:55:06,
    on the same port path. Its fresh probe returned status `0x01`, valid HP EDID,
    RAM 58 MB, and initialized successfully. At 18:55:14 it disconnected again,
    then re-enumerated as device 18 at 18:55:15. This time raw head-0 status was
    `0x00`; probe returned `-ENODEV` before chip setup or DRM registration. No
    agent-issued USB reset/reload caused these events; their physical cause was
    not yet confirmed by the user. No T6 warning/oops/USB transport error was
    logged. At 18:58 the module refcount was zero, taint remained 12288, the
    interface was unbound, and eDP-1/VT2 were healthy. The test window migrated
    with workspace 5 to the laptop when the external monitor disappeared.
    A screenshot of HDMI-A-2 could not be taken because that output no longer
    existed. The user was asked to verify HP power/input, reseat the cable in the
    standalone MCT HDMI port, and reconnect USB-C once. No connection guard was
    bypassed and no further reload was attempted while awaiting that check.
18. The user subsequently confirmed HP power/input, reseated HDMI in the
    standalone MCT HDMI port between DP and VGA, and reconnected USB-C once.
    The dock disconnected from old `2-3` at 21:15:50 and the exact T6 appeared
    at `2-1.4.1:1.0`, USB device 23, at 21:16:39. All guarded descriptors,
    revision `1010`, and 5000 Mbit/s matched. The resident module still selected
    old `2-3.4.1`, so its path guard refused the new device before vendor I/O.
    At 21:17, the module had refcount zero and the proven hash/srcversion;
    taint remained 12288, VT2/eDP-1 remained healthy, and there was no T6 DRM card.
    A bind alone cannot change a readonly insertion parameter. Therefore
    `tools/reload_after_port_move.sh` was prepared for one normal removal of the
    unbound module and insertion of the same artifact with only `device_path`
    changed. It pins both old/current module state and the new device number,
    cached-descriptor SHA-256, path, kernel, taint, and artifact. It contains no
    unbind, device reset, force flag, or guard override. Its default invocation
    is inert; the eleventh source regression test covers that boundary.
    A visible terminal was opened for user `sudo` authentication at 21:19.
19. At 21:24:16 authentication succeeded and the port-move wrapper returned 0.
    The same `6eff96df…` artifact read RAM 58 MB, raw status `0x01`, and valid HP
    EDID on the new path, then Hyprland submitted frames. However device 23
    disconnected at 21:24:23; device 24 appeared at 21:24:25 and disconnected at
    21:24:32, followed by further T6-only re-enumerations. No other hub/device
    removal or agent-issued reset accompanied this sequence. USB-core reprobes
    automatically repeated the active initialization with resident parameters.
    At one 21:25 snapshot device 27 reported 78 sent frames, 320,614,624 bulk
    bytes, zero transfer/send/short-write errors, active CRTC 38/framebuffer 49,
    and the test window on HDMI-A-2/workspace 5. These observations do not negate
    the repeated disconnects or establish physical readability. No screenshot
    or further active visual experiment was attempted after discovering the loop.
20. The user was asked to unplug USB-C immediately. A cleanup wrapper permits
    one normal `rmmod` only after a device/physical disconnect leaves zero module
    references and no interface driver; it waits at most 15 seconds and never
    unbinds, resets, or forces removal. A 45-second background `pkexec` attempt
    timed out before execution. The same reviewed cleanup was then opened in a
    visible terminal for user `sudo` authentication. At 21:32 that prompt still
    awaited input and the old module remained resident. There was no host
    warning/oops or added taint; USB power policy read `on`, runtime `active`,
    so no runtime-autosuspend event was established as the cause.
21. Offline source review identified a definite containment gap: disconnect
    destroys a per-device fault latch, allowing the USB core to initialize a
    fresh instance automatically. Current source adds an atomic module-global
    one-active-probe latch after all identity/manual/parameter checks and before
    allocation or I/O. It never clears except by ordinary module removal.
    Thirteen guard checks/64 host policy cases pass; the `W=1` build succeeded
    with the expected pahole warning only. New artifact SHA-256 is
    `27987c90ebf62670cfffd7cf68e2d59b21fc01c69b9ccb77daa9c21301145fd1`, srcversion
    `57CD0FF21972DE205D7C134`, same vermagic. It is not yet loaded or hardware
    tested. The previous binary is preserved as ignored
    `trigger6-before-reprobe-guard.ko`. This change contains automatic retries;
    it does not claim to fix the underlying disconnect. A raw-frame idle or
    firmware-watchdog issue is only a hypothesis pending a contained test.
22. The visible cleanup prompt expired without executing its wrapper. The old
    module therefore remained loaded. Device 61 initialized at 21:30:36, just
    before Omarchy's normal screensaver launch at 21:30:38.619. Its counters
    reached 6,914 frames and 22.78 GB with no USB errors. At the normal idle lock
    (21:33:08.620), both monitors went DPMS-off and T6 CRTC 38 became inactive.
    No module command caused this quiet interval. User activity at 21:35:43.502
    was followed by further T6-only reconnects. Device 81 initialized at
    21:39:07, alongside a new screensaver launch at 21:39:07.579; it sent 6,071
    frames/17,677,479,664 bulk bytes, then remained quiet after the 21:41:37.581
    idle lock. It was still the same device at 22:00 with zero USB/send errors.
    The installed idle intervals are 150/300 seconds and were not changed.
    The user reported an entirely black HP screen with a white power LED;
    software frame/CRTC observations have not established readable output.
23. Source review compared the donor's raw, boot-primer, keepalive, and DPMS
    paths with MCT's GPL monitor-power helper. A new default-off
    `raw_idle_refresh=1` experiment repeats the last successfully sent real raw
    frame after one idle second, only while head 0 is active, connected, cached,
    and unfaulted. Disable cancels refresh and invalidates the cache before
    monitor-off; no startup black primer was restored. The one-probe latch is
    retained. [The design record](IDLE_REFRESH_EXPERIMENT.md) documents the
    source evidence, concurrency gates, and required physical checks.
    Artifact SHA-256 is
    `71c43fee30514153bdda59a1ed20a08b9b7c35f43550652c3d3ee75d4c47a064`, srcversion
    `3C037EE0098BDEC7A3211D5`. The exact-header `W=1` build passes; 15 Python
    checks, 64 descriptor cases, and 128 refresh-policy combinations pass.
    Both C harnesses pass GCC/Clang ASan/UBSan, and kernel delta checkpatch has
    zero errors/warnings. The old `6eff96df…` and one-probe-only `27987c90…`
    binaries are preserved under ignored artifacts.
24. The user authorized one exact-interface unbind/removal and this new artifact
    with `manual_only=0 output_mask=1 aquamarine_evdi_name=1 raw_idle_refresh=1
    serialize_usb_bus=1`, followed by a 45-second static image and scoped external
    DPMS-off/on observation. `tools/test_idle_refresh.sh` checks the literal
    current `2-1.4.1` path, cached descriptor hash, old/new source/artifact state,
    healthy eDP/VT2, taint, exact driver/DRM removal, and zero references; it uses
    bounded normal operations only. The first visible prompt at 21:49 expired
    at 21:54 without executing. One fresh prompt was opened around 21:57 after
    the user was alerted to wake/unlock normally and authenticate. At 22:00 its
    log was still empty and the old source remained loaded: the new artifact
    had not yet communicated with hardware. No off-state monitor was woken by
    the agent, and no compositor screenshot had been taken. By 22:02:39 the
    fresh prompt had also expired with `sudo: timed out reading password` and
    `sudo: a password is required`; no wrapper action ran. Old source
    `DC2FAAE96B693A6F3C47599` remained resident, device 81 remained bound, and
    the new artifact remained offline. Another prompt was not stacked. The
    prepared source/tests/docs were committed locally as `f4a6dcd`; no push.
    Actual user authentication is the next blocking condition, not a build or
    kernel-header problem. A fresh prompt must be coordinated while the user
    is at the laptop; the existing expired terminal cannot authenticate a
    command that has already exited.
25. At the user's further direction, the same exact wrapper was launched once
    through the Omarchy skill's agent/background privilege path:

    ```sh
    /usr/bin/timeout --signal=TERM --kill-after=2s 45s /usr/bin/pkexec /usr/bin/bash "$REPO/tools/test_idle_refresh.sh" --run-reviewed-idle-refresh
    ```

    The graphical authentication helper started, but the command timed out at
    22:04:22 with exit 124 and an empty captured log. The wrapper never began.
    Read-only `omarchy-shell lock isLocked` returned `true` and both monitor
    DPMS states were false. No lock or authentication setting was changed or
    bypassed. The exact next prerequisite is for the user to wake and unlock
    the laptop normally before a fresh authentication prompt; repeated expired
    prompts cannot substitute for that step. Old module/device/counters remained
    unchanged, and no static-image or DPMS experiment ran on the new artifact.
26. The user returned and unlocked the laptop. Old device 81 disconnected at
    23:29:52, and its earlier repeating initialization sequence resumed. A
    45-second graphical authentication attempt at 23:31:14 expired without
    running. Read-only PAM/Omarchy source inspection showed fingerprint-first
    authentication, followed by a password field; no authentication settings
    were changed. At the user's explicit next retry, a single 120-second-bounded
    prompt appeared on eDP-1 (`omarchy-polkit`, alpha 1) at 23:33:16. The user
    authenticated immediately. The exact `test_idle_refresh.sh` wrapper ran at
    23:33:17, unbound only the current T6 interface, removed the old module, and
    inserted `71c43fee…` with the approved parameters. It returned 0 at 23:33:18.
    Device number 101 did not change. Raw head-0 status was `0x01`, HP EDID valid,
    RAM 58 MB, and all initial error counters zero. Hyprland activated CRTC 38
    / plane 36 / connector 35 without configuration or session changes.
27. The old agent-created test window was closed with SIGTERM after its graceful
    close request required confirmation. Its PID/command were checked first;
    no user-work window was closed. A new opaque, cursor-hidden static terminal
    using `tools/static_display_check.sh` was placed fullscreen on workspace 5
    / HDMI-A-2; focus stayed on the user's existing eDP terminal. An external-only
    `grim` screenshot confirmed readable compositor content, not physical pixels.
    From 23:36:05 to 23:36:50, device 101 and active CRTC stayed stable:
    `sent_frames=296→338`, `keepalive_sent=152→194`, and
    `bulk_bytes=1,878,344,128→2,226,712,288`. All 42 successful frames in this
    sample were idle refreshes, about 0.93 Hz with USB transfer time. Every
    transport/send/short-write/fault counter remained zero. The user explicitly
    confirmed the physical HP remained completely blank, so the display test
    failed despite these software/USB milestones.
28. `tools/check_external_dpms.sh` is an inert-by-default user-session wrapper
    that addresses only HDMI-A-2 and restores it on exit/signals. The first
    attempt at 23:37:47 could not verify off state after one second and restored
    immediately; it did not establish a ten-second off sample or a cause.
    A diagnostic retry at 23:44:23 completed successfully. From 23:44:24 to
    23:44:34, head-0 `scanout_active=0`, frames 1,643, keepalives 605, and bulk
    bytes 8,564,175,920 remained completely unchanged. eDP stayed on. Re-enable
    sent 13 real frames by 23:44:35, with a full-frame payload of 8,294,448 bytes;
    keepalives remained 605 during those updates, then reached 610 after five
    further seconds. No USB disconnect, warning, fault, or taint change occurred.
    The earlier inability to hold off state is not reproduced by this run;
    concurrent input/wake is plausible but unproven. Monitor control uses the
    reviewed request `0x03`, value head 0, index 0/off or 1/on. Successful
    `scanout_active=1` and no error prove that the zero-length control transfer
    completed, not that the HDMI transmitter displayed readable pixels.
29. The user authorized sequential output identification, never two active
    heads. A default-off `query_only` branch was added after the existing
    RAM/status/EDID IN queries and before chip initialization, worker/frame
    allocation, any vendor OUT, or DRM registration. It retains exact device
    matching, manual-descriptor precedence, single-output selection, and the
    one-attempt latch. A clean query binds with NULL data after releasing the
    USB/DMA references; errors refuse binding. The preserved live artifact is
    `trigger6-idle-refresh-proven.ko` (`71c43fee…`). Query-build SHA-256 is
    `3564df8fc611461d252483dcaaf5c751c72bfe2651e8353d167e1e2dfd8ed802`, srcversion
    `DE5C92E23618EE9D77CE6F7`. Exact-header W=1, 18 Python checks, 64 descriptor
    cases, 128 refresh cases under GCC/Clang ASan/UBSan, and checkpatch all pass
    (query kernel delta: 0 errors/warnings, 29 lines). The reviewed
    `query_head1_restore.sh` will query only head 1, require no DRM card, then
    normally restore saved head 0 after clean completion. It stops without
    automatic reinitialization if a query fails. Head-1 frames require a valid
    sink/EDID and a separately reviewed next stage; none have been sent.
30. At **23:49:07**, the authenticated head-1 query returned raw status **0x00**,
    EDID bytes 0, no sink; no OUT/init/DRM/frames occurred. After normal query
    removal, immediate saved `71c43fee…` head-0 restoration returned status 1 but
    invalid EDID, failing -19 before initialization. The wrapper exited 1; this
    was not a successful restoration. No short-transfer/error log accompanied
    the invalid full-length EDID. Device 101 disconnected at 23:49:12 and device
    **102** appeared at 23:49:13. The one-attempt latch refused automatic probe.
    Saved `71c43fee…` remained resident/refcount 0, interface unbound, no T6 DRM.
    eDP/VT2 remained healthy, taint 12288 unchanged. Evidence:
    `head1-query-restore.log` and `head1-query-restore-kernel.log`, ignored.
31. Through **00:06:49 on September 6**, device 102 stayed quiet/unbound without
    another disconnect or warning. Source comparison identified mismatched
    sync fields in the inherited mode blob and audio requests mislabeled as
    color/timing. A query side effect, idle-sensitive firmware, and immediate
    restoration readiness remain competing explanations for item 30. The
    [new timing query](TIMING_QUERY.md) is prepared offline and will restore
    quiet state, never active video. Its future authenticated result must be
    appended separately. The user also confirmed workspace 5/test content
    migrated to eDP after external connector loss: this is compositor evidence,
    not physical HP scanout.
32. At **00:13:59 on September 6**, the single graphical timing-query action
    authenticated promptly. Head0 status1 and valid HP EDID gated the exact
    count/table reads: total36, captured16, 512 bytes. No further I/O followed;
    device102 remained stable for ten seconds. At 00:14:09 normal unbind/removal
    succeeded, exit0, module absent, eDP on, no T6 DRM. All first-page records
    decode with valid geometry, but none is 1080p. Raw/decoded evidence is
    `head0-timing-query.log` / `head0-timing-query-decoded.json`, ignored.
    Source/capture comparison then established byte-offset paging and a correct
    1080p record26 in the public JCD543 capture, whose first512 bytes match
    this dock. The precise guarded offset512 continuation is prepared offline;
    its actual result follows separately. No frame or corrected mode was sent.
33. At **00:27:33**, the continuation prompt authenticated. RAM58 was followed
    by head0 raw status **0x00**, so the connected-sink guard stopped before
    EDID/count/page512. The normal cleanup removed the module immediately;
    wrapper exit1, no OUT/init/DRM/frames, device102 unchanged/unbound. The user
    requested another prompt. After checking no prior process, module absence,
    eDP On, and clean commit `c4a4101`, one fresh120-second prompt was launched
    at 00:29:03. Omarchy-polkit alpha1 was observed on active eDP at 00:29:04.
    It expired124 around 00:31:03, empty output log, no second probe. At 00:31:16
    module absence/device102 were reverified. Live record26 remains unread;
    the table continuation must await a valid HP connection and authentication.
    Evidence: `timing-page1-query.log` / `timing-page1-query-user-retry.log`.
34. The user power-cycled the HP. At **00:34:22**, a single polkit prompt was
    verified visible on active eDP after fresh device102/hash/unbound checks.
    It authenticated at00:34:23; status1/validHP EDID/count36 permitted the
    exact512-byte read at offset512. All16 geometries are valid. The entire
    page matches the public JCD543 capture, and record26 matches its Windows
    1080p modeset exactly. Normal cleanup passed at00:34:33, exit0, module
    absent, device102 unchanged, eDP on, taint12288, no new faults/disconnects.
    Logs: `timing-page1-after-hp-power.log` and its decoded JSON. This proves
    the four inherited timing-byte errors; it is not yet visible-output proof.
35. Prepared the four-byte-only timing correction, build `cec6a342…`, srcversion
    `F6D5C7316849C7428A83002`. All audio/init/stream/guard behavior is unchanged;
    dedicated regressions assert this isolation and exact firmware mode bytes.
    W=1,34 Python checks, GCC/Clang ASan/UBSan matrices and checkpatch0/0 pass.
    The reviewed single-head active wrapper adds a90-second fault watcher and
    bounded automatic rollback, with a separately scoped external DPMS test.
    Its actual invocation/result must be recorded separately below.
36. **September 6, 00:44:48:** the single graphical authentication succeeded and
    `tools/test_verified_timing.sh --run-reviewed-verified-timing` inserted the
    corrected artifact from source `f79493e`. The outer command was bounded by
    `timeout --signal=TERM --kill-after=5s 240s pkexec bash` with the reviewed
    wrapper; its own root watcher was 90 seconds. SHA-256:
    `cec6a3429df95e8b3d79ab01e02ff0b7ff96ccee5aa39a11ad30938c09374c35`;
    srcversion `F6D5C7316849C7428A83002`, matching kernel vermagic. Exact parameters:
    `device_path=2-1.4.1 manual_only=0 output_mask=1 query_only=0 query_timings=0
    query_timing_page1=0 aquamarine_evdi_name=1 raw_idle_refresh=1 serialize_usb_bus=1`.
    Device 102 returned RAM 58, head0 status 1 and valid HP EDID. Hyprland created
    active `HDMI-A-2` at 1920×1080@60. At 00:45:24 the existing named test window
    was moved/fullscreened on external workspace 5 using runtime dispatch only;
    no config was edited. **Around 00:45:25 the user confirmed that the physical
    HP displayed the test screen.** This is distinct from the earlier window
    migrating to eDP, from software counters, and from the external-only screenshot.
37. **Settled 45-second sample, 00:45:29→00:46:14:** frames 441→485 (+44), idle
    refreshes 29→73 (+44), bulk bytes 866,636,432→1,231,593,552 (+364,957,120).
    All 44 increments were full idle refreshes at approximately 1 Hz. Bulk/send/
    short-write/keepalive/transport faults remained zero; head1 frames stayed 0;
    device 102 never re-enumerated. The 90-second root watcher completed at about
    00:46:20 with exit 0; its automatic fault rollback was not needed. It left
    the successful module live as designed.
38. **External-only DPMS, after the root watcher completed:**
    `tools/check_verified_dpms.sh --run-reviewed-verified-dpms` ran in the user
    session, with its EXIT/INT/TERM external-on restoration trap and the driver's
    fault latch. Settled OFF at 00:46:33: CRTC inactive, frames 513, refreshes 89,
    bulk bytes 1,457,373,008. At 00:46:43, all three counters were unchanged after
    ten OFF seconds. Re-enable at 00:46:43 produced 14 fresh real frames by
    00:46:44 (frames 527, refreshes still 89, full payload 8,294,448 bytes), then
    five idle refreshes by 00:46:49 (frames 532, refreshes 94). Exit 0, no faults
    or disconnect, eDP remained on. **The user separately confirmed the physical
    HP went off and visibly came back on during this test.** The root watcher
    had already ended; no claim is made that its automatic rollback covered DPMS.
39. **00:52:12 follow-up:** same device 102/path/module, refcount 1, head0 active,
    frames 858, refreshes 397, bulk bytes 4,150,248,512; every error counter zero.
    No kernel log after the original initialization, no disconnect in 7m24s,
    taint unchanged 12288, eDP/VT2 healthy. The working binary was preserved as
    ignored `trigger6-verified-timing-proven.ko`, hash verified identical. Logs:
    `verified-timing-live.log`, `verified-timing-dpms.log`,
    `verified-timing-post-success.log`; scoped screenshot
    `verified-timing-HDMI-A-2.png`. All remain ignored private local artifacts.
    The user authorized saving/committing the evidence. No installation,
    auto-load, package, service, DKMS, or desktop configuration was created.
40. **Later detach/hibernate/resume, observed read-only at 08:26:** at 01:04:26
    both dock hub trees, card reader, Ethernet and T6 detached together. T6's
    outstanding activity latched `-19` and disconnected normally. The journal
    records hibernation entry at 01:04:32, S4 resume and root-hub power loss at
    08:17:00, then T6 device106 at the same port at 08:17:01. The module logged
    exactly one refusal: active probe already attempted. It remains
    `F6D5C7316849C7428A83002`, refcount0, unbound, no T6 DRM/metrics; Hyprland has
    only eDP (idle/locked and DPMS off). No agent module/USB/control action ran
    during this interval. This is a whole-dock/system-power sequence, not a
    demonstrated recurrence of the old T6-only seven-second loop. Initial dock
    detach cause is unknown. Hibernation also logged non-T6 platform/USB resume
    warnings; do not attribute them to this driver without evidence or report
    this unattended interval as a clean controlled resume test. The working
    `.ko` and preserved copy still hash `cec6a342…`. Raw journal is kept private.

### libdrm selector correction

On installed libdrm 2.4.134, `modetest -D` feeds the DRM **bus ID** to `drmOpen`,
not a device-node path. This driver's `drmGetBusid` response is empty. The earlier
commands containing `-D /dev/dri/card0` actually succeeded through driver-name
fallback, not path-based selection; the single-device checks kept their target
unambiguous. `-D` alone failed to open and made no change. Use `-M trigger6` for
the default build, or `-M evdi` for the explicitly enabled shim, only after
checking that the exact T6 is the sole matching DRM driver and no real evdi module
or DisplayLink service is present. Do not treat a pathname passed to `-D` as an
identity guard on this libdrm version.

## Confirmed userspace integration boundary

Installed versions are Hyprland 0.56.2 (`efb50993780079460b0cbed1363e2166a2de1d9f`)
and Aquamarine 0.14.0. Aquamarine reports an EGL-device/secondary-renderer failure
before a frame reaches the driver. Inspection of exact-tag `DRM.cpp` shows:

- `registerGPU()` recognizes `evdi` as a renderless KMS special case, clears its
  secondary/primary relation, and sets `rendererRequired=false`.
- `trigger6` is classified UNKNOWN and keeps the default secondary-renderer path.
- `initMgpu()` tries EGL on the T6 node, which has no rendering implementation;
  `applyCommit()` aborts when that renderer cannot be created.

This matched the original inactive CRTC/zero counters. The explicit name-shim
experiment now proves that entering the generic renderless branch permits
Hyprland frames on this host. It is not evdi private-ABI compatibility and must
not be presented as such or made the default. A capability-based compositor fix
is the proper long-term integration. Restarting Hyprland or changing monitor
rules was unnecessary and has not been demonstrated to fix the original path.

The cached base EDID decodes correctly with checksum `0x82` and includes
1920×1080@60 as a standard timing. Its real preferred DTD is 2560×1440@59.95.
The inherited driver's diagnostic clamped the preferred dimensions before logging
them and therefore printed 1920×1200; that logging-only defect was corrected in
the shim build. The driver still exposes only fixed CEA 1080p60.

## Next supervised step and recovery

The corrected head-0 image and external DPMS return are physically confirmed.
After the later whole-dock/hibernation sequence, the module is resident but
unbound and needs a newly reviewed lifecycle/reload step. Preserve the working
artifact; review the [usability specification](USABILITY_SPEC.md) and
[persistence proposal](PERSISTENCE_PLAN.md) before any system write. Head 1 has no
sink and remains inactive. Stop and recover on a new disconnect or fault; the
single-probe latch prevents automatic reinitialization. No head-1, multi-output,
suspend, hotplug-loop, or permanent-install experiment is implied by this success.

To stop, close the temporary test window, physically unplug the dock, then use
ordinary `rmmod trigger6` with user authentication (direct agent launch: pkexec;
visible user terminal: sudo). Verify module absence and the healthy laptop panel.
Never force an in-use unload. No installed module or autoload exists, so a reboot
does not reload this repo's driver. The kernel remains diagnostically tainted
12288 (out-of-tree + unsigned) until reboot; no extra warning/oops taint was seen.

## Sources and local evidence

- [Official libdrm 2.4.134 source archive](https://dri.freedesktop.org/libdrm/libdrm-2.4.134.tar.xz),
  `tests/modetest/modetest.c`, inspected as source only.
- [Aquamarine 0.14.0 DRM implementation](https://github.com/hyprwm/aquamarine/blob/v0.14.0/src/backend/drm/DRM.cpp),
  `registerGPU`, `initMgpu`, `updateSecondaryRendererState`, `applyCommit`.
- [MCT GPL protocol definitions](https://github.com/mcttrigger/triggerdm/blob/63cecc7ef3308bcd4ad213e1ebd3139d804ffb8a/t6.h)
  and `t6usbdongle.c`: request 0x87 is connection status, request 0x03 is monitor
  power. This source was inspected only; no donor program was executed.
- Raw preflight/kernel/modetest/metrics snapshots and inspected source downloads:
  ignored `artifacts/runtime-2026-09-05/`. The later external-only static capture
  is compositor evidence only and is not included in tracked/shared files.
