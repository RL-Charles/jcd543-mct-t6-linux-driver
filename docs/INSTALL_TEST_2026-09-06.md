# Supervised package installation and lifecycle test — September 6, 2026

Times are Mountain daylight time (UTC−06:00). This records explicitly authorized
host actions, separately from offline tests and the earlier manual experiment.
Private transaction logs, binary comparisons and raw runtime samples remain in
ignored artifacts. USB paths/device numbers below are session observations, not
portable selectors. No monitor serial, host identity, private key, or raw desktop
capture is published here.

## Current acceptance boundary

The installed DKMS artifact produced a **user-confirmed physical HP image** after
a full dock cold reset and one bounded supervised start at 12:53:27. The installed
watcher subsequently adopted that same generation without another initialization.
After a failed sleep-cleanup test, cold recovery restored a physically confirmed
image on device119. The installed controller correction then passed isolated
stop, but firmware re-enumeration remained. A further dock reset left head0
status0; **HP-only AC power cycling restored status1 on unchanged device125**.
Its single start at 14:15:11 produced a test window the user explicitly confirmed
was visible and stable. The later rel4 installed stop/warm-restart passed without
changing that generation; the module is live and **startup explicitly enabled
at 15:59:51**, with no-reload watcher adoption. A separately symbolized Ghostty SIGSEGV in GTK/Wayland display
feedback handling adds a desktop-client safety gate before further lifecycle
tests; it is not a kernel/driver fault or a completed integration acceptance.
The four-byte timing correction is unchanged; rel4 adds the tested final-off
profile. Laptop i915/eDP
and the existing Hyprland session remain available; no desktop config was edited.
Actual reboot, suspend, replug, one-hour soak and uninstall acceptance remain open.

## Historical rel1/rel2 artifacts — current rel4 recorded below

- Initial source/helper package: `jcd543-trigger6-dkms 0.1.0-1`, built from the reviewed
  private implementation at `638af350c148e06183c009516e47f43a5607af13`.
- Reviewed archive SHA-256:
  `05b7b8054e8c02b220fb514b095c56e02496bc6af44d3c72654aaf127d3992d6`.
- Then-current source/helper package: `0.1.0-2`, reviewed controller correction from
  `95c01830146fb1d6a2c7aae775333111b99d981b`, archive SHA-256
  `bad8b9a4c9284e17ea840dc962f85473b93bca795430894beb7fda76df66bc86`.
- Approved module: `/usr/lib/modules/7.1.9-arch1-2/updates/dkms/trigger6.ko.zst`.
- Compressed installed SHA-256:
  `404a3d3755feaabbef9d12ab018b4055ac495e774320dfc3c082945c95890a8e`.
- Decompressed installed SHA-256:
  `45795b4d1b1dd37b069c62500e26c5e18a1c094cd306e35bc82b89f2152c24c7`.
- Srcversion `F6D5C7316849C7428A83002`; vermagic
  `7.1.9-arch1-2 SMP preempt mod_unload`; no module dependencies; exact USB alias
  `usb:v0711p5601d*dc*dsc*dp*icFFisc00ip00in*`.
- Preserved earlier physically successful uncompressed manual binary:
  `cec6a3429df95e8b3d79ab01e02ff0b7ff96ccee5aa39a11ad30938c09374c35`.
  It remains an ignored rollback artifact, not the current resident module.

Installed approval is root-owned mode0644 under a root-owned mode0755 directory.
It pins the compressed artifact above and the enrolled session port policy
`pci-0000:00:0d.0-usb-0:1.4.1`. The active profile uses freshly discovered
`device_path`, `manual_only=0 output_mask=1 aquamarine_evdi_name=1
raw_idle_refresh=1 serialize_usb_bus=1`; every query and secondary experiment is
off. Head1 has sent zero frames. The compressed artifact is locally DKMS-signed;
signing identity/private material is not published.

## Installation, inspection and explicit approval

