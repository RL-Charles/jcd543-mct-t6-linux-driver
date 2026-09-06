#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Inert unless explicitly invoked as root with the exact review token below.
# One-run, current-topology experiment. No installation or persistent writes.
set -eu
export PATH=/usr/bin

if [[ $# != 1 || $1 != --run-reviewed-vt3-pattern || $EUID != 0 ]]; then
    printf '%s\n' 'Inert: requires explicit reviewed root invocation with --run-reviewed-vt3-pattern.' >&2
    exit 2
fi

# All targets are literal, reviewed values. Refuse changed topology/session.
[[ $(</sys/class/tty/tty0/active) == tty2 ]]
[[ $(</sys/module/trigger6/parameters/manual_only) == N ]]
[[ $(</sys/module/trigger6/parameters/output_mask) == 1 ]]
[[ $(</sys/module/trigger6/parameters/device_path) == 2-3.4.1 ]]
# This historical wrapper is for the first, default-name KMS-proven build only.
# Refuse the later DRM-name shim rather than relying on a misleading -D path.
[[ $(</sys/module/trigger6/srcversion) == 9FFD650A0E1CCAB304076E4 ]]
[[ $(</sys/bus/usb/devices/2-3.4.1/idVendor) == 0711 ]]
[[ $(</sys/bus/usb/devices/2-3.4.1/idProduct) == 5601 ]]
[[ $(</sys/bus/usb/devices/2-3.4.1/bcdDevice) == 1010 ]]
[[ $(</sys/class/drm/card0-HDMI-A-2/connector_id) == 35 ]]
[[ $(</sys/class/drm/card0-HDMI-A-2/status) == connected ]]
[[ $(/usr/bin/readlink -f /sys/class/drm/card0/device/driver) == /sys/bus/usb/drivers/trigger6 ]]
[[ $(/usr/bin/readlink -f /sys/class/drm/card0/device) == $(/usr/bin/readlink -f /sys/bus/usb/devices/2-3.4.1:1.0) ]]

restore_vt() {
    local result=$?
    trap - EXIT INT TERM
    /usr/bin/chvt 2 || printf '%s\n' 'Return to VT2 failed; press Ctrl+Alt+F2.' >&2
    printf 'VT pattern wrapper exit=%s; active VT: ' "$result"
    /usr/bin/head -c 32 /sys/class/tty/tty0/active
    exit "$result"
}
trap restore_vt EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

/usr/bin/date --iso-8601=seconds
/usr/bin/modetest -M trigger6 -a -c -p -e
printf '%s\n' 'Switching to VT3 for at most 12 seconds of KMS pattern plus 2-second kill grace.'
/usr/bin/chvt 3
/usr/bin/sleep 1
set +e
/usr/bin/timeout --signal=TERM --kill-after=2s 12s /usr/bin/modetest -M trigger6 -a -s 35@38:1920x1080-60@XR24 -P 36@38:1920x1080+0+0@XR24
test_result=$?
set -e
printf 'modetest exit=%s (124 means the planned timeout, not a successful pattern by itself)\n' "$test_result"
/usr/bin/head -c 16384 /sys/bus/usb/devices/2-3.4.1:1.0/t6_metrics
/usr/bin/date --iso-8601=seconds
exit "$test_result"
