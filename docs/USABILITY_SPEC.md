# ThinkPad + JCD543 usability specification and staged plan

Status: **M1/M4 installed; packaged M3 image physically verified; rel4 M2
active stop/warm restart passed; startup explicitly enabled at user request**.
The live installed watcher adopted the working generation without reload at
15:59:51 on September 6. Actual reboot, suspend/resume, deliberate replug,
uninstall/rollback and a one-hour soak remain release gates, not completed work.
A separate
GTK/Wayland hotplug SIGSEGV in the main Ghostty singleton adds a desktop-client
safety gate before further reviewed lifecycle work.
This plan turns the narrowly working
manual experiment into a maintainable, explicitly opt-in setup for the tested
ThinkPad/Omarchy system. It does not authorize system writes or runtime changes.
Read [DEVELOPMENT.md](DEVELOPMENT.md) for the current implementation and
[PERSISTENCE_PLAN.md](PERSISTENCE_PLAN.md) for immediate rollback requirements.
The implemented package/controller and exact rollout gates are documented in
[INSTALLATION.md](INSTALLATION.md); later sections retain broader future work.

## Target and definition of done

Initial supported profile: one exact `0711:5601` revision `1010`, the measured
three-endpoint SuperSpeed vendor interface, head0/standalone MCT HDMI, one HP X27q
at 1920×1080@60, Intel i915 as the primary GPU. Target the measured kernel and
Hyprland/Aquamarine versions first; a version matrix must identify later verified
versions explicitly. JCD543P labels, other firmware, VGA, two heads, higher modes,
and the separate DP Alt Mode HDMI/DP pair are not implied by this profile.

The 08:26 starting state was an old resident/unbound module after whole-dock
detach/S4 resume. Matching headers, DKMS and the reviewed package have since
been installed and approved. Cold reset plus the unchanged packaged kernel
produced a physically confirmed HP image; ten software DPMS cycles passed.
Sleep pre-cleanup refused, the warm guarded restore saw status0, and a second
cold reset restored a user-confirmed image. The revised stop fix passed; another
dock cold reset left status0, whereas an HP-only AC cycle restored status1 and
physical output on unchanged device125. The rel4 installed active stop/restart
kept that generation stable; current state is module live and watcher enabled/
running after explicit user authorization. The [dated record](INSTALL_TEST_2026-09-06.md)
separates these outcomes and the host's standard UKI rebuild from future work.

Other dock functions stay separate: the observed AX88179B `0b95:1790` uses native
`cdc_ncm`, while NetworkManager reports Ethernet unavailable; no separate dock
USB audio entity was observed. Diagnose physical Ethernet link/configuration and
audio enumeration independently. Do not claim trigger6 implements the entire
dock or bind non-video interfaces to make them appear supported.

"Usable" means a user can inspect compatibility, build/install a reviewed
artifact, opt into starting it, use the external desktop, stop/recover it, and
uninstall it without losing eDP/input or unrelated system state. Kernel upgrades,
missing dock, invalid EDID, disconnect, suspend and transport failure must have
defined fail-closed behavior. "Fully automatic" is a later milestone, not a
reason to remove the current safety interlocks.

The initial release must meet these acceptance gates:

- A fresh dry-run reports exact prospective files/actions and changes nothing.
- A matching, reviewed artifact can be loaded once after explicit opt-in; the
  HP shows readable desktop/text and correct labeled color bars. User confirms
  pointer/window interaction; captures alone do not count as physical proof.
- At least a one-hour mixed static/animated workload and ten external-only DPMS
  cycles complete without disconnect, warning/oops, short transfer, new fault,
  frozen eDP/input, or refresh traffic while the external CRTC is off.
- Install/update/uninstall and rollback are tested against a manifest; boot with
  the dock detached remains normal. Unsupported kernel/version/state refuses
  cleanly and explains the next reviewed step.
- Until separately validated, unplug or suspend requires an explicit fresh test;
  documentation states that limitation visibly instead of silently retrying.

These remain **release thresholds**. Short static samples, installed-image
physical confirmation and ten software DPMS cycles passed. The final physical
DPMS confirmation crossed with the failed sleep pre-test, so it is not counted
as a separately confirmed ten-cycle physical return. One-hour soak, clean sleep,
hotplug, reboot/upgrade and actual uninstall acceptance are incomplete.

