#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Package/manifest tests in a synthetic tree with injected command runners."""

import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = load("t6_setup", ROOT / "control/setup.py")
M = load("t6_manifest", ROOT / "packaging/manifest.py")
PKGBUILD = (ROOT / "packaging/PKGBUILD").read_text()
PACKAGE_RELEASE = (re.search(r"^pkgver=([0-9.]+)$", PKGBUILD, re.M)[1] + "-" +
                   re.search(r"^pkgrel=([1-9][0-9]*)$", PKGBUILD, re.M)[1])


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="t6 package synthetic ")
        self.root = Path(self.temporary.name)
        names = S.ALLOWED_FILES | {"usr/lib/jcd543-trigger6/controller.py", "usr/lib/jcd543-trigger6/setup.py",
                                   "usr/src/jcd543-trigger6-0.1.0/dkms.conf",
                                   "usr/src/jcd543-trigger6-0.1.0/kernel/trigger6_drv.c",
                                   "usr/share/doc/jcd543-trigger6/INSTALLATION.md"}
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic payload: " + name)
            path.chmod(0o644)
        self.document = M.collect(self.root, PACKAGE_RELEASE)
        self.release_patch = mock.patch.object(S, "installed_package_release", return_value=PACKAGE_RELEASE)
        self.release_patch.start()
        self.addCleanup(self.release_patch.stop)
        self.manifest = self.root / S.MANIFEST
        self.manifest.parent.mkdir(parents=True)
        self.save_manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.document))
        self.manifest.chmod(0o644)

    def test_exact_payload_verifies_in_synthetic_root(self):
        self.assertEqual(S.verify(self.root, os.geteuid()), self.document)

    def test_changed_or_missing_file_refuses_and_preserves_other_files(self):
        path = self.root / self.document["files"][0]["path"]
        other = self.root / self.document["files"][1]["path"]
        original = other.read_bytes()
        path.write_text("user change must survive")
        with self.assertRaises(S.Refusal):
            S.verify(self.root, os.geteuid())
        self.assertEqual(path.read_text(), "user change must survive")
        self.assertEqual(other.read_bytes(), original)
        path.unlink()
        with self.assertRaises(OSError):
            S.verify(self.root, os.geteuid())
        self.assertEqual(other.read_bytes(), original)

    def test_manifest_scope_duplicate_and_completeness_refused(self):
        original = json.dumps(self.document)
        for replacement in ("../../etc/passwd", "/etc/passwd", "etc/unrelated.conf"):
            self.document = json.loads(original)
            self.document["files"][0]["path"] = replacement
            self.save_manifest()
            with self.assertRaises(S.Refusal):
                S.verify(self.root, os.geteuid())
        self.document = json.loads(original)
        self.document["files"].append(self.document["files"][0])
        self.save_manifest()
        with self.assertRaises(S.Refusal):
            S.verify(self.root, os.geteuid())

    def test_symlink_or_writable_payload_refused(self):
        path = self.root / self.document["files"][0]["path"]
        path.chmod(0o666)
        with self.assertRaises(S.Refusal):
            S.verify(self.root, os.geteuid())
        path.unlink()
        path.symlink_to(self.manifest)
        with self.assertRaises(S.Refusal):
            S.verify(self.root, os.geteuid())
        with self.assertRaises(ValueError):
            M.collect(self.root, PACKAGE_RELEASE)

    def test_manifest_release_matches_package_metadata_not_a_pinned_revision(self):
        self.assertEqual(PACKAGE_RELEASE, "0.1.0-4")
        self.assertEqual(self.document["version"], PACKAGE_RELEASE)
        self.assertIn('"$pkgdir" "$pkgver-$pkgrel"', PKGBUILD)
        self.assertIn("QUIESCE_EXPERIMENT.md", PKGBUILD)
        self.assertNotIn('"version": "0.1.0-1"', (ROOT / "packaging/manifest.py").read_text())
        for wrong in ("0.1.0-1", "0.1.0-3", "0.1.0-5", "0.2.0-4", "", None, 4):
            self.document["version"] = wrong
            self.save_manifest()
            with self.assertRaises(S.Refusal):
                S.verify(self.root, os.geteuid())

    def test_manifest_generation_requires_an_explicit_valid_release(self):
        for invalid in ("", "0.1.0", "0.1.0-0", "0.1.0-01", "0.1.0-4\n", "0.1.0-4;true", None, 4):
            with self.assertRaises(ValueError):
                M.collect(self.root, invalid)
        self.assertEqual(M.collect(self.root, "0.1.0-5")["version"], "0.1.0-5")

    def test_installed_release_failure_is_fail_closed_without_file_changes(self):
        before = self.manifest.read_bytes()
        for failure in (S.Refusal("package unavailable"), subprocess.TimeoutExpired("pacman", 5)):
            with mock.patch.object(S, "installed_package_release", side_effect=failure):
                with self.assertRaises(type(failure)):
                    S.verify(self.root, os.geteuid())
            self.assertEqual(self.manifest.read_bytes(), before)

    def test_synthetic_archive_reader_cannot_bypass_release_shape_or_exactness(self):
        self.assertEqual(S.verify(self.root, os.geteuid(), release_reader=lambda: PACKAGE_RELEASE), self.document)
        for invalid in (None, 4, "0.1.0-03", "0.1.0-3", "0.2.0-4"):
            with self.assertRaises(S.Refusal):
                S.verify(self.root, os.geteuid(), release_reader=lambda: invalid)