1. At 12:20, the authorized Omarchy prerequisite transaction installed matching
   `linux-headers 7.1.9.arch1-2`, `dkms 3.4.3-2` and dependency `pahole 1:1.31-2`.
   Package checks reported 21,599 / 28 / 50 files respectively, zero altered.
   The running/installed kernel was not upgraded.
2. At 12:21, the separately reviewed exact archive was installed through pacman.
   DKMS built this module for the current kernel with `W=1`, no compiler warnings.
   Package integrity: 41 files, zero altered; installed payload manifest: 22 files
   verified. Modalias blacklist was installed; the unit remained disabled/inactive.
3. At 12:33, `jcd543-trigger6-setup prepare --apply` verified the payload and the
   already installed current-kernel DKMS build. Kmod's `/lib/modules` result was
   normalized only through Arch's verified `/lib` → `/usr/lib` alias. Metadata,
   ownership, mode and the actual compressed artifact hash matched.
4. A read-only transient capability preflight at 12:35–36 used the installed
   service sandbox. CapEff/CapPrm/CapBnd were exactly `0000000000010000`
   (`CAP_SYS_MODULE` only); NoNewPrivs was 1; inheritable/ambient masks were zero.
   Access/stat verified the exact trigger6 interface-unbind endpoint was writable
   without writing it. Protected helper and status/manifest checks passed.
   No speculative sandbox relaxation was made.
5. At 12:38, explicit artifact approval created the guarded root-owned manifest.
   Approval did not load a module, start a service, or enable startup.

Every agent-launched privileged stage used one bounded graphical pkexec request;
no password was supplied in commands. Uninstall and a reboot were not performed.

## Important host package-hook side effect: UKI rebuilt

The package has no `.INSTALL` action or startup-enabling hook. However, this
Omarchy host's stock `limine-mkinitcpio-hook` pacman trigger includes
`usr/src/*/dkms.conf`. Consequently the 12:21 package transaction also rebuilt
`/boot/EFI/Linux/omarchy_linux.efi` and updated `/boot/limine.conf`. This was not
anticipated by the original no-initramfs-change plan. Work paused for review;
an explicitly authorized read-only privileged audit followed. No extra boot
rebuild or repair was run.

The audit used local `bootctl kernel-identify`, `objdump`, and `lsinitcpio`;
temporary extraction stayed in a private temporary directory and was cleaned.

- The 52,706,304-byte image identifies as a parseable x86-64 UKI, with kernel,
  initrd, kernel release, OS release and command-line sections.
- UKI SHA-256:
  `201a715ed94589020c5f9659512a8fa30ad380cb8434ab1d16830f24ba706413`.
- No trigger6 module payload exists among the 940 main initramfs entries.
  `etc/modprobe.d/jcd543-trigger6.conf` is included and exactly matches the
  installed blacklist-only file. The host configuration has `MODULES=()`.
- The PE signature directory is empty: this UKI is unsigned. Secure Boot is
  disabled. Dedicated signature-verification tools were absent; parseability
  is not cryptographic validation or a successful reboot test.
- The Limine menu still lists the current Omarchy kernel, earlier snapshot
  entries and Windows Boot Manager. A `.old` config exists. Their bootability,
  all fallback image hashes and the menu URI digest were not independently
  validated; those limits must not be represented as a proven fallback boot.
- UKI/config hashes were unchanged before versus after the read-only audit.
  Hook warnings mentioned possible missing `xhci_pci_renesas` and `qat_6xxx`
  firmware; whether they predated this transaction was not established.

Future package/DKMS update or removal can invoke these same host boot hooks.
Review them as part of rollback; do not promise removal has no boot-image effect.

## First packaged start failed safely at 12:40

The exact T6 was device106, unbound after the earlier whole-dock detach and S4
resume, with the old manual module resident/refcount0. One controller start
waited for the stable generation, ordinarily removed only that owned old module,
then inserted the approved package artifact once.

RAM58 and head0 status1/valid HP EDID succeeded. About 42 ms after active probe
began, the T6 alone disconnected. Initialization later returned `-110` (timeout),
before DRM registration or frame transfers. The controller consumed one attempt,
latched its circuit, and removed its failed module normally. Device108 returned
unbound; eDP stayed active. There was no blind retry, forced operation or USB reset.

