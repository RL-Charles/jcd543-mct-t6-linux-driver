# Development boundary

This is a no-load development repository until the user explicitly starts a
reviewed hardware test. Preserve upstream copyright, SPDX tags, and provenance.

- Work as the normal user. Keep changes and build artifacts inside this repo.
- Never install packages, DKMS entries, udev rules, services, or autostart here.
- Never load/unload kernel modules or write USB/DRM/sysfs controls automatically.
- Never change `/etc`, `/usr`, `/boot`, `/lib/modules`, or desktop configuration.
- Never run the donor install, host-guard, VM, or USB/IP scripts.
- Never force a module unload, bypass a device match, or broaden USB IDs without
  new evidence and a deliberate scope decision.
- Use `make preflight` and `make check`; `make build` compiles only if matching
  prepared headers already exist. A failed prerequisite check is a real blocker.
- A verified Arch header package may be extracted under ignored `artifacts/`
  without a package transaction. Validate its checksum and signature with a
  repo-local keyring copy before using bundled Kbuild tools. `make build-staged`
  reuses the matching extracted tree and omits optional module BTF; it never
  downloads, installs, or loads anything. See `docs/LOCAL_BUILD.md`.
- Keep `manual_only=1`, an empty `device_path`, and `output_mask=0` as defaults.
- Keep the exact descriptor policy and the kernel probe connected to the same
  `trigger6_match.h` functions exercised by the host tests.
- Record build, static, and hardware results separately in `docs/EVIDENCE.md`.
- Do not imply kernel API or hardware support from a host C test.
- Treat `docs/MANUAL_TEST.md` commands as future user-run instructions, not as
  permission to execute them. Preserve unrelated user changes.

No sub-agent delegation is required by these instructions.