## Milestones and dependencies

| Milestone | Deliverable | Exit evidence |
| --- | --- | --- |
| M0 — done narrowly | Verified mode fix, inert defaults, supervised head0 image and DPMS return | Dated local physical report, exact hash, zero-fault short samples |
| M1 — installed, acceptance partial | Root-owned setup/controller, exact artifact approval, status/start/stop and manifest uninstall | Installed manifest/Qkk and sandbox checks pass; actual removal/rollback untested; status UX correction installed/verified |
| M2 — rel4 installed, lifecycle partial | Exact final-off controller profile, fresh descriptor/udev generations, budgets/circuit breaker, bounded sleep quiesce; unchanged kernel latch | Installed stop returned0 with15s quiet; warm restart and45s streaming passed; actual replug/sleep/one-hour matrix pending |
| M3 — packaged image verified, startup opted in | Existing 0.56.2/0.14.0 compatibility shim; package versions pinned before activation; no config edits | User confirmed packaged image/recovery; enabled watcher adopted without reload; GTK Wayland hotplug crash remains a client risk; actual boot and native capability integration pending |
| M4 — current-kernel DKMS installed | DKMS source package, root-owned manifest, build-only autoinstall, explicit current-kernel hash approval | Installed W=1 artifact approved and physically tested; stock UKI rebuild audited; boot/upgrade/rollback runtime gates pending |
| M5 — broader displays | Validated EDID/firmware-mode selection and separately evaluated head1 | Per-mode/per-port physical evidence; no simultaneous heads by assumption |

M1 must retain the single-attempt guard. Automatic reconnect/startup depends on
M2 ownership/fault proofs; M4 must not auto-enable features that have not passed
M2/M3. M5 is independent research, not required to make head0 1080p usable.
The user's September 6 early startup opt-in does not waive or mark the remaining
release thresholds passed. Native 2560×1440, head1/VGA and dual-head remain outside
the currently installed head0 1080p60 profile.

The initial controller supports the currently reviewed kernel only until another
installed artifact is explicitly approved. DKMS never updates approval. The first
approval command refuses to overwrite a different existing manifest; adding a
new-kernel approval remains a separate reviewed maintenance step. This fail-closed
upgrade boundary is tested, not equivalent to a completed cross-kernel test.

## M1: discovery, identity, deployment and removal

### Read-only preflight and device selection

Extend the existing cached-sysfs report with a stable machine-readable schema
and actionable refusal codes: wrong kernel/artifact, absent/multiple candidate,
descriptor mismatch, existing binding, unexpected DRM owner, missing monitor,
and missing prerequisites. Do not open USB device nodes merely to enumerate.

Resolve a **fresh port path** only after exactly one candidate passes the full
descriptor policy. Present the selection for explicit consent; pass that exact
path to the unchanged kernel guard. Bus/device numbers are generation checks,
not saved identity. Optionally allow a user-approved physical port restriction;
USB has no serial here, so neither path nor descriptors prove cryptographic
identity. Revalidate immediately before binding and inside the kernel. Refuse
ambiguity; do not bind the first VID/PID match or use `new_id`/driver overrides.

Acceptance: synthetic sysfs trees exercise missing/duplicate/malformed/hot-unplug
cases and symlinks; no-match/multiple-match cases issue no USB/control write.
Changing the dock's port requires a new explicit selection, not an old selector
silently broadened to all T6 hardware.

### Installation and activation policy

Keep build and install separate. A future installer must default to `--dry-run`,
require an explicit reviewed action, verify source/artifact/kernel/dependencies,
and deploy root-owned files from an exact manifest. Never execute an unattended
root loader from a user-writable checkout. Record modes/owners/hashes and stage
files before activation; refuse existing foreign files and preserve changed ones.

Choose either a versioned explicit-path deployment or the standard current-kernel
module tree with reviewed dependency metadata updates. Document the modalias
autoload implications of that choice. Startup enablement, udev rules,
DisplayLink manager or compositor config changes are not implicit in install.
Host package hooks are a separate installation effect: on this Omarchy host,
the DKMS source package triggered a UKI rebuild and Limine update. Audit and
document those effects for installation, update and removal.
Activation stays one user-requested attempt, query switches off, one head only.