No request-level USB trace was running, and the inherited control wrapper logs
only the generic error. Therefore the **exact failed OUT request/ordinal is
unknown**. The unchanged candidate sequence is:

| Ordinal | OUT request | Value / index | Length |
| --- | --- | --- | --- |
| 1 | 0x1c | 0 / 0 | 0 |
| 2 | 0x1c | 0x100 / 0 | 0 |
| 3 | 0x23 | 0 / 0 | 40 |
| 4 | 0x24 | 0 / 0 | 16 (pre) |
| 5 | 0x12 | head0 / 0 | 32 (verified timing) |
| 6 | 0x31 | head0 / 0 | 0 |
| 7 | 0x03 | head0 / 1 | 0 |
| 8 | 0x24 | 0 / 0 | 16 (post) |
| 9 | 0x1c | 2 / 0 | 0 |

All use vendor EP0 OUT (`bmRequestType=0x40`). A roughly one-second timeout and
42 ms disconnect do not identify which control failed. If repeated, add narrowly
bounded error-tuple instrumentation in a separately reviewed build rather than
guessing an ordinal or changing several requests at once.

## Binary and public-capture comparison

Offline ELF comparison of the installed build and saved working manual binary
found `.text` byte-identical: 33,848 bytes, SHA-256
`cdf5a9dd5489d6546e77c9bbdf5b914e0c2621565916f06353159130d55fa515`.
Init/exit code, data, parameter tables and module metadata also match. The sole
`.rodata` difference is a 96-byte staged-header-directory prefix omitted from
the diagnostic `include/linux/ucopysize.h` filename. All non-debug relocations
are semantically identical after normalizing that exact string offset change;
compiler comments match and neither build has BTF sections. Build-id, debug path
metadata and the appended local signature differ. This supports behavioral
equivalence, not a claim that firmware state is conclusively diagnosed.

The existing public JCD543 Windows capture has 0x31 earlier in initialization and
a different 40-byte 0x23 audio-node payload. Its 0x24 pre/post blobs and the
corrected 32-byte mode match. It also sends three identity-gamma 0x1d tables that
this driver does not send. These inherited differences existed in the earlier
physically successful source too; they are not a packaging regression. No audio,
gamma, initialization-order or pixel-stream change was made for the next test.
The 0x23/0x24 audio-side-effect risk remains open; see [SAFETY.md](../SAFETY.md).

## Full dock cold reset and packaged physical success

The user completed a true dock power reset, not merely a monitor reset. The
whole dock detached and re-enumerated; new T6 device113 matched the same exact
descriptor SHA and enrolled ID_PATH. Module remained absent and interface
unbound. The installed artifact/approval were independently unchanged; eDP was
active/unlocked and no earlier privilege process remained.

One authorized fixed sequence invoked installed `clear-circuit --apply`, then
`start --apply`; it did not enable a service or change protocol bytes. After
15-second debounce, initialization at **12:53:27** succeeded. Head0 status1 and
HP X27q EDID returned; Hyprland exposed HDMI-A-2 at 1920×1080@60. The existing
display-check window returned to external workspace5. **The user physically
confirmed that the installed DKMS module displays on the HP.**

At 12:54:25.810–12:55:10.813 (45.003 seconds), ten samples showed:

| Counter | Start | End | Delta |
| --- | --- | --- | --- |
| Head0 sent frames | 104 | 148 | 44 |
| Idle refreshes | 51 | 94 | 43 |
| Device bulk bytes | 763,663,392 | 1,128,689,744 | 365,026,352 |

All fault/error/short-write counters were zero, head1 frames zero, and USB
generation unchanged. No kernel warning, oops or T6 reconnect occurred. Bulk
totals above are decoded from the exact `bulk_bytes` field in preserved raw
metrics, not the separate `last_bulk_bytes` field.

A separately authorized `systemctl start jcd543-trigger6.service` then adopted
the existing root ledger: one attempt, same managed generation, clear circuit,
no inflight operation. Frames/refreshes were unchanged across adoption. The
service became active/running but remained **disabled**. This is temporary
supervised watcher activation, not startup acceptance.

