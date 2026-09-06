# JCD543 / MCT Trigger 6 Linux development

Experimental, manual-test fork for the **USB graphics** portion of a j5create
JCD543/JCD543P-family dock enumerating as `0711:5601`, revision `1010`.
The source is adapted for this ThinkPad's Arch/Omarchy development workflow.
**User-confirmed visible output on the HP X27q: 2026-09-06, around 00:45 Mountain.**
The corrected head-0 build displays the test screen through the dock's standalone
MCT HDMI port at 1920×1080@60 in the existing Hyprland session. The user also
confirmed the HP visibly turned off and came back on during the scoped DPMS test.
A settled 45-second sample and the 90-second fault watcher passed with zero
transport faults or USB re-enumeration. This is a successful supervised test on
this exact dock/host, **not general hardware support or unattended-use validation**.

The decisive fix is four bytes in the inherited 32-byte 1080p timing record.
The complete live firmware page matches a public JCD543 USB capture; live record
26 also matches that capture's Windows modeset byte-for-byte. Correcting the
three sync fields produced the first physically confirmed image. The
[timing investigation](docs/TIMING_QUERY.md) preserves the provenance and exact
diff; the [runtime record](docs/RUNTIME_TEST_2026-09-05.md) preserves earlier blank
screens, reconnects, and the successful test separately.

The working `cec6a342…` module remains temporarily loaded with the explicit
head-0 Aquamarine name shim and raw idle refresh enabled. Head 1 has no sink and
has never received frames. All defaults remain inert, including the one-probe
latch that prevents reconnect/reinitialization loops. `W=1` and offline
Python/GCC/Clang sanitizer checks pass against exact signed Arch headers staged
inside this repo. **Nothing is permanently installed, and no desktop config was
changed.** System headers remain uninstalled. A rollback-safe
[persistence plan](docs/PERSISTENCE_PLAN.md) is proposed only; it has not run.

## Start here — no installation

```sh
make                 # show available development commands
make preflight       # cached sysfs and prerequisite report
make check           # offline source checks and sanitized host C tests
make build-staged    # use the verified repo-local headers; optional BTF omitted
make build           # alternative: use system-installed matching headers
```

`make install` and `make uninstall` deliberately fail. The repository contains
no DKMS, udev, service, autostart, firmware updater, or unattended loader.
The privileged one-run tools are inert by default, require explicit root review tokens,
and reject changed device/session/artifact state; normal make targets never run them.
They are historical, machine-session-specific experiments, not general setup
scripts. Their artifact paths now resolve from the reviewed checkout with full
quoting; hashes, USB paths/device numbers, and runtime guards remain pinned.
Do not edit a guard simply to make a historical test run on another session.
The existing `kernel/trigger6.ko` has matching vermagic. A build establishes
compiler/API compatibility, not hardware compatibility or successful loading.

## Scope and defaults

The donor driver models two logical outputs per MCT chip. This dock exposes
one MCT USB device, whereas the donor's primary test adapter had two chips.
The dock's separate DP Alt Mode HDMI/DP pair is outside this project; it must
be diagnosed through the laptop's USB-C/display path.

| Control | Default | Effect |
| --- | --- | --- |
| `device_path` | empty | Refuses every device until an exact USB port path is supplied |
| `manual_only` | `1` | Checks cached descriptors and binds only; no vendor transfers, DRM device, work queue, or display activation |
| `output_mask` | `0` | Active operation requires `1` (logical head 0) or `2` (logical head 1) |
| `aquamarine_evdi_name` | `0` | Head-0-only, temporary DRM-name compatibility experiment for Aquamarine 0.14.0; module and USB driver remain `trigger6`, with no evdi private ABI |
| `raw_idle_refresh` | `0` | Head-0-only experiment: replay the last real raw frame after one idle second, only while the CRTC is active and all connection/fault guards pass |
| `query_only` | `0` | With explicit non-manual single-head selection, query RAM/status/valid base EDID only; no vendor OUT, chip setup, DRM, or frames. `manual_only=1` still permits descriptors only |
| `query_timings` | `0` | Requires query-only head 0, valid sink/EDID, and disabled shim/refresh; read a timing count and at most 16 firmware records through EP0 IN, never apply them |
| `query_timing_page1` | `0` | Requires the timing query and measured count 36; read only records 16–31 at documented byte offset 512, still 512 bytes maximum |

All module parameters are read-only after insertion. Active tests use one
logical output, fixed 1920×1080 at 60 Hz, and the donor's 58 MB RAM layout.
Head 0 uses raw XRGB8888; head 1 uses NV12. The presently attached HDMI monitor
answered EDID on head 0 and now produces a user-confirmed visible test screen;
other wiring and detailed color/image quality remain unverified.
Both inherited DRM connector
names say HDMI-A; those names do not identify the physical VGA port.

Faults latch USB traffic off. There are no automatic USB resets, background
reprobes, startup black-frame bursts, or resume reinitialization. A deliberately
reconnected test is required after an error or suspend.
The current source permits only **one active probe attempt per module insertion**,
including failed probes. Further USB-core probes refuse before allocation/I/O;
ordinary removal and a separately reviewed insertion are required for another
attempt. Earlier tested artifacts did not have this additional guard. Unload
the module after a supervised test to end that authorization.

## Review and testing

- [Safety boundary and residual risks](SAFETY.md)
- [Preflight, staged manual test, recovery, and removal](docs/MANUAL_TEST.md)
- [Verified local header staging and exact build result](docs/LOCAL_BUILD.md)
- [Hardware evidence and verification results](docs/EVIDENCE.md)
- [Supervised runtime tests and physical success](docs/RUNTIME_TEST_2026-09-05.md)
- [Contained raw idle-refresh experiment and DPMS safeguards](docs/IDLE_REFRESH_EXPERIMENT.md)
- [Bounded timing query, request provenance, and offline decoder](docs/TIMING_QUERY.md)
- [Proposed persistence and rollback plan — not installed](docs/PERSISTENCE_PLAN.md)
- [Upstream audit, provenance, limitations, and licensing](docs/UPSTREAM_AUDIT.md)
- [Development rules](AGENTS.md)

Build, KMS transfer, compositor submission, and physical readability are separate
milestones. The corrected timing build has now reached all four on this host;
the user-confirmed DPMS return is additional physical evidence. Preserve the
laptop's session; there has been no compositor restart or configuration change.
Inherited requests 0x23/0x24 are audio controls despite their donor names and
remain unchanged to isolate the timing fix. Their necessity/safety, long-run
reliability, hotplug, and suspend remain open; see [SAFETY.md](SAFETY.md).

## Provenance

Kernel-only baseline:
[`ramifriedman/mct-t6-linux` at `e2aca2ca89650a68df3184918f93e37fce933f2e`](https://github.com/ramifriedman/mct-t6-linux/tree/e2aca2ca89650a68df3184918f93e37fce933f2e).
Local baseline commit: `2e15c5c`. Upstream history is retained at the `upstream`
remote and in the public branch's ancestry. Original local development commit
IDs in the evidence identify the private test history, not public commit URLs;
see [publication provenance](docs/PUBLICATION.md). The kernel is GPL-2.0-only.
Original attribution and [LICENSE](LICENSE) are retained, with the full license
text in [LICENSES/GPL-2.0-only.txt](LICENSES/GPL-2.0-only.txt).
