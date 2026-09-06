#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# One reviewed reload after the user's physical USB-C port move, 2026-09-05.
# Literal current selectors only; no bind override, unbind, or device reset.
set -eu
export PATH=/usr/bin

if [[ $# != 1 || $1 != --run-reviewed-port-move || $EUID != 0 ]]; then
    printf '%s\n' 'Inert: requires explicit reviewed root invocation with --run-reviewed-port-move.' >&2
    exit 2
fi
# Resolve this reviewed checkout, not a caller-supplied path or working directory.
script_path=$(/usr/bin/realpath -e -- "${BASH_SOURCE[0]}")
repo_root=${script_path%/tools/reload_after_port_move.sh}
[[ $repo_root != "$script_path" && -f "$repo_root/Makefile" && -f "$repo_root/LICENSE" ]]
readonly script_path repo_root

trap 'result=$?; printf "Port-move wrapper exit=%s\n" "$result"' EXIT

check_new_device() {
    [[ $(</sys/bus/usb/devices/2-1.4.1/idVendor) == 0711 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/idProduct) == 5601 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/bcdDevice) == 1010 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/speed) == 5000 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/devnum) == 23 ]]
    [[ $(/usr/bin/sha256sum /sys/bus/usb/devices/2-1.4.1/descriptors) == '61ed0a266c3b3db8f8be6dfab701a1fa9e1e1a1e1cd7681f14999e854c01b12f  /sys/bus/usb/devices/2-1.4.1/descriptors' ]]
    [[ ! -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]]
    [[ ! -e /sys/bus/usb/devices/2-3.4.1 ]]
}

[[ $(/usr/bin/uname -r) == 7.1.9-arch1-2 ]]
[[ $(</sys/class/tty/tty0/active) == tty2 ]]
[[ $(</sys/class/drm/card1-eDP-1/status) == connected ]]
[[ $(</proc/sys/kernel/tainted) == 12288 ]]
[[ $(</sys/module/trigger6/refcnt) == 0 ]]
[[ $(</sys/module/trigger6/srcversion) == DC2FAAE96B693A6F3C47599 ]]
[[ $(</sys/module/trigger6/parameters/device_path) == 2-3.4.1 ]]
[[ $(</sys/module/trigger6/parameters/manual_only) == N ]]
[[ $(</sys/module/trigger6/parameters/output_mask) == 1 ]]
[[ $(</sys/module/trigger6/parameters/aquamarine_evdi_name) == Y ]]
[[ ! -e /sys/class/drm/card0 ]]
[[ ! -d /sys/module/evdi ]]
[[ $(/usr/bin/sha256sum "${repo_root}/kernel/trigger6.ko") == "6eff96df530353d1a6e296616990c72c5b90881439a4552b81f9f867cf515c04  ${repo_root}/kernel/trigger6.ko" ]]
check_new_device

/usr/bin/date --iso-8601=seconds
printf '%s\n' 'Removing the unbound, zero-reference module so its readonly path can be selected afresh.'
/usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/rmmod trigger6
[[ ! -d /sys/module/trigger6 ]]
[[ $(</proc/sys/kernel/tainted) == 12288 ]]
check_new_device

printf '%s\n' 'One explicit head-0 probe on current device 2-1.4.1:1.0; every kernel guard remains enabled.'
/usr/bin/timeout --signal=TERM --kill-after=2s 12s /usr/bin/insmod "${repo_root}/kernel/trigger6.ko" device_path=2-1.4.1 manual_only=0 output_mask=1 aquamarine_evdi_name=1
if [[ $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0/driver) != /sys/bus/usb/drivers/trigger6 ]]; then
    printf '%s\n' 'Probe refused; leave the resident module unbound and inspect status/logs. Do not repeat blindly.' >&2
    exit 1
fi
[[ $(</proc/sys/kernel/tainted) == 12288 ]]
/usr/bin/date --iso-8601=seconds
/usr/bin/head -c 16384 /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics
printf '%s\n' 'Guarded probe bound successfully. Physical image confirmation is still required.'
