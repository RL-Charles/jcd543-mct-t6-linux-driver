#!/bin/bash
# install.sh -- Single-command installer for the MCT Trigger 6 driver
# Usage: sudo ./install.sh
set -euo pipefail

VERSION="0.9.0"
PACKAGE="trigger6"
SRC_DIR="/usr/src/${PACKAGE}-${VERSION}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: run as root (sudo $0)"
    exit 1
fi

KVER="$(uname -r)"

# Check prerequisites
echo "[1/7] Checking prerequisites..."
MISSING=()
[ ! -d "/lib/modules/${KVER}/build" ] && MISSING+=("linux-headers-${KVER}")
command -v dkms &>/dev/null || MISSING+=("dkms")
command -v gcc &>/dev/null || MISSING+=("build-essential")
if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Missing: ${MISSING[*]}"
    echo "Install with: sudo apt install ${MISSING[*]}"
    exit 1
fi

# Remove previous DKMS registration
if dkms status "${PACKAGE}/${VERSION}" 2>/dev/null | grep -q "${PACKAGE}"; then
    echo "[2/7] Removing previous DKMS registration..."
    dkms remove "${PACKAGE}/${VERSION}" --all 2>/dev/null || true
fi

# Copy source
echo "[2/7] Installing source to ${SRC_DIR}..."
rm -rf "${SRC_DIR}"
mkdir -p "${SRC_DIR}/kernel"
cp "${SCRIPT_DIR}/kernel/trigger6_drv.c" "${SRC_DIR}/kernel/"
cp "${SCRIPT_DIR}/kernel/trigger6_connector.c" "${SRC_DIR}/kernel/"
cp "${SCRIPT_DIR}/kernel/trigger6_codec.c" "${SRC_DIR}/kernel/"
cp "${SCRIPT_DIR}/kernel/trigger6.h" "${SRC_DIR}/kernel/"
cp "${SCRIPT_DIR}/kernel/trigger6_codec.h" "${SRC_DIR}/kernel/"
cp "${SCRIPT_DIR}/kernel/Kbuild" "${SRC_DIR}/kernel/"
cp "${SCRIPT_DIR}/kernel/Makefile" "${SRC_DIR}/kernel/"
cp "${SCRIPT_DIR}/dkms.conf" "${SRC_DIR}/"

# DKMS build + install
echo "[3/7] Building module via DKMS..."
dkms add "${PACKAGE}/${VERSION}"
dkms build "${PACKAGE}/${VERSION}" -k "${KVER}"
dkms install "${PACKAGE}/${VERSION}" -k "${KVER}"

# Udev rules
echo "[4/7] Installing udev rules..."
cp "${SCRIPT_DIR}/99-trigger6.rules" /etc/udev/rules.d/
udevadm control --reload-rules

# Modprobe config
echo "[5/7] Installing modprobe.d configuration..."
cp "${SCRIPT_DIR}/trigger6.conf" /etc/modprobe.d/

# Companion CLI tool
echo "[6/8] Installing companion tools..."
cp "${SCRIPT_DIR}/userspace/mct_t6_ctl.py" /usr/local/bin/mct-t6-ctl
chmod +x /usr/local/bin/mct-t6-ctl

# GUI companion (optional — needs PyGObject + GTK4)
echo "[7/8] Installing GUI companion..."
cp "${SCRIPT_DIR}/userspace/mct_t6_settings.py" /usr/local/bin/mct-t6-settings
chmod +x /usr/local/bin/mct-t6-settings
cp "${SCRIPT_DIR}/userspace/mct_t6_tray.py" /usr/local/bin/mct-t6-tray
chmod +x /usr/local/bin/mct-t6-tray
cp "${SCRIPT_DIR}/userspace/mct-t6-companion.desktop" /usr/share/applications/ 2>/dev/null || true
# Autostart tray on login
mkdir -p /etc/xdg/autostart
cat > /etc/xdg/autostart/mct-t6-tray.desktop <<'TRAYEOF'
[Desktop Entry]
Name=MCT Trigger6 Tray
Exec=mct-t6-tray
Icon=video-display
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
NoDisplay=true
TRAYEOF

# Depmod
echo "[8/8] Updating module dependencies..."
depmod -a "${KVER}"

echo ""
echo "=== MCT Trigger 6 driver v${VERSION} installed ==="
echo ""
echo "Verify: lsmod | grep trigger6"
echo "Status: mct-t6-ctl status"
echo "Monitor: mct-t6-ctl monitor"
echo "Uninstall: sudo ./uninstall.sh"
