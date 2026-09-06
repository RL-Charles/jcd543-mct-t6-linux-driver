#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fail-closed, single-device controller. Status/plan are read-only by default."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import tempfile
import time

DESCRIPTOR_SHA = "61ed0a266c3b3db8f8be6dfab701a1fa9e1e1a1e1cd7681f14999e854c01b12f"
USB_ALIAS = "usb:v0711p5601d*dc*dsc*dp*icFFisc00ip00in*"
COMPOSITOR_PACKAGES = "hyprland 0.56.2-1\naquamarine 0.14.0-2"
PROFILE = {"manual_only": "N", "output_mask": "1", "query_only": "N",
           "query_timings": "N", "query_timing_page1": "N",
           "aquamarine_evdi_name": "Y", "raw_idle_refresh": "Y",
           "final_monitor_off": "Y",
           "serialize_usb_bus": "Y", "experimental_secondary_raw": "N",
           "secondary_userspace_jpeg": "N"}
STABLE_SECONDS = 15
COOLDOWN_SECONDS = 120
RAPID_LOSS_SECONDS = 60
HOURLY_ATTEMPTS = 3
BOOT_ATTEMPTS = 6
# The sleep hook still has its independent 3s TERM + 1s KILL ceiling.
STOP_SECONDS = 2.5
REFCOUNT_SETTLE_SECONDS = 0.5
REFCOUNT_POLL_SECONDS = 0.025
CONFIG = "/etc/jcd543-trigger6/approved.json"
RUNTIME = "/run/jcd543-trigger6"
INSTALLED_HELPER = "/usr/lib/jcd543-trigger6/controller.py"
PORT_RE = re.compile(r"[0-9]+-[0-9]+(?:\.[0-9]+)*\Z")
KERNEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,95}\Z")
FAULT_RE = re.compile(r"(?:io_faulted|io_last_error|send_errors|transport_faults|"
                      r"bulk_errors|bulk_short_writes|keepalive_errors|last_error)=(-?\d+)")


class Refusal(RuntimeError):
    pass


class NotReady(Refusal):
    """Cached enumeration/udev is incomplete; never authorize an operation."""


class Busy(Refusal):
    """Another controller operation owns the lock; no mutation was attempted."""


def fresh_state(boot_id):
    return {"schema": 1, "boot_id": boot_id, "desired": False, "paused": False,
            "circuit": None, "attempts": [], "candidate": None,
            "candidate_since": 0, "managed_generation": None,
            "last_attempt": None, "inflight": None, "reason": "not started"}


