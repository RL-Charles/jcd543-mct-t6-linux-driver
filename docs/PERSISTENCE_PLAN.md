# Proposed persistence and rollback — not installed

Status: design only, following the user-confirmed HP image and DPMS return on
2026-09-06. The current module is temporarily loaded. No package, module copy in
a system directory, DKMS entry, udev rule, service, autoload, initramfs change,
or desktop config change has been made. `make install` still refuses.

## Preserve the verified state first

The successful source is `f79493e`; its binary SHA-256 is
`cec6a3429df95e8b3d79ab01e02ff0b7ff96ccee5aa39a11ad30938c09374c35`,
srcversion `F6D5C7316849C7428A83002`, vermagic
`7.1.9-arch1-2 SMP preempt mod_unload `. An identical binary is preserved under
ignored runtime artifacts as `trigger6-verified-timing-proven.ko`. Preserve that
file and the local test logs before any future rebuild.

The verified profile is head0/raw 1920×1080@60, `manual_only=0 output_mask=1
aquamarine_evdi_name=1 raw_idle_refresh=1 serialize_usb_bus=1`, with all query
switches off and the exact freshly validated device path. The successful session
used `2-1.4.1`, device 102; those values are observations, not permanent identity.
The laptop i915/eDP must remain available. No active parameters become defaults.

## Recommended staged rollout, requiring separate approval

1. **Manual, current-kernel deployment first.** Prepare a reviewed root-owned
   copy and manifest, but retain explicit user-initiated insertion. It must
   refuse another kernel, changed hash/descriptors, multiple candidates, an
   existing unrelated module/DRM device, or an unhealthy laptop display. Retain
   a single attempt and fault latch. A user-writable source tree must not become
   an unattended root execution path. Choose and approve the exact deployment
   locations before writing them; this proposal writes nothing.
2. **One supervised reboot check.** Boot normally without loading this driver,
   verify the laptop session and correct monitor input, then explicitly load the
   current-kernel artifact through the reviewed launcher. Verify image, counters,
   and DPMS again. A kernel upgrade must fail closed until a matching build and
   supervised revalidation exist; do not copy the old `.ko` to the new kernel.
3. **Optional boot/session startup only after that passes.** Review a dedicated
   oneshot loader and ownership manifest separately. No automatic retries,
   `Restart=always`, USB reset, or blind module-alias loading. It must be possible
   to boot with the dock detached and with the loader disabled. Define when USB
   identity and the graphical session are ready; a fixed sleep is not readiness.
   Prefer an explicit session opt-in while suspend/hotplug remain unsupported.
4. **Defer DKMS and automatic hotplug.** They need a larger kernel lifecycle and
   reconnect state-machine design. The current one-attempt latch intentionally
   requires deliberate reload after disconnect/suspend/fault. Do not weaken it
   simply to make autoload convenient. Do not edit initramfs, blacklist i915, add
   an evdi alias, or install a DisplayLink manager for this name shim.

No privileged installer is provided yet. Before implementation, agree on an
exact file manifest, owner/mode, activation policy, kernel-upgrade refusal, and
failure/rollback behavior. Review system-wide `depmod` metadata changes if using
the standard module tree. A root-owned explicit-path deployment outside that
tree avoids accidental USB modalias autoload, but still requires new approved
system writes and a maintained update/removal policy.

## Required uninstall implementation and recovery contract

The future installer must ship an inert-by-default, reviewed uninstall command
that uses the same manifest. It must:

- Disable/remove only this project's own optional activation entry first; leave
  every unrelated service, rule, module, and desktop configuration untouched.
- Revalidate the live trigger6 identity/path, stop its activity, unbind only the
  selected interface if safe, and attempt ordinary module removal. Never force
  an in-use module or unload i915; stop for user recovery if cleanup is incomplete.
- Verify every deployed file's ownership and recorded hash before removal.
  Preserve or quarantine changed files instead of deleting an unknown version.
  No recursive deletion or wildcard system-directory target is acceptable.
- Remove only manifest-owned files and regenerate dependency metadata only if
  the approved installation actually changed the standard module tree.
- Preserve source, working binary, and evidence in the user's repository unless
  separately asked to remove them. Report exactly what was removed/recoverable.
- Verify no project startup remains, the dock interface is unbound/module absent,
  and the laptop panel remains usable. A reboot clears the diagnostic unsigned/
  out-of-tree taint; uninstall alone cannot clear it.

For the **current temporary test**, there is no installed state to uninstall.
Close the test window when desired, unplug the dock, and use normal authenticated
`rmmod trigger6` once references release. If it cannot be removed normally, keep
the dock detached, save work on eDP, and use a normal reboot after user review.
The repo driver will not load on that reboot. See [MANUAL_TEST.md](MANUAL_TEST.md)
for the full recovery procedure. Do not disturb a clean live display just to
exercise this proposed future installer.