Cold reset plus unchanged-binary success supports a firmware/power-state
dependency as a working hypothesis. It does not establish warm restart, sleep,
hotplug or long-run reliability. Those require the following lifecycle gates.

## Ten external-only DPMS cycles: software PASS

From 12:57:29.800 to 12:59:00.185, ten cycles used one second to settle off,
three measured off seconds and five on seconds. In every settled-off interval,
sent frames, refresh count and bulk bytes were identical before/after: zero
frame traffic. Each on interval increased real frames excluding refreshes.
Device113/generation was unchanged, head1 frames and all faults stayed zero,
and eDP stayed on. The watcher reported CRTC-off/active without reinitialization.

The per-cycle real-frame increments after on were 15, 15, 15, 15, 16, 106, 372,
173, 259 and 125. Later cycles included user-session damage, not a purely static
workload. The output was restored on exit. The request for final physical
confirmation crossed with the following sleep test/outage, so it is **not**
recorded as an independent ten-cycle physical-return PASS or a DPMS physical
failure. Earlier physical single-cycle return remains valid separate evidence.

## Sleep pre-hook refused; post was never called

At 13:02:24.101479, the installed pre-sleep hook began one exact-interface
unbind. No actual host sleep was requested. The acceptance runner's final
failure-log mtime was 13:02:24.127349, just 25.87ms later. Therefore this was
not exhaustion of the 1.5s unbind or 3s outer hook timeout. A transient nonzero
reference or immediate ordinary-removal refusal is plausible; the exact original
error is unavailable because the acceptance runner captured subprocess stderr
but printed only its `CalledProcessError`. Future runners must print bounded
captured stderr before raising, as the subsequent recovery runner does.

The root ledger retained `paused=true`, sleep inhibition and inflight
`sleep-stop`. The watcher latched manual recovery and issued no further cleanup
or initialization. At 13:02:28.814081, the T6 self-disconnected, 4.71s after
logical unbind, then returned as device114. Its one-probe latch refused another
initialization. The module later had zero references and no surviving unbind
task. eDP stayed available. The post hook was not invoked after the failed pre.

The originally installed status command misleadingly returned a fresh stopped
ledger for a normal user unable to traverse the root-private runtime directory.
Authenticated canonical status confirmed the real paused/inflight/circuit state.
This is a reporting defect, not two real controller states or an absent circuit.

## Restore refusal, then physically confirmed cold recovery

After preserving the root ledger, a separately reviewed restore-only sequence
stopped the blocked service, ordinarily removed the now-unbound zero-ref module,
cleared the circuit explicitly, then attempted one start on device114. At
13:06:02, RAM58 returned but head0 status was **0x00**. Probe stopped with
`-ENODEV` before initialization OUT, DRM or frames. The controller cleaned up
and latched again; service stayed inactive/disabled. No sink guard was bypassed.

The user completed another true dock cold reset. Device119 appeared at 13:07:38,
matching exact descriptors and enrolled port policy. One separately authorized
clear/start succeeded at **13:11:38**: RAM58, status1, valid HP EDID, HDMI-A-2 at
1080p60/workspace5. **The user explicitly confirmed the HP displays the test
window.** Service remained inactive/disabled; no more sleep/DPMS tests followed.

The 13:12:16–21 sample advanced frames134→139, refresh31→36 and bulk bytes
891,963,488→933,435,888; faults/head1 frames zero and device119 unchanged.
At 13:19:48–53, frames715→720, refresh452→457 and bulk bytes
4,832,940,880→4,874,413,280 were likewise fault-free. This working runtime is
preserved while the following fix is reviewed offline.

## Focused offline controller correction — before the 13:40 installation

`stop_module` previously read refcount immediately after successful unbind.
Earlier successful manual wrappers allowed up to two seconds for userspace
references to release. The new controller permits **at most 500ms**, polling
cached refcount every 25ms, within a shared 2.5s stop deadline. Discovery and
mutating command timeouts use the remaining budget; the separate hook retains
3s TERM plus 1s kill-after. One unbind is followed by fresh generation/identity/
binding checks and at most one ordinary removal. Busy/malformed/reacquired
references, stale state or timeout refuse; no force, repeated unbind or retry.