Provide explicit stop/status commands and the manifest-based uninstall described
in `PERSISTENCE_PLAN.md`. Disable owned activation first, revalidate the exact
live device/module, quiesce/unbind only its interface, and remove normally when
references release. A stop timeout must report safe unplug/reboot recovery; no
force flags or whole-controller reset. Preserve user source/logs and rollback
binary; remove only owned, unchanged files. Test partial-install rollback and
uninstall from both loaded and already-detached states without touching i915.

## M2: lifecycle, static scanout and fault containment

Define explicit states before implementing automatic behavior: selected/inert,
querying, active, DPMS-off, suspended, disconnected, and faulted. Track a device
generation so delayed work from an old USB enumeration cannot reach a replacement.
Specify lock ordering and ownership for USB/device/DRM references, frame buffers,
timers and workers. Drain work before memory or USB references are released;
verify no post-disconnect completion accesses old storage.

Preserve the existing module-global one-attempt latch until a replacement
state-machine policy is separately reviewed and tested. A **normal physical
reattach** and a **fault-induced re-enumeration** must not share an unconditional
reprobe loop. Faulted state requires explicit user recovery; no timer clears it.
Suspend must quiesce traffic and invalidate cached frames. Resume must not replay
a stale framebuffer or initialize repeatedly; initially require explicit restart.

The present idle refresh is opt-in and sends a valid last raw frame after about
one idle second only while scanout is active. Keep DPMS-off traffic at zero and
require a new real full frame after on. Instrument normal frames, refreshes,
payload bytes, cache validity/generation and transport faults without logging
pixels. Measure power/bandwidth and long-run stability before choosing a product
default. Do not assert a firmware watchdog fix from short-run correlation.

Acceptance matrix: unplug during idle/damage/full-frame send; fault/short transfer
at each control/chunk boundary; DPMS during queued work; suspend during active and
off states; repeated deliberate reconnects. Verify bounded cleanup, zero new I/O
after the relevant latch/state transition, no stale generation access, and laptop
availability. Use kernel lifetime/race tooling where available, plus supervised
physical tests. Host truth-table tests alone cannot establish these properties.

## M3: Hyprland integration and startup

The current explicit `aquamarine_evdi_name=1` changes only the DRM name to enter
Aquamarine 0.14.0's renderless KMS branch; it implements **no evdi private ABI**.
Replace this workaround through a narrowly reviewed compositor capability path
or explicit supported-backend policy. Retain Intel as the primary rendering GPU,
reuse generic buffer/atomic KMS support, and avoid creating an EGL renderer on a
renderless USB device. Do not add fake private ioctls to satisfy an unrelated
DisplayLink stack. Track the upstream discussion/change and exact supported tags.

Acceptance: the module reports `trigger6`, compositor discovers the secondary
device and submits real frames, physical HP image works, and failure/removal
leaves eDP and workspaces usable. Exercise test-window migration so an absent
external connector cannot be mistaken for external success. No logout/restart
is performed without saving work and an explicit resumable plan.

Only after lifecycle gates pass, offer a separately enabled oneshot/session
startup mechanism with root-owned code, readiness checks, one bounded attempt,
and a clearly documented disable path. No automatic retry daemon, all-device
udev match, or broad `modules-load.d` activation by default. Kernel upgrades or
unknown compositor versions must refuse or fall back to manual mode. Any Omarchy
user-config change needs backup, minimal diff, reload and config-error checks;
the current successful session required none.

## M4: packaging, kernels, CI and documentation

Start with a current-kernel-only package/deployment and a tested fallback boot
entry. Record exact prepared header package/version/signature, compiler/config,
source commit, artifact hash, vermagic, aliases and dependencies. Rebuilding for
a new kernel is distinct from verifying it on hardware. Never use force-vermagic,
copy an old module into a new ABI tree, or install mismatched rolling headers.