class SetupPolicyTests(unittest.TestCase):
    def test_checkout_apply_is_refused_before_system_operations(self):
        result = subprocess.run([sys.executable, str(ROOT / "control/setup.py"), "prepare", "--apply"],
                                capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("root-owned installed", result.stderr)

    def test_plan_is_read_only_and_does_not_install(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["setup.py", "plan"]), \
                mock.patch.object(S.Path, "exists", return_value=False), \
                mock.patch.object(S, "run") as runner, contextlib.redirect_stdout(output):
            S.main()
        self.assertTrue(json.loads(output.getvalue())["read_only"])
        runner.assert_not_called()

    def test_installed_release_reads_only_exact_pacman_package_record(self):
        runner = mock.Mock(return_value="jcd543-trigger6-dkms " + PACKAGE_RELEASE)
        self.assertEqual(S.installed_package_release(runner), PACKAGE_RELEASE)
        runner.assert_called_once_with(["/usr/bin/pacman", "-Q", "jcd543-trigger6-dkms"], timeout=5)
        for output in ("", "other 0.1.0-4", "jcd543-trigger6-dkms 0.2.0-4", "jcd543-trigger6-dkms 0.1.0-04",
                       "jcd543-trigger6-dkms 0.1.0-4\nextra", "jcd543-trigger6-dkms 0.1.0-4 --force"):
            runner.return_value = output
            with self.assertRaises(S.Refusal):
                S.installed_package_release(runner)

    def test_partial_dkms_failure_never_approves_loads_or_enables(self):
        calls = []

        def fail(argv, **_kwargs):
            calls.append(argv)
            raise S.Refusal("synthetic build failure")

        with self.assertRaises(S.Refusal):
            S.prepare(fail)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["/usr/bin/dkms", "install", "jcd543-trigger6/0.1.0"])
        self.assertNotIn("--modprobe-on-install", calls[0])
        self.assertNotIn("--force", calls[0])

    def test_prepare_only_targets_current_kernel_and_reports_artifact(self):
        release = S.platform.release()
        calls = []

        def runner(argv, **_kwargs):
            calls.append(argv)
            return f"/usr/lib/modules/{release}/updates/dkms/trigger6.ko.zst" if argv[0].endswith("modinfo") else ""

        self.assertTrue(S.prepare(runner).endswith("trigger6.ko.zst"))
        self.assertEqual(calls[0][-2:], ["-k", release])
        self.assertEqual(len(calls), 2)

    def test_modinfo_lib_alias_is_canonicalized_only_on_matching_layout(self):
        release = S.platform.release()
        for suffix in ("", ".zst", ".xz", ".gz"):
            for prefix in ("/lib", "/usr/lib"):
                value = f"{prefix}/modules/{release}/updates/dkms/trigger6.ko{suffix}"

                def runner(argv, **_kwargs):
                    return value if argv[0].endswith("modinfo") else ""

                with mock.patch.object(S.Path, "resolve", return_value=Path("/usr/lib")):
                    self.assertEqual(S.prepare(runner), f"/usr/lib/modules/{release}/updates/dkms/trigger6.ko{suffix}")
                if prefix == "/lib":
                    with mock.patch.object(S.Path, "resolve", return_value=Path("/unreviewed-layout")):
                        with self.assertRaises(S.Refusal):
                            S.prepare(runner)

    def test_prepared_artifact_guard_refuses_symlink_escape(self):
        with tempfile.TemporaryDirectory(prefix="t6 prepared artifact ") as directory:
            root = Path(directory)
            module = root / "usr/lib/modules/test/updates/dkms/trigger6.ko.zst"
            module.parent.mkdir(parents=True)
            module.write_bytes(b"synthetic module")
            S.trusted(module, root, os.geteuid())
            module.unlink()
            module.symlink_to("/etc/passwd")
            with self.assertRaises(S.Refusal):
                S.trusted(module, root, os.geteuid())
            # Even a resolved escape cannot pass the installation-root boundary.
            with self.assertRaises(S.Refusal):
                S.trusted(module.resolve(strict=True), root, os.geteuid())
        source = (ROOT / "control/setup.py").read_text()
        self.assertLess(source.index('trusted(Path(module), Path("/"), 0)'),
                        source.index('"sha256": hashlib.sha256(Path(module).read_bytes())'))

    def test_modinfo_traversal_foreign_kernel_or_name_refuses(self):
        release = S.platform.release()
        for value in (f"/usr/lib/modules/{release}/../trigger6.ko", "/usr/lib/modules/other/trigger6.ko",
                      f"/usr/lib/modules/{release}/i915.ko.zst", "/tmp/trigger6.ko"):
            def runner(argv, **_kwargs):
                return value if argv[0].endswith("modinfo") else ""

            with self.assertRaises(S.Refusal):
                S.prepare(runner)

    def test_uninstall_stop_failure_aborts_before_dkms_or_package_removal(self):
        calls = []

        def fail(argv, **_kwargs):
            calls.append(argv)
            raise S.Refusal("synthetic stop failure")

        with self.assertRaises(S.Refusal):
            S.uninstall(fail)
        self.assertEqual(calls, [["/usr/bin/systemctl", "disable", "--now", "jcd543-trigger6.service"]])

    def test_package_contains_no_enable_or_install_execution_hook(self):
        build = (ROOT / "packaging/PKGBUILD").read_text()
        for forbidden in ("post_install", "systemctl", "insmod", "modprobe ", "sudo", "pkexec", "curl", "wget"):
            self.assertNotIn(forbidden, build)
        self.assertIn("AUTOINSTALL=\"yes\"", (ROOT / "packaging/dkms.conf").read_text())
        self.assertNotIn("--modprobe-on-install", (ROOT / "packaging/dkms.conf").read_text())
        blacklist = (ROOT / "packaging/jcd543-trigger6.conf").read_text()
        commands = [line.strip() for line in blacklist.splitlines() if line.strip() and not line.startswith("#")]
        self.assertEqual(commands, ["blacklist trigger6"])
        for path in (ROOT / "packaging/PKGBUILD", ROOT / "packaging/dkms.conf",
                     ROOT / "packaging/jcd543-trigger6", ROOT / "packaging/jcd543-trigger6-setup",
                     ROOT / "packaging/jcd543-trigger6-sleep"):
            subprocess.run(["/usr/bin/bash", "-n", str(path)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
