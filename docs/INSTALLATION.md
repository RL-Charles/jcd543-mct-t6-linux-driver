# Local package and guarded lifecycle — implementation review

Status at **2026-09-06 15:59 Mountain: `0.1.0-4` installed, approved and live;
startup explicitly enabled by the user**. The installed image was physically
confirmed. The exact final-off profile then passed one active stop, 15 seconds
of same-generation quiet, one warm start and a 45-second zero-fault sample.
At 15:59:51 the service adopted the existing managed generation without reload.
This explicit early opt-in is not completion of the release acceptance matrix:
actual reboot, suspend/resume, deliberate unplug/replug, uninstall/rollback and
a one-hour mixed-workload soak remain unverified. Earlier ten software DPMS
cycles and physical single-cycle return are separate evidence.

Installed compressed module SHA-256:
`6eaaacab55b70c1a27b92fdf9cf32c4b1058c7743c33c12ec22cfdf3c5e91f60`,
srcversion `CC62C8A09077D5A5D804316`, kernel `7.1.9-arch1-2`.
An active resident with `final_monitor_off` absent/off is not owned by this
profile. The old approval/artifact were preserved before a separately reviewed
replacement approval; nothing silently overwrites or regenerates approval.
The package upgrade and standard DKMS/UKI effects were independently audited.
The four-byte timing correction is unchanged. Read the exact
[installation, approval, lifecycle and startup record](INSTALL_TEST_2026-09-06.md).
No command below is permission to execute it on another installation.

## Components and ownership

`packaging/PKGBUILD` creates a local `jcd543-trigger6-dkms` Arch package from this
reviewed checkout, without downloading code. It contains:

- GPL kernel source and `dkms.conf` under `/usr/src/jcd543-trigger6-0.1.0/`.
- Root-owned isolated-Python helpers under `/usr/lib/jcd543-trigger6/` and two
  fixed `/usr/bin/jcd543-trigger6*` entry points.
- `jcd543-trigger6.service`, initially disabled, and a bounded root-owned
  system-sleep hook. No user-writable script is run by the installed service.
- A **blacklist-only** modprobe file preventing USB modalias autoload. Explicit
  `modprobe trigger6` remains possible, but its inert default parameters refuse
  activation. The controller uses the exact separately approved artifact path.
- A file SHA/mode manifest under `/usr/share/jcd543-trigger6/files.json`, license,
  and documentation. Changed/foreign/symlinked files make setup/removal refuse.
  PKGBUILD passes its actual `pkgver-pkgrel` into manifest generation. Verification
  requires the exact installed package release from read-only `pacman -Q` (5s
  bound), alongside the existing file ownership/mode/hash checks. A mismatch or
  unavailable package record refuses; no package database or manifest is repaired
  automatically. The older rel1/rel2 metadata field was pinned incorrectly:
  use the old installed helper for pre-upgrade checks, then verify the new package
  only after its transaction completes. Synthetic roots inject a package-record
  reader in tests; the installed CLI exposes no bypass or alternate root.

No udev rule, polkit privilege bypass, DisplayLink manager, custom boot-image
operation, i915 modification, or Hyprland config is included. **Host package hooks
can still rebuild boot images:** this Omarchy installation's stock hook matches
`usr/src/*/dkms.conf`, so package installation rebuilt its UKI and updated Limine.
The audit found the blacklist but no trigger6 payload inside the new initramfs;
reboot/fallback bootability remains untested. Review these hooks before every
install/update/removal, including rollback. The default-off Aquamarine
shim remains the tested current-version integration, not a generic evdi ABI.
Activation pins the reviewed package versions `hyprland 0.56.2-1` and
`aquamarine 0.14.0-2`; an update requires compatibility review before a new start.
An already active module is not disrupted merely because a package was updated.

The separately created `/etc/jcd543-trigger6/approved.json` records an exact
installed `.ko` path, SHA-256, srcversion and vermagic for each approved kernel
(initial implementation creates one current-kernel entry), plus an optional
explicitly enrolled udev `ID_PATH`. It is root-owned and never auto-updated by
DKMS. A new kernel/build fails closed until a separately reviewed approval
update is implemented/performed. Builds can be available before activation is
approved; compilation alone does not validate hardware support.

