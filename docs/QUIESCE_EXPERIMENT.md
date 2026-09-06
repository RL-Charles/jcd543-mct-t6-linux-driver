# Orderly final monitor-off — isolated experiment and later integration

Status: offline validation and the separately reviewed bridge/load/active-stop
phases passed. The user physically confirmed the new module's HP test image;
its one-shot final-off request then succeeded and the module was removed normally.
At that checkpoint the same USB generation was unbound and startup disabled.
The later rel4 package integrated the proven profile and passed an installed
active stop/warm restart; the user then explicitly enabled startup. See the
[dated installed record](INSTALL_TEST_2026-09-06.md) for current state and open
reboot/suspend/replug gates. This historical experiment does not authorize another
load, package update or approval change.

## Evidence and narrow hypothesis

The revised controller stopped in 120ms, including a 25ms module-reference wait.
The T6 still disconnected/re-enumerated 4.36s after teardown. A dock cold reset
left head0 status0; HP-only AC cycling restored status1 and a physical image on
the same USB generation. Thus cleanup timing is fixed, but firmware/HDMI power
state remains a separate problem. These observations do not prove its mechanism.

Current `t6_usb_disconnect` calls `drm_dev_unplug` before atomic shutdown.
`t6_crtc_atomic_disable` stops software activity, then requires `drm_dev_enter`
before monitor-off. That protected path cannot run after unplug. The
[DRM lifetime documentation](https://docs.kernel.org/gpu/drm-internals.html)
explicitly describes this hardware-disable limitation. The
[v7.1 DRM implementation](https://github.com/torvalds/linux/blob/v7.1/drivers/gpu/drm/drm_drv.c#L463)
marks unplugged, drains protected readers, then unregisters.

MCT GPL `t6.h` defines monitor control as vendor OUT `40/03`, output in `wValue`,
off/on in `wIndex`. `t6usbdongle.c:t6_libusb_set_monitor_power` sends a zero-length
control transfer; `main.c:mct_dpms_handler` uses it for DPMS off/on. These exact
sources and commit attribution are recorded in [UPSTREAM_AUDIT.md](UPSTREAM_AUDIT.md).
The proposed head0 request is only `40/03 value=0 index=0 length=0`, already used
by the current live DPMS path. No reset, audio request, mode record or frame is
added. The hypothesis is that sending this final off before releasing the USB
device prevents the later firmware teardown/sink-readiness failure.

## Chosen ordering: keep unplug first

Readonly/default-off module switch: `final_monitor_off=0`, limited to
the existing exact head0 profile. Reject contradictory active settings at probe.
The default path must preserve current behavior.

1. Capture whether head0 scanout was active before starting teardown.
2. Keep `drm_dev_unplug` first: drain protected operations and refuse new ones.
3. Wake export readers, cancel every timer/work producer, flush/destroy the
   workqueue, preserving the existing buffer-lifetime ordering.
4. In one **private disconnect-only helper**, take `io_lock`, recheck the strict
   eligibility policy, and send the one zero-length EP0 monitor-off request.
5. Perform the existing atomic shutdown, userspace teardown and buffer/ref release.

The helper deliberately is not a userspace/worker entry point: this callback
still owns the device references, after ordinary entry points have been drained.
It does not remove or relax any existing `drm_dev_enter` protection. Moving
atomic shutdown before unplug would instead need additional synchronization
against concurrent commits/re-enable; that broader change is not proposed.

The [v7.1 USB unbind path](https://github.com/torvalds/linux/blob/v7.1/drivers/usb/core/driver.c#L403)
normally disables interface endpoints before calling disconnect. However,
[usb_disable_interface](https://github.com/torvalds/linux/blob/v7.1/drivers/usb/core/message.c#L1318)
iterates only the current alternate's endpoint descriptors. This exact profile
lists bulk81/bulk02/interrupt83, not EP0. The final EP0 request therefore does not
require changing `soft_unbind` or keeping bulk endpoints operational. If earlier
endpoint cancellation has already latched a transfer fault, skip the request;
do not override the fault merely to attempt shutdown.

## Required eligibility and failure handling

All conditions must pass, including a second check under `io_lock`:

- Explicit opt-in; exact descriptor/path match and the existing one-probe latch.
- Active non-manual/non-query head0 only; fixed tested transport/profile.
- Cached head0 status1 and valid base EDID; previously active scanout.
- No head/device fault, no suspend-fault state, and USB state still CONFIGURED.
- Live callback-owned USB reference; all asynchronous producers drained.

Manual/query/head1/already-off/physical-detach/suspended/faulted cases send
**nothing**. A detach racing the final configured-state check can still fail the
one transfer; USB-core lifetime rules and the retained reference handle that
race. There is no retry, reset, fault clearing or other post-unplug request.

Dedicated transfer deadline: **250ms**, shorter than the existing 1s
general control deadline. Use the exact fixed tuple and accept return0 only.
Report a negative or unexpected positive result without changing any global or
head I/O-fault latch during disconnect. Log attempt/skip reason,
return code and elapsed time, without EDID serials or other private payloads.
This deadline is a conservative experiment bound, not a vendor-specified timeout.

Disconnect returns void: successful unbind/rmmod alone cannot prove final-off
succeeded. The initial experiment must check the precise kernel result. A later
installed-controller integration will need a reviewed way to preserve the
quiesce outcome before removing the module; do not count skipped/failed off as
successful firmware quiescence. The existing 2.5s controller/3s+1s hook ceilings
remain unchanged. An uninterruptible kernel task is not bounded by userland
timeouts, so any timeout is a stop/review condition, never an automatic retry.

## Offline gates before any runtime proposal

The default-off branch and shared policy tests are implemented locally;
validation results must be recorded before proposing a load. Required checks:

- Pure C policy matrix covering every eligibility bit and disallowed USB state;
  exact request/direction/head/index/length/timeout and one-shot result behavior.
- Source guards: default-off readonly parameter, exact match unchanged, request
  reachable only after unplug/activity drain and before USB reference release;
  no general entry-point guard bypass, new bulk/audio/reset/control surface, or
  changed timing/init stream.
- Mock zero/error/short-or-positive-return handling; request failure/skip leaves
  teardown safe and cannot authorize resume or repeat traffic.
- W=1/checkpatch, full Python checks, fresh GCC/Clang ASan/UBSan matrices;
  inspect module metadata and preserve the current `404a3d37...` installed and
  `cec6a342...` manual artifacts. A new build requires separate hash approval.
- Review exact kernel/USB locking and post-unplug lifetime again against the
  final code, not just this outline. No production controller/package rollout.

## First supervised test, still behind separate review

Protect the user's terminal work first: the main Ghostty singleton previously
crashed in GTK/Wayland DMA-BUF feedback during output hotplug. The separate
display-test terminal survived. This is a client-integration gate; no implicit
terminal/config change or forced client termination is authorized.

After offline review, propose one exact new-artifact load and one intentional
stop, with eDP available. Check actual monitor-off request/result and observe the
quiet device for at least 15s, exceeding the measured 4.36s reset interval.
No automatic restart, watcher, post hook or host sleep belongs in this first
experiment. If reset recurs or off skips/fails, stop and preserve evidence. Any
later warm-start or actual sleep test needs its own review and physical result.

Recovery preserves the known working artifact and approval. A new generation or
status0 requires read-only review and the explicitly agreed physical intervention;
HP-only power cycling previously restored the sink. Never treat a compositor
window/counter alone as physical output or enable startup from this experiment.

The runner must fix both earlier orchestration defects: compare controller
ledger times with CLOCK_BOOTTIME, and separate a bounded authentication window
from a **privileged execution timeout**. Put that execution bound inside pkexec,
with sufficient overall capture budget; reject authentication after its reviewed
deadline before any mutation. An outer user-owned timeout cannot be treated as
proof that its privileged child stopped. Preserve exact results and revalidate
process/state before considering another authorized action.

## Offline validation result — September 6

Implementation and tests pass locally; **no runtime test or package installation
of this branch has occurred**. The source package release is explicitly advanced
to `0.1.0-3` and includes the new header, but no new package archive is installed
or approved. Installed controller and its artifact approval are unchanged.

- Isolated `W=1` build against installed `7.1.9-arch1-2` prepared headers: exit0,
  no compiler warnings/errors. Both USB-state/interface-condition guards compile.
- New module SHA-256:
  `d54cf17bd604629be0dd39d1c21c18eefaa135366ae0010467f3d30d3d7a480b`.
  Srcversion `CC62C8A09077D5A5D804316`; vermagic
  `7.1.9-arch1-2 SMP preempt mod_unload `; exact original USB alias, no dependencies.
  This local artifact includes BTF and is not the signed installed module.
- ELF places `t6_final_monitor_off` in zero-initialized BSS; the parameter is
  readonly/default false. No ordinary I/O-fault state is mutated by the helper.
- 114 Python checks pass: 38 source/capture/policy, 63 controller, 13 setup.
  Three new source tests enforce opt-in/query/head guards, two-stage locked
  policy, one fixed control request, unchanged ordinary DRM protections and
  unplug/work-drain/reference-release ordering.
- Fresh GCC and Clang ASan/UBSan each pass 64 descriptor, 128 refresh,
  39,475,200 query tuples plus nine bounds, 40,960 final-off policy combinations,
  and 8,193 control-return cases. These are host tests, not kernel scheduling or
  USB hardware tests. Negative/positive returns are recorded, never retried.
- Strict checkpatch: driver diff and new header/C test each zero errors,
  warnings and checks. Package shell syntax, unchanged service-unit verification
  and diff-whitespace checks pass. Sparse/ShellCheck remain unavailable.

The original `kernel/trigger6.ko` remains byte-identical at `cec6a342...`; the
installed compressed artifact remains `404a3d37...`. Isolated binaries/logs are
ignored artifacts, not public releases. Stop here for code/runtime-plan review.

### Local archive audit and staged runtime proposal

Implementation commit: `5679130425430f41b8dc9e71f0bb6d24a709c3b5`.
Normal-user makepkg completed without installation or downloads. The ignored
`artifacts/quiesce-package-fxoPuP/jcd543-trigger6-dkms-0.1.0-3-x86_64.pkg.tar.zst`
has SHA-256 `b4c992a4bd558be1e92eda437d0d0d39faeaf5a7f6671881c203b502451020a6`.
All 45 archive entries have safe root ownership/modes and no links, special files
or path escapes. All 23 payload files match the generated SHA/mode manifest;
kernel sources/new header match the checkout. Controller/setup match the
installed files. Service, sleep hook, blacklist and DKMS configuration are
unchanged; there is no installation script, enable link or autoload entry.

An inherited metadata issue is explicitly deferred: both manifest generator and
setup verifier pin their `version` field to `0.1.0-1`; `.PKGINFO` correctly says
`0.1.0-3`. Do not misreport that field as the package release or silently change
the installed verifier as part of this experiment. This archive is an offline
audit artifact, not an approved rollout. Its private build metadata is ignored.

The smaller runtime route uses the isolated module, leaving the package and
approval unchanged. Review these as separate phases, never an automatic chain:

1. **Old-module bridge only:** after authentication, the normal-user compositor
   coordinator turns off only HDMI-A-2. Require eDP on, head0 scanout inactive,
   zero fault counters and stable traffic counters before one installed
   controller stop. Observe the exact USB generation for 15 seconds; a reset,
   timeout or fault ends the experiment. The new module remains unloaded.
2. **New-module load, separately approved:** only after a clean bridge, revalidate
   the same generation and load a private root-owned, hash-verified snapshot of
   the isolated artifact once with the old profile plus `final_monitor_off=1`.
   Require a 45-second clean sample and a user-confirmed physical image. No
   installed-artifact approval, package update, service start or enable occurs.
3. **New-module active stop, separately approved:** head0 must be actively scanning
   out immediately before exact-interface unbind. Do not DPMS-off the new module
   first: that would make `was_active` false and skip the experimental request.
   Require one exact final-off result, ordinary reference-settled removal and
   15 seconds without re-enumeration. Hold unbound afterward; no automatic resume.

DPMS-off on the old module is a safety bridge and independent observation, not
evidence that the new disconnect helper works. Once the new module has initialized
and visibly scanned out, its later active stop tests the proposed path directly;
it still is not a randomized comparison or proof of suspend/resume reliability.
Protect terminal work and compare userspace crash counts around output removal.

Read-only verification at 14:53–54 found the same live device125, head0 active,
zero faults, both panels on and service inactive/disabled. The installed module,
controller and approval hashes remained unchanged. No offline build touched DKMS
or the live driver.

## Phase A result — old-module bridge, September 6 at 15:02

**Software PASS for old-module DPMS-off/stop/quiet only.** The first authenticated
runner encountered a Hyprland Lua parse error before DPMS or stop: legacy dispatch
syntax returned7. No hardware or controller mutation occurred. Its failed log
was preserved and all state/process checks repeated before the separately
authorized corrected attempt. The accepted user-session API was the already
tested `hl.dispatch(hl.dsp.dpms({ action = "disable", monitor = "HDMI-A-2" }))`
through `hyprctl eval`, executed after authentication so password input could
not wake the output between off and stop.

Head0 became inactive, and the two-second settled off sample held exactly at
10,711 sent frames, 2,453 refreshes and 48,991,281,968 bulk bytes: zero traffic
delta and zero faults; eDP stayed on. At **15:02:04.405**, exactly one installed
controller stop returned0 in **116.885ms**, including the exact-interface unbind
event at14.463ms and reference settle25.252ms. Stderr was empty. The module and
external DRM device were removed normally; ledger desired=false, managed=null,
inflight=null, circuit=null, paused=false. Service stayed inactive/disabled.

The subsequent 15-second observation retained **the same device125, unbound**,
without the earlier 4.36-second firmware disconnect/re-enumeration. The kernel
delta contained only the expected driver disconnect callback and deregistration.
Coredump count stayed at one prior Ghostty event, with no new crash; no privileged
runner/timeout/tee/rmmod process remained. This is stronger evidence for the
monitor-off-before-teardown hypothesis, not proof of the new helper, warm restart
or host suspend. No new module was loaded in Phase A.

Private logs: `artifacts/quiesce-phase-a-0lY4dS.log` (syntax refusal) and
`artifacts/quiesce-phase-a-lua-Rzreog.log` (successful bridge). The diagnostic
Python import incidentally created one root-owned0644 controller bytecode cache
under `/usr/lib/jcd543-trigger6/__pycache__` at15:00:01; no package-owned file
changed. This side effect was reported immediately when discovered. Further
privileged Python runners use `-B`; the exact generated cache is retained for a
separately reviewed cleanup audit, not silently removed during a hardware test.

## Phase B result — isolated warm load, September 6 at 15:08

**45-second software PASS, followed by explicit user physical PASS.** A
separate approved bounded authentication/execution runner kept the same quiet,
unbound device125 and unchanged stopped controller ledger. It read the isolated
artifact with `O_NOFOLLOW`, checked its SHA and exact metadata, then exclusively
created a root-owned0600 copy in a fresh protected0700 directory under `/run`.
Source and sealed-copy hashes/metadata were rechecked immediately before one
insertion. No package, approval, controller, service or user configuration changed.
Python `-B` prevented further import bytecode writes.

At **15:08:45–46**, the same USB generation returned head0 status1 and valid
cached128-byte HP X27q EDID. The isolated artifact SHA remains
`d54cf17bd604629be0dd39d1c21c18eefaa135366ae0010467f3d30d3d7a480b`, srcversion
`CC62C8A09077D5A5D804316`; original profile plus readonly `final_monitor_off=1`.
HDMI-A-2 became active at1080p60. Workspace5 and the existing dedicated test window
returned automatically; no compositor dispatch was needed in this phase.

The 45-second active sample advanced **87 sent frames, 42 idle refreshes and
638,984,336 bulk bytes**. Every sampled device/head fault, transport error and
head1 traffic counter stayed zero. No USB re-enumeration, kernel warning or new
coredump occurred. Root/coordinator returned0 and no privileged process remained.
Installed module/approval and exact controller ledger hashes were unchanged.
Service remains inactive/disabled; the new module is left live, never stopped
by this runner. Its source version deliberately differs from the installed
approval, so the installed controller reports it as unowned and must stay stopped.

The user subsequently explicitly confirmed the HP monitor displayed the test
window. That physical evidence is distinct from counters and compositor state.
The successful warm load following the old normal-off bridge strengthens the
power-state hypothesis. Phase B did not exercise the final-off helper; the
separately approved Phase C below did. The sealed artifact remains in `/run` for
exact-identity review and later bounded cleanup, not persistent installation.
Raw evidence remains private in `artifacts/quiesce-phase-b-oZKtHW.log`.

## Phase C result — active final-off, September 6 at 15:15

**One-shot final-off/ordinary removal/15-second quiet software PASS.** Fresh
guards verified the same device125 and sealed `d54cf17b...` artifact, exact live
parameters with `final_monitor_off=1`, status1/valid cached HP EDID, active CRTC,
advancing frames and zero faults. No preceding DPMS-off was issued. At the
immediate pre-unbind sample, head0 remained active with442 frames/352 refreshes.

Kernel events:

| Local timestamp | Observed event |
| --- | --- |
| 15:15:05.944212 | Disconnect callback begins |
| 15:15:05.944512 | Exactly one final-off `40/03 value=0 index=0 length=0 timeout_ms=250` |
| 15:15:05.946077 | `ret=0 error=0 duration_us=1576`; no skip |
| 15:15:05.956221 | Ordinary driver deregistration |

Exact-interface unbind returned0 in4.327ms; reference settle0.202ms; ordinary
rmmod returned0 with total measured stop31.867ms. Both stderr captures were
empty. The subsequent15-second observation retained the same unbound device125,
module absent, eDP on, no USB disconnect/re-enumeration, new coredump, kernel
warning or stuck privileged process. Root/coordinator returned0. Installed
package/artifact/approval and controller ledger remained unchanged; service
inactive/disabled. No reload, recovery, host sleep or installation followed.

Private log `artifacts/quiesce-phase-c-TyuIr5.log`, SHA-256
`5a833e548d17c2b07a4451fdd41dd11f87a7b87b601f432f95c762b51ecabec5`.
This confirms the private post-unplug EP0 request can complete on this exact
configured interface and coincides with a quiet teardown. It is one supervised
trial, not proof of every teardown race, repeated cycles, warm restart after this
helper, unplug/replug or actual suspend/resume. Those remain separate gates.
