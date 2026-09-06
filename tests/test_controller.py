#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic controller tests. No USB, module, package, or system mutations."""

import copy
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("t6_controller", ROOT / "control/controller.py")
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


def observation(generation="A", driver=None, **extra):
    result = {"device": {"generation": generation, "path": "2-1.4.1",
                         "interface": "2-1.4.1:1.0", "driver": driver},
              "panel_ready": True, "hyprland_present": True, "module_present": False,
              "owned_module": False, "drm_present": False, "scanout_active": False}
    result.update(extra)
    return result


def ready_state():
    state = C.fresh_state("synthetic-boot")
    state.update(desired=True, candidate="A", candidate_since=0)
    return state


class FinalOffProfileTests(unittest.TestCase):
    def test_selected_profile_requires_proven_final_off(self):
        self.assertEqual(C.PROFILE["final_monitor_off"], "Y")
        self.assertEqual(C.PROFILE["output_mask"], "1")
        self.assertEqual(C.PROFILE["manual_only"], "N")

    def test_resident_without_exact_final_off_parameter_is_unowned(self):
        with tempfile.TemporaryDirectory(prefix="t6 final-off profile ") as directory:
            host = C.Host()
            host.root = Path(directory)
            module = host.path("/sys/module/trigger6")
            params = module / "parameters"
            params.mkdir(parents=True)
            (module / "srcversion").write_text("SYNTHETIC-REVIEWED")
            (params / "device_path").write_text("2-1.4.1")
            for name, value in C.PROFILE.items():
                (params / name).write_text(value)
            entry = {"srcversion": "SYNTHETIC-REVIEWED"}
            self.assertEqual(host.resident_identity(entry), (True, True, "2-1.4.1"))
            for value in ("N", "1", "", "Y\nN"):
                (params / "final_monitor_off").write_text(value)
                self.assertEqual(host.resident_identity(entry), (True, False, "2-1.4.1"))
            (params / "final_monitor_off").unlink()
            self.assertEqual(host.resident_identity(entry), (True, False, "2-1.4.1"))

    def test_one_load_passes_final_off_once_with_unchanged_single_head_guards(self):
        host = C.Host()
        host.verify_artifact = mock.Mock()
        unbound = observation(inhibited=False, fault=False)
        bound = observation(driver="trigger6", module_present=True, owned_module=True,
                            inhibited=False, fault=False, drm_present=True)
        host.snapshot = mock.Mock(side_effect=[unbound, unbound, bound])
        with mock.patch.object(C, "run_command", return_value=C.COMPOSITOR_PACKAGES) as run:
            host.start_module({}, {"path": "/synthetic/trigger6.ko"}, "A")
        self.assertEqual(len(run.call_args_list), 2)
        argv = run.call_args_list[1].args[0]
        self.assertEqual(argv[:3], ["/usr/bin/insmod", "/synthetic/trigger6.ko", "device_path=2-1.4.1"])
        self.assertEqual(argv.count("final_monitor_off=1"), 1)
        self.assertIn("output_mask=1", argv)
        self.assertIn("query_only=0", argv)
        self.assertIn("serialize_usb_bus=1", argv)


