#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# One supervised, unprivileged HP-only DPMS cycle; no configuration writes.
set -euo pipefail
export PATH=/usr/bin
if [[ $# != 1 || $1 != --run-reviewed-hp-dpms || $EUID == 0 ]]; then
    printf '%s\n' 'Inert: requires reviewed user-session invocation with --run-reviewed-hp-dpms.' >&2
    exit 2
fi

check_live() {
    [[ $(</sys/module/trigger6/srcversion) == 3C037EE0098BDEC7A3211D5 ]]
    [[ $(</sys/module/trigger6/parameters/device_path) == 2-1.4.1 ]]
    [[ $(</sys/module/trigger6/parameters/output_mask) == 1 ]]
    [[ $(</sys/module/trigger6/parameters/raw_idle_refresh) == Y ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/devnum) == 101 ]]
    [[ $(/usr/bin/readlink -f /sys/class/drm/card0/device) == $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0) ]]
    [[ $(</sys/class/tty/tty0/active) == tty2 ]]
    [[ $(</sys/class/drm/card1-eDP-1/status) == connected ]]
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
metrics
trap restore_external EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
/usr/bin/hyprctl eval 'hl.dispatch(hl.dsp.dpms({ action = "disable", monitor = "HDMI-A-2" }))'
/usr/bin/sleep 1
check_live
printf '%s\n' 'Observed monitor and driver state one second after external disable:'
/usr/bin/hyprctl -j monitors | /usr/bin/jq '[.[] | {name,dpmsStatus}]'
metrics
/usr/bin/hyprctl -j monitors | /usr/bin/jq -e 'any(.[]; .name == "HDMI-A-2" and (.dpmsStatus | not)) and any(.[]; .name == "eDP-1" and .dpmsStatus)' >/dev/null
/usr/bin/rg -q '^head0 .*scanout_active=0 ' /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics
printf '%s\n' 'EXTERNAL OFF: counters after disable settled'
metrics
/usr/bin/sleep 10
check_live
printf '%s\n' 'EXTERNAL OFF: counters after ten seconds'
metrics
restore_external
/usr/bin/sleep 1
check_live
printf '%s\n' 'EXTERNAL ON: first-frame/refresh counters'
metrics
/usr/bin/sleep 5
check_live
metrics
/usr/bin/hyprctl -j monitors | /usr/bin/jq -e 'any(.[]; .name == "HDMI-A-2" and .dpmsStatus) and any(.[]; .name == "eDP-1" and .dpmsStatus)' >/dev/null
printf '%s\n' 'External DPMS cycle complete; eDP stayed on. Physical pixels require user confirmation.'