## Build and dry-run without system writes

Run `make check`, inspect `git diff`, and verify the package staging code first.
The local PKGBUILD builds only the source/helper package; it does not load or
enable anything. Run makepkg as an ordinary user with outputs confined to ignored
artifacts; do not use `--syncdeps`/`--install` in the offline build. Dependency
checks may be skipped for this source-only archive when the packages are absent;
installation still requires the real prerequisites.

```sh
python3 control/controller.py status
python3 control/setup.py plan
```

When an older installed manifest has the known revision mismatch, the new
checkout's setup plan will report that mismatch. It is read-only; inspect the
existing installed setup helper and the reviewed upgrade plan, rather than
rewriting the old manifest to silence the check.

Every mutation command requires `--apply`, root, and execution at its protected
installed helper path. Running `control/controller.py start --apply` from the
checkout refuses even if privileged. Synthetic tests inject fake adapters/roots;
there is no mutating production `--root` override.

Before installation, inspect the complete archive (paths, root ownership, modes,
absence of `.INSTALL`/startup-enabling hooks or private artifacts), verify its
SHA, and record the source commit. Missing system headers/DKMS are prerequisites,
not a reason to mutate during a dry-run. On this host the separately reviewed
Omarchy prerequisite route is `omarchy pkg add linux-headers dkms`; first verify
the sync database still supplies headers matching the installed/running kernel.
Do not silently perform a partial rolling upgrade. Agent-launched authentication
uses pkexec; interactive user-terminal commands use sudo per the Omarchy skill.

## Supervised installation and approval gates

1. Save work, keep eDP/input available, preserve the known working binary/logs,
   and revalidate exact dock/monitor identity. Require the user ready to approve
   each visible authentication prompt. The service remains disabled.
2. After package/archive review, install the prerequisites and exact local package
   through the reviewed Omarchy/pacman path. Standard DKMS hooks may build/install
   a module **and host hooks may rebuild the UKI/initramfs or update the boot menu**.
   Review/capture these effects and independently inspect the resulting images;
   blacklist/inert defaults prevent automatic display activation.
3. Run installed `jcd543-trigger6-setup verify`, then a reviewed
   `jcd543-trigger6-setup prepare --apply` if needed. It validates every owned
   file and builds/installs only this DKMS module for the running kernel. A failed
   build leaves the package disabled and unapproved; it does not enable/start or
   delete unrelated packages. Preserve/report any partial DKMS state for recovery.
4. Independently inspect the installed module's actual path/hash/srcversion/
   vermagic/aliases/dependencies. Then approve that exact artifact using installed
   `jcd543-trigger6 approve --apply --module PATH --sha256 HASH --srcversion VALUE`
   and optional `--id-path VALUE`. This creates approval atomically and refuses
   to overwrite a different existing approval. It does not load or enable.
5. Start one supervised attempt with installed `jcd543-trigger6 start --apply`.
   It waits for the active i915 eDP, Hyprland presence and 15 seconds of a stable
   exact generation. Current resident zero-ref trigger6 is removable only if its
   srcversion and every guarded active parameter match the approval. Unknown
   modules are left untouched. Capture fresh KMS/Hyprland counters and obtain
   physical confirmation again for the packaged/DKMS artifact.
6. Run a supervised watcher (`systemctl start jcd543-trigger6.service`) only
   after the one-run check; adopt/start state is preserved under `/run`. Verify
   scoped DPMS, full-frame return, deliberate unplug/replug after cooldown, and
   sleep-hook quiesce/resume simulation before any actual suspend/hibernate.
   Actual sleep needs a resumable user plan; it can interrupt the control session.
7. Enable startup only after the agreed live acceptance gates pass. A package
   install alone never enables the unit. Record the exact enable action separately.

On this host the user separately authorized early startup on September 6 despite
the documented remaining matrix. The recorded command was
`pkexec /usr/bin/systemctl enable --now jcd543-trigger6.service`. It adopted the
already managed generation rather than inserting again. On a future boot the
watcher must still see the exact approved artifact, matching device, active i915
panel, Hyprland and a stable generation before a bounded start. Enabling a unit
does not prove that future boot or resume path works.

