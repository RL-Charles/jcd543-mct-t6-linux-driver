# Head-0 firmware timing diagnosis

Investigation and result, 2026-09-06. The bounded IN-only queries established
that four inherited mode bytes were wrong. Correcting only those bytes produced
the **user-confirmed physical HP test screen**, followed by a user-confirmed
external DPMS off/on return. Historical preparation/failure stages below are
retained explicitly; they are distinct from the successful final active test.

## Evidence motivating the query

The inherited `t6_mode_1080p` array matches donor userspace `MODE_1080P` exactly.
The donor labels it a Windows-captured 1080p mode. However, interpreting those
32 bytes using MCT's own `RESOLUTIONTIMING` layout gives the following mismatch:

| Field | Inherited USB blob | Advertised DRM CEA 1080p60 |
| --- | --- | --- |
| Pixel clock / refresh | 148500 kHz / 60 Hz | same |
| Horizontal total / active | 2200 / 1920 | same |
| Horizontal sync start / width | **1816 / 44** | **2008 / 44** |
| Vertical total / active | 1125 / 1080 | same |
| Vertical sync start / width | **1000 / 29** | **1084 / 5** |
| Sync polarities | positive / positive | same |

Both inherited sync starts precede active-area completion. MCT explicitly
documents these fields as active size plus front porch, and the independent
cyrozap dissector identifies the same offsets. This is concrete evidence of a
timing inconsistency. The subsequent timing-only active test below produced the
first physically confirmed image. The inherited PLL fields (FNUM=699, FDEN=1000, IDIV=29,
OutputSelect=1) are reported, not guessed or modified.

The inherited names `T6_REQ_SET_COLOR` (0x23) and `T6_REQ_SET_TIMING` (0x24)
are also misleading. MCT defines those requests as audio node values and audio
engine state. The 16-byte pre/post blobs decode to engine Activity=0/1,
ReturnSize=9600, and CyclicBufferSize=131072 under `T6AUD_SETENGINESTATE`.
That is not a video color/timing control. Their removal is a separate potential
experiment; this query does not execute or change the inherited active sequence.
Request 0x1c remains undocumented in the inspected MCT headers; no new reset is
proposed. Do not substitute the documented hardware reset request 0x30.

The raw frame structure agrees with the GPL definitions: 32-byte video bulk
header, 48-byte primary-flip command, RGB32 format 8, 7680-byte pitch, framebuffer
pixel offset after the flip header, and 8,294,400 pixel bytes. The raw helper in
the GPL lineage has no additional JPEG-style 1024-byte end pad. The inherited
0x80 first-frame flag is documented as a JPEG reset, despite its use for raw
frames in the donor; this remains a separate uncertainty. Successful full-length
USB transfers do not validate destination memory, transmitter setup, or pixels.

## Request provenance and exact bounds

