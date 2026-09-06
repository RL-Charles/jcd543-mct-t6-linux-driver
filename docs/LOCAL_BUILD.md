# Verified local build for 7.1.9-arch1-2

On 2026-09-05 the module built successfully against exact prepared headers for
the running kernel, without installing a package or loading a module. Kernel
source remained at commit `e6d79cf`; no further DRM API adaptation was required.
This section records the initial build, before the separately authorized
[runtime tests](RUNTIME_TEST_2026-09-05.md). Those later tests rebuilt a small
default-off Aquamarine compatibility/diagnostic change using this same verified
tree; the runtime record identifies its final artifact hash and actual results.

## Trusted inputs

The pacman cache did not contain the header package. The existing, unchanged
core sync database offered `linux-headers 7.1.9.arch1-2`, the same version as
the installed `linux` package. Arch's current rolling package page had already
advanced, so the exact archive package was used instead of a newer header ABI.

- [Header package](https://archive.archlinux.org/packages/l/linux-headers/linux-headers-7.1.9.arch1-2-x86_64.pkg.tar.zst)
- [Detached signature](https://archive.archlinux.org/packages/l/linux-headers/linux-headers-7.1.9.arch1-2-x86_64.pkg.tar.zst.sig)
- Package size: 64,615,158 bytes.
- Package SHA-256: `36d43837ef8230db8b6fcf31e8f67e19b5ab41dca863c426056a55f40b00350b`.
- Signing fingerprint: `05C7775A9E8B977407FE08E69D4C5AA15426DA0A`, Frederik Schwan,
  including the `freswa@archlinux.org` identity.
- Signature time: 2026-08-21 23:37:48 UTC.
- Existing trust material: installed `archlinux-keyring 20260727-1`.

The downloaded SHA-256 matched `%SHA256SUM%` in the local core database. Its
detached signature exactly matched the database's decoded `%PGPSIG%`. GPGV
returned `GOODSIG` and `VALIDSIG` with the fingerprint above, using only a
repo-local dearmored copy of `/usr/share/pacman/keyrings/archlinux.gpg`. That
fingerprint was absent from the installed revoked-key list. No key refresh,
system trust-database write, pacman download transaction, or package install ran.

The first GPGV attempt could not read the armored keyring as a binary keyring.
Dearmoring the existing file locally resolved the format issue; signature
verification succeeded before extraction or execution of packaged build tools.

## Local layout and repeatable build

Downloaded package/signature, local public keyring, extracted headers, temporary
files, and build logs are under ignored `artifacts/headers-7.1.9-arch1-2/`.
The extracted header root is:

```text
artifacts/headers-7.1.9-arch1-2/root/usr/lib/modules/7.1.9-arch1-2/build
```

Archive symlinks were inspected before extraction. They are relative and resolve
within the extracted tree. Extraction used `bsdtar --no-same-owner
--no-same-permissions -xf PACKAGE -C LOCAL_ROOT`; no install hooks ran. The
signed package's normal Kbuild scripts, modpost, and objtool were used after
verification. Source directories were not copied into the system module tree.

From the repo, use:

```sh
make preflight
make check
make build-staged
modinfo kernel/trigger6.ko
sha256sum kernel/trigger6.ko
```

`make build-staged` never downloads or installs. It uses only the existing
repo-local prepared tree for `uname -r`, requires its matching release and
`Module.symvers`, and fails if those files are absent. After a kernel upgrade,
this old tree must not be reused for the new kernel. Staging a new package
requires its own provenance and signature checks. Preflight reports file
availability, not cryptographic trust; do not substitute an unverified tree.

The successful direct invocation, with the personal checkout prefix normalized
to `REPO`, was (run from the repository root):

```sh
REPO=$(pwd -P)
TMPDIR="$REPO/artifacts/headers-7.1.9-arch1-2/tmp" \
make -C kernel \
  KSRC="$REPO/artifacts/headers-7.1.9-arch1-2/root/usr/lib/modules/7.1.9-arch1-2/build" \
  KVER=7.1.9-arch1-2 CONFIG_DEBUG_INFO_BTF_MODULES= -j2 modules
```

The repository's kernel Makefile passes `W=1` to Kbuild. The compiler matched
the kernel's recorded GCC `16.2.1 20260810`. `pahole` is absent, so optional
module BTF generation was explicitly disabled with an **empty**
`CONFIG_DEBUG_INFO_BTF_MODULES=` override. Passing `n` would not disable the
Kbuild `ifdef`. The extracted kernel configuration was not edited.

Kbuild reported the expected pahole-version difference (kernel: 131, local: 0).
Compilation, object linking, modpost, and final module linking all succeeded,
with no C compiler warnings. DWARF debug information remains present; `.BTF`
is absent. This omission affects optional debugging/type metadata and is not a
kernel-version bypass or a module-signature workaround.

## Artifact and static results

| Item | Result |
| --- | --- |
| Artifact | `kernel/trigger6.ko`, ELF x86-64 relocatable, about 1.4 MiB |
| SHA-256 | `9fc97547029ebcd91bb1876f28b1d62f144110374a4af4849e3503840567fc14` |
| Source version | `9FFD650A0E1CCAB304076E4` |
| Vermagic | `7.1.9-arch1-2 SMP preempt mod_unload` |
| USB alias | `usb:v0711p5601d*dc*dsc*dp*icFFisc00ip00in*` |
| Module dependencies | Empty; this kernel builds DRM, KMS helpers, and GEM shmem helpers into `vmlinux` |
| Signer | Empty; the locally built module is unsigned |
| Build status | Successful `W=1`; expected missing-pahole version warning only |
| Kernel checkpatch | 0 errors, 1 informational `FILE_PATH_CHANGES` warning asking about MAINTAINERS; 1,485 diff lines checked |
| Offline tests | Seven Python checks and 64 C policy cases remain passing |
| Runtime at completion of this initial build | Not yet inserted, bound, or hardware tested; see subsequent runtime record |

The alias is deliberately supplemented by stricter probe checks for revision,
descriptors, speed, and exact selected USB port. Built-in helper configuration
and `Module.symvers` were checked to explain the empty dependency field; no
dependency modules were loaded. The system still has no `linux-headers` package
installed and no `/usr/lib/modules/7.1.9-arch1-2/build` directory.

The local staging directory uses approximately 372 MiB including the compressed
download and extracted tree. It is ignored by Git. It can be archived or moved
to trash through the normal file manager after retaining desired evidence; no
OS uninstall is necessary. No artifact was pushed or distributed.

The successful compile resolves the earlier missing-header build blocker.
It does not establish safe module insertion, compatible dock firmware, a correct
physical output mapping, visible video, or Hyprland operation. Continue with
the separately supervised [manual test procedure](MANUAL_TEST.md).