Inspect with `systemctl status jcd543-trigger6.service` and
`jcd543-trigger6 status`; authenticate the latter for canonical root ledger state.
To end automatic operation, the reviewed inverse is
`pkexec /usr/bin/systemctl disable --now jcd543-trigger6.service`.
Its stop action intentionally removes this owned external display; eDP is not
touched. Preserve logs and follow recovery below if stop refuses. Never add a
manual reload or circuit reset merely because the watcher reports a refusal.

## Bounded recovery policy

Each candidate must match the full measured cached descriptor SHA, speed,
revision and active configuration/interface; udev `ID_PATH`, device number,
port path, descriptor hash and initialization epoch identify its generation.
Multiple or mismatched devices are refused. Incomplete interface/udev enumeration
waits without authorizing a start; a fresh full generation restarts debounce.
Selection is rechecked immediately
before the exact-interface unbind and insertion. No hub/controller reset exists.

The kernel retains its one-active-attempt latch. For a new approved generation,
the controller may normally remove its own zero-ref old module and insert one
fresh instance. It uses a 15-second stable-generation delay, 120-second minimum
between attempts, at most three attempts/hour and six/boot. Loss/re-enumeration
within 60 seconds of activation trips a manual-recovery circuit breaker instead
of recreating the earlier seven-second loop. A very quick intentional unplug
can therefore require explicit recovery too. Active transport faults stop and
latch; malformed/unknown state refuses. No automatic budget/fault reset occurs.

Ledger writes are atomic, mode0600, guarded by a nonblocking flock, and preserved
across service restarts in `/run/jcd543-trigger6`. Observer lock contention skips
a sample, while an explicit operation refuses immediately instead of racing
another owner. A mutation consumes its attempt
before I/O. Interrupted cleanup retains an inflight marker; automatic re-entry
is blocked. Explicit `clear-circuit --apply` requires no bound device and is a
user-reviewed reset, not a daemon retry path.

The pre-sleep hook writes an inhibit marker before slow queries/locks, records
pending quiesce, and attempts only exact normal stop. Its outer timeout is three
seconds plus one kill-after second; it never waits for a user compositor reply.
Post-sleep merely clears a **successfully completed** pause and lets the watcher
observe a fresh generation/readiness; an incomplete pre keeps inhibition until
manual recovery. USB suspend callbacks/fault latches remain a kernel backstop.
A task stuck inside the kernel may outlive a userspace timeout; normal unplug/
reboot recovery remains necessary in that case.

The rel4 controller explicitly requires `final_monitor_off=1`. The kernel option
is still default-off for manual/modalias loads; for the exact healthy active
head0 profile it sends one bounded EP0 off after unplug/work drain. It skips
manual/query/head1/already-off/detached/suspended/faulted cases and never retries,
resets or clears a fault. A successful rmmod does not itself prove final-off:
supervised lifecycle acceptance must inspect its exact attempt/result/skip log.
There is not yet a durable controller acknowledgement of the disconnect-only
request; automatic-resume acceptance remains gated on separately reviewed tests.

The systemd service restricts capabilities to `CAP_SYS_MODULE`, protects system
and home files, uses private temporary storage and disables automatic restart.
It retains only the sysfs access needed for exact unbind; no root Hyprland
dispatch/configuration is used. Read-only proc/sysfs presence plus exact DRM/
metrics verify readiness/health; physical readability stays user-confirmed.
Missing/malformed metric fields count as failed health, not zero errors. Status
reports real-frame, keepalive and bulk-byte counters separately; it does not infer
physical readability from them.

The revised, offline-tested and installed controller allows at most 500ms of cached refcount
settling after its one successful exact unbind, checking every 25ms. Discovery,
unbind and normal removal share a 2.5s deadline; the unchanged outer sleep hook
retains its 3s TERM plus 1s kill-after ceiling. Before removal it rechecks the
resident identity, generation, unbound interface and zero references. Changed
state, a new reference, timeout or malformed data refuses without another unbind
or removal attempt. No compositor control or kernel/control-sequence change is
part of this patch. Userspace timing cannot guarantee recovery of a stuck kernel
task or that every compositor releases its references within 500ms.

