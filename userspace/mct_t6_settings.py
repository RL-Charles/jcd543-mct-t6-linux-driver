#!/usr/bin/env python3
"""mct-t6-settings -- GTK4 settings window for the MCT Trigger6 USB display driver."""

import glob
import os
import platform
import sys
import time

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Pango  # noqa: E402

METRICS_GLOB = "/sys/bus/usb/devices/*/t6_metrics"
MODULE_PARAM_DIR = "/sys/module/trigger6/parameters"


def sysfs_read(path):
    try:
        with open(path) as f:
            return f.read()
    except (OSError, IOError):
        return None


def sysfs_write(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except (PermissionError, OSError):
        return False


def parse_metrics(text):
    result = {}
    for line in text.strip().splitlines():
        parts = line.split()
        if not parts:
            continue
        prefix = parts[0]
        kvs = {}
        for token in parts[1:]:
            if "=" in token:
                k, v = token.split("=", 1)
                kvs[k] = v
        if prefix in result:
            result[prefix].update(kvs)
        else:
            result[prefix] = kvs
    return result


def discover_devices():
    devices = []
    for path in sorted(glob.glob(METRICS_GLOB)):
        raw = sysfs_read(path)
        if raw is None:
            continue
        devices.append((os.path.dirname(path), parse_metrics(raw)))
    return devices


def fmt_us(val):
    try:
        us = int(val)
    except (ValueError, TypeError):
        return val or "-"
    if us == 0:
        return "-"
    if us < 1000:
        return f"{us}µs"
    if us < 1_000_000:
        return f"{us / 1000:.1f}ms"
    return f"{us / 1_000_000:.2f}s"


def fmt_bytes(val):
    try:
        b = int(val)
    except (ValueError, TypeError):
        return val or "-"
    if b < 1024:
        return f"{b}B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f}K"
    if b < 1024**3:
        return f"{b / 1024**2:.1f}M"
    return f"{b / 1024**3:.2f}G"


def g(d, key, default="-"):
    return d.get(key, default)


def find_t6_connectors():
    """Find DRM connectors belonging to trigger6."""
    connectors = []
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        name = os.path.basename(card)
        if "-" in name:
            continue
        driver_link = os.path.join(card, "device", "driver")
        if not os.path.islink(driver_link):
            continue
        driver = os.path.basename(os.path.realpath(driver_link))
        if driver != "trigger6":
            continue
        for conn in sorted(glob.glob(f"/sys/class/drm/{name}-*")):
            connectors.append(conn)
    return connectors


class T6SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(title="MCT Trigger6 Display Settings",
                         default_width=620, default_height=520, **kwargs)
        self.prev_frames = {}
        self.prev_time = time.monotonic()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(box)

        # Header
        header = Gtk.HeaderBar()
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda _: self.rebuild())
        header.pack_start(refresh_btn)
        self.set_titlebar(header)

        # Scrolled content
        scroll = Gtk.ScrolledWindow(vexpand=True)
        box.append(scroll)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                               spacing=12, margin_top=12, margin_bottom=12,
                               margin_start=12, margin_end=12)
        scroll.set_child(self.content)

        self.rebuild()
        GLib.timeout_add_seconds(2, self._poll)

    def rebuild(self):
        # Clear
        while child := self.content.get_first_child():
            self.content.remove(child)

        self._build_devices()
        self._build_connectors()
        self._build_quality()
        self._build_about()

    def _build_devices(self):
        devices = discover_devices()
        if not devices:
            lbl = Gtk.Label(label="No Trigger6 devices found. Is the module loaded?")
            lbl.add_css_class("dim-label")
            self.content.append(lbl)
            return

        self.device_labels = []
        for _, dev in devices:
            t6 = dev.get("trigger6", {})
            frame = Gtk.Frame(label=f"Device: {g(t6, 'interface')}")
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                           margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
            frame.set_child(vbox)

            faulted = g(t6, "io_faulted", "0")
            status = "OK" if faulted == "0" else "FAULTED"
            vbox.append(Gtk.Label(label=f"Bus {g(t6, 'bus')}  Dev {g(t6, 'dev')}  [{status}]",
                                  xalign=0))

            for hi in range(2):
                h = dev.get(f"head{hi}", {})
                if not h:
                    continue
                conn = "connected" if g(h, "connected") == "1" else "disconnected"
                transport = g(h, "transport")
                lbl = Gtk.Label(xalign=0)
                lbl.set_markup(
                    f"<b>head{hi}</b>  {transport}  {g(h, 'width')}×{g(h, 'height')}  "
                    f"<span foreground='{'green' if conn == 'connected' else 'gray'}'>{conn}</span>")
                vbox.append(lbl)

                metrics_lbl = Gtk.Label(xalign=0)
                metrics_lbl.add_css_class("dim-label")
                metrics_lbl.set_text(
                    f"  sent={g(h, 'sent_frames')}  skip={g(h, 'skipped_frames')}  "
                    f"encode={fmt_us(g(h, 'encode_avg_us'))}  "
                    f"usb={fmt_us(g(h, 'usb_avg_us'))}  "
                    f"payload={fmt_bytes(g(h, 'last_payload_bytes'))}")
                vbox.append(metrics_lbl)
                self.device_labels.append((t6.get("interface", ""), hi, metrics_lbl))

            self.content.append(frame)

    def _build_connectors(self):
        connectors = find_t6_connectors()
        if not connectors:
            return
        frame = Gtk.Frame(label="DRM Connectors")
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                       margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        frame.set_child(vbox)
        for conn_path in connectors:
            name = os.path.basename(conn_path)
            status = (sysfs_read(os.path.join(conn_path, "status")) or "").strip()
            modes = sysfs_read(os.path.join(conn_path, "modes")) or ""
            mode_list = [m.strip() for m in modes.strip().splitlines() if m.strip()]
            mode_str = ", ".join(mode_list[:4]) if mode_list else "none"
            lbl = Gtk.Label(xalign=0)
            lbl.set_text(f"{name}: {status}  modes: {mode_str}")
            vbox.append(lbl)
        self.content.append(frame)

    def _build_quality(self):
        frame = Gtk.Frame(label="Quality Settings")
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                       margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        frame.set_child(vbox)

        params = [
            ("jpeg_quality", "JPEG Quality", 1, 100),
            ("frame_min_interval_ms", "Frame Interval (ms)", 0, 1000),
            ("secondary_frame_min_interval_ms", "Secondary Interval (ms)", 0, 5000),
        ]
        for param, label, lo, hi in params:
            path = os.path.join(MODULE_PARAM_DIR, param)
            current = int((sysfs_read(path) or "0").strip()) if os.path.exists(path) else 0
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hbox.append(Gtk.Label(label=label, width_chars=24, xalign=0))
            adj = Gtk.Adjustment(value=current, lower=lo, upper=hi, step_increment=1)
            scale = Gtk.Scale(adjustment=adj, hexpand=True)
            scale.set_draw_value(True)
            scale.connect("value-changed", self._on_param_changed, param)
            hbox.append(scale)
            vbox.append(hbox)

        self.content.append(frame)

    def _build_about(self):
        frame = Gtk.Frame(label="About")
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                       margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        frame.set_child(vbox)

        loaded = os.path.isdir("/sys/module/trigger6")
        vbox.append(Gtk.Label(label=f"Driver: trigger6 ({'loaded' if loaded else 'not loaded'})",
                              xalign=0))
        vbox.append(Gtk.Label(label=f"Kernel: {platform.release()}", xalign=0))
        vbox.append(Gtk.Label(label="Package: 0.9.0-beta", xalign=0))
        self.content.append(frame)

    def _on_param_changed(self, scale, param):
        val = int(scale.get_value())
        path = os.path.join(MODULE_PARAM_DIR, param)
        if not sysfs_write(path, val):
            scale.set_tooltip_text("Permission denied — run as root to change")

    def _poll(self):
        devices = discover_devices()
        now = time.monotonic()
        dt = now - self.prev_time
        self.prev_time = now

        for _, dev in devices:
            t6 = dev.get("trigger6", {})
            intf = t6.get("interface", "")
            for hi in range(2):
                h = dev.get(f"head{hi}", {})
                if not h:
                    continue
                key = f"{intf}-{hi}"
                sent = int(g(h, "sent_frames", "0"))
                prev = self.prev_frames.get(key, sent)
                fps = (sent - prev) / dt if dt > 0 else 0
                self.prev_frames[key] = sent

                for stored_intf, stored_hi, lbl in getattr(self, "device_labels", []):
                    if stored_intf == intf and stored_hi == hi:
                        lbl.set_text(
                            f"  fps={fps:.0f}  sent={g(h, 'sent_frames')}  "
                            f"encode={fmt_us(g(h, 'encode_avg_us'))}  "
                            f"usb={fmt_us(g(h, 'usb_avg_us'))}  "
                            f"payload={fmt_bytes(g(h, 'last_payload_bytes'))}")
        return True


class T6SettingsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.authentra.trigger6.settings")

    def do_activate(self):
        win = T6SettingsWindow(application=self)
        win.present()


def main():
    app = T6SettingsApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