Command phase, exit code and bounded escaped output are now retained. Pause/stop
failure causes persist in inflight/circuit state across later observer ticks;
failed-start cleanup retains both errors. Inaccessible root state reports
`state=null`, `ledger_available=false`, and `next_action=unknown` while preserving
read-only hardware observations. Unknown sleep-inhibit state cannot authorize
a mutation. Root-owned execution and approval guards are unchanged.

The [kernel DRM lifetime documentation](https://docs.kernel.org/gpu/drm-internals.html)
states that unplug can coexist with open users and describes the protected
shutdown-after-unplug limitation. This matches the driver's current ordering:
its later atomic-disable callback cannot enter the unplugged device to send
monitor-off. That is a **separate plausible firmware-power issue**, not proof of
the lost controller error. Kernel order and every USB/control/timing byte remain
unchanged in this patch. Any orderly-quiesce experiment must be separately
reviewed; do not reorder physical-disconnect I/O blindly or bypass unplug guards.

Validation: 35 source-policy + 63 controller + 13 setup Python tests; freshly
compiled GCC and Clang ASan/UBSan matrices each pass 64 descriptor cases,
128 refresh cases, 39,475,200 query tuples and nine count/overflow bounds.
Unit verification, shell syntax and diff-whitespace checks pass. No new kernel
build is needed for this controller-only patch; the installed proven kernel and
its already successful W=1 build remain unchanged. Sparse/ShellCheck remain
unavailable. These offline results do not establish live sleep recovery.

## 13:40 — reviewed controller package upgrade, live module preserved

After source/archive review, the exact `0.1.0-2` archive identified in
[EVIDENCE.md](EVIDENCE.md) was installed in one bounded authenticated pacman
transaction. Read-only inspection first confirmed the stock DKMS upgrade hook
removes/rebuilds on-disk modules without unloading them; modprobe-on-install and
package pre/post scripts were absent. The old compressed module, controller,
approval and file manifest were preserved in private ignored rollback artifacts.

The transaction and independent post-audit passed: package Qkk 41 files/zero
altered; manifest 22/22; installed controller equals the reviewed checkout at
SHA-256 `88d442054be2ad3e003b0a7fe78bd7e1676aefbc4f449f220a79edbcc97767e2`.
DKMS rebuilt/installed for the running kernel; the compressed module remained
byte-identical at `404a3d37...`, with the same exact metadata. Existing approval
bytes remained unchanged and valid; no approval rewrite was necessary or done.
The resident module's sysfs inode, exact device119 generation and binding were
unchanged; frames15534→15547 and refresh1311→1324 advanced with all faults zero.

The stock UKI/Limine hook ran again, with the same two firmware warnings recorded
earlier. Pre/post UKI SHA `201a715e...` and Limine config SHA `564f27b9...` were
byte-identical. The image still parsed as a UKI; its 940 main initramfs entries
contained no trigger6 payload, and the embedded blacklist exactly matched the
installed file. Private temporary extraction was cleaned. This is not a reboot
or cryptographic signature test.

The revised normal-user status now correctly reports the root ledger unknown;
authenticated status confirms one attempt, no circuit/inflight and the original
managed generation. At this checkpoint eDP and HDMI-A-2 were active, service
inactive/disabled, and live cleanup was still behind separate review. The
following later tests were explicitly authorized; the upgrade itself did not
start them.

## 13:50 — isolated STOP correction passes; firmware teardown still re-enumerates

With the exact device119 generation, controller/module/approval hashes and
inactive/disabled service revalidated, one authenticated runner invoked the
installed `pre suspend` hook **once**. It did not suspend the host or invoke post.
The hook exited zero in **119.897ms**, stderr empty. Its exact-interface unbind
event reported 14.371ms elapsed and reference release took **25.271ms**. Ordinary
module removal succeeded. Root state preserved desired intent and sleep
inhibition, with `paused=true`, `inflight=null`, `circuit=null`, no managed
generation, module absent and interface unbound. No `tee`/`rmmod` task remained.

Despite clean removal, the T6 disconnected at **13:50:58.069128**, 4.362s after
the disconnect callback and 4.328s after module deregistration. It re-enumerated
as device120 at 13:50:59.788143 and stayed unbound. eDP remained on; no warning,
oops or hung task appeared. This validates bounded userspace-reference cleanup,
not firmware shutdown or a full sleep cycle. No post, reload, watcher start or
second operation followed this isolated test.

## 13:56 — dock cold reset alone does not restore sink readiness

The user then performed another true dock cold reset. The entire dock hub tree
detached at 13:52:50 and returned at 13:53:28; T6 device125 appeared at
13:53:29.680257 with the exact measured descriptors and enrolled physical path.
One reviewed recovery first verified completed pause/inhibition and no pending
action or circuit. The installed `post suspend` hook exited zero and changed
only state: it cleared pause/inhibition without inserting a module or adding an
attempt. The service remained inactive/disabled.

The single explicit start, after 15s debounce, received RAM58 and head0 raw
status **0x00** at 13:56:37.999729. It refused `-ENODEV` before EDID, initialization
OUT, DRM or frames. Normal cleanup removed the module and latched the circuit;
device125 stayed enumerated/unbound. No retry followed.

The journal shows the following settled starts, using the same approved module:

| T6 generation | Seconds from enumeration to status read | Result |
| --- | ---: | --- |
| device113, after dock cold reset | 292.198 | status1, valid HP EDID, physical image |
| device114, after logical teardown/re-enumeration | 211.871 | status0, refused before OUT |
| device119, after dock cold reset | 239.925 | status1, valid HP EDID, physical image |
| device125, after dock cold reset | 188.319 | status0, refused before OUT |

These delays do not support an immediate USB-enumeration race. USB logs establish
whole-dock detach/return but cannot establish HP AC/HDMI ordering or its internal
power state. An earlier IN-only experiment was more discriminating: on unchanged
device102, status0 at 00:27:33 became status1/valid EDID at 00:34:23 after HP-only
power cycling with dock USB left connected. Both the MCT GPL request definition
and public protocol research define `C0/87`, head0, one byte, as connector status:
zero means disconnected, one connected. A zero response is not a USB timeout.

## 14:15 — HP-only physical recovery PASS on the same USB generation

The user explicitly completed an **HP-only AC power cycle of about 20 seconds**,
then restored the same HDMI input. HDMI and dock USB/power remained connected;
there was no second HDMI reseat or dock reset in this intervention. Device125,
its descriptors and generation were unchanged.

An initial authentication succeeded but the recovery wrapper refused before any
mutation: an additional cooldown assertion incorrectly compared monotonic time
with the controller's `CLOCK_BOOTTIME` ledger. This was a wrapper defect, not a
controller or USB failure. Its log and unchanged canonical ledger were preserved.
After explicit review, only that clock comparison was corrected; the actual
elapsed cooldown exceeded 900 seconds. No kernel attempt had been consumed.

The next authenticated runner preserved the original ledger bytes, explicitly
cleared the known circuit, and called installed `start --apply` **once**. At
**14:15:11.516657**, the unchanged device125 reported **status1** and valid HP X27q
EDID. The same `404a3d37...` artifact created HDMI-A-2 at 1920×1080@60. Its canonical
root result was start exit0, one managed attempt, no circuit/inflight operation,
and active scanout. No service was started or enabled.

The authentication was late in the 120-second outer capture window. That
user-owned timeout ended with exit137; the privileged runner continued its
internally bounded single start and five-second read-only sample and completed.
The final log explicitly records start exit0 and complete canonical after-state.
Independent checks found no remaining privilege/module-operation processes.
This is an **orchestration timeout-boundary defect**, not a reason to assume an
action never ran or to retry. Future runners need separate authentication and
execution deadlines, with the execution timeout inside the privileged process.

The root five-second sample advanced frames4→115, refresh0→3 and bulk bytes
41,472,448→370,420,240, with zero faults. The later **14:16:49–14:16:54** raw-metrics
sample advanced frames433→437, refresh77→81 and bulk bytes
1,303,022,320→1,336,200,240. Adjacent status and metrics reads are not atomic;
the first status observation was one frame earlier than the raw metrics.
Through 14:17:13 all I/O/send/keepalive/short-write/transport faults and all head1
frames/bytes/refresh were zero, with no T6 reconnect or kernel warning. eDP and
HDMI-A-2 were active. **The user explicitly confirmed the display was stable and
the test window visible.** This is physical evidence, separate from counters.

The HP-only intervention restored the detected sink without a USB generation
change. It supports a monitor/HDMI-handshake dependency but does not establish
the monitor firmware's internal cause or prove automatic warm recovery. A
separate Ghostty terminal crash is recorded below. The physically working module
is preserved; watcher inactive, startup disabled, source/control bytes and
system/desktop configuration unchanged by this documentation update.

### Separate desktop-client crash gate

Independent read-only core analysis identified one main Ghostty singleton
**SIGSEGV at 14:15:11.921**, within about 20ms of DRM ready. It symbolized to
GTK4 **4.22.4**, `gdk/wayland/gdkdmabuf-wayland.c`: `dmabuf_formats_free`, called
by `linux_dmabuf_done` while handling a Wayland feedback event. No OOM or kernel/
driver fault was found. The dedicated `single-instance=false` display-test
terminal survived, and the user confirmed its visible HP image remained stable.

This is an external GTK/Wayland hotplug failure, separate from driver transport
and physical scanout proof. It still matters to end-user integration: further
output cycling must preserve terminal work and minimize exposure of the main
singleton. No Ghostty/system configuration was changed and no workaround was
installed. Only offline shutdown design proceeds until another runtime action
is separately reviewed. A working test window does not certify other clients'
hotplug behavior.

## 15:41–15:59 — rel4 installed cycle and user-authorized startup

The reviewed `0.1.0-4` archive was installed in a separate transaction while the
module was absent and the service inactive/disabled. Its archive SHA-256 is
`a55d62f6501a93dfa96dd078929edfad3bf587eb2aad464e3ce92f1ece7ba90d`.
Post-transaction audit passed: package Qkk43 files/0 altered, setup manifest24
files, exact installed controller/setup payloads and current-kernel DKMS state.
The standard UKI/package-hook result was independently inspected read-only; this
is not a reboot or fallback-boot test.

The new compressed module at
`/usr/lib/modules/7.1.9-arch1-2/updates/dkms/trigger6.ko.zst` has SHA-256
`6eaaacab55b70c1a27b92fdf9cf32c4b1058c7743c33c12ec22cfdf3c5e91f60`,
srcversion `CC62C8A09077D5A5D804316`, vermagic
`7.1.9-arch1-2 SMP preempt mod_unload `, the exact0711:5601/ff0000 alias and no
dependencies. Its controller SHA is
`47ee89b3e7b749ec228be3fa50cf5ef41dc75d6fbd42081f8935eb92624bf454`;
setup SHA `de9ca247e103b4f8d52472bc83b3966dcb5fd4d6ee8ffe053ed4d63e2edcd34e`;
payload manifest SHA
`b17f30fb973c1f6fd74ed05db2d811e68e5441af22ee547119e7d0a36a58aa84`.

Before approval replacement, an exact-byte old approval backup was preserved in
a protected, hash-named `/var/lib` location and verified against SHA-256
`1592b20ba909d89c31c2d2e1b9d5191cfba0cfd8167787f6528a1be71a2a8a8c`.
Canonical approval was moved to a pending name with restoration on failure;
the installed approval command created the new manifest, and the pending copy
was removed only after backup comparison. There was no concurrent controller,
watcher or module. This reviewed handover did not hold the controller flock;
do not generalize it into a concurrent-upgrade procedure. New canonical approval
is root-owned0644, SHA-256
`eb4271c4d6f849cc10513cbd9528b241cbec417f8ae16fdffdb9d57fc5a1c494`,
with the exact new artifact and enrolled ID_PATH. Old binaries/approval and the
sealed isolated recovery module remain preserved privately.

The initial rel4 installed warm start succeeded on unchanged device125; the user
physically confirmed the HP image before the following separately authorized
cycle. Exact active profile: `manual_only=0 output_mask=1`,
`aquamarine_evdi_name=1 raw_idle_refresh=1 final_monitor_off=1 serialize_usb_bus=1`,
all query/secondary switches0, and freshly validated `device_path=2-1.4.1`.
That USB path/device number is session-specific evidence, not a portable command.

### One installed active stop, quiet interval and warm restart

One bounded graphical authentication launched the reviewed fixed cycle. It
preserved canonical ledger/logs and revalidated installed hashes, ownership,
generation, eDP, active scanout, service inactivity, cooldown and attempt budgets.
Authentication and root execution had separate deadlines. There was **no DPMS-off
before stop**, retry, circuit clear or watcher activation.

- **15:41:36.238443:** exactly one final-off request
  `40/03 value=0 index=0 length=0 timeout_ms=250`.
- **15:41:36.241078:** ret0/error0, duration1866us, no skip. Installed stop
  exited0 in100.758ms; exact unbind18.620ms, reference settle0.287ms, stderr empty.
- The next15 seconds kept device125 enumerated/unbound, module absent and eDP on,
  without firmware reconnect, warning or new core.
- **15:41:51:** one installed `start --apply` exited0 in550.922ms; status1 at
  15:41:51.469655, DRM ready at15:41:51.830285, valid HP EDID and active HDMI-A-2
  at1920×1080@60. Workspace5 returned through existing compositor behavior.
  The already stable same-generation candidate did not require a new15s debounce;
  cooldown and attempt budgets were still checked and preserved.
- The subsequent45-second sample added83 frames,41 refreshes and614,024,400 bulk
  bytes. All faults and head1 traffic stayed0; no USB generation change, kernel
  warning, new coredump or privileged process leftover occurred. The approved
  module was left live. This post-cycle software proof is separate from the
  user's physical confirmation before the cycle.

Private ignored evidence: `artifacts/installed-cycle-rel4-bfe2pM.log`, SHA-256
`c7d3991eb4c714ffac8f98d997f5ec1ef2f73f30dbb4327933255695387fdb07`.
No raw logs, EDID serials, screenshots or compiled modules are published.

### 15:59:51 — explicit early startup opt-in and no-reload adoption

After the user explicitly requested automatic startup, the reviewed command was
`pkexec /usr/bin/systemctl enable --now jcd543-trigger6.service`.
It became active/running and enabled with PID1203441. Its first status was
`active`: the existing canonical managed generation was adopted, not unbound or
reloaded. Device125 stayed unchanged and frames1622→1638 advanced. HDMI-A-2 and
eDP remained active, with zero transport errors.

The actual process had only CAP_SYS_MODULE in effective/bounding capabilities,
NoNewPrivs1 and seccomp mode2/14 filters. Installed unit inspection confirmed
ProtectSystem=strict, ProtectHome=yes, PrivateTmp=yes, Restart=no, private0700
runtime state and isolated Python from the root-owned installed path. The
bounded sleep hook is present and unchanged; an installed hook is not proof of
successful real suspend/resume. Normal-user status correctly reports unknown
ledger state when the private root ledger cannot be read.

This was the user's explicit experimental startup opt-in before the complete
release matrix, not unattended-use certification. **Still unverified:** actual
reboot/boot-with-dock-absent, suspend/resume/S4, deliberate unplug/replug recovery,
one-hour mixed workload, actual uninstall/rollback and new-kernel activation.
Native1440p, head1/VGA and simultaneous heads are not in the installed profile.
The inherited0x23/0x24 audio requests remain unchanged; native dock Ethernet/audio
are separate from trigger6. No desktop configuration changed. The previous GTK
client crash remains documented despite no recurrence during this cycle.
