#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# One reviewed head-1 IN-only probe, then restoration of the saved head-0 build.
set -euo pipefail
export PATH=/usr/bin
if [[ $# != 1 || $1 != --run-reviewed-head1-query || $EUID != 0 ]]; then
    printf '%s\n' 'Inert: requires explicit reviewed root invocation with --run-reviewed-head1-query.' >&2
    exit 2
fi
# Resolve this reviewed checkout, not a caller-supplied path or working directory.
script_path=$(/usr/bin/realpath -e -- "${BASH_SOURCE[0]}")
repo_root=${script_path%/tools/query_head1_restore.sh}
[[ $repo_root != "$script_path" && -f "$repo_root/Makefile" && -f "$repo_root/LICENSE" ]]
readonly script_path repo_root
trap 'result=$?; printf "Head1 query/restore wrapper exit=%s\n" "$result"' EXIT

check_device() {
    [[ $(</sys/bus/usb/devices/2-1.4.1/idVendor) == 0711 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/idProduct) == 5601 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/bcdDevice) == 1010 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/speed) == 5000 ]]
    [[ $(</sys/bus/usb/devices/2-1.4.1/devnum) == 101 ]]
    [[ $(/usr/bin/sha256sum /sys/bus/usb/devices/2-1.4.1/descriptors) == '61ed0a266c3b3db8f8be6dfab701a1fa9e1e1a1e1cd7681f14999e854c01b12f  /sys/bus/usb/devices/2-1.4.1/descriptors' ]]
    [[ $(</sys/class/tty/tty0/active) == tty2 ]]
    [[ $(</sys/class/drm/card1-eDP-1/status) == connected ]]
    [[ $(</proc/sys/kernel/tainted) == 12288 ]]
}
unbind_exact() {
    [[ $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0/driver) == /sys/bus/usb/drivers/trigger6 ]]
    /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/tee /sys/bus/usb/drivers/trigger6/unbind <<< '2-1.4.1:1.0'
    [[ ! -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]]
    [[ ! -e /sys/class/drm/card0 ]]
}
remove_unbound() {
    for attempt in {1..20}; do
        [[ $(</sys/module/trigger6/refcnt) == 0 ]] && break
        /usr/bin/sleep 0.1
    done
    [[ $(</sys/module/trigger6/refcnt) == 0 ]]
    /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/rmmod trigger6
    [[ ! -d /sys/module/trigger6 ]]
}
[[ $(/usr/bin/uname -r) == 7.1.9-arch1-2 ]]
[[ $(</sys/module/trigger6/srcversion) == 3C037EE0098BDEC7A3211D5 ]]
[[ $(</sys/module/trigger6/parameters/device_path) == 2-1.4.1 ]]
[[ $(</sys/module/trigger6/parameters/manual_only) == N ]]
[[ $(</sys/module/trigger6/parameters/output_mask) == 1 ]]
[[ $(</sys/module/trigger6/parameters/aquamarine_evdi_name) == Y ]]
[[ $(</sys/module/trigger6/parameters/raw_idle_refresh) == Y ]]
[[ $(</sys/module/trigger6/parameters/serialize_usb_bus) == Y ]]
[[ $(/usr/bin/sha256sum "${repo_root}/kernel/trigger6.ko") == "3564df8fc611461d252483dcaaf5c751c72bfe2651e8353d167e1e2dfd8ed802  ${repo_root}/kernel/trigger6.ko" ]]
[[ $(/usr/bin/sha256sum "${repo_root}/artifacts/runtime-2026-09-05/trigger6-idle-refresh-proven.ko") == "71c43fee30514153bdda59a1ed20a08b9b7c35f43550652c3d3ee75d4c47a064  ${repo_root}/artifacts/runtime-2026-09-05/trigger6-idle-refresh-proven.ko" ]]
check_device
query_started=$(/usr/bin/date --iso-8601=seconds)
printf 'Query/restore start: %s\n' "$query_started"
/usr/bin/head -c 16384 /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics
[[ $(/usr/bin/readlink -f /sys/class/drm/card0/device) == $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0) ]]
unbind_exact
remove_unbound
check_device
/usr/bin/timeout --signal=TERM --kill-after=2s 12s /usr/bin/insmod "${repo_root}/kernel/trigger6.ko" device_path=2-1.4.1 manual_only=0 output_mask=2 query_only=1 aquamarine_evdi_name=0 raw_idle_refresh=0 serialize_usb_bus=1
[[ $(</sys/module/trigger6/srcversion) == DE5C92E23618EE9D77CE6F7 ]]
[[ $(</sys/module/trigger6/parameters/query_only) == Y ]]
[[ $(</sys/module/trigger6/parameters/output_mask) == 2 ]]
[[ ! -e /sys/class/drm/card0 ]]
/usr/bin/journalctl -k --since "$query_started" --no-pager -o short-iso | /usr/bin/rg 'trigger6|usb 2-1\.4\.1'
# A successful query-only probe binds with NULL data, even for status 0/no sink.
# Any failed IN/EDID query leaves it unbound: stop, do not retry hardware/restore.
if [[ ! -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]]; then
    printf '%s\n' 'Query did not complete cleanly; no head1 frames or automatic head0 reinitialization.' >&2
    exit 1
fi
check_device
printf '%s\n' 'Head1 queries complete with no DRM/frame activation. Restoring preserved head0 artifact.'
unbind_exact
remove_unbound
check_device
/usr/bin/timeout --signal=TERM --kill-after=2s 12s /usr/bin/insmod "${repo_root}/artifacts/runtime-2026-09-05/trigger6-idle-refresh-proven.ko" device_path=2-1.4.1 manual_only=0 output_mask=1 aquamarine_evdi_name=1 raw_idle_refresh=1 serialize_usb_bus=1
check_device
[[ $(</sys/module/trigger6/srcversion) == 3C037EE0098BDEC7A3211D5 ]]
[[ $(</sys/module/trigger6/parameters/output_mask) == 1 ]]
[[ $(</sys/module/trigger6/parameters/raw_idle_refresh) == Y ]]
[[ $(/usr/bin/readlink -f /sys/bus/usb/devices/2-1.4.1:1.0/driver) == /sys/bus/usb/drivers/trigger6 ]]
/usr/bin/head -c 16384 /sys/bus/usb/devices/2-1.4.1:1.0/t6_metrics
printf '%s\n' 'Preserved head0 artifact restored. Head1 was never modeset or sent a frame.'
