#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# One reviewed IN-only continuation; begin/end absent module and unbound device.
set -euo pipefail
export PATH=/usr/bin
if [[ $# != 1 || $1 != --run-reviewed-timing-page1 || $EUID != 0 ]]; then
    printf '%s\n' 'Inert: requires explicit reviewed root invocation with --run-reviewed-timing-page1.' >&2
    exit 2
fi
# Resolve this reviewed checkout, not a caller-supplied path or working directory.
script_path=$(/usr/bin/realpath -e -- "${BASH_SOURCE[0]}")
repo_root=${script_path%/tools/query_timing_page1.sh}
[[ $repo_root != "$script_path" && -f "$repo_root/Makefile" && -f "$repo_root/LICENSE" ]]
readonly script_path repo_root
query_insert_attempted=0
query_started=''
check_device() {
    [[ $(</sys/bus/usb/devices/2-1.4.1/idVendor) == 0711 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/idProduct) == 5601 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/bcdDevice) == 1010 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/speed) == 5000 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/devnum) == 102 ]]
    [[ $(/usr/bin/sha256sum /sys/bus/usb/devices/2-1.4.1/descriptors) == '61ed0a266c3b3db8f8be6dfab701a1fa9e1e1a1e1cd7681f14999e854c01b12f  /sys/bus/usb/devices/2-1.4.1/descriptors' ]]
    [[ $(</sys/class/tty/tty0/active) == tty2 ]]
    [[ $(</sys/class/drm/card1-eDP-1/status) == connected ]]
    [[ $(</sys/class/drm/card1-eDP-1/enabled) == enabled ]]
    [[ $(</sys/class/drm/card1-eDP-1/dpms) == On ]]
    [[ $(</proc/sys/kernel/tainted) == 12288 ]]
    [[ ! -e /sys/class/drm/card0 ]]
}
finish() {
    result=$?
    trap - EXIT INT TERM
    set +e
    if [[ $query_insert_attempted == 1 && -d /sys/module/trigger6 ]]; then
        if [[ $(</sys/module/trigger6/srcversion) == 0DA9B2181DC790C77E8B79F &&
              $(</sys/module/trigger6/parameters/query_only) == Y &&
              $(</sys/module/trigger6/parameters/query_timings) == Y &&
              $(</sys/module/trigger6/parameters/query_timing_page1) == Y &&
              $(</sys/module/trigger6/parameters/output_mask) == 1 &&
              ! -e /sys/class/drm/card0 ]]; then
            if [[ -r /sys/bus/usb/devices/2-1.4.1/devnum &&
                  $(</sys/bus/usb/devices/2-1.4.1/devnum) == 102 &&
                  $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0/driver) == /sys/bus/usb/drivers/trigger6 ]]; then
                /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/tee /sys/bus/usb/drivers/trigger6/unbind <<< '2-1.4.1:1.0'
                [[ $? == 0 ]] || result=1
            fi
            if [[ $(</sys/module/trigger6/refcnt) == 0 ]]; then
                /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/rmmod trigger6
                [[ $? == 0 ]] || result=1
            else
                printf '%s\n' 'Query module still referenced; unplug and review normal removal. No force.' >&2
                result=1
            fi
        else
            printf '%s\n' 'Cleanup identity/state mismatch; refusing further mutations.' >&2
            result=1
        fi
    fi
    if [[ -n $query_started ]]; then
        /usr/bin/journalctl -k --since "$query_started" --no-pager -o short-iso
    fi
    [[ ! -d /sys/module/trigger6 ]] || result=1
    [[ ! -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]] || result=1
    [[ ! -e /sys/class/drm/card0 ]] || result=1
    printf 'Timing page1 exit=%s; active video was never initialized. Decode record26 before further testing.\n' "$result"
    exit "$result"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
[[ $(/usr/bin/uname -r) == 7.1.9-arch1-2 ]]
[[ ! -d /sys/module/trigger6 ]]
[[ ! -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]]
[[ $(/usr/bin/sha256sum "${repo_root}/kernel/trigger6.ko") == "debce8f3f8b2409dbe3de5502bb9f16a7309314132565ae59c0773a4ea817edf  ${repo_root}/kernel/trigger6.ko" ]]
[[ $(/usr/bin/modinfo -F vermagic "${repo_root}/kernel/trigger6.ko") == '7.1.9-arch1-2 SMP preempt mod_unload ' ]]
check_device
query_started=$(/usr/bin/date --iso-8601=seconds)
printf 'Timing page1 query start: %s\n' "$query_started"
query_insert_attempted=1
/usr/bin/timeout --signal=TERM --kill-after=2s 12s /usr/bin/insmod "${repo_root}/kernel/trigger6.ko" device_path=2-1.4.1 manual_only=0 output_mask=1 query_only=1 query_timings=1 query_timing_page1=1 aquamarine_evdi_name=0 raw_idle_refresh=0 serialize_usb_bus=1
[[ $(</sys/module/trigger6/srcversion) == 0DA9B2181DC790C77E8B79F ]]
[[ $(</sys/module/trigger6/parameters/query_timing_page1) == Y ]]
[[ $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0/driver) == /sys/bus/usb/drivers/trigger6 ]]
[[ ! -e /sys/class/drm/card0 ]]
/usr/bin/sleep 10
check_device
printf '%s\n' 'Continuation IN completed; removing query module and leaving dock quiet.'