class PolicyTests(unittest.TestCase):
    def test_default_stays_inert(self):
        state, action = C.decide(C.fresh_state("boot"), observation(), 999)
        self.assertEqual(action, "wait")
        self.assertFalse(state["desired"])

    def test_exact_debounce_and_panel_hypr_gates(self):
        state = ready_state()
        self.assertEqual(C.decide(state, observation(), 14.999)[1], "wait")
        self.assertEqual(C.decide(state, observation(), 15)[1], "start")
        for field in ("panel_ready", "hyprland_present"):
            self.assertEqual(C.decide(state, observation(**{field: False}), 100)[1], "wait")

    def test_new_generation_restarts_debounce(self):
        state, action = C.decide(ready_state(), observation("B"), 100)
        self.assertEqual(action, "wait")
        self.assertEqual(state["candidate_since"], 100)
        self.assertEqual(C.decide(state, observation("B"), 115)[1], "start")

    def test_fault_and_missing_drm_request_stop_once_then_latch(self):
        for damage in ({"fault": True}, {"drm_present": False}):
            state = ready_state()
            state["managed_generation"] = "A"
            sample = observation(driver="trigger6", owned_module=True, drm_present=True)
            sample.update(damage)
            state, action = C.decide(state, sample, 100)
            self.assertEqual(action, "stop")
            self.assertIsNotNone(state["circuit"])
            self.assertEqual(C.decide(state, sample, 10000)[1], "wait")

    def test_active_and_dpms_off_do_not_reload(self):
        state = ready_state()
        state["managed_generation"] = "A"
        for active in (False, True):
            sample = observation(driver="trigger6", owned_module=True, drm_present=True, scanout_active=active)
            after, action = C.decide(state, sample, 999)
            self.assertEqual(action, "wait")
            self.assertIsNone(after["circuit"])

    def test_rapid_loss_and_reenumeration_trip_without_retry(self):
        state = ready_state()
        state.update(managed_generation="A", last_attempt=100)
        for sample in (observation("B"), {"device": None}):
            after, action = C.decide(state, sample, 107)
            self.assertEqual(action, "wait")
            self.assertIn("rapid", after["circuit"])
            self.assertEqual(C.decide(after, observation("B"), 10000)[1], "wait")

    def test_whole_dock_s4_generation_after_long_gap_is_bounded_recoverable(self):
        state = ready_state()
        state.update(managed_generation="A", last_attempt=100, attempts=[100])
        sample = observation("B", module_present=True, owned_module=True)
        state, action = C.decide(state, sample, 27000)
        self.assertEqual(action, "wait")
        self.assertEqual(C.decide(state, sample, 27015)[1], "start")

    def test_cooldown_hourly_and_boot_budgets(self):
        state = ready_state()
        state.update(last_attempt=0, attempts=[0])
        self.assertEqual(C.decide(state, observation(), 119)[1], "wait")
        self.assertEqual(C.decide(state, observation(), 120)[1], "start")
        state.update(last_attempt=600, attempts=[0, 300, 600])
        self.assertIn("budget", C.decide(state, observation(), 1000)[0]["circuit"])
        state.update(last_attempt=10000, attempts=[0, 2000, 4000, 6000, 8000, 10000])
        self.assertIn("budget", C.decide(state, observation(), 20000)[0]["circuit"])

    def test_inflight_unknown_module_and_binding_are_fail_closed(self):
        state = ready_state()
        state["inflight"] = {"action": "start"}
        self.assertIsNotNone(C.decide(state, observation(), 100)[0]["circuit"])
        for sample in (observation(module_present=True), observation(driver="foreign"),
                       observation(driver="trigger6", owned_module=True)):
            after, action = C.decide(ready_state(), sample, 100)
            self.assertEqual(action, "wait")
            self.assertIsNotNone(after["circuit"])

    def test_sleep_inhibit_and_pause_always_prevent_start(self):
        for paused in (False, True):
            state = ready_state()
            state["paused"] = paused
            self.assertEqual(C.decide(state, observation(inhibited=True), 1000)[1], "wait")
        state["paused"] = True
        self.assertEqual(C.decide(state, observation(), 1000)[1], "wait")

    def test_input_state_not_mutated(self):
        state = ready_state()
        original = copy.deepcopy(state)
        C.decide(state, observation("B"), 100)
        self.assertEqual(state, original)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="t6 state synthetic ")
        self.boundary = Path(self.temporary.name)
        self.store = C.StateStore(self.boundary / "runtime", os.geteuid(), self.boundary)

    def tearDown(self):
        self.temporary.cleanup()

    def test_roundtrip_boot_reset_and_private_modes(self):
        with self.store.lock():
            state = ready_state()
            self.store.write(state)
            self.assertEqual(self.store.read("synthetic-boot"), state)
            self.assertEqual(self.store.read("new-boot"), C.fresh_state("new-boot"))
        self.assertEqual((self.store.directory / "state.json").stat().st_mode & 0o777, 0o600)

    def test_lock_is_nonblocking_and_exclusive(self):
        with self.store.lock():
            with self.assertRaises(C.Refusal):
                with self.store.lock():
                    self.fail("second lock acquired")

    def test_atomic_write_failure_preserves_previous_and_cleans_temporary(self):
        self.store.write(ready_state())
        before = (self.store.directory / "state.json").read_bytes()
        with mock.patch.object(C.os, "replace", side_effect=OSError("synthetic rename failure")):
            with self.assertRaises(OSError):
                self.store.write(C.fresh_state("changed"))
        self.assertEqual((self.store.directory / "state.json").read_bytes(), before)
        self.assertEqual(list(self.store.directory.glob(".state-*")), [])

    def test_symlink_and_writable_state_refused(self):
        self.store.prepare()
        outside = self.boundary / "unrelated"
        outside.write_text("preserve")
        target = self.store.directory / "state.json"
        target.symlink_to(outside)
        with self.assertRaises(C.Refusal):
            self.store.write(ready_state())
        self.assertEqual(outside.read_text(), "preserve")
        target.unlink()
        self.store.write(ready_state())
        target.chmod(0o666)
        with self.assertRaises(C.Refusal):
            self.store.read("synthetic-boot")

    def test_malformed_and_nonfinite_ledger_refused(self):
        for changed in ({"attempts": [float("nan")]}, {"desired": "yes"},
                        {"candidate_since": "15"}, {"attempts": list(range(7))}):
            state = ready_state()
            state.update(changed)
            self.store.prepare()
            target = self.store.directory / "state.json"
            target.write_text(json.dumps(state))
            target.chmod(0o600)
            with self.assertRaises(C.Refusal):
                self.store.read("synthetic-boot")