def decide(state, observation, now):
    """Pure policy; returns a copied state and one bounded action, never I/O."""
    state = dict(state)
    state["attempts"] = list(state["attempts"])

    def answer(action, reason, trip=False):
        state["reason"] = reason
        if trip:
            state["circuit"] = reason
        return state, action

    if state["inflight"]:
        return answer("wait", state["circuit"] or "unfinished prior mutation: manual recovery required", True)
    if state["circuit"]:
        return answer("wait", state["circuit"])
    if not state["desired"] or state["paused"] or observation.get("inhibited"):
        return answer("wait", "stopped or sleep-inhibited")
    if "inhibited" in observation and observation["inhibited"] is None:
        return answer("wait", "sleep inhibition state unavailable: manual review required", True)
    if observation.get("error"):
        return answer("wait", observation["error"], True)
    device = observation.get("device")
    if not device:
        state["candidate"] = None
        if state["managed_generation"] and state["last_attempt"] is not None:
            if now - state["last_attempt"] < RAPID_LOSS_SECONDS:
                return answer("wait", "rapid device loss: automatic recovery blocked", True)
        return answer("wait", observation.get("pending", "exact device absent"))
    generation = device["generation"]
    if state["candidate"] != generation:
        state["candidate"] = generation
        state["candidate_since"] = now
    if device.get("driver"):
        if device["driver"] != "trigger6" or not observation.get("owned_module"):
            return answer("wait", "foreign binding or unapproved resident module", True)
        if generation != state["managed_generation"]:
            return answer("wait", "bound generation was not started/adopted by controller", True)
        if observation.get("fault"):
            return answer("stop", "active transport fault: circuit breaker latched", True)
        if not observation.get("drm_present"):
            return answer("stop", "managed DRM device missing", True)
        return answer("wait", "active" if observation.get("scanout_active") else "connected; CRTC off")
    if observation.get("module_present") and not observation.get("owned_module"):
        return answer("wait", "unapproved resident module", True)
    if generation == state["managed_generation"]:
        return answer("wait", "binding lost without a new device generation", True)
    if state["managed_generation"] and state["last_attempt"] is not None:
        if now - state["last_attempt"] < RAPID_LOSS_SECONDS:
            return answer("wait", "rapid re-enumeration: automatic recovery blocked", True)
    if not observation.get("panel_ready") or not observation.get("hyprland_present"):
        return answer("wait", "waiting for active laptop panel and Hyprland")
    if now - state["candidate_since"] < STABLE_SECONDS:
        return answer("wait", "waiting for stable exact generation")
    attempts = state["attempts"]
    if len(attempts) >= BOOT_ATTEMPTS or sum(now - stamp < 3600 for stamp in attempts) >= HOURLY_ATTEMPTS:
        return answer("wait", "attempt budget exhausted: manual recovery required", True)
    if state["last_attempt"] is not None and now - state["last_attempt"] < COOLDOWN_SECONDS:
        return answer("wait", "automatic attempt cooldown")
    return answer("start", "stable approved generation ready")


def text_file(path, limit=16384):
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise Refusal(f"oversized data: {path.name}")
        return data.decode("utf-8").strip()
    except (OSError, UnicodeError):
        return None


def path_present(path):
    """Unlike Path.exists(), never mistake an inaccessible entry for absence."""
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except PermissionError:
        return None


def remaining_timeout(deadline, maximum, phase):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Refusal(f"stop deadline exhausted before {phase}; no further mutation")
    return min(maximum, remaining)


def settle_module_references(module, deadline):
    """Read-only settling after one unbind; never retry unbind or force removal."""
    started = time.monotonic()
    until = min(deadline, started + REFCOUNT_SETTLE_SECONDS)
    while True:
        references = text_file(module / "refcnt", 16)
        if references is None or not re.fullmatch(r"0|[1-9][0-9]{0,8}", references):
            raise Refusal("module refcount unavailable/malformed after unbind; no removal")
        if int(references) == 0:
            return time.monotonic() - started
        remaining = until - time.monotonic()
        if remaining <= 0:
            raise Refusal(f"module still referenced after bounded settle (refcnt={references}); no removal or force")
        time.sleep(min(REFCOUNT_POLL_SECONDS, remaining))


def metrics_summary(metrics):
    """Require the current driver's essential schema; missing fields are faults."""
    metrics = metrics or ""
    required = (r"^trigger6 .* io_faulted=\d+ io_last_error=-?\d+$",
                r"^device .* bulk_errors=\d+ bulk_short_writes=\d+ ",
                r"^head0 transport=raw connected=\d+ io_faulted=\d+ .* scanout_active=[01] ",
                r"^head0 .* transport_faults=\d+ ",
                r"^head0 sent_frames=\d+ .* send_errors=\d+ .* keepalive_errors=\d+ ")
    valid = all(re.search(pattern, metrics, re.M) for pattern in required)
    sent = re.search(r"^head0 sent_frames=(\d+)", metrics, re.M)
    keepalive = re.search(r"^head0 sent_frames=.* keepalive_sent=(\d+)", metrics, re.M)
    bulk = re.search(r"^device .* bulk_bytes=(\d+)", metrics, re.M)
    return {"fault": not valid or any(int(value) != 0 for value in FAULT_RE.findall(metrics)),
            "scanout_active": bool(valid and re.search(r"^head0 .*scanout_active=1(?: |$)", metrics, re.M)),
            "sent_frames": int(sent[1]) if sent else 0,
            "keepalive_sent": int(keepalive[1]) if keepalive else 0,
            "bulk_bytes": int(bulk[1]) if bulk else 0}


