#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# User-session-only external DPMS recovery for the verified timing artifact.
set -euo pipefail
export PATH=/usr/bin
if [[ $# != 1 || $1 != --run-reviewed-verified-dpms || $EUID == 0 ]]; then
    printf '%s\n' 'Inert: requires reviewed user-session invocation with --run-reviewed-verified-dpms.' >&2
    exit 2
fi
check_live() {
    [[ $(</sys/module/trigger6/srcversion) == F6D5C7316849C7428A83002 ]]
    [[ $(</sys/module/trigger6/parameters/device_path) == 2-1.4.1 ]]
    [[ $(</sys/module/trigger6/parameters/output_mask) == 1 ]]
    [[ $(</sys/module/trigger6/parameters/raw_idle_refresh) == Y ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/devnum) == 102 ]]
    [[ $(/usr/bin/readlink -f /sys/class/drm/card0/device) == $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0) ]]
    [[ $(</sys/class/tty/tty0/active) == tty2 ]]
    [[ $(</sys/class/drm/card1-eDP-1/dpms) == On ]]
    [[ $(</proc/sys/kernel/tainted) == 12288 ]]
}
metrics() {
    /usr/bin/date --iso-8601=seconds
    /usr/bin/head -c 16384 /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics
}
restore_external() {
    /usr/bin/hyprctl eval 'hl.dispatch(hl.dsp.dpms({ action = "enable", monitor = "HDMI-A-2" }))'
}
check_live
[[ $(/usr/bin/omarchy-shell lock isLocked) == false ]]
/usr/bin/hyprctl -j monitors | /usr/bin/jq -e 'any(.[]; .name == "HDMI-A-2" and .dpmsStatus) and any(.[]; .name == "eDP-1" and .dpmsStatus)' >/dev/null
trap restore_external EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
metrics
/usr/bin/hyprctl eval 'hl.dispatch(hl.dsp.dpms({ action = "disable", monitor = "HDMI-A-2" }))'
/usr/bin/sleep 1
check_live
/usr/bin/rg -q '^head0 .*scanout_active=0 ' /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics
printf '%s\n' 'EXTERNAL OFF: settled baseline'
metrics
/usr/bin/sleep 10
check_live
/usr/bin/rg -q '^head0 .*scanout_active=0 ' /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics
printf '%s\n' 'EXTERNAL OFF: ten-second sample'
metrics
restore_external
/usr/bin/sleep 1
check_live
printf '%s\n' 'EXTERNAL ON: real full-frame resend'
metrics
/usr/bin/sleep 5
check_live
metrics
/usr/bin/hyprctl -j monitors | /usr/bin/jq -e 'any(.[]; .name == "HDMI-A-2" and .dpmsStatus) and any(.[]; .name == "eDP-1" and .dpmsStatus)' >/dev/null
printf '%s\n' 'Scoped external DPMS recovery completed; eDP stayed on.'
