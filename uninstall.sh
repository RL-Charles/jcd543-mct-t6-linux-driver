#!/bin/bash
# uninstall.sh -- Clean removal of the MCT Trigger 6 driver
# Usage: sudo ./uninstall.sh
set -euo pipefail

VERSION="0.9.0"
PACKAGE="trigger6"

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: run as root (sudo $0)"
    exit 1
fi

# Unload module
if lsmod | grep -q "^trigger6"; then
    echo "Unloading trigger6 module..."
    rmmod trigger6 2>/dev/null || echo "Warning: could not unload (may be in use)"
fi

# DKMS removal
if command -v dkms &>/dev/null; then
    if dkms status "${PACKAGE}/${VERSION}" 2>/dev/null | grep -q "${PACKAGE}"; then
        echo "Removing DKMS registration..."
        dkms remove "${PACKAGE}/${VERSION}" --all
    fi
fi

# Remove source
rm -rf "/usr/src/${PACKAGE}-${VERSION}"

# Remove companion tools
rm -f /usr/local/bin/mct-t6-ctl
rm -f /usr/local/bin/mct-t6-settings
rm -f /usr/local/bin/mct-t6-tray
rm -f /usr/share/applications/mct-t6-companion.desktop
rm -f /etc/xdg/autostart/mct-t6-tray.desktop

# Remove configs
rm -f /etc/udev/rules.d/99-trigger6.rules
rm -f /etc/modprobe.d/trigger6.conf
rm -f /etc/modprobe.d/trigger6-blacklist.conf

# Reload udev + depmod
udevadm control --reload-rules 2>/dev/null || true
depmod -a

echo "MCT Trigger 6 driver uninstalled."