def protected(path, owner=0, directory=False, boundary=Path("/")):
    """Require trusted ownership/no group-or-other writes through all parents."""
    absolute = path.absolute()
    if not absolute.is_relative_to(boundary):
        raise Refusal("protected path escaped its trusted boundary")
    for item in (absolute, *absolute.parents):
        info = item.lstat()
        if info.st_uid != owner or info.st_mode & 0o022:
            raise Refusal(f"untrusted ownership/mode: {item}")
        if stat.S_ISLNK(info.st_mode):
            raise Refusal(f"symlink in protected path: {item}")
        if item == boundary:
            break
    info = absolute.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        raise Refusal("unexpected protected file type")


def run_command(argv, *, timeout=2, input_text=None):
    """No shell, fixed absolute executables, bounded output/lifetime."""
    if argv[0] not in {"/usr/bin/modinfo", "/usr/bin/udevadm", "/usr/bin/insmod",
                       "/usr/bin/rmmod", "/usr/bin/tee", "/usr/bin/pacman"}:
        raise Refusal("command not allowed")
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                   stdout=output, stderr=output, env={"PATH": "/usr/bin", "LC_ALL": "C"})
        try:
            process.communicate(input_text.encode() if input_text is not None else None, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            process.kill()
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass  # A stuck kernel task cannot be forcibly repaired here.
            raise Refusal(f"{Path(argv[0]).name} timed out after {timeout:.3f}s; manual recovery required") from error
        output.seek(0)
        data = output.read(65537)
        if process.returncode != 0 or len(data) > 65536:
            # Preserve bounded stderr/stdout without emitting terminal controls.
            detail = json.dumps(data.decode("utf-8", errors="replace"))
            suffix = " [output truncated]" if len(detail) > 2048 else ""
            raise Refusal(f"command refused: {Path(argv[0]).name} exit {process.returncode}: "
                          f"{detail[:2048]}{suffix}")
        return data.decode("utf-8", errors="replace").strip()


class Host:
    """Production adapter. Tests replace it; no simulated-root mutation CLI exists."""

    def __init__(self):
        self.root = Path("/")
        self.release = platform.release()

    def path(self, name):
        return self.root / name.lstrip("/")

    def now(self):
        return time.clock_gettime(time.CLOCK_BOOTTIME)

    def boot_id(self):
        return text_file(self.path("/proc/sys/kernel/random/boot_id"), 64)

    def read_config(self):
        path = self.path(CONFIG)
        protected(path)
        try:
            config = json.loads(text_file(path) or "")
        except (ValueError, TypeError) as error:
            raise Refusal("invalid approval manifest") from error
        if config.get("schema") != 1 or not isinstance(config.get("kernels"), dict):
            raise Refusal("unknown approval manifest schema")
        port = config.get("id_path")
        if port is not None and (not isinstance(port, str) or not re.fullmatch(r"[A-Za-z0-9_.:+-]{1,160}", port)):
            raise Refusal("invalid enrolled ID_PATH")
        entry = config["kernels"].get(self.release)
        if not isinstance(entry, dict):
            raise Refusal("running kernel has no approved artifact; rebuild and review explicitly")
        if (not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))) or
                not re.fullmatch(r"[0-9A-F]{23,24}", str(entry.get("srcversion", ""))) or
                not isinstance(entry.get("path"), str) or not isinstance(entry.get("vermagic"), str)):
            raise Refusal("invalid artifact approval fields")
        return config, entry

    def verify_artifact(self, entry):
        name = entry.get("path", "")
        prefix = f"/usr/lib/modules/{self.release}/"
        if not KERNEL_RE.fullmatch(self.release) or not name.startswith(prefix):
            raise Refusal("artifact outside current-kernel module tree")
        if not re.fullmatch(r"[A-Za-z0-9_./+-]+/trigger6\.ko(?:\.(?:zst|xz|gz))?", name) or ".." in Path(name).parts:
            raise Refusal("invalid installed module path")
        path = self.path(name)
        protected(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
            raise Refusal("installed artifact hash changed; new approval required")
        values = {field: run_command(["/usr/bin/modinfo", "-F", field, str(path)])
                  for field in ("name", "srcversion", "vermagic", "alias", "depends")}
        if (values["name"] != "trigger6" or values["alias"] != USB_ALIAS or values["depends"] or
                values["srcversion"] != entry.get("srcversion") or
                values["vermagic"] != entry.get("vermagic") or
                not values["vermagic"].startswith(self.release + " ")):
            raise Refusal("module metadata does not match reviewed profile")

    def discover(self, config, deadline=None):
        candidates = []
        matches = [path for path in sorted(self.path("/sys/bus/usb/devices").glob("*"))
                   if text_file(path / "idVendor") == "0711" and text_file(path / "idProduct") == "5601"]
        if len(matches) > 1:
            raise Refusal("multiple exact-ID candidates: automatic selection refused")
        for path in matches:
            if not PORT_RE.fullmatch(path.name):
                raise Refusal("invalid USB port name")
            try:
                descriptors = (path / "descriptors").read_bytes()
            except FileNotFoundError:
                continue  # Normal detach racing a cached-sysfs observation.
            if (len(descriptors) > 1024 or hashlib.sha256(descriptors).hexdigest() != DESCRIPTOR_SHA or
                    text_file(path / "bcdDevice") != "1010" or text_file(path / "speed") != "5000"):
                raise Refusal("candidate descriptor/profile mismatch")
            interface = path.parent / (path.name + ":1.0")
            if not interface.is_dir():
                if not path.exists():
                    continue
                raise NotReady("waiting for cached USB interface enumeration")
            if (text_file(interface / "bAlternateSetting") not in ("0", "00") or
                    text_file(path / "bConfigurationValue") != "1"):
                raise Refusal("candidate interface/alternate mismatch")
            try:
                timeout = remaining_timeout(deadline, 2, "cached USB discovery") if deadline is not None else 2
                properties = run_command(["/usr/bin/udevadm", "info", "--query=property", "--path", str(path)],
                                         timeout=timeout)
            except Refusal:
                if not path.exists():
                    continue
                raise
            props = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
            id_path = props.get("ID_PATH")
            epoch = props.get("USEC_INITIALIZED")
            if not id_path or not epoch:
                raise NotReady("waiting for udev ID_PATH and initialization epoch")
            if not re.fullmatch(r"[A-Za-z0-9_.:+-]{1,160}", id_path) or not re.fullmatch(r"[0-9]{1,20}", epoch):
                raise Refusal("invalid stable ID_PATH or initialization epoch")
            if config.get("id_path") is not None and id_path != config["id_path"]:
                raise Refusal("candidate outside explicitly enrolled physical port")
            devnum = text_file(path / "devnum", 16)
            if not devnum or not devnum.isdecimal() or not 1 <= int(devnum) <= 127:
                raise Refusal("invalid USB generation number")
            driver_link = interface / "driver"
            driver = driver_link.resolve().name if driver_link.is_symlink() else None
            identity = [id_path, path.name, devnum, DESCRIPTOR_SHA, epoch]
            candidates.append({"path": path.name, "interface": interface.name, "devnum": int(devnum),
                               "id_path": id_path, "driver": driver,
                               "generation": hashlib.sha256(json.dumps(identity).encode()).hexdigest()})
        if len(candidates) > 1:
            raise Refusal("multiple exact devices: automatic selection refused")
        return candidates[0] if candidates else None

    def resident_identity(self, entry):
        module = self.path("/sys/module/trigger6")
        present = module.is_dir()
        params = {key: text_file(module / "parameters" / key) for key in PROFILE}
        selected = text_file(module / "parameters/device_path")
        owned = (present and text_file(module / "srcversion") == entry["srcversion"] and
                 params == PROFILE and selected is not None and PORT_RE.fullmatch(selected) is not None)
        return present, owned, selected

    def snapshot(self, config, entry, deadline=None):
        pending = None
        try:
            device = self.discover(config, deadline)
        except NotReady as error:
            device = None
            pending = str(error)
        present, owned, selected = self.resident_identity(entry)
        panels = self.path("/sys/class/drm").glob("card*-eDP-*/status")
        panel_ready = any(text_file(item) == "connected" and
                          text_file(item.parent / "enabled") == "enabled" and
                          text_file(item.parent / "dpms") == "On" and
                          (item.parent / "device/device/driver").resolve().name == "i915" for item in panels)
        hyprland = any(text_file(item, 64) == "Hyprland"
                       for item in self.path("/proc").glob("[0-9]*/comm"))
        result = {"device": device, "module_present": present, "owned_module": owned,
                  "module_path": selected, "panel_ready": panel_ready,
                  "hyprland_present": hyprland, "inhibited": path_present(self.path(RUNTIME + "/sleep-inhibit")),
                  "fault": False, "drm_present": False, "scanout_active": False}
        if pending:
            result["pending"] = pending
        taint = text_file(self.path("/proc/sys/kernel/tainted"), 32)
        if taint is None or not taint.isdecimal() or int(taint) & ~12288:
            result["error"] = "unexpected kernel taint; manual review required"
        if device and device["driver"] == "trigger6":
            if selected != device["path"]:
                result["error"] = "bound path differs from resident module selector"
            interface = self.path("/sys/bus/usb/devices") / device["interface"]
            metrics = text_file(interface / "t6_metrics")
            result.update(metrics_summary(metrics))
            result["drm_present"] = any(item.resolve() == interface.resolve()
                                        for item in self.path("/sys/class/drm").glob("card[0-9]*/device"))
        return result

    def stop_module(self, config, entry):
        started = time.monotonic()
        deadline = started + STOP_SECONDS
        observation = self.snapshot(config, entry, deadline)
        if not observation["module_present"]:
            return
        if not observation["owned_module"]:
            raise Refusal("refusing removal of unapproved resident module")
        device = observation["device"]
        if device and device["driver"] == "trigger6":
            fresh = self.discover(config, deadline)
            if not fresh or fresh["generation"] != device["generation"] or fresh["driver"] != "trigger6":
                raise Refusal("generation changed before exact unbind")
            try:
                run_command(["/usr/bin/tee", "/sys/bus/usb/drivers/trigger6/unbind"],
                            timeout=remaining_timeout(deadline, 1.5, "unbind"),
                            input_text=device["interface"] + "\n")
            except (Refusal, OSError) as error:
                raise Refusal(f"exact-interface unbind failed: {error}") from error
            print(json.dumps({"event": "exact-interface-unbound", "interface": device["interface"],
                              "elapsed_ms": round((time.monotonic() - started) * 1000, 3)}), flush=True)
        module = self.path("/sys/module/trigger6")
        settled = settle_module_references(module, deadline)
        present, owned, selected = self.resident_identity(entry)
        if not present or not owned or selected != observation["module_path"]:
            raise Refusal("resident identity changed during stop; no removal")
        fresh = self.discover(config, deadline)
        if (fresh["generation"] if fresh else None) != (device["generation"] if device else None):
            raise Refusal("generation changed during stop; no removal")
        if fresh and fresh["driver"]:
            raise Refusal("interface rebound during stop; no removal")
        if text_file(module / "refcnt", 16) != "0":
            raise Refusal("module acquired a new reference after settle; no removal")
        print(json.dumps({"event": "module-references-released", "settle_ms": round(settled * 1000, 3)}), flush=True)
        try:
            run_command(["/usr/bin/rmmod", "trigger6"],
                        timeout=remaining_timeout(deadline, 1.5, "ordinary removal"))
        except (Refusal, OSError) as error:
            raise Refusal(f"ordinary module removal failed: {error}") from error
        if module.exists():
            raise Refusal("module remains resident after normal removal")

    def start_module(self, config, entry, generation):
        self.verify_artifact(entry)
        before = self.snapshot(config, entry)
        device = before["device"]
        if (before.get("error") or before["inhibited"] is not False or not before["panel_ready"] or
                not before["hyprland_present"] or not device or device["generation"] != generation or device["driver"]):
            raise Refusal("generation/panel/readiness changed before insertion")
        if run_command(["/usr/bin/pacman", "-Q", "hyprland", "aquamarine"]) != COMPOSITOR_PACKAGES:
            raise Refusal("unreviewed compositor packages; name-shim compatibility review required")
        if before["module_present"]:
            self.stop_module(config, entry)
        fresh = self.snapshot(config, entry)
        if (fresh["inhibited"] is not False or fresh.get("error") or not fresh["panel_ready"] or
                not fresh["device"] or fresh["device"]["generation"] != generation or
                fresh["device"]["driver"] or fresh["module_present"]):
            raise Refusal("state changed while removing old one-attempt module")
        arguments = [f"{name}={'1' if value == 'Y' else '0' if value == 'N' else value}"
                     for name, value in PROFILE.items()]
        run_command(["/usr/bin/insmod", entry["path"], f"device_path={device['path']}", *arguments], timeout=8)
        after = self.snapshot(config, entry)
        if (not after["device"] or after["device"]["generation"] != generation or
                after["device"]["driver"] != "trigger6" or not after["owned_module"] or
                after["fault"] or not after["drm_present"]):
            raise Refusal("single insertion failed its binding/DRM/transport checks")


class StateStore:
    def __init__(self, directory, owner=0, boundary=Path("/")):
        self.directory = directory
        self.owner = owner
        self.boundary = boundary

    def check(self, path, directory=False):
        protected(path, self.owner, directory, self.boundary)

    def prepare(self):
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.check(self.directory, directory=True)

    @contextlib.contextmanager
    def lock(self):
        self.prepare()
        descriptor = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if info.st_uid != self.owner or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
                raise Refusal("unsafe lock file")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Busy("controller busy; operation refused without waiting") from error
            yield
        finally:
            os.close(descriptor)

    def read(self, boot_id):
        path = self.directory / "state.json"
        try:
            path.lstat()
        except FileNotFoundError:
            return fresh_state(boot_id)
        self.check(path)
        try:
            state = json.loads(text_file(path) or "")
        except (TypeError, ValueError) as error:
            raise Refusal("malformed state: manual inspection required") from error
        if state.get("schema") != 1 or set(state) != set(fresh_state(boot_id)):
            raise Refusal("unknown state schema")
        if state["boot_id"] != boot_id:
            return fresh_state(boot_id)
        if (not isinstance(state["attempts"], list) or len(state["attempts"]) > BOOT_ATTEMPTS or
                any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                    for value in state["attempts"])):
            raise Refusal("invalid attempt ledger")
        if (type(state["desired"]) is not bool or type(state["paused"]) is not bool or
                type(state["candidate_since"]) not in (int, float) or
                not math.isfinite(state["candidate_since"]) or state["candidate_since"] < 0 or
                (state["last_attempt"] is not None and
                 (type(state["last_attempt"]) not in (int, float) or
                  not math.isfinite(state["last_attempt"]) or state["last_attempt"] < 0))):
            raise Refusal("invalid state types/timestamps")
        return state

    def write(self, state):
        self.prepare()
        target = self.directory / "state.json"
        if target.exists() or target.is_symlink():
            self.check(target)
        descriptor, name = tempfile.mkstemp(prefix=".state-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(state, stream, sort_keys=True, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def tick(host, store, state, config, entry):
    try:
        observation = host.snapshot(config, entry)
    except (Refusal, OSError) as error:
        state["circuit"] = str(error)
        state["reason"] = str(error)
        store.write(state)
        return state
    state, action = decide(state, observation, host.now())
    store.write(state)
    if action == "wait":
        return state
    generation = observation["device"]["generation"]
    state["inflight"] = {"action": action, "generation": generation}
    if action == "start":
        state["attempts"].append(host.now())
        state["last_attempt"] = host.now()
    store.write(state)  # A crash/timeout preserves a fail-closed, consumed attempt.
    try:
        if action == "start":
            host.start_module(config, entry, generation)
            state["managed_generation"] = generation
            state["reason"] = "managed KMS started; physical confirmation remains separate"
        else:
            host.stop_module(config, entry)
            state["managed_generation"] = None
        state["inflight"] = None
    except (Refusal, OSError) as error:
        state["circuit"] = str(error)
        state["reason"] = str(error)
        # A failed start gets one bounded normal cleanup. Never repeat a failed
        # stop: a timed-out unbind may still be executing inside the kernel.
        if action == "start":
            try:
                host.stop_module(config, entry)
                state["managed_generation"] = None
                state["inflight"] = None
            except (Refusal, OSError) as cleanup_error:
                # Retain both causes; observers must not replace them with a
                # generic inflight message or submit a second cleanup.
                state["inflight"]["cleanup_error"] = str(cleanup_error)[:2048]
                state["circuit"] += f"; cleanup failed: {str(cleanup_error)[:2048]}"
                state["reason"] = state["circuit"]
    store.write(state)
    return state


def require_installed():
    if os.geteuid() != 0 or Path(__file__).absolute() != Path(INSTALLED_HELPER):
        raise Refusal("mutations require the root-owned installed helper and explicit --apply")
    protected(Path(INSTALLED_HELPER))


def approve(host, args):
    if (not args.module or not args.sha256 or not args.srcversion or
            not re.fullmatch(r"[0-9a-f]{64}", args.sha256) or
            not re.fullmatch(r"[0-9A-F]{23,24}", args.srcversion)):
        raise Refusal("approval requires an exact installed path, reviewed SHA-256 and srcversion")
    entry = {"path": args.module, "sha256": args.sha256, "srcversion": args.srcversion,
             "vermagic": run_command(["/usr/bin/modinfo", "-F", "vermagic", args.module])}
    host.verify_artifact(entry)
    config = {"schema": 1, "id_path": args.id_path, "kernels": {host.release: entry}}
    if args.id_path is not None and not re.fullmatch(r"[A-Za-z0-9_.:+-]{1,160}", args.id_path):
        raise Refusal("invalid approved physical port ID_PATH")
    destination = Path(CONFIG)
    if destination.exists():
        protected(destination)
        previous = json.loads(text_file(destination) or "")
        if previous != config:
            raise Refusal("approval already exists; stop and review a separate manifest update")
        return
    destination.parent.mkdir(mode=0o755, exist_ok=True)
    protected(destination.parent, directory=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".approval-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(config, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        os.link(temporary, destination)  # Atomic publication; never overwrite approval.
    finally:
        os.unlink(temporary)
    print("Current-kernel artifact approved. Approval did not enable the service or load a module.")


def stop_preserving_failure(command, host, store, state, config, entry):
    try:
        host.stop_module(config, entry)
    except (Refusal, OSError) as error:
        message = f"{command} failed: {str(error)[:2048]}"
        state["circuit"] = message
        state["reason"] = message
        state["inflight"]["error"] = str(error)[:2048]
        store.write(state)
        raise Refusal(message) from error


def operate(command, host, store, state, config, entry):
    """Called under the ledger lock; injectable adapter permits synthetic tests."""
    inhibit = store.directory / "sleep-inhibit"
    if command == "pause":
        if not state["desired"]:
            store.check(inhibit)
            inhibit.unlink()
            return state
        state["paused"] = True
        state["inflight"] = {"action": "sleep-stop"}
        store.write(state)
        stop_preserving_failure(command, host, store, state, config, entry)
        state["managed_generation"] = None
        state["inflight"] = None
    elif command == "resume":
        if not state["desired"] and not state["paused"] and not inhibit.exists():
            return state
        if not state["paused"] or state["inflight"]:
            raise Refusal("sleep quiesce was incomplete: inhibit retained for manual recovery")
        state["paused"] = False
        state["candidate"] = None
        if inhibit.exists():
            store.check(inhibit)
            inhibit.unlink()
    elif command == "stop":
        state["desired"] = False
        state["inflight"] = {"action": "stop"}
        store.write(state)
        stop_preserving_failure(command, host, store, state, config, entry)
        state["managed_generation"] = None
        state["inflight"] = None
    elif command == "clear-circuit":
        observation = host.snapshot(config, entry)
        if observation["device"] and observation["device"]["driver"]:
            raise Refusal("stop the module before explicit circuit recovery")
        state = fresh_state(host.boot_id())
        if inhibit.exists():
            store.check(inhibit)
            inhibit.unlink()
    else:
        host.verify_artifact(entry)
        state["desired"] = True
    store.write(state)
    return state


def status_report(host, store, config, entry):
    observation = host.snapshot(config, entry)
    try:
        state = store.read(host.boot_id())
    except (Refusal, OSError) as error:
        # A private root ledger is unknown to this caller, never a fabricated
        # stopped/default state. Cached hardware observations remain useful.
        return {"observation": observation, "state": None, "ledger_available": False,
                "next_action": "unknown", "read_only": True,
                "reason": "controller ledger unavailable; authenticate for canonical state",
                "ledger_error": str(error)[:2048]}
    planned, action = decide(state, observation, host.now())
    return {"observation": observation, "state": state, "ledger_available": True,
            "next_action": action, "reason": planned["reason"], "read_only": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "plan", "approve", "start", "stop", "watch", "pause", "resume", "clear-circuit"))
    parser.add_argument("--apply", action="store_true", help="explicit installed-helper mutation opt-in")
    parser.add_argument("--module", help="approval only: reviewed root-owned installed module path")
    parser.add_argument("--sha256", help="approval only: independently reviewed installed-artifact hash")
    parser.add_argument("--srcversion", help="approval only: independently reviewed source version")
    parser.add_argument("--id-path", help="approval only: optional exact udev ID_PATH physical port policy")
    args = parser.parse_args()
    host = Host()
    store = StateStore(Path(RUNTIME))
    mutating = args.apply and args.command not in ("status", "plan")
    if mutating:
        require_installed()
    if args.command == "approve":
        if not args.apply:
            print("Read-only plan: approve one reviewed installed artifact; does not start or enable the driver.")
            return
        approve(host, args)
        return
    inhibit = store.directory / "sleep-inhibit"
    if mutating and args.command == "pause":
        # Written before any potentially slow query/lock; an incomplete pre hook
        # retains this inhibition across post/resume until explicit recovery.
        store.prepare()
        descriptor = os.open(inhibit, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
    if not Path(CONFIG).exists() and not mutating:
        print(json.dumps({"read_only": True, "approved": False, "kernel": host.release,
                          "module_present": Path("/sys/module/trigger6").exists(),
                          "reason": "no approved installed artifact; inspect preflight and install plan"}, indent=2))
        return
    config, entry = host.read_config()
    if args.command in ("status", "plan") or not args.apply:
        print(json.dumps(status_report(host, store, config, entry), indent=2))
        return
    with store.lock():
        state = store.read(host.boot_id())
        state = operate(args.command, host, store, state, config, entry)
    if args.command in ("start", "watch"):
        deadline = host.now() + STABLE_SECONDS + 3
        previous = None
        while True:
            try:
                with store.lock():
                    state = tick(host, store, store.read(host.boot_id()), config, entry)
            except Busy:
                if args.command == "start" and host.now() >= deadline:
                    raise Refusal("controller remained busy through bounded start deadline")
                time.sleep(1)  # Observer only; a busy iteration never mutates.
                continue
            if state["reason"] != previous:
                print(json.dumps({"status": state["reason"], "circuit": bool(state["circuit"])}), flush=True)
                previous = state["reason"]
            if args.command == "start" and (state["managed_generation"] or state["circuit"] or host.now() >= deadline):
                if state["circuit"] or not state["managed_generation"]:
                    raise Refusal(state["reason"])
                break
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except (Refusal, OSError, ValueError, KeyError) as error:
        print(f"Refused: {error}", file=sys.stderr)
        sys.exit(1)