DKMS is optional later work: define supported kernel ranges, missing-header
behavior, build failure visibility, module signing/Secure Boot policy, retention
of the prior working artifact, and explicit activation after an update. A DKMS
compile must not imply hardware support or auto-enable untested startup. Package
hooks must not reset USB, unload i915, modify a running compositor, or start the
driver without the user's selected policy. Use reviewed Arch/Omarchy packaging
conventions; do not pipe downloaded scripts into privileged shells.

CI proposal (not installed by this plan): Python parser/source tests; GCC and
Clang warning-as-error ASan/UBSan host matrices; pinned-kernel `W=1` builds;
checkpatch plus optional sparse; shell syntax and ShellCheck; synthetic malformed
EDID/timing/descriptor/capture cases; manifest install/uninstall tests in an
isolated test root. No real USB/module load in untrusted CI, no root operations
from pull-request code, and no downloaded artifact trusted without provenance.
CI should report hardware tests as unavailable unless a supervised rig actually
performed them. Audit public outputs for local paths, credentials and raw pixels.

Document first use, physical port diagram/labels, supported-version matrix,
failure messages, normal stop, unplug recovery, boot-with-dock-detached recovery,
uninstall, kernel updates and known limitations. Public reports must redact
serials/hostnames/private paths. Keep legal attribution and licenses; publish no
proprietary binaries or private captures. Upstream contribution is a separate
reviewed action, with the minimal four-byte fix independent of packaging/shim.

## M5: EDID, timing selection, audio isolation and extra outputs

### Supported modes

Keep only fixed 1080p60 initially. The HP advertises 2560×1440 preferred, but that
is not a supported transport mode here. A future modeset must intersect valid
EDID modes, complete validated firmware records, RAM/address bounds, pixel-format
and pitch limits, USB bandwidth and transmitter constraints. Reject invalid
totals/syncs/clocks/polarities, malformed/short/duplicate tables and arithmetic
overflow. Preserve documented PLL bytes; do not synthesize unexplained values.

The current diagnostic reads only first page or exact offset512/count36 page1,
never loops. General table reading requires independently bounded allocation,
request length (at most512), validated byte offsets, count ceilings, and complete
response checks. Cache against device generation and head; do not silently apply
a record from another firmware. Select record26 only because its exact geometry
and captured modeset were verified. Full EDID extension parsing/hotplug detection
needs a separate bounded design; current code exposes a validated base block only.

Acceptance: parser/fuzz tests then one mode at a time with labeled physical test
content and rollback to known 1080p. Record color order/stride/position, not just
valid EDID/status. Do not advertise an untested mode merely because it was listed.

### Remove or replace misidentified audio controls

First rename/document request semantics without changing traffic, updating tests
accordingly. Inventory exact inherited 0x23/0x24 parameters and public capture
order; identify whether any audio setup is genuinely required for video. Then
run separately authorized, default-off omission experiments one operation/group
at a time, preserving the verified timing and stream. Require physical image,
DPMS, long-run/no-reconnect and dock-audio checks before removing a call from the
baseline. Replace only with an independently documented necessary request; do
not guess a "video timing" replacement based on the donor name. Keep 0x1c and
the raw first-frame flag as separate hypotheses, not bundled changes.

### Head1/VGA and dual-head limits

Current head1 returned status0/no EDID and received no frames. Its modeled NV12
path and HDMI-A connector name do not prove physical VGA wiring or success.
First identify a valid sink with guarded IN-only status/EDID, then test that head
alone with a named pattern and a bounded rollback. Do not enable both output bits
to search for a port. Parallel heads require a separate RAM/transport/address/
bandwidth and lifecycle audit with per-head physical evidence. DP Alt Mode is
outside the MCT protocol and cannot be probed by sending this chip other heads.

## Release evidence and stop conditions

Every milestone records source/public commit, kernel/compiler, module hash,
selected device generation/profile, exact operations, counter deltas, kernel
logs, actual user-visible result and cleanup state. Keep raw evidence private
unless separately approved for publication. A regression in eDP, warning/oops,
short transfer, unexpected reconnect, or malformed query ends that experiment;
recover normally and preserve the last verified artifact. Scope expansion is
reviewed explicitly. The current resident module is left untouched by this plan.
