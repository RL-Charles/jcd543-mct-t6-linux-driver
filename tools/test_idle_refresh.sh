#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Reviewed one-time replacement for the 2026-09-05 static-frame experiment.
set -eu
export PATH=/usr/bin
if [[ $# != 1 || $1 != --run-reviewed-idle-refresh || $EUID != 0 ]]; then
    printf '%s\n' 'Inert: requires explicit reviewed root invocation with --run-reviewed-idle-refresh.' >&2
    exit 2
fi
# Resolve this reviewed checkout, not a caller-supplied path or working directory.
script_path=$(/usr/bin/realpath -e -- "${BASH_SOURCE[0]}")
repo_root=${script_path%/tools/test_idle_refresh.sh}
[[ $repo_root != "$script_path" && -f "$repo_root/Makefile" && -f "$repo_root/LICENSE" ]]
readonly script_path repo_root
trap 'result=$?; printf "Idle-refresh wrapper exit=%s\n" "$result"' EXIT

check_device() {
    [[ $(</sys/bus/usb/devices/2-1.4.1/idVendor) == 0711 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/idProduct) == 5601 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/bcdDevice) == 1010 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/speed) == 5000 ]]
    [[ $(/usr/bin/sha256sum /sys/bus/usb/devices/2-1.4.1/descriptors) == '61ed0a266c3b3db8f8be6dfab701a1fa9e1e1a1e1cd7681f14999e854c01b12f  /sys/bus/usb/devices/2-1.4.1/descriptors' ]]
    [[ ! -e /sys/bus/usb/devices/2-3.4.1 ]]
}
[[ $(/usr/bin/uname -r) == 7.1.9-arch1-2 ]]
[[ $(</sys/class/tty/tty0/active) == tty2 ]]
[[ $(</sys/class/drm/card1-eDP-1/status) == connected ]]
[[ $(</proc/sys/kernel/tainted) == 12288 ]]
[[ $(</sys/module/trigger6/srcversion) == DC2FAAE96B693A6F3C47599 ]]
[[ $(</sys/module/trigger6/parameters/device_path) == 2-1.4.1 ]]
[[ $(</sys/module/trigger6/parameters/manual_only) == N ]]
[[ $(</sys/module/trigger6/parameters/output_mask) == 1 ]]
[[ $(</sys/module/trigger6/parameters/aquamarine_evdi_name) == Y ]]
[[ ! -d /sys/module/evdi ]]
[[ $(/usr/bin/sha256sum "${repo_root}/kernel/trigger6.ko") == "71c43fee30514153bdda59a1ed20a08b9b7c35f43550652c3d3ee75d4c47a064  ${repo_root}/kernel/trigger6.ko" ]]
[[ $(/usr/bin/sha256sum "${repo_root}/artifacts/runtime-2026-09-05/trigger6-before-reprobe-guard.ko") == "6eff96df530353d1a6e296616990c72c5b90881439a4552b81f9f867cf515c04  ${repo_root}/artifacts/runtime-2026-09-05/trigger6-before-reprobe-guard.ko" ]]
check_device
/usr/bin/date --iso-8601=seconds
printf 'Fresh T6 USB device number: '
/usr/bin/head -c 32 /sys/bus/usb/devices/2-1.4.1/devnum
if [[ -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]]; then
    [[ $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0/driver) == /sys/bus/usb/drivers/trigger6 ]]
    [[ $(/usr/bin/readlink -f /sys/class/drm/card0/device) == $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0) ]]
    /usr/bin/head -c 16384 /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics
    printf '%s\n' 'Unbinding ONLY the exact T6 interface; i915/hubs/other dock functions are untouched.'
    /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/tee /sys/bus/usb/drivers/trigger6/unbind <<< '2-1.4.1:1.0'
else
    printf '%s\n' 'The device is already unbound in a disconnect gap; no unbind write.'
fi
[[ ! -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]]
[[ ! -e /sys/class/drm/card0 ]]
for attempt in {1..20}; do
    [[ $(</sys/module/trigger6/refcnt) == 0 ]] && break
    /usr/bin/sleep 0.1
done
[[ $(</sys/module/trigger6/refcnt) == 0 ]]
/usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/rmmod trigger6
[[ ! -d /sys/module/trigger6 ]]
[[ $(</proc/sys/kernel/tainted) == 12288 ]]
check_device
[[ ! -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]]
/usr/bin/timeout --signal=TERM --kill-after=2s 12s /usr/bin/insmod "${repo_root}/kernel/trigger6.ko" device_path=2-1.4.1 manual_only=0 output_mask=1 aquamarine_evdi_name=1 raw_idle_refresh=1 serialize_usb_bus=1
[[ $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0/driver) == /sys/bus/usb/drivers/trigger6 ]]
[[ $(</sys/module/trigger6/srcversion) == 3C037EE0098BDEC7A3211D5 ]]
[[ $(</sys/module/trigger6/parameters/raw_idle_refresh) == Y ]]
[[ $(</proc/sys/kernel/tainted) == 12288 ]]
/usr/bin/date --iso-8601=seconds
/usr/bin/head -c 16384 /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics
printf '%s\n' 'One-probe guarded refresh module bound. Observe static-frame and DPMS counters before judging output.'