class AdapterTests(unittest.TestCase):
    def test_checkout_cannot_mutate_even_with_apply(self):
        result = subprocess.run([sys.executable, str(ROOT / "control/controller.py"), "start", "--apply"],
                                capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("root-owned installed helper", result.stderr)

    def test_command_allowlist_refuses_before_spawning(self):
        with mock.patch.object(C.subprocess, "Popen") as spawn:
            with self.assertRaises(C.Refusal):
                C.run_command(["/usr/bin/bash", "-c", "false"])
            spawn.assert_not_called()

    def test_stale_generation_never_unbinds(self):
        host = C.Host()
        host.snapshot = lambda *_: observation(driver="trigger6", module_present=True, owned_module=True)
        host.discover = lambda *_: observation("B")["device"]
        with mock.patch.object(C, "run_command") as run:
            with self.assertRaises(C.Refusal):
                host.stop_module({}, {})
            run.assert_not_called()

    def test_stale_generation_never_inserts(self):
        host = C.Host()
        host.verify_artifact = lambda *_: None
        host.snapshot = lambda *_: observation("B", inhibited=False)
        with mock.patch.object(C, "run_command") as run:
            with self.assertRaises(C.Refusal):
                host.start_module({}, {}, "A")
            run.assert_not_called()

    def test_unreviewed_compositor_refuses_before_module_mutation(self):
        host = C.Host()
        host.verify_artifact = lambda *_: None
        host.snapshot = lambda *_: observation(inhibited=False)
        with mock.patch.object(C, "run_command", return_value="hyprland new-version") as run:
            with self.assertRaisesRegex(C.Refusal, "unreviewed compositor"):
                host.start_module({}, {}, "A")
            run.assert_called_once_with(["/usr/bin/pacman", "-Q", "hyprland", "aquamarine"])

    def test_failed_start_consumes_attempt_and_cleanup_does_not_retry(self):
        class FakeHost:
            def __init__(self):
                self.calls = []

            def snapshot(self, *_):
                return observation()

            def now(self):
                return 100

            def start_module(self, *_):
                self.calls.append("start")
                raise C.Refusal("synthetic short transfer")

            def stop_module(self, *_):
                self.calls.append("stop")

        host = FakeHost()
        store = mock.Mock()
        state = C.tick(host, store, ready_state(), {}, {})
        self.assertEqual(host.calls, ["start", "stop"])
        self.assertEqual(state["attempts"], [100])
        self.assertIsNotNone(state["circuit"])
        C.tick(host, store, state, {}, {})
        self.assertEqual(host.calls, ["start", "stop"])

    def test_failed_cleanup_preserves_inflight_for_manual_recovery(self):
        host = mock.Mock()
        host.snapshot.return_value = observation()
        host.now.return_value = 100
        host.start_module.side_effect = C.Refusal("start failed")
        host.stop_module.side_effect = C.Refusal("still referenced")
        state = C.tick(host, mock.Mock(), ready_state(), {}, {})
        self.assertIsNotNone(state["inflight"])
        self.assertIsNotNone(state["circuit"])
        self.assertEqual(state["attempts"], [100])
        self.assertEqual(state["inflight"]["cleanup_error"], "still referenced")
        self.assertIn("start failed; cleanup failed: still referenced", state["circuit"])
        following = C.tick(host, mock.Mock(), state, {}, {})
        self.assertEqual(following["circuit"], state["circuit"])
        host.start_module.assert_called_once()
        host.stop_module.assert_called_once()

    def test_failed_fault_stop_is_never_attempted_twice(self):
        host = mock.Mock()
        host.snapshot.return_value = observation(driver="trigger6", owned_module=True,
                                                 drm_present=True, fault=True)
        host.now.return_value = 100
        host.stop_module.side_effect = C.Refusal("synthetic unbind timeout")
        state = ready_state()
        state["managed_generation"] = "A"
        state = C.tick(host, mock.Mock(), state, {}, {})
        self.assertIsNotNone(state["inflight"])
        self.assertIsNotNone(state["circuit"])
        C.tick(host, mock.Mock(), state, {}, {})
        host.stop_module.assert_called_once()
        host.start_module.assert_not_called()


class MetricsTests(unittest.TestCase):
    SAMPLE = ("trigger6 bus=002 dev=106 interface=2-1.4.1:1.0 manual_only=0 io_faulted=0 io_last_error=0\n"
              "device bulk_calls=4 bulk_chunks=4 bulk_bytes=123456 bulk_errors=0 bulk_short_writes=0 tx_work_runs=4\n"
              "head0 transport=raw connected=1 io_faulted=0 status=1 pending=0 width=1920 height=1080 frame_seq=2 scanout_active=1 raw_idle_refresh=1\n"
              "head0 queue_attempts=4 queued_frames=4 transport_faults=0 jpeg_quality=80\n"
              "head0 sent_frames=4 sent_bytes=123456 send_errors=0 keepalive_sent=2 keepalive_errors=0 last_payload_bytes=8294448\n")

    def test_current_schema_counters_and_dpms_parse(self):
        result = C.metrics_summary(self.SAMPLE)
        self.assertFalse(result["fault"])
        self.assertTrue(result["scanout_active"])
        self.assertEqual((result["sent_frames"], result["keepalive_sent"], result["bulk_bytes"]), (4, 2, 123456))
        off = C.metrics_summary(self.SAMPLE.replace("scanout_active=1", "scanout_active=0"))
        self.assertFalse(off["scanout_active"])
        self.assertFalse(off["fault"])

    def test_missing_schema_and_each_fault_refuse_health(self):
        for broken in (None, "", "trigger6=disconnected", self.SAMPLE.replace("io_last_error=0", "")):
            self.assertTrue(C.metrics_summary(broken)["fault"])
        for key in ("io_faulted", "io_last_error", "send_errors", "transport_faults", "bulk_errors",
                    "bulk_short_writes", "keepalive_errors"):
            self.assertTrue(C.metrics_summary(self.SAMPLE.replace(key + "=0", key + "=1"))["fault"])


class StopSettlingTests(unittest.TestCase):
    """Exercise production stop sequencing with a synthetic module and clock."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="t6 stop synthetic ")
        self.host = C.Host()
        self.host.root = Path(self.temporary.name)
        self.module = self.host.path("/sys/module/trigger6")
        self.module.mkdir(parents=True)
        self.sample = observation(driver="trigger6", module_present=True, owned_module=True,
                                  module_path="2-1.4.1")
        self.current = copy.deepcopy(self.sample["device"])
        self.host.snapshot = mock.Mock(side_effect=lambda *_: copy.deepcopy(self.sample))
        self.host.discover = mock.Mock(side_effect=lambda *_: copy.deepcopy(self.current))
        self.host.resident_identity = mock.Mock(return_value=(True, True, "2-1.4.1"))
        self.stamp = 10.0
        self.references = ["0"]
        self.sleeps = []
        self.calls = []
        self.on_sleep = lambda: None
        self.unbind_cost = 0
        self.fail_phase = None

        def sleep(delay):
            self.sleeps.append(delay)
            self.stamp += delay
            self.on_sleep()

        def read(path, *_):
            self.assertEqual(path, self.module / "refcnt")
            return self.references.pop(0) if len(self.references) > 1 else self.references[0]

        def run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            phase = Path(argv[0]).name
            if self.fail_phase == phase:
                raise C.Refusal(f"{phase} synthetic exact error")
            if phase == "tee":
                self.current["driver"] = None
                self.stamp += self.unbind_cost
            elif phase == "rmmod":
                self.module.rmdir()
            else:
                self.fail("unexpected mutating command")
            return ""

        self.stack = contextlib.ExitStack()
        self.stack.enter_context(mock.patch.object(C.time, "monotonic", lambda: self.stamp))
        self.stack.enter_context(mock.patch.object(C.time, "sleep", sleep))
        self.stack.enter_context(mock.patch.object(C, "text_file", read))
        self.stack.enter_context(mock.patch.object(C, "run_command", run))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def executables(self):
        return [Path(argv[0]).name for argv, _ in self.calls]

    def test_hyprland_references_settle_then_one_ordinary_removal(self):
        self.references = ["2", "1", "0", "0"]
        self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee", "rmmod"])
        self.assertEqual(len(self.sleeps), 2)
        self.assertEqual(self.calls[0][0][1], "/sys/bus/usb/drivers/trigger6/unbind")
        self.assertEqual(self.calls[0][1]["input_text"], "2-1.4.1:1.0\n")
        self.assertEqual(self.calls[1][0], ["/usr/bin/rmmod", "trigger6"])
        self.assertLessEqual(sum(self.sleeps), C.REFCOUNT_SETTLE_SECONDS)

    def test_zero_references_do_not_sleep(self):
        self.host.stop_module({}, {})
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.executables(), ["tee", "rmmod"])

    def test_busy_references_exhaust_half_second_without_removal_or_retry(self):
        self.references = ["1"]
        with self.assertRaisesRegex(C.Refusal, "refcnt=1"):
            self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee"])
        self.assertAlmostEqual(sum(self.sleeps), C.REFCOUNT_SETTLE_SECONDS)
        self.assertLessEqual(max(self.sleeps), C.REFCOUNT_POLL_SECONDS)

    def test_missing_or_malformed_refcount_refuses_without_waiting(self):
        for value in (None, "bad", "-1", "", "01", "١", "9" * 10):
            with self.subTest(value=value):
                self.current["driver"] = "trigger6"
                self.references = [value]
                self.calls.clear()
                with self.assertRaisesRegex(C.Refusal, "refcount unavailable/malformed"):
                    self.host.stop_module({}, {})
                self.assertEqual(self.executables(), ["tee"])
                self.assertEqual(self.sleeps, [])

    def test_failed_unbind_preserves_exact_phase_and_never_settles_or_retries(self):
        self.fail_phase = "tee"
        with self.assertRaisesRegex(C.Refusal, "exact-interface unbind failed: tee synthetic exact error"):
            self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee"])
        self.assertEqual(self.sleeps, [])

    def test_failed_rmmod_reports_exact_phase_without_second_attempt(self):
        self.fail_phase = "rmmod"
        with self.assertRaisesRegex(C.Refusal, "ordinary module removal failed: rmmod synthetic exact error"):
            self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee", "rmmod"])

    def test_changed_generation_during_settle_cancels_removal(self):
        self.references = ["1", "0", "0"]
        self.on_sleep = lambda: self.current.update(generation="replacement")
        with self.assertRaisesRegex(C.Refusal, "generation changed during stop"):
            self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee"])

    def test_rebound_interface_during_settle_cancels_removal(self):
        self.references = ["1", "0", "0"]
        self.on_sleep = lambda: self.current.update(driver="foreign")
        with self.assertRaisesRegex(C.Refusal, "interface rebound"):
            self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee"])

    def test_changed_resident_identity_during_settle_cancels_removal(self):
        self.host.resident_identity.return_value = (True, False, "2-1.4.1")
        with self.assertRaisesRegex(C.Refusal, "resident identity changed"):
            self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee"])

    def test_new_reference_after_zero_never_retries(self):
        self.references = ["0", "1"]
        with self.assertRaisesRegex(C.Refusal, "acquired a new reference"):
            self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee"])

    def test_elapsed_snapshot_budget_refuses_before_unbind(self):
        def snapshot(*_):
            self.stamp += C.STOP_SECONDS
            return copy.deepcopy(self.sample)
        self.host.snapshot.side_effect = snapshot
        with self.assertRaisesRegex(C.Refusal, "stop deadline exhausted before unbind"):
            self.host.stop_module({}, {})
        self.assertEqual(self.calls, [])

    def test_removal_timeout_uses_remaining_shared_budget(self):
        self.unbind_cost = 1.4
        self.references = ["1"] * 20 + ["0", "0"]
        self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee", "rmmod"])
        self.assertAlmostEqual(self.calls[1][1]["timeout"], C.STOP_SECONDS - 1.4 - sum(self.sleeps))
        self.assertLess(self.calls[1][1]["timeout"], 1.5)

    def test_reference_release_after_stop_deadline_never_removes(self):
        self.references = ["1", "0", "0"]
        self.on_sleep = lambda: setattr(self, "stamp", self.stamp + C.STOP_SECONDS)
        with self.assertRaisesRegex(C.Refusal, "deadline exhausted before ordinary removal"):
            self.host.stop_module({}, {})
        self.assertEqual(self.executables(), ["tee"])

    def test_already_absent_module_is_noop(self):
        self.sample["module_present"] = False
        self.host.stop_module({}, {})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.sleeps, [])


class DiagnosticTests(unittest.TestCase):
    def test_failed_command_preserves_bounded_escaped_output_and_exit(self):
        def spawn(_argv, **kwargs):
            kwargs["stdout"].write(b"rmmod: module busy\n\x1b[31m" + b"x" * 4096)
            return mock.Mock(returncode=1)
        with mock.patch.object(C.subprocess, "Popen", spawn):
            with self.assertRaises(C.Refusal) as caught:
                C.run_command(["/usr/bin/rmmod", "trigger6"])
        message = str(caught.exception)
        self.assertIn("rmmod exit 1", message)
        self.assertIn("rmmod: module busy", message)
        self.assertIn("[output truncated]", message)
        self.assertNotIn("\x1b", message)
        self.assertLess(len(message), 2300)

    def test_timeout_identifies_command_and_deadline(self):
        process = mock.Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired("tee", 0.25)
        with mock.patch.object(C.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(C.Refusal, "tee timed out after 0.250s"):
                C.run_command(["/usr/bin/tee", "/sys/bus/usb/drivers/trigger6/unbind"], timeout=0.25)
        process.kill.assert_called_once()

    def test_private_ledger_is_unknown_not_fabricated_stopped(self):
        host, store = mock.Mock(), mock.Mock()
        host.snapshot.return_value = observation(driver="trigger6", inhibited=None)
        store.read.side_effect = PermissionError("private root ledger")
        report = C.status_report(host, store, {}, {})
        self.assertIsNone(report["state"])
        self.assertFalse(report["ledger_available"])
        self.assertEqual(report["next_action"], "unknown")
        self.assertIn("authenticate", report["reason"])
        self.assertEqual(report["observation"]["device"]["driver"], "trigger6")

    def test_permission_error_is_not_absence_for_state_or_inhibit(self):
        with mock.patch.object(C.Path, "lstat", side_effect=PermissionError("synthetic denied")):
            with self.assertRaises(PermissionError):
                C.StateStore(Path("/synthetic-root-runtime")).read("boot")
            self.assertIsNone(C.path_present(Path("/synthetic-root-runtime/sleep-inhibit")))
        with mock.patch.object(C.Path, "lstat", side_effect=FileNotFoundError):
            self.assertEqual(C.StateStore(Path("/synthetic-missing-runtime")).read("boot"), C.fresh_state("boot"))
            self.assertFalse(C.path_present(Path("/synthetic-missing-runtime/sleep-inhibit")))

    def test_unknown_inhibition_refuses_start(self):
        state, action = C.decide(ready_state(), observation(inhibited=None), 999)
        self.assertEqual(action, "wait")
        self.assertIn("inhibition state unavailable", state["circuit"])

    def test_root_canonical_status_preserves_real_circuit(self):
        host, store = mock.Mock(), mock.Mock()
        host.snapshot.return_value = observation()
        host.now.return_value = 999
        state = ready_state()
        state.update(circuit="pause failed: exact refusal", inflight={"action": "sleep-stop"})
        store.read.return_value = state
        report = C.status_report(host, store, {}, {})
        self.assertTrue(report["ledger_available"])
        self.assertEqual(report["state"], state)
        self.assertEqual(report["reason"], state["circuit"])
        self.assertEqual(report["next_action"], "wait")


class DiscoveryTests(unittest.TestCase):
    DESCRIPTORS = bytes.fromhex(
        "12012003ff00000911070156101001020001"
        "09023900010100801f0904000003ff000000"
        "07058102000400063001000000"
        "07050202000400063001000000"
        "07058303400005063000000000")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="t6 sysfs synthetic ")
        self.host = C.Host()
        self.host.root = Path(self.temporary.name)
        self.device = self.add_device("2-1.4.1")

    def tearDown(self):
        self.temporary.cleanup()

    def add_device(self, name):
        path = self.host.path("/sys/bus/usb/devices") / name
        path.mkdir(parents=True)
        for key, value in {"idVendor": "0711", "idProduct": "5601", "bcdDevice": "1010",
                           "speed": "5000", "bConfigurationValue": "1", "devnum": "106"}.items():
            (path / key).write_text(value)
        (path / "descriptors").write_bytes(self.DESCRIPTORS)
        interface = path.parent / (name + ":1.0")
        interface.mkdir()
        (interface / "bAlternateSetting").write_text(" 0\n")
        return path

    def properties(self, *_args, **_kwargs):
        return "ID_PATH=pci-test-usb-0:1.4.1\nUSEC_INITIALIZED=123456\n"

    def test_observed_descriptor_fixture_and_exact_discovery(self):
        self.assertEqual(C.hashlib.sha256(self.DESCRIPTORS).hexdigest(), C.DESCRIPTOR_SHA)
        with mock.patch.object(C, "run_command", self.properties):
            result = self.host.discover({"id_path": "pci-test-usb-0:1.4.1"})
        self.assertEqual(result["devnum"], 106)
        self.assertIsNone(result["driver"])

    def test_stop_discovery_uses_shared_remaining_deadline(self):
        with mock.patch.object(C.time, "monotonic", return_value=10):
            with mock.patch.object(C, "run_command", return_value=self.properties()) as run:
                self.host.discover({}, deadline=10.25)
                self.assertEqual(run.call_args.kwargs["timeout"], 0.25)
            with mock.patch.object(C, "run_command") as run:
                with self.assertRaisesRegex(C.Refusal, "deadline exhausted before cached USB discovery"):
                    self.host.discover({}, deadline=10)
                run.assert_not_called()

    def test_descriptor_mutation_and_extra_candidate_refused(self):
        with mock.patch.object(C, "run_command", self.properties):
            (self.device / "descriptors").write_bytes(self.DESCRIPTORS[:-1])
            with self.assertRaises(C.Refusal):
                self.host.discover({})
            (self.device / "descriptors").write_bytes(self.DESCRIPTORS)
            self.add_device("2-1.4.2")
            with self.assertRaises(C.Refusal):
                self.host.discover({})

    def test_port_policy_and_missing_id_path_refused(self):
        with mock.patch.object(C, "run_command", self.properties):
            with self.assertRaises(C.Refusal):
                self.host.discover({"id_path": "another-port"})
        with mock.patch.object(C, "run_command", return_value="ID_VENDOR=MCT"):
            with self.assertRaises(C.Refusal):
                self.host.discover({})

    def test_devnum_and_initialization_epoch_change_generation(self):
        with mock.patch.object(C, "run_command", self.properties):
            first = self.host.discover({})["generation"]
            (self.device / "devnum").write_text("107")
            second = self.host.discover({})["generation"]
        with mock.patch.object(C, "run_command", return_value=self.properties() + "USEC_INITIALIZED=999999\n"):
            third = self.host.discover({})["generation"]
        self.assertEqual(len({first, second, third}), 3)

    def test_detach_before_descriptor_read_returns_absent(self):
        (self.device / "descriptors").unlink()
        with mock.patch.object(C, "run_command") as command:
            self.assertIsNone(self.host.discover({}))
            command.assert_not_called()

    def test_partial_enumeration_and_udev_wait_without_authorizing(self):
        interface = self.device.parent / (self.device.name + ":1.0")
        (interface / "bAlternateSetting").unlink()
        interface.rmdir()
        with self.assertRaises(C.NotReady):
            self.host.discover({})
        interface.mkdir()
        (interface / "bAlternateSetting").write_text("0")
        with mock.patch.object(C, "run_command", return_value="ID_PATH=pci-test"):
            with self.assertRaises(C.NotReady):
                self.host.discover({})
        state = ready_state()
        state, action = C.decide(state, {"device": None, "pending": "waiting for udev"}, 100)
        self.assertEqual(action, "wait")
        self.assertIsNone(state["circuit"])
        self.assertIsNone(state["candidate"])
        self.assertEqual(state["reason"], "waiting for udev")


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="t6 artifact synthetic ")
        self.host = C.Host()
        self.host.root = Path(self.temporary.name)
        self.host.release = "7.1.9-arch1-2"
        self.name = "/usr/lib/modules/7.1.9-arch1-2/updates/dkms/trigger6.ko.zst"
        self.path = self.host.path(self.name)
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"synthetic module, never executable")
        self.entry = {"path": self.name, "sha256": C.hashlib.sha256(self.path.read_bytes()).hexdigest(),
                      "srcversion": "F6D5C7316849C7428A83002", "vermagic": self.host.release + " SMP preempt mod_unload"}
        self.values = {"name": "trigger6", "srcversion": self.entry["srcversion"],
                       "vermagic": self.entry["vermagic"], "alias": C.USB_ALIAS, "depends": ""}
        original_protected = C.protected
        self.guard = mock.patch.object(C, "protected", lambda path, **kwargs:
                                       original_protected(path, os.geteuid(), boundary=self.host.root, **kwargs))
        self.guard.start()

    def tearDown(self):
        self.guard.stop()
        self.temporary.cleanup()

    def metadata(self, argv, **_kwargs):
        self.assertEqual(argv[:2], ["/usr/bin/modinfo", "-F"])
        return self.values[argv[2]]

    def test_exact_current_kernel_artifact_metadata_passes(self):
        with mock.patch.object(C, "run_command", self.metadata):
            self.host.verify_artifact(self.entry)

    def test_hash_path_symlink_and_writable_artifacts_refuse(self):
        for update in ({"sha256": "0" * 64}, {"path": "/tmp/trigger6.ko"},
                       {"path": self.name.replace("/updates/", "/../updates/")}):
            with mock.patch.object(C, "run_command") as run:
                with self.assertRaises(C.Refusal):
                    self.host.verify_artifact(dict(self.entry, **update))
                run.assert_not_called()
        self.path.chmod(0o666)
        with self.assertRaises(C.Refusal):
            self.host.verify_artifact(self.entry)
        self.path.unlink()
        self.path.symlink_to(self.host.root / "unrelated")
        with self.assertRaises(C.Refusal):
            self.host.verify_artifact(self.entry)

    def test_alias_dependency_name_srcversion_and_vermagic_changes_refuse(self):
        for field in self.values:
            before = self.values[field]
            self.values[field] = "unreviewed value"
            with mock.patch.object(C, "run_command", self.metadata):
                with self.assertRaises(C.Refusal):
                    self.host.verify_artifact(self.entry)
            self.values[field] = before

    def test_new_kernel_requires_new_explicit_approval(self):
        path = self.host.path(C.CONFIG)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema": 1, "id_path": None, "kernels": {self.host.release: self.entry}}))
        self.assertEqual(self.host.read_config()[1], self.entry)
        self.host.release = "7.2.0-unreviewed"
        with self.assertRaisesRegex(C.Refusal, "no approved artifact"):
            self.host.read_config()


class SleepTests(unittest.TestCase):
    setUp = StoreTests.setUp
    tearDown = StoreTests.tearDown

    def make_inhibit(self):
        self.store.prepare()
        inhibit = self.store.directory / "sleep-inhibit"
        inhibit.touch(mode=0o600)
        return inhibit

    def test_successful_pre_quiesces_then_post_only_rearms_observation(self):
        inhibit = self.make_inhibit()
        host = mock.Mock()
        state = ready_state()
        state.update(managed_generation="A", attempts=[100], last_attempt=100)

        def verify_pending(*_args):
            saved = self.store.read("synthetic-boot")
            self.assertTrue(saved["paused"])
            self.assertIsNotNone(saved["inflight"])
            self.assertTrue(inhibit.exists())

        host.stop_module.side_effect = verify_pending
        with self.store.lock():
            state = C.operate("pause", host, self.store, state, {}, {})
        self.assertTrue(state["paused"])
        self.assertIsNone(state["managed_generation"])
        with self.store.lock():
            state = C.operate("resume", host, self.store, state, {}, {})
        self.assertFalse(inhibit.exists())
        self.assertFalse(state["paused"])
        self.assertEqual(state["attempts"], [100])
        host.stop_module.assert_called_once()
        host.start_module.assert_not_called()

    def test_failed_pre_preserves_inhibit_and_post_refuses(self):
        inhibit = self.make_inhibit()
        host = mock.Mock()
        host.stop_module.side_effect = C.Refusal("synthetic stop timeout")
        with self.store.lock():
            with self.assertRaises(C.Refusal):
                C.operate("pause", host, self.store, ready_state(), {}, {})
        saved = self.store.read("synthetic-boot")
        self.assertTrue(saved["paused"])
        self.assertIsNotNone(saved["inflight"])
        self.assertEqual(saved["circuit"], "pause failed: synthetic stop timeout")
        self.assertEqual(saved["inflight"]["error"], "synthetic stop timeout")
        host.snapshot.return_value = observation(inhibited=True)
        host.now.return_value = 100
        after = C.tick(host, self.store, saved, {}, {})
        self.assertEqual(after["circuit"], saved["circuit"])
        host.stop_module.assert_called_once()
        with self.store.lock():
            with self.assertRaises(C.Refusal):
                C.operate("resume", host, self.store, saved, {}, {})
        self.assertTrue(inhibit.exists())
        host.start_module.assert_not_called()

    def test_explicit_stop_preserves_exact_error_and_stopped_intent(self):
        host = mock.Mock()
        host.stop_module.side_effect = C.Refusal("module still referenced (refcnt=1)")
        with self.store.lock():
            with self.assertRaisesRegex(C.Refusal, "stop failed: module still referenced"):
                C.operate("stop", host, self.store, ready_state(), {}, {})
        saved = self.store.read("synthetic-boot")
        self.assertFalse(saved["desired"])
        self.assertEqual(saved["circuit"], "stop failed: module still referenced (refcnt=1)")
        self.assertEqual(saved["inflight"]["action"], "stop")
        self.assertEqual(saved["inflight"]["error"], "module still referenced (refcnt=1)")

    def test_pre_lock_failure_keeps_marker_and_post_refuses(self):
        inhibit = self.make_inhibit()
        state = ready_state()
        self.store.write(state)
        with self.store.lock():
            with self.assertRaises(C.Refusal):
                with self.store.lock():
                    self.fail("busy pre must not acquire")
        with self.store.lock():
            with self.assertRaises(C.Refusal):
                C.operate("resume", mock.Mock(), self.store, state, {}, {})
        self.assertTrue(inhibit.exists())

    def test_disabled_intent_does_not_stop_an_existing_manual_module(self):
        inhibit = self.make_inhibit()
        host = mock.Mock()
        C.operate("pause", host, self.store, C.fresh_state("synthetic-boot"), {}, {})
        self.assertFalse(inhibit.exists())
        host.stop_module.assert_not_called()

    def test_hook_is_bounded_and_service_keeps_capability_boundary(self):
        hook = (ROOT / "packaging/jcd543-trigger6-sleep").read_text()
        self.assertIn("--kill-after=1s 3s", hook)
        self.assertIn('"$sleep_action" --apply', hook)
        self.assertNotIn("hyprctl", hook)
        unit = (ROOT / "packaging/jcd543-trigger6.service").read_text()
        self.assertIn("CapabilityBoundingSet=CAP_SYS_MODULE", unit)
        self.assertIn("Restart=no", unit)
        self.assertIn("RuntimeDirectoryPreserve=yes", unit)
        self.assertIn("NoNewPrivileges=yes", unit)
        self.assertNotIn("ExecStartPost=", unit)
        source = (ROOT / "control/controller.py").read_text().split("def main():", 1)[1]
        self.assertLess(source.index("os.open(inhibit"), source.index("host.read_config()"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