The same revision records the exact stop phase, exit status and bounded escaped
command output; pause/stop causes persist in circuit/inflight state across
observer ticks. An unreadable private root ledger reports `state: null` and
`next_action: unknown`, not a fabricated stopped state. Authenticate for canonical
controller state. The original `0.1.0-1` revision lacked these diagnostic fixes;
normal-user and authenticated status were verified separately after the upgrade.

One live isolated pre-hook completed in 119.897ms with a 25.271ms reference
settle and normal removal. It did not run post or suspend the host. The T6
disconnected 4.36s later despite clean removal. A later post hook was separately
verified to rearm only state, not insert a module; a subsequent explicit start
still required sink recovery. These results do not certify an actual sleep cycle.
Do not simulate repeated pre/post or clear a circuit to bypass status0. Preserve
the ledger and require a reviewed physical intervention before another attempt.

## Stop, uninstall and rollback

Installed `jcd543-trigger6 stop --apply` records stopped intent before a bounded
normal unbind/removal. Never force a referenced module. If cleanup is incomplete,
unplug the dock, save work on eDP, then review ordinary removal/reboot. With
startup disabled, the experimental driver does not activate on the next boot.

`jcd543-trigger6-setup uninstall` is a read-only plan until `--apply`. The applied
operation first verifies the package manifest, disables/stops only the project
unit, confirms ordinary module cleanup, removes only DKMS `jcd543-trigger6/0.1.0`
and this package, and reloads the unit inventory. It never removes DKMS/header
prerequisite packages, user source, working binaries, or unrelated config. Changed
owned files cause refusal and are preserved for review. A failure stops before
later destructive steps; record any already-completed steps instead of claiming
the transaction was all-or-nothing.

The approval file is moved to a hash-named recovery copy under
`/var/lib/jcd543-trigger6` when present. Transient `/run` evidence expires at reboot.
Only the owned package/activation and module entries are removed. Keep a known
working kernel boot option; do not claim a tested upgrade or suspend lifecycle
until the corresponding supervised gate actually passed.
The host's standard DKMS/package-removal hooks can also rebuild boot images and
update Limine; uninstall does not automatically restore the previous UKI bytes.
Preserve reviewed boot recovery evidence and report these transaction effects.

## Offline gates and remaining acceptance

`make check` includes source-policy tests, 66 controller cases, 18 setup/manifest
cases, and the host C sanitizer matrices. Fixtures cover the measured 23-character
kernel srcversion, installed artifact hash/alias/dependency/vermagic changes,
unapproved kernels/compositor versions, exact descriptors and udev generation,
partial enumeration, stale-work cancellation, budgets, fault latches, failed
cleanup, and sleep-inhibit preservation. A real source-only makepkg archive was
built without dependency installation; extracted payload hashes/modes are checked
against the generated manifest. Systemd and shell syntax checks are separate.
A failed start permits one bounded cleanup; a failed stop is never repeated,
because its timed-out kernel operation may still be in flight.
The setup helper canonicalizes kmod's measured `/lib/modules/...` spelling to
`/usr/lib/modules/...` only when `/lib` is exactly the expected `/usr/lib` alias;
it still rejects foreign kernels, traversal, wrong module names and untrusted
resolved payload paths before reporting an artifact for approval.
Both compressed (`.zst`/`.xz`/`.gz`) and uncompressed `.ko` layouts are tested.
Before the first installed start, a separately authenticated transient read-only
process must verify the unchanged service sandbox retains effective
`CAP_SYS_MODULE`, `NoNewPrivs=1`, and access to the exact interface's unbind file
without writing it. Offline unit syntax verification alone does not prove that.

Installation and a same-kernel package upgrade have been tested on this host;
actual uninstall, rollback and suspend acceptance remain incomplete.
The initial approval tool creates one manifest and refuses replacement; new-kernel
approval maintenance, the one-hour mixed-workload soak, true S4 resume, and a reboot check
remain explicit gates. The residual inherited 0x23/0x24 audio control calls are
unchanged; broad dock Ethernet/audio support is outside trigger6.

The build/install distinction follows the upstream
[DKMS 3.4.3 manual](https://github.com/dkms-project/dkms/blob/v3.4.3/dkms.8.in).
In particular, this package never opts into DKMS `--modprobe-on-install`.
