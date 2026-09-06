#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# One reviewed corrected-head0 insertion with a bounded fault/identity watcher.
set -euo pipefail
export PATH=/usr/bin
if [[ $# != 1 || $1 != --run-reviewed-verified-timing || $EUID != 0 ]]; then
    printf '%s\n' 'Inert: requires explicit reviewed root invocation with --run-reviewed-verified-timing.' >&2
    exit 2
fi
# Resolve this reviewed checkout, not a caller-supplied path or working directory.
script_path=$(/usr/bin/realpath -e -- "${BASH_SOURCE[0]}")
repo_root=${script_path%/tools/test_verified_timing.sh}
[[ $repo_root != "$script_path" && -f "$repo_root/Makefile" && -f "$repo_root/LICENSE" ]]
readonly script_path repo_root
insert_attempted=0
test_success=0
test_started=''
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
}
finish() {
    result=$?
    trap - EXIT INT TERM
    set +e
    if [[ $insert_attempted == 1 && ( $result != 0 || $test_success != 1 ) && -d /sys/module/trigger6 ]]; then
        printf '%s\n' 'Fault/interruption: attempting exact-interface unbind and normal module removal.' >&2
        if [[ $(</sys/module/trigger6/srcversion) == F6D5C7316849C7428A83002 &&
              $(</sys/module/trigger6/parameters/device_path) == 2-1.4.1 &&
              $(</sys/module/trigger6/parameters/output_mask) == 1 ]]; then
            if [[ -r /sys/bus/usb/devices/2-1.4.1/devnum &&
                  $(</sys/bus/usb/devices/2-1.4.1/devnum) == 102 &&
                  $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0/driver) == /sys/bus/usb/drivers/trigger6 ]]; then
                /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/tee /sys/bus/usb/drivers/trigger6/unbind <<< '2-1.4.1:1.0'
            fi
            for attempt in {1..20}; do
                [[ $(</sys/module/trigger6/refcnt) == 0 ]] && break
                /usr/bin/sleep 0.1
            done
            if [[ $(</sys/module/trigger6/refcnt) == 0 ]]; then
                /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/rmmod trigger6
            fi
        fi
        if [[ -d /sys/module/trigger6 ]]; then
            printf '%s\n' 'Normal cleanup incomplete: unplug dock, then review ordinary removal/reboot. Never force.' >&2
        fi
        result=1
    fi
    if [[ -n $test_started ]]; then
        /usr/bin/journalctl -k --since "$test_started" --no-pager -o short-iso
    fi
    printf 'Verified-timing wrapper exit=%s. Success keeps the temporary module loaded for physical confirmation; nothing is installed.\n' "$result"
    exit "$result"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
[[ $(/usr/bin/uname -r) == 7.1.9-arch1-2 ]]
[[ ! -d /sys/module/trigger6 && ! -d /sys/module/evdi ]]
[[ ! -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]]
[[ ! -e /sys/class/drm/card0 ]]
[[ $(/usr/bin/sha256sum "${repo_root}/kernel/trigger6.ko") == "cec6a3429df95e8b3d79ab01e02ff0b7ff96ccee5aa39a11ad30938c09374c35  ${repo_root}/kernel/trigger6.ko" ]]
[[ $(/usr/bin/modinfo -F vermagic "${repo_root}/kernel/trigger6.ko") == '7.1.9-arch1-2 SMP preempt mod_unload ' ]]
check_device
test_started=$(/usr/bin/date --iso-8601=seconds)
printf 'Verified-timing test start: %s\n' "$test_started"
insert_attempted=1
/usr/bin/timeout --signal=TERM --kill-after=2s 12s /usr/bin/insmod "${repo_root}/kernel/trigger6.ko" device_path=2-1.4.1 manual_only=0 output_mask=1 query_only=0 query_timings=0 query_timing_page1=0 aquamarine_evdi_name=1 raw_idle_refresh=1 serialize_usb_bus=1
[[ $(</sys/module/trigger6/srcversion) == F6D5C7316849C7428A83002 ]]
[[ $(</sys/module/trigger6/parameters/query_only) == N ]]
[[ $(</sys/module/trigger6/parameters/query_timings) == N ]]
[[ $(</sys/module/trigger6/parameters/raw_idle_refresh) == Y ]]
[[ $(</sys/module/trigger6/parameters/aquamarine_evdi_name) == Y ]]
printf '%s\n' 'Guarded corrected timing inserted. Ninety-second fault watcher begins; user-session pattern/DPMS may run now.'
for sample in {0..89}; do
    check_device
    [[ $(/usr/bin/readlink -f /sys/class/drm/card0/device) == $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0) ]]
    metrics=$(/usr/bin/head -c 16384 /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics)
    if /usr/bin/rg -q '(io_faulted|io_last_error|send_errors|transport_faults|bulk_errors|bulk_short_writes|keepalive_errors|last_error)=[1-9-]' <<< "$metrics"; then
        printf '%s\n' "$metrics" >&2
        exit 1
    fi
    watch_log=$(/usr/bin/journalctl -k --since "$test_started" --no-pager -o cat)
    if /usr/bin/rg -q 'WARNING:|BUG:|Oops:|general protection fault|xhci.*(ERROR|timed out|not responding)' <<< "$watch_log"; then
        exit 1
    fi
    if (( sample % 5 == 0 )); then
        /usr/bin/date --iso-8601=seconds
        printf '%s\n' "$metrics"
    fi
    /usr/bin/sleep 1
done
[[ $metrics =~ head0[[:space:]]sent_frames=([0-9]+) ]]
[[ ${BASH_REMATCH[1]} != 0 ]]
test_success=1
printf '%s\n' 'Bounded transport watcher passed; physical readability still requires the user. Module remains temporary and loaded.'
