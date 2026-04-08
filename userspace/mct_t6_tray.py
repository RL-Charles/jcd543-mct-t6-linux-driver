#!/usr/bin/env python3
"""mct-t6-tray -- System tray indicator for the MCT Trigger6 USB display driver."""

import glob
import os
import subprocess
import sys

try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import Gtk, GLib, AyatanaAppIndicator3
except (ImportError, ValueError) as e:
    print(f"mct-t6-tray: missing dependency: {e}", file=sys.stderr)
    print("Install: sudo apt install gir1.2-ayatanaappindicator3-0.1 python3-gi",
          file=sys.stderr)
    sys.exit(1)

METRICS_GLOB = "/sys/bus/usb/devices/*/t6_metrics"


def sysfs_read(path):
    try:
        with open(path) as f:
            return f.read()
    except (OSError, IOError):
        return None


def count_connected_heads():
    total_devices = 0
    total_heads = 0
    for path in glob.glob(METRICS_GLOB):
        raw = sysfs_read(path)
        if not raw:
            continue
        total_devices += 1
        for line in raw.splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0].startswith("head"):
                for token in parts[1:]:
                    if token == "connected=1":
                        total_heads += 1
    return total_devices, total_heads


class T6Tray:
    def __init__(self):
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "mct-t6-companion",
            "video-display",
            AyatanaAppIndicator3.IndicatorCategory.HARDWARE)
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self._build_menu()
        self._prev_devs = 0
        self._prev_heads = 0
        GLib.timeout_add_seconds(3, self._poll)
        self._poll()

    def _build_menu(self):
        menu = Gtk.Menu()

        self.status_item = Gtk.MenuItem(label="Checking...")
        self.status_item.set_sensitive(False)
        menu.append(self.status_item)

        menu.append(Gtk.SeparatorMenuItem())

        settings = Gtk.MenuItem(label="Open Settings...")
        settings.connect("activate", self._on_settings)
        menu.append(settings)

        terminal = Gtk.MenuItem(label="Open Monitor (terminal)")
        terminal.connect("activate", self._on_monitor)
        menu.append(terminal)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: Gtk.main_quit())
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)

    def _notify(self, title, body):
        try:
            subprocess.Popen(["notify-send", "-i", "video-display",
                              "-a", "Trigger6", title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass

    def _poll(self):
        devs, heads = count_connected_heads()
        if devs == 0:
            self.indicator.set_icon_full("dialog-warning", "No T6 devices")
            self.status_item.set_label("No Trigger6 devices detected")
        else:
            self.indicator.set_icon_full("video-display", "T6 Connected")
            self.status_item.set_label(
                f"{devs} adapter{'s' if devs != 1 else ''}, "
                f"{heads} monitor{'s' if heads != 1 else ''} connected")

        # Notify on connect/disconnect changes
        if heads > self._prev_heads and self._prev_heads >= 0:
            self._notify("Trigger6 Monitor Connected",
                         f"{heads} monitor{'s' if heads != 1 else ''} active")
        elif heads < self._prev_heads and self._prev_heads > 0:
            self._notify("Trigger6 Monitor Disconnected",
                         f"{heads} monitor{'s' if heads != 1 else ''} remaining")
        self._prev_devs = devs
        self._prev_heads = heads
        return True

    def _on_settings(self, _):
        subprocess.Popen(["mct-t6-settings"])

    def _on_monitor(self, _):
        # Try common terminal emulators
        for term in ["cosmic-term", "gnome-terminal", "konsole", "xterm"]:
            try:
                subprocess.Popen([term, "--", "mct-t6-ctl", "monitor"])
                return
            except FileNotFoundError:
                continue
        subprocess.Popen(["mct-t6-ctl", "monitor"])


def main():
    T6Tray()
    Gtk.main()


if __name__ == "__main__":
    main()
