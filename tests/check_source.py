#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Regression checks for the no-load development boundary; not a C compiler."""

import ast
import importlib.util
import io
from pathlib import Path
import re
import subprocess
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SourceBoundaryTests(unittest.TestCase):
    def test_inert_probe_precedes_allocation_and_usb_queries(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        probe = source.split("static int t6_usb_probe(", 1)[1].split("static void t6_usb_disconnect", 1)[0]
        self.assertLess(probe.index("t6_match_interface"), probe.index("if (t6_manual_only)"))
        self.assertLess(probe.index("strcmp(t6_device_path"), probe.index("if (t6_manual_only)"))
        manual = probe.split("if (t6_manual_only)", 1)[1].split("\n\t}", 1)[0]
        self.assertIn("return 0;", manual)
        for forbidden in ("t6_ctrl_", "t6_bulk_", "drm_dev_register", "alloc_workqueue"):
            self.assertNotIn(forbidden, manual)
        self.assertLess(probe.index("if (t6_manual_only)"), probe.index("devm_drm_dev_alloc"))
        self.assertLess(probe.index("t6_output_mask_valid"), probe.index("devm_drm_dev_alloc"))
        self.assertIn("static bool t6_manual_only = true;", source)
        self.assertIn('static char *t6_device_path = "";', source)

    def test_no_reset_retry_or_writable_control_surface(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        for forbidden in ("usb_queue_reset_device", "usb_reset_device", "t6_schedule_reprobe",
                          "DEVICE_ATTR_WO", "DEVICE_ATTR_RW", "0644"):
            self.assertNotIn(forbidden, source)
        self.assertIn("USB_DEVICE_AND_INTERFACE_INFO(T6_VID, T6_PID, 0xff, 0, 0)", source)
        self.assertNotRegex(source, r"\bUSB_DEVICE\(")
        error_cleanup = source.split("err_buffers:", 1)[1].split("err_put:", 1)[0]
        for forbidden in ("drm_encoder_cleanup(", "drm_crtc_cleanup(", "drm_plane_cleanup("):
            self.assertNotIn(forbidden, error_cleanup)

    def test_io_failures_latch_and_do_not_clear(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        self.assertNotIn("WRITE_ONCE(t6->io_faulted, false)", source)
        self.assertGreaterEqual(source.count("t6_latch_io_error(t6,"), 4)
        self.assertIn("head->edid_data[126] = 0;", source)
        self.assertIn("memcmp(edid, header, sizeof(header))", source)

    def test_fixed_mode_and_no_installer(self):
        connector = (ROOT / "kernel/trigger6_connector.c").read_text()
        self.assertIn("drm_mode_equal(mode, &t6_1080p_mode)", connector)
        self.assertNotIn("drm_cvt_mode(", connector)
        for path in (ROOT / "Makefile", ROOT / "kernel/Makefile", *ROOT.glob("tools/*")):
            if path.is_file():
                text = path.read_text()
                self.assertNotRegex(text, r"(?m)^\s*(?:sudo|pkexec|insmod|modprobe|rmmod|depmod|dkms)\s")
        for name in ("install.sh", "dkms.conf", "99-trigger6.rules", "trigger6.conf"):
            self.assertFalse((ROOT / name).exists())

    def test_aquamarine_name_shim_is_opt_in_and_generic(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        self.assertIn("static bool t6_aquamarine_evdi_name;", source)
        self.assertIn("t6_aquamarine_evdi_name, bool, 0444", source)
        self.assertIn("t6_aquamarine_evdi_name && t6_output_mask != 1", source)
        probe = source.split("static int t6_usb_probe(", 1)[1]
        self.assertLess(probe.index("if (t6_manual_only)"),
                        probe.index("&t6_aquamarine_drm_driver"))
        shim = source.split("static const struct drm_driver t6_aquamarine_drm_driver", 1)[1].split("};", 1)[0]
        self.assertIn('.name = "evdi"', shim)
        self.assertIn(".fops = &t6_fops", shim)
        self.assertIn("DRM_GEM_SHMEM_DRIVER_OPS", shim)
        self.assertNotIn(".ioctls", source)
        usb = source.split("static struct usb_driver t6_usb_driver", 1)[1]
        self.assertIn(".name = DRIVER_NAME", usb)
        self.assertIn('#define DRIVER_NAME\t"trigger6"', source)

    def test_vt_wrapper_is_explicit_bounded_and_inert_by_default(self):
        path = ROOT / "tools/vt_pattern_test.sh"
        source = path.read_text()
        self.assertIn("--run-reviewed-vt3-pattern", source)
        self.assertIn("$EUID != 0", source)
        self.assertIn("trap restore_vt EXIT", source)
        self.assertIn("/usr/bin/chvt 2", source)
        self.assertIn("--kill-after=2s 12s", source)
        self.assertIn("/sys/class/drm/card0/device/driver", source)
        self.assertIn("/sys/module/trigger6/srcversion", source)
        self.assertNotIn("-D /dev/dri/card0", source)
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
        result = subprocess.run(["bash", str(path)], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Inert:", result.stderr)

    def test_reload_wrapper_is_exact_explicit_and_inert_by_default(self):
        path = ROOT / "tools/reload_name_shim.sh"
        source = path.read_text()
        self.assertIn("--run-reviewed-head0-shim", source)
        self.assertIn("$EUID != 0", source)
        self.assertIn("/sys/bus/usb/drivers/trigger6/unbind", source)
        self.assertIn("[[ ! -e /sys/class/drm/card0 ]]", source)
        self.assertIn("[[ ! -d /sys/module/trigger6 ]]", source)
        self.assertIn("initial_taint", source)
        self.assertIn("sha256sum", source)
        self.assertNotIn("rmmod -f", source)
        self.assertNotIn("modprobe", source)
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
        result = subprocess.run(["bash", str(path)], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Inert:", result.stderr)

    def test_python_syntax(self):
        for path in (*ROOT.glob("tools/*.py"), *ROOT.glob("tests/*.py")):
            ast.parse(path.read_text(), filename=str(path))

    def test_reviewed_wrappers_resolve_their_checkout_with_quoted_paths(self):
        wrappers = [path for path in ROOT.glob("tools/*.sh")
                    if "readonly script_path repo_root" in path.read_text()]
        self.assertEqual(len(wrappers), 7)
        for path in wrappers:
            source = path.read_text()
            self.assertLess(source.index("exit 2"), source.index("script_path="))
            self.assertIn('realpath -e -- "${BASH_SOURCE[0]}"', source)
            self.assertIn('"${repo_root}/kernel/trigger6.ko"', source)
            self.assertRegex(source, r'== "[0-9a-f]{64}  \$\{repo_root\}/kernel/trigger6\.ko"')
            self.assertNotRegex(source, r"/home/[^\s/]+/")
            for line in source.splitlines():
                if "/usr/bin/insmod " in line:
                    self.assertIn('/usr/bin/insmod "${repo_root}/', line)
            # Execute only the pure path-resolution prologue, never hardware code.
            prologue = source.split("script_path=", 1)[1].split("readonly script_path repo_root", 1)[0]
            with tempfile.TemporaryDirectory(prefix="t6 quoted checkout ") as temporary:
                checkout = Path(temporary)
                (checkout / "tools").mkdir()
                (checkout / "Makefile").touch()
                (checkout / "LICENSE").touch()
                fixture = checkout / "tools" / path.name
                fixture.write_text("set -eu\nscript_path=" + prologue +
                                   'readonly script_path repo_root\nprintf "%s\\n" "$repo_root"\n')
                result = subprocess.run(["/usr/bin/bash", str(fixture)], cwd="/tmp",
                                        capture_output=True, text=True, check=True,
                                        timeout=5, env={"PATH": "/usr/bin", "repo_root": "/untrusted"})
                self.assertEqual(result.stdout.strip(), str(checkout))

    def test_port_move_wrapper_requires_fresh_review_and_exact_identity(self):
        path = ROOT / "tools/reload_after_port_move.sh"
        source = path.read_text()
        for required in ("--run-reviewed-port-move", "$EUID != 0",
                         "/sys/module/trigger6/refcnt", "/sys/module/trigger6/srcversion",
                         "/sys/bus/usb/devices/2-1.4.1/descriptors",
                         "sha256sum", "--kill-after=2s 12s", "check_new_device"):
            self.assertIn(required, source)
        for forbidden in ("/unbind", "new_id", "driver_override", "rmmod -f", "modprobe"):
            self.assertNotIn(forbidden, source)
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
        result = subprocess.run(["bash", str(path)], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Inert:", result.stderr)

    def test_one_active_probe_per_insertion_latches_before_io(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        probe = source.split("static int t6_usb_probe(", 1)[1].split("static void t6_usb_disconnect", 1)[0]
        self.assertIn("static atomic_t t6_active_probe_used = ATOMIC_INIT(0);", source)
        guard = "atomic_cmpxchg(&t6_active_probe_used, 0, 1)"
        self.assertEqual(source.count(guard), 1)
        self.assertEqual(source.count("t6_active_probe_used"), 2)
        self.assertLess(probe.index("if (t6_manual_only)"), probe.index(guard))
        self.assertLess(probe.index("t6_output_mask_valid"), probe.index(guard))
        self.assertLess(probe.index(guard), probe.index("devm_drm_dev_alloc"))
        self.assertIn("refusing automatic re-enumeration", probe)

    def test_loop_cleanup_only_attempts_normal_removal_at_zero_refs(self):
        path = ROOT / "tools/stop_disconnect_loop.sh"
        source = path.read_text()
        for required in ("--run-reviewed-stop-loop", "$EUID != 0",
                         "/sys/module/trigger6/refcnt", "{1..150}",
                         "--kill-after=2s 8s /usr/bin/rmmod trigger6"):
            self.assertIn(required, source)
        for forbidden in ("/unbind", "insmod", "modprobe", "rmmod -f", "driver_override"):
            self.assertNotIn(forbidden, source)
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
        result = subprocess.run(["bash", str(path)], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Inert:", result.stderr)

    def test_raw_refresh_is_opt_in_active_only_and_uses_normal_frame_path(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        self.assertIn("static bool t6_raw_idle_refresh;", source)
        self.assertIn("t6_raw_idle_refresh, bool, 0444", source)
        self.assertIn("t6_raw_idle_refresh && t6_output_mask != 1", source)
        self.assertIn("#define T6_RAW_IDLE_REFRESH_MS\t1000", source)
        gate = source.split("static bool t6_raw_refresh_eligible", 1)[1].split("static void t6_head_defaults", 1)[0]
        for required in ("t6_raw_refresh_allowed", "t6->manual_only", "scanout_active",
                         "last_sent_valid", "t6->io_faulted", "head->io_faulted"):
            self.assertIn(required, gate)
        work = source.split("static void t6_frame_work(struct work_struct *work)\n{", 1)[1].split("static void t6_crtc_atomic_enable", 1)[0]
        self.assertIn("t6_send_frame_raw(t6, head, head->last_sent_frame", work)
        self.assertIn("time_before(jiffies, deadline)", work)
        self.assertNotIn("t6_ctrl_out", work)
        disable = source.split("static void t6_crtc_atomic_disable", 1)[1].split("static void t6_crtc_atomic_flush", 1)[0]
        self.assertLess(disable.index("scanout_active, false"), disable.index("cancel_work_sync"))
        self.assertLess(disable.index("last_sent_valid, false"), disable.index("t6_ctrl_out"))
        self.assertEqual(disable.count("timer_delete_sync(&head->keepalive_timer)"), 2)
        raw = source.split("static int t6_send_frame_raw", 1)[1].split("static int t6_send_jpeg_blob", 1)[0]
        self.assertIn("pixels != head->last_sent_frame", raw)
        self.assertIn("raw_last_sent_jiffies", raw)

    def test_final_off_is_default_off_head0_and_shared_with_host_matrix(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        self.assertIn("static bool t6_final_monitor_off;", source)
        self.assertIn("t6_final_monitor_off, bool, 0444", source)
        probe = source.split("static int t6_usb_probe(", 1)[1].split("static const char *t6_final_off_policy", 1)[0]
        gate = "t6_final_monitor_off && (t6_query_only || t6_output_mask != 1)"
        self.assertLess(probe.index("if (t6_manual_only)"), probe.index(gate))
        self.assertLess(probe.index(gate), probe.index("atomic_cmpxchg"))
        policy = source.split("static const char *t6_final_off_policy", 1)[1].split("static void t6_final_off_disconnect", 1)[0]
        for required in ("t6_final_off_skip", "t6_match_interface(intf)", "strcmp(t6_device_path",
                         "head->status) == 1", "t6_edid_base_block_valid", "head->edid_len == 128",
                         "head->io_faulted", "t6->io_faulted", "USB_STATE_CONFIGURED",
                         "USB_INTERFACE_UNBINDING", "drm_dev_is_unplugged", "!READ_ONCE(t6->wq)"):
            self.assertIn(required, policy)
        self.assertIn("trigger6_quiesce.h", (ROOT / "packaging/PKGBUILD").read_text())

    def test_final_off_is_one_private_locked_request_without_fault_mutation(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        helper = source.split("static void t6_final_off_disconnect", 1)[1].split("static void t6_usb_disconnect", 1)[0]
        self.assertLess(helper.index("if (!t6_final_monitor_off)"), helper.index("mutex_lock"))
        self.assertEqual(helper.count("t6_final_off_policy(t6, intf, was_active)"), 2)
        locked = helper.split("mutex_lock(&t6->io_lock);", 1)[1]
        self.assertLess(locked.index("t6_final_off_policy"), locked.index("usb_control_msg"))
        self.assertEqual(helper.count("usb_control_msg("), 1)
        for required in ("usb_sndctrlpipe(t6->udev, 0)", "T6_FINAL_OFF_REQUEST, T6_FINAL_OFF_TYPE",
                         "T6_FINAL_OFF_VALUE, T6_FINAL_OFF_INDEX, NULL", "T6_FINAL_OFF_LENGTH",
                         "T6_FINAL_OFF_TIMEOUT_MS", "ret=%d error=%d duration_us=%llu",
                         "t6_final_off_error(ret)"):
            self.assertIn(required, helper)
        for forbidden in ("drm_dev_enter(", "t6_ctrl_out(", "t6_latch_io_error(", "WRITE_ONCE(",
                          "t6_bulk_", "usb_reset", "for (", "while (", "queue_work", "mod_timer"):
            self.assertNotIn(forbidden, helper)

    def test_final_off_preserves_unplug_and_complete_drain_before_usb_release(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        disconnect = source.split("static void t6_usb_disconnect", 1)[1].split("static int t6_usb_suspend", 1)[0]
        ordered = ("was_active = READ_ONCE", "drm_dev_unplug(&t6->drm)",
                   "t6_cancel_head_activity(t6)", "destroy_workqueue(t6->wq)",
                   "t6->wq = NULL", "t6_final_off_disconnect(t6, intf, was_active)",
                   "drm_atomic_helper_shutdown(&t6->drm)", "t6_free_head_buffers(t6)",
                   "usb_put_dev(t6->udev)")
        positions = [disconnect.index(token) for token in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(source.count("t6_final_off_disconnect(t6, intf, was_active)"), 1)
        disable = source.split("static void t6_crtc_atomic_disable", 1)[1].split("static int t6_crtc_atomic_check", 1)[0]
        self.assertLess(disable.index("drm_dev_enter(&t6->drm"), disable.index("t6_ctrl_out"))
        self.assertNotIn(".soft_unbind", source)

    def test_idle_refresh_wrapper_pins_reviewed_state_and_is_inert(self):
        path = ROOT / "tools/test_idle_refresh.sh"
        source = path.read_text()
        for required in ("--run-reviewed-idle-refresh", "$EUID != 0",
                         "/sys/module/trigger6/srcversion", "check_device",
                         "/sys/class/tty/tty0/active", "/proc/sys/kernel/tainted",
                         "/sys/class/drm/card1-eDP-1/status", "sha256sum",
                         "[[ ! -e /sys/class/drm/card0 ]]",
                         "[[ ! -d /sys/module/trigger6 ]]",
                         "--kill-after=2s 8s /usr/bin/rmmod trigger6",
                         "--kill-after=2s 12s /usr/bin/insmod",
                         "raw_idle_refresh=1 serialize_usb_bus=1"):
            self.assertIn(required, source)
        self.assertLess(source.index("sha256sum"), source.index("/unbind"))
        for forbidden in ("rmmod -f", "modprobe", "new_id", "driver_override",
                          "chvt", "hyprctl", "pacman", "/etc/", "/usr/lib/"):
            self.assertNotIn(forbidden, source)
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
        result = subprocess.run(["bash", str(path)], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Inert:", result.stderr)

    def test_query_only_precedes_every_output_or_async_activation(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        self.assertIn("static bool t6_query_only;", source)
        self.assertIn("t6_query_only, bool, 0444", source)
        probe = source.split("static int t6_usb_probe(", 1)[1].split("static void t6_usb_disconnect", 1)[0]
        query = probe.index("if (t6_query_only)")
        for prior in ("t6_match_interface", "strcmp(t6_device_path", "if (t6_manual_only)",
                      "t6_output_mask_valid", "atomic_cmpxchg", "t6_probe_head(t6, head)"):
            self.assertLess(probe.index(prior), query)
        for later in ("t6_log_head(head)", "mutex_init", "alloc_workqueue",
                      "t6_alloc_head_buffers", "t6_chip_init", "drmm_mode_config_init",
                      "drm_dev_register"):
            self.assertGreater(probe.index(later), query)
        branch = probe.split("if (t6_query_only)", 1)[1].split("\n\t}", 1)[0]
        self.assertIn("ret = 0;", branch)
        self.assertIn("goto err_put;", branch)
        cleanup = probe.split("err_put:", 1)[1]
        self.assertIn("usb_set_intfdata(intf, NULL)", cleanup)
        self.assertIn("put_device(t6->dmadev)", cleanup)
        self.assertIn("usb_put_dev(t6->udev)", cleanup)
        for forbidden in ("t6_ctrl_out", "t6_bulk_write", "queue_work", "mod_timer"):
            self.assertNotIn(forbidden, probe[:query])

    def test_head1_query_wrapper_preserves_guards_and_saved_head0_restore(self):
        path = ROOT / "tools/query_head1_restore.sh"
        source = path.read_text()
        for required in ("--run-reviewed-head1-query", "$EUID != 0", "check_device",
                         "sha256sum", "/sys/module/trigger6/srcversion",
                         "[[ ! -e /sys/class/drm/card0 ]]", "remove_unbound",
                         "--kill-after=2s 8s /usr/bin/rmmod trigger6",
                         "query_only=1 aquamarine_evdi_name=0 raw_idle_refresh=0",
                         "Query did not complete cleanly", "trigger6-idle-refresh-proven.ko"):
            self.assertIn(required, source)
        insertions = [line for line in source.splitlines() if "/usr/bin/insmod " in line]
        self.assertEqual(len(insertions), 2)
        self.assertIn("output_mask=2 query_only=1", insertions[0])
        self.assertIn("trigger6-idle-refresh-proven.ko", insertions[1])
        self.assertIn("output_mask=1 aquamarine_evdi_name=1 raw_idle_refresh=1", insertions[1])
        for forbidden in ("output_mask=3", "rmmod -f", "modprobe", "new_id",
                          "driver_override", "/etc/", "chvt"):
            self.assertNotIn(forbidden, source)
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
        result = subprocess.run(["bash", str(path)], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Inert:", result.stderr)

    def test_external_dpms_wrapper_is_scoped_inert_and_restores_on_exit(self):
        path = ROOT / "tools/check_external_dpms.sh"
        source = path.read_text()
        for required in ("--run-reviewed-hp-dpms", "$EUID == 0", "check_live",
                         "trap restore_external EXIT", "monitor = \"HDMI-A-2\"",
                         "scanout_active=0", "/usr/bin/sleep 10"):
            self.assertIn(required, source)
        self.assertEqual(source.count("hl.dsp.dpms("), 2)
        for forbidden in ("sudo", "pkexec", "insmod", "rmmod", "~/.config", "hl.monitor("):
            self.assertNotIn(forbidden, source)
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
        result = subprocess.run(["bash", str(path)], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Inert:", result.stderr)

    def test_timing_query_is_default_off_bounded_head0_and_in_only(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        self.assertIn("static bool t6_query_timings;", source)
        self.assertIn("t6_query_timings, bool, 0444", source)
        probe = source.split("static int t6_usb_probe(", 1)[1].split("static void t6_usb_disconnect", 1)[0]
        gate = "t6_query_timings && (!t6_query_only || t6_output_mask != 1 ||"
        self.assertLess(probe.index("if (t6_manual_only)"), probe.index(gate))
        self.assertLess(probe.index(gate), probe.index("atomic_cmpxchg"))
        self.assertLess(probe.index("t6_probe_head(t6, head)"), probe.index("t6_query_head0_timings(t6)"))
        self.assertLess(probe.index("if (t6_query_only)"), probe.index("t6_query_head0_timings(t6)"))
        helper = source.split("static int t6_query_head0_timings", 1)[1].split("static int t6_alloc_head_buffers", 1)[0]
        for required in ("!t6_query_only || !t6_query_timings || t6->output_mask != 1",
                         "!head->connected || head->status != 1 || head->edid_len != 128",
                         "T6_REQ_GET_RES_COUNT, 0, 0, &count_le, 4",
                         "T6_REQ_GET_RES_TABLE, 0,", "first * T6_RES_ENTRY_SIZE, table, size",
                         "t6_timing_query_entries(count - first)", "if (!entries)",
                         "size = entries * T6_RES_ENTRY_SIZE", "if (ret == size)", "kfree(table)"):
            self.assertIn(required, helper)
        self.assertLess(helper.index("!head->connected"), helper.index("t6_ctrl_in"))
        self.assertEqual(helper.count("t6_ctrl_in("), 2)
        for forbidden in ("t6_ctrl_out", "t6_bulk_", "usb_", "mod_timer", "queue_work", "t6_chip_init"):
            self.assertNotIn(forbidden, helper)

    def test_query_only_transport_helpers_deny_out_and_unlisted_in(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        outbound = source.split("static int t6_ctrl_out(")[-1].split("static int t6_ctrl_in", 1)[0]
        bulk = source.split("static int t6_bulk_write(")[-1].split("static int t6_chip_init", 1)[0]
        inbound = source.split("static int t6_ctrl_in(")[-1].split("static bool t6_edid_base_block_valid", 1)[0]
        for body, io_call in ((outbound, "usb_control_msg"), (bulk, "usb_bulk_msg")):
            self.assertIn("if (t6_query_only)\n\t\treturn -EPERM;", body)
            self.assertLess(body.index("if (t6_query_only)"), body.index(io_call))
        self.assertIn("t6_query_in_allowed(t6->output_mask, t6_query_timings,", inbound)
        self.assertIn("t6_query_timing_page1, req, val, idx, size)", inbound)
        self.assertLess(inbound.index("t6_query_in_allowed"), inbound.index("usb_control_msg"))
        self.assertIn("usb_rcvctrlpipe(t6->udev, 0)", inbound)
        self.assertIn("USB_TYPE_VENDOR | USB_DIR_IN", inbound)
        self.assertIn("if (ret == size)", inbound)

    def test_timing_wrapper_restores_quiet_not_active_and_is_inert(self):
        path = ROOT / "tools/query_head0_timings.sh"
        source = path.read_text()
        for required in ("--run-reviewed-head0-timings", "$EUID != 0", "check_device",
                         "trap finish EXIT", "trap 'exit 130' INT", "trap 'exit 143' TERM",
                         "query_insert_attempted", "/sys/module/trigger6/refcnt",
                         "== 102", "sha256sum", "modinfo -F vermagic",
                         "query_only=1 query_timings=1 aquamarine_evdi_name=0 raw_idle_refresh=0",
                         "--kill-after=2s 8s /usr/bin/rmmod trigger6",
                         "--kill-after=2s 12s /usr/bin/insmod", "/usr/bin/sleep 10"):
            self.assertIn(required, source)
        insertions = [line for line in source.splitlines() if "/usr/bin/insmod " in line]
        self.assertEqual(len(insertions), 1)
        self.assertIn("output_mask=1 query_only=1 query_timings=1", insertions[0])
        for forbidden in ("output_mask=2", "output_mask=3", "query_only=0", "rmmod -f",
                          "modprobe", "new_id", "driver_override", "chvt", "hyprctl", "/etc/"):
            self.assertNotIn(forbidden, source)
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
        result = subprocess.run(["bash", str(path)], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Inert:", result.stderr)

    def test_page1_is_opt_in_count36_and_exact_read_tuple(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        self.assertIn("static bool t6_query_timing_page1;", source)
        self.assertIn("t6_query_timing_page1, bool, 0444", source)
        helper = source.split("static int t6_query_head0_timings", 1)[1].split("static int t6_alloc_head_buffers", 1)[0]
        self.assertIn("t6_query_timing_page1 ? T6_RES_MAX_ENTRIES : 0", helper)
        self.assertLess(helper.index("t6_query_timing_page1 && count != 36"),
                        helper.index("t6_timing_query_entries(count - first)"))
        self.assertIn("first * T6_RES_ENTRY_SIZE, table, size", helper)
        probe = source.split("static int t6_usb_probe(", 1)[1]
        self.assertLess(probe.index("t6_query_timing_page1 && !t6_query_timings"),
                        probe.index("atomic_cmpxchg"))
        policy = (ROOT / "kernel/trigger6_query.h").read_text()
        self.assertIn("if (page1 && !timings)", policy)
        self.assertIn("timings && value == 0 && index == 512 && size == 512", policy)

    def test_page1_wrapper_begins_ends_absent_and_is_inert(self):
        path = ROOT / "tools/query_timing_page1.sh"
        source = path.read_text()
        for required in ("--run-reviewed-timing-page1", "$EUID != 0", "trap finish EXIT",
                         "query_timing_page1=1", "== 102", "sha256sum", "check_device",
                         "[[ ! -d /sys/module/trigger6 ]]", "[[ ! -e /sys/class/drm/card0 ]]",
                         "--kill-after=2s 12s /usr/bin/insmod", "/usr/bin/sleep 10"):
            self.assertIn(required, source)
        self.assertEqual(source.count("/usr/bin/insmod "), 1)
        for forbidden in ("query_only=0", "output_mask=2", "output_mask=3", "rmmod -f",
                          "modprobe", "new_id", "driver_override", "chvt", "hyprctl"):
            self.assertNotIn(forbidden, source)
        subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
        result = subprocess.run(["bash", str(path)], capture_output=True,
                                text=True, check=False, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Inert:", result.stderr)

    def test_verified_timing_wrappers_are_inert_and_have_bounded_recovery(self):
        path = ROOT / "tools/test_verified_timing.sh"
        source = path.read_text()
        for required in ("--run-reviewed-verified-timing", "$EUID != 0", "trap finish EXIT",
                         "for sample in {0..89}", "test_success=1", "check_device", "== 102",
                         "sha256sum", "modinfo -F vermagic", "WARNING:|BUG:|Oops:",
                         "bulk_short_writes", "/sys/bus/usb/drivers/trigger6/unbind",
                         "--kill-after=2s 8s /usr/bin/rmmod trigger6",
                         "query_only=0 query_timings=0 query_timing_page1=0",
                         "aquamarine_evdi_name=1 raw_idle_refresh=1 serialize_usb_bus=1"):
            self.assertIn(required, source)
        self.assertEqual(source.count("/usr/bin/insmod "), 1)
        for forbidden in ("output_mask=2", "output_mask=3", "rmmod -f", "modprobe",
                          "driver_override", "new_id", "chvt", "hyprctl", "/etc/"):
            self.assertNotIn(forbidden, source)
        dpms = ROOT / "tools/check_verified_dpms.sh"
        dpms_source = dpms.read_text()
        self.assertIn("trap restore_external EXIT", dpms_source)
        self.assertEqual(dpms_source.count("hl.dsp.dpms("), 2)
        self.assertIn('monitor = "HDMI-A-2"', dpms_source)
        self.assertIn("/usr/bin/sleep 10", dpms_source)
        for script in (path, dpms):
            subprocess.run(["bash", "-n", str(script)], check=True, timeout=5)
            result = subprocess.run(["bash", str(script)], capture_output=True,
                                    text=True, check=False, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Inert:", result.stderr)


class CaptureParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("inspect_timing_capture", ROOT / "tools/inspect_timing_capture.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def block(self, kind, body):
        body += bytes((-len(body)) % 4)
        size = len(body) + 12
        return struct.pack("<II", kind, size) + body + struct.pack("<I", size)

    def container(self, link, packets):
        result = self.block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
        result += self.block(1, struct.pack("<HHI", link, 0, 65535))
        for packet in packets:
            result += self.block(6, struct.pack("<IIIII", 0, 0, 0, len(packet), len(packet)) + packet)
        return result

    def test_usbmon_pair_uses_setup_index_and_matching_completion(self):
        setup = bytearray(64)
        struct.pack_into("<QBBBBHBB", setup, 0, 123, ord("S"), 2, 0x80, 25, 6, 0, 0)
        struct.pack_into("<BBHHH", setup, 40, 0xC0, 0x89, 0, 512, 32)
        response = bytearray(setup)
        response[8] = ord("C")
        struct.pack_into("<iII", response, 28, 0, 32, 32)
        record = self.module.inspect(io.BytesIO(self.container(220, [setup, response + bytes(range(32))])))[0]
        self.assertEqual((record["index"], record["expected"], record["captured"], record["status"]), (512, 32, 32, 0))
        self.assertEqual(record["data_hex"], bytes(range(32)).hex())

    def test_usbpcap_pair_and_truncated_blocks(self):
        setup = struct.pack("<HQIHBHHBBIB", 28, 123, 0, 0, 0, 6, 25, 0x80, 2, 8, 0)
        setup += struct.pack("<BBHHH", 0xC0, 0x89, 0, 512, 32)
        response = struct.pack("<HQIHBHHBBIB", 28, 123, 0, 0, 1, 6, 25, 0x80, 2, 32, 3) + bytes(32)
        data = self.container(249, [setup, response])
        self.assertEqual(self.module.inspect(io.BytesIO(data))[0]["index"], 512)
        for cut in (1, 7, len(data) - 1, len(data) - 5):
            with self.subTest(cut=cut), self.assertRaises(ValueError):
                self.module.inspect(io.BytesIO(data[:cut]))


class TimingDecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("decode_timings", ROOT / "tools/decode_timings.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        blob = source.split("static const u8 t6_mode_1080p[]", 1)[1].split("};", 1)[0]
        blob = re.sub(r"/\*.*?\*/", "", blob, flags=re.DOTALL)
        cls.kernel_mode = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", blob))
        # Preserve the donor mistake as a regression fixture, not active timing.
        cls.donor = bytes.fromhex("144402003c009808800718072c0065043804e8031d00bb02e8031d0101010000")
        values = list(cls.module.TIMING.unpack(cls.donor))
        for key, value in cls.module.CEA_1080P60.items():
            values[cls.module.FIELDS.index(key)] = value
        cls.cea = cls.module.TIMING.pack(*values)

    def make_log(self, total=1, start=0):
        count = min(total - start, 16)
        header = f"kernel: Timing query head 0: total={total} captured={count} bytes={count * 32} start={start}; raw diagnostic only\n"
        return header + "\n".join(f"kernel: T6 timing[{index}]: {self.cea.hex()}" for index in range(start, start + count))

    def test_documented_layout_detects_inherited_geometry_mismatch(self):
        self.assertEqual(self.module.TIMING.size, 32)
        result = self.module.decode_record(self.donor)
        self.assertEqual(result["h_sync_start"], 1816)
        self.assertEqual(result["v_sync_start"], 1000)
        self.assertEqual(result["v_sync_width"], 29)
        self.assertEqual(len(result["geometry_errors"]), 2)
        self.assertEqual(set(result["cea_1080p60_differences"]), {"h_sync_start", "v_sync_start", "v_sync_width"})
        self.assertEqual(result["pll_fnum"], 699)
        self.assertEqual(result["pll_fden"], 1000)
        self.assertEqual(result["pll_idiv"], 29)

    def test_kernel_mode_matches_live_record26_and_only_four_donor_bytes_change(self):
        # Live 2026-09-06 head0 record26 and public JCD543 Windows 0x12 data agree.
        verified = bytes.fromhex("144402003c0098088007d8072c00650438043c040500bb02e8031d0101010000")
        self.assertEqual(self.kernel_mode, verified)
        self.assertEqual(self.cea, verified)
        self.assertEqual([(index, before, after) for index, (before, after)
                          in enumerate(zip(self.donor, self.kernel_mode, strict=True)) if before != after],
                         [(0x0A, 0x18, 0xD8), (0x12, 0xE8, 0x3C), (0x13, 0x03, 0x04), (0x14, 0x1D, 0x05)])

    def test_audio_control_blobs_and_requests_are_unchanged_for_timing_isolation(self):
        source = (ROOT / "kernel/trigger6_drv.c").read_text()
        expected = {
            "t6_init_color": "000000000000001f0000001f0000000f0000000f0000000f0000000f0000000f0000000f00000000",
            "t6_init_timing_pre": "00000000000000008025000000000200",
            "t6_init_timing_post": "01000000000000008025000000000200",
        }
        for name, value in expected.items():
            blob = source.split(f"static const u8 {name}[]", 1)[1].split("};", 1)[0]
            data = bytes(int(item, 16) for item in re.findall(r"0x([0-9a-fA-F]{2})", blob))
            self.assertEqual(data.hex(), value)
        header = (ROOT / "kernel/trigger6.h").read_text()
        self.assertRegex(header, r"#define T6_REQ_SET_COLOR\s+0x23")
        self.assertRegex(header, r"#define T6_REQ_SET_TIMING\s+0x24")
        self.assertEqual(source.count("t6_ctrl_out(t6, T6_REQ_SET_COLOR, 0, 0,"), 1)
        self.assertEqual(source.count("t6_ctrl_out(t6, T6_REQ_SET_TIMING, 0, 0,"), 2)

    def test_synthetic_cea_matches_actual_drm_definition(self):
        result = self.module.decode_record(self.cea)
        self.assertFalse(result["geometry_errors"])
        self.assertFalse(result["cea_1080p60_differences"])
        self.assertEqual(result["calculated_refresh_hz"], 60)
        connector = (ROOT / "kernel/trigger6_connector.c").read_text()
        for literal in ("148500", "1920, 2008, 2052, 2200", "1080, 1084, 1089, 1125"):
            self.assertIn(literal, connector)

    def test_zero_short_long_and_invalid_geometry_records(self):
        for size in (0, 1, 31, 33, 64):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.module.decode_record(bytes(size))
        self.assertTrue(self.module.decode_record(bytes(32))["geometry_errors"])
        for key, value in (("h_sync_width", 65535), ("v_polarity", 2), ("pixel_clock_khz", 0)):
            record = list(self.module.TIMING.unpack(self.cea))
            record[self.module.FIELDS.index(key)] = value
            self.assertTrue(self.module.decode_record(self.module.TIMING.pack(*record))["geometry_errors"])

    def test_table_log_bounds_and_truncation(self):
        for total in (1, 15, 16, 17, 0xFFFFFFFF):
            result = self.module.parse_kernel_log(self.make_log(total))
            self.assertEqual(result["captured"], min(total, 16))
            self.assertEqual(result["truncated"], total > 16)

    def test_continuation_accepts_only_second_page_of_measured_table(self):
        result = self.module.parse_kernel_log(self.make_log(36, 16))
        self.assertEqual(result["start"], 16)
        self.assertEqual(result["captured"], 16)
        for total, start in ((35, 16), (37, 16), (36, 32), (36, 512)):
            with self.subTest(total=total, start=start), self.assertRaises(ValueError):
                self.module.parse_kernel_log(self.make_log(total, start))

    def test_table_log_rejects_partial_duplicate_extra_and_bad_counts(self):
        good = self.make_log()
        malformed = (
            "", self.make_log(0), self.make_log(0x100000000), good + "\n" + good,
            good.replace("bytes=32", "bytes=31"), good.replace("captured=1", "captured=17"),
            good.replace("start=0", "start=1"), good[:-2], good.replace("timing[0]", "timing[1]"),
            good + f"\nkernel: T6 timing[0]: {self.cea.hex()}",
            good + f"\nkernel: T6 timing[1]: {self.cea.hex()}", "x" * (1024 * 1024 + 1),
        )
        for index, log in enumerate(malformed):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.module.parse_kernel_log(log)


class DescriptorParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("preflight", ROOT / "tools/preflight.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_endpoint(self):
        result = self.module.parse_descriptors(bytes.fromhex("07050202000400"))
        self.assertEqual(result[0]["address"], "0x02")
        self.assertEqual(result[0]["max_packet"], 1024)

    def test_malformed_lengths(self):
        for data in (b"\x00\x05", b"\x01\x05", b"\x07\x05", b"\x07", b"\x02\x01"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.module.parse_descriptors(data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