Primary source: MCT `triggerdm` commit
`63cecc7ef3308bcd4ad213e1ebd3139d804ffb8a`,
[`t6.h`](https://github.com/mcttrigger/triggerdm/blob/63cecc7ef3308bcd4ad213e1ebd3139d804ffb8a/t6.h)
defines requests 0x84 and 0x89 and the 32-byte `_ResolutionTiming` structure.
[`t6usbdongle.c`](https://github.com/mcttrigger/triggerdm/blob/63cecc7ef3308bcd4ad213e1ebd3139d804ffb8a/t6usbdongle.c)
implements the four-byte count and count-times-structure table read.
[`t6auddef.h`](https://github.com/mcttrigger/triggerdm/blob/63cecc7ef3308bcd4ad213e1ebd3139d804ffb8a/t6auddef.h)
documents the audio engine structure. These GPL sources were inspected, not run.

Independent corroboration: cyrozap commit
`13ff4300cf2ae66fe5bd02fd6cce2c0b303f0e47`,
[`Protocol-T6.md`](https://github.com/cyrozap/mct-usb-display-adapter-re/blob/13ff4300cf2ae66fe5bd02fd6cce2c0b303f0e47/doc/Protocol-T6.md)
records head-selected 0xc0/0x89 reads of 512 bytes, and the
[`dissector`](https://github.com/cyrozap/mct-usb-display-adapter-re/blob/13ff4300cf2ae66fe5bd02fd6cce2c0b303f0e47/wireshark/proto_t6.c)
agrees on timing geometry. MCT describes nonzero wIndex as StartIndex, whereas
the research note calls it a byte offset. This experiment fixes wIndex=0 and
does not page, avoiding that unresolved unit difference. Research files/captures
were retained only in ignored artifacts; no capture was replayed or binary run.
The research's software/non-software licenses remain 0BSD / CC BY-SA 4.0.

After the already-used RAM/status/valid-base-EDID reads, these are the **only new
USB transactions**:

| bmRequestType | bRequest | wValue | wIndex | Expected response |
| --- | --- | --- | --- | --- |
| 0xc0, vendor/device IN | 0x84, timing count | 0, head 0 | 0 | exactly 4 bytes, little-endian unsigned count |
| 0xc0, vendor/device IN | 0x89, timing records | 0, head 0 | 0 | exactly `32 * min(count, 16)` bytes; 32–512 bytes |

Zero count fails without a table request. The cap is applied before multiplication,
including a UINT_MAX count. Larger tables are explicitly truncated to the first
16 records; missing 1080p there does not establish its absence from the full table.
One-second transfer timeouts and exact-length checks remain in force. There is
no retry, interrupt/bulk read, audio request, OUT data stage, mode application,
DRM registration, frame allocation, or timer/work activation. EP0 control IN
still includes USB setup/handshake packets; "IN-only" does not mean electrical
silence or a guarantee against a firmware side effect.

`query_timings=1` defaults off and requires `manual_only=0 query_only=1
output_mask=1 aquamarine_evdi_name=0 raw_idle_refresh=0`. Exact USB identity/path,
RAM=58, raw status=1, valid EDID, and the single-probe latch remain mandatory.
`manual_only=1` retains descriptor-only precedence. All query-mode EP0 IN calls
pass a shared tested tuple allowlist; every vendor OUT and bulk sender separately
refuses query mode. Audio requests 0x20–0x27/0xa0–0xa7 cannot pass that allowlist.

## Reviewed one-shot execution and quiet restoration

`tools/query_head0_timings.sh` is inert without its explicit root token. It pins
device 102 at `2-1.4.1`, the complete cached descriptor hash, kernel, VT2, healthy
eDP, taint 12288, the resident unbound `71c43fee…` build, and query build hash
`ee5d9402b5a1ff65c1100c36e3229a0e9f1b5ad4d165f5e3cdcb2fc31418481c`
(srcversion `DE73E2F323EF05B0DD600AF`). It normally removes the already-unbound
old module, inserts the query variant once, observes passively for ten seconds,
then unbinds only the exact original query interface and normally removes it.
EXIT/INT/TERM cleanup is bounded and refuses unexpected module/device state.
It never restores active video. A disconnect causes failure; a re-enumerated
interface is not touched using the stale device number. Normal removal of the
known query module is allowed only at zero references. No force flag is used.

The separately authenticated action, when expressly approved, is:

```sh
/usr/bin/pkexec /usr/bin/bash "$REPO/tools/query_head0_timings.sh" --run-reviewed-head0-timings
```

The orchestrator bounds the graphical prompt and captures stdout/stderr under
ignored artifacts. Authentication timing out is not a completed query. This
wrapper is tied to the measured state, not a generic installer or hotplug tool;
fresh state or a rebuilt module requires a new review. The starting **quiet**
state is restored, not the earlier blank-screen streaming state.

After cleanup, decode the one-query log as the normal user:

```sh
python3 tools/decode_timings.py --log artifacts/runtime-2026-09-05/head0-timing-query.log
```

The decoder requires exactly one count header and the exact bounded set of
32-byte indexed records. Missing/duplicate/extra/truncated records fail. Geometry
errors are printed with exit status 3; malformed input exits 2. It reports the
PLL bytes untouched and compares each record to the actual DRM 1080p60 geometry.
Neither a parsed record nor a matching geometry authorizes a modeset. No frames
are permitted until a separately reviewed timing-only change is supported by
the response. The subsequent test must preserve the stream format and obtain
the user's physical readable-output confirmation.

## Offline verification

Exact prepared 7.1.9-arch1-2 headers, GCC W=1: pass, no C warnings; only the known
missing-pahole version warning, with optional BTF omitted. All 26 Python checks,
64 descriptor cases, 128 refresh cases, and 11,842,560 query-IN tuple cases plus
nine count/overflow bounds pass. Both GCC and Clang C harnesses use
`-Wall -Wextra -Werror -fsanitize=address,undefined`. The new tuple matrix covers
every request byte, masks 0–4, both timing settings, values/indices 0–2, and
lengths 0–513. Source checks tie it to the live helper and verify early OUT/bulk
denial. Kernel delta checkpatch: 0 errors/warnings, 162 lines; query header: 0/0,
59 lines. Tests do not emulate USB firmware or prove the entire kernel driver.

The first decoder fixture run caught the fixture parser mistaking `1920x1080`
inside a C comment for a hex byte. Stripping comments fixed that test-only
parser; subsequent tests pass. The driver timing bytes remain unchanged.

## Page-0 result and exact continuation

At 00:13:59 on September 6, graphical authentication succeeded promptly and
page 0 actually returned: head0 status 1, valid HP X27q EDID, count 36, exactly
512 bytes/16 records. The query stayed device 102 through a ten-second passive
observation, then normal unbind/removal completed at 00:14:09 (exit 0).
No new disconnect, warning, OUT, initialization, DRM, or frame occurred. Module
absence and healthy eDP were verified. `head0-timing-query.log` and its decoded
JSON preserve all raw records under ignored artifacts.

All 16 records pass documented geometry checks:

| Indices | Firmware modes | Also in HP base EDID |
| --- | --- | --- |
| 0, 1 | 640×480, 60/75 Hz | 60 Hz |
| 2, 3, 4 | 800×600, 60/72/75 Hz | 60 Hz |
| 5, 6, 7 | 1024×768, 60/70/75 Hz | 60 Hz |
| 8 | 1152×864, 75 Hz | not listed |
| 9 | 1280×720, 60 Hz | yes |
| 10, 11 | 1280×768, 60/75 Hz | not listed |
| 12, 13 | 1280×800, 60/75 Hz | 60 Hz |
| 14 | 1280×960, 60 Hz | not listed |
| 15 | 1280×1024, 60 Hz | yes |

The HP's cached base EDID also lists 1920×1080@60 with 148.5 MHz pixel clock;
its preferred detailed timing is 2560×1440@59.95. These are mode advertisements,
not evidence that the current USB stream produces pixels.

The public cyrozap
[`trace-JCD543-20220514T1925…1080p-edid.pcapng.gz`](https://github.com/cyrozap/mct-usb-display-adapter-re/blob/13ff4300cf2ae66fe5bd02fd6cce2c0b303f0e47/captures/trace-JCD543-20220514T1925-win10-plug-in-dongle-with-hdmi-disconnected-then-connect-1080p-edid.pcapng.gz)
settles the earlier offset question. Its head0 0xc0/0x89 transactions use offsets
0/512/1024, response lengths 512/512/128, all status 0. Its first 512 bytes are
**byte-for-byte identical to the live page 0**. Record 26 on the second page is
exact CEA 1080p60. A later captured 0x40/0x12 modeset uses the same record:

```text
144402003c0098088007d8072c00650438043c040500bb02e8031d0101010000
```

This differs from the donor in four bytes spanning three fields: hsync-start
low byte at 0x0a, vsync-start bytes at 0x12–0x13, and vsync-width low byte at
0x14. All other bytes, including PLL configuration, agree. The open capture was
parsed **offline only**, not replayed. `tools/inspect_timing_capture.py` pairs
captured requests/completions using the documented Linux usbmon / USBPcap
formats; synthetic paired/truncated-container tests cover that parser. It does
not capture live USB, load usbmon, execute a Windows binary, or infer replay
authorization. Raw capture and analysis JSON remain ignored.

The next explicit `query_timing_page1=1` experiment replaces the first-page
read with exactly **0xc0/0x89, value 0, byte offset 512, length 512**, after the
usual valid status/EDID and a fresh count query returning exactly 36. It does
not issue the ambiguous offset-1 sentinel, read the final page, or use automatic
paging. Every transfer stays within 512 bytes. The shared allowlist enforces
that exact continuation tuple. The decoder now accepts indices 16–31 only for
the measured total 36, preserves global indices, and must identify record 26
as exact valid CEA1080p60 before any active change is proposed.

Prepared continuation artifact:
`debce8f3f8b2409dbe3de5502bb9f16a7309314132565ae59c0773a4ea817edf`,
srcversion `0DA9B2181DC790C77E8B79F`. W=1 passes; kernel delta checkpatch is 0/0
over 97 lines. All 31 Python tests and GCC/Clang ASan/UBSan matrices pass,
including 39,475,200 query tuples plus nine count/overflow bounds. The
`query_timing_page1.sh --run-reviewed-timing-page1` root wrapper requires the
exact fresh device 102, descriptor hash, eDP/VT2/taint, absent module, and this
artifact/vermagic. It inserts once and normally removes after ten passive
seconds, with guarded EXIT/INT/TERM cleanup and no active-video restoration.
The first-page artifact `ee5d9402…` is preserved separately. A build/commit is
not the continuation's runtime result; the dated log records actual invocation.

## Continuation attempts: connection guard and authentication

At 00:27:33 on September 6, the first page1 action authenticated. RAM returned
58, but head0 connection status was **0x00**. The guard stopped before EDID,
count, or the offset512 table request. Normal removal succeeded in the same
second; wrapper exit 1, module absent, device102 unchanged/unbound. There was
no OUT/init/frame or USB disconnect. This is a missing-sink precondition,
not malformed timing data or a failed page-offset operation.

The user explicitly requested another prompt. After verifying the first process
had exited and eDP was on, one fresh120-second prompt was launched at 00:29:03.
Its Omarchy polkit layer was visibly mapped (alpha1) on active eDP. It expired
with status124 around 00:31:03, with an empty log and no second wrapper/probe.
Current state is module absent, exact device102 unbound, laptop eDP healthy.
Logs: `timing-page1-query.log` and `timing-page1-query-user-retry.log`, ignored.

At that historical point, the live second page and record26 remained **unread**.
The following advice applied before the successful retry below: do not turn the public
capture's valid record into a claim of a successful current-laptop test. Wake
or power-cycle the HP on the correct HDMI input, leaving dock USB connected,
then revalidate all state before any explicitly requested single query retry.
If USB is reconnected instead, a new device number/path requires wrapper review.
Never bypass status/EDID or initialize video merely to make the query proceed.

For comparison when a complete live page is available, the public second-page
SHA-256 is `089c8d569b079b1e52403eaf5a4167b6460d808510968f36cfd1dc34b723da2b`;
public record26 SHA-256 is
`bd7bf8c211ff90448fcb958274969b82ba09f6a9a9a8d86fd087fbaa5e0cbcda`.
No active timing bytes had been changed at that preparation point.

## Live record26 verified; four-byte correction

After the user power-cycled the HP, authentication succeeded at **00:34:23**.
Head0 status1, valid HP X27q EDID, and count36 gated the offset512/length512
read. All sixteen returned records pass geometry validation. The complete page
matches the public JCD543 capture exactly, and record26 matches both that
capture's table and its actual Windows modeset byte-for-byte. Both hashes above
are now also verified **live-device** hashes. Record26 is exact 148.5 MHz
CEA1080p60 with sync starts2008/1084 and widths44/5. Device102 remained stable;
normal unbind/removal completed at00:34:33, exit0, eDP on, module absent, no
new fault/disconnect/taint. Raw and decoded logs are
`timing-page1-after-hp-power.log` and `timing-page1-after-hp-power-decoded.json`.

Source commit `f79493e` corrects exactly four data bytes in `t6_mode_1080p`:
0x0a:18→d8, 0x12:e8→3c, 0x13:03→04, 0x14:1d→05. No other mode byte, PLL
configuration, request, initialization order, frame format/stride/address,
damage/refresh behavior, or matching/one-probe/fault guard changes. Comments
are updated to reflect the verified match. Regression tests retain the inherited
bad record and assert the complete fixed record plus exactly those differences.

The inherited audio0x23/0x24 calls and their40/16/16-byte blobs are explicitly
unchanged and covered by regression checks. Their purpose is suspicious for a
video-only driver, but removing them concurrently would obscure whether this
confirmed timing defect explains the blank screen. This isolation does not
certify the existing active sequence as safe. It introduces no additional
command, pixel clock, mode size, bandwidth, or memory address; the corrected
timing is independently observed from this firmware and the JCD543 Windows
driver. Any later audio removal remains a separate review/test.

Corrected build SHA-256:
`cec6a3429df95e8b3d79ab01e02ff0b7ff96ccee5aa39a11ad30938c09374c35`,
srcversion `F6D5C7316849C7428A83002`. W=1 passes with only the known BTF warning;
kernel diff checkpatch0/0 over23 lines;34 Python checks and GCC/Clang sanitizer
matrices pass. The query artifact is preserved as `trigger6-timing-page1-proven.ko`.

`tools/test_verified_timing.sh --run-reviewed-verified-timing` pins the exact
artifact/device102/eDP/VT2/taint and absent module, then inserts head0 only with
the existing Aquamarine shim/idle refresh enabled and all query switches off.
It monitors identity, laptop panel, kernel warnings and transport counters for
ninety seconds. A detected fault or interruption triggers bounded exact-interface
unbind and ordinary removal; a changed enumeration is not unbound using stale
device102. Incomplete normal cleanup requires unplug/review/reboot, never force.
Success leaves the temporary module loaded for physical confirmation; it does
not install it. The user-session static pattern and a45-second sample run during
this watch, followed by `check_verified_dpms.sh --run-reviewed-verified-dpms`,
which disables only HDMI-A-2 for ten seconds and restores it on EXIT/INT/TERM.
Keep eDP on and require fresh real full-frame resend after re-enable. Physical
readability is a separate user-confirmed milestone; no installation is approved
merely because the timing record/build/USB test passes.

## Physical result of the isolated correction

The exact corrected build above was inserted at 00:44:48. At about 00:45:25,
the user confirmed the physical HP displayed the named test screen on standalone
MCT HDMI/head0. This is the first physical image confirmation, not an inference
from the successful firmware queries, KMS counters, or compositor screenshot.

The settled 45-second sample sent 44 idle refreshes with zero faults and no USB
re-enumeration. The 90-second root watcher passed. Afterwards, an external-only
ten-second DPMS-off interval held frame/refresh/bulk counters unchanged; on sent
fresh real full frames and resumed idle refresh. The user separately confirmed
the HP physically turned off and came back on. Full timestamps, exact parameters,
metrics, hashes, and live state are in the [runtime record](RUNTIME_TEST_2026-09-05.md).

This controlled timing-only change is strong evidence that the inherited sync
fields caused the observed blank screen on this HP/dock. It does not prove the
cause of older idle disconnects, remove the 0x23/0x24 audio uncertainty, validate
other modes/outputs, or establish long-run safety. The one-probe latch, exact
device guards, opt-in shim/refresh, and no-persistence boundary remain in force.
