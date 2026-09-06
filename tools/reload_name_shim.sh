#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# One explicitly authorized, exact-device runtime reload. Never an installer.
set -eu
export PATH=/usr/bin

if [[ $# != 1 || $1 != --run-reviewed-head0-shim || $EUID != 0 ]]; then
    printf '%s\n' 'Inert: requires explicit reviewed root invocation with --run-reviewed-head0-shim.' >&2
    exit 2
fi
# Resolve this reviewed checkout, not a caller-supplied path or working directory.
script_path=$(/usr/bin/realpath -e -- "${BASH_SOURCE[0]}")
repo_root=${script_path%/tools/reload_name_shim.sh}
[[ $repo_root != "$script_path" && -f "$repo_root/Makefile" && -f "$repo_root/LICENSE" ]]
readonly script_path repo_root

[[ $(</sys/class/tty/tty0/active) == tty2 ]]
[[ $(/usr/bin/uname -r) == 7.1.9-arch1-2 ]]
[[ $(</sys/module/trigger6/parameters/manual_only) == N ]]
[[ $(</sys/module/trigger6/parameters/output_mask) == 1 ]]
[[ $(</sys/module/trigger6/parameters/device_path) == 2-3.4.1 ]]
[[ $(</sys/bus/usb/devices/2-3.4.1/idVendor) == 0711 ]]
[[ $(</sys/bus/usb/devices/2-3.4.1/idProduct) == 5601 ]]
[[ $(</sys/bus/usb/devices/2-3.4.1/bcdDevice) == 1010 ]]
[[ ! -d /sys/module/evdi ]]
[[ $(/usr/bin/sha256sum "${repo_root}/kernel/trigger6.ko") == "6eff96df530353d1a6e296616990c72c5b90881439a4552b81f9f867cf515c04  ${repo_root}/kernel/trigger6.ko" ]]
[[ $(/usr/bin/sha256sum "${repo_root}/artifacts/runtime-2026-09-05/trigger6-kms-proven.ko") == "9fc97547029ebcd91bb1876f28b1d62f144110374a4af4849e3503840567fc14  ${repo_root}/artifacts/runtime-2026-09-05/trigger6-kms-proven.ko" ]]
initial_taint=$(</proc/sys/kernel/tainted)

/usr/bin/date --iso-8601=seconds
if [[ -L /sys/bus/usb/devices/2-3.4.1:1.0/driver ]]; then
    [[ $(/usr/bin/readlink -f /sys/bus/usb/devices/2-3.4.1:1.0/driver) == /sys/bus/usb/drivers/trigger6 ]]
    [[ $(/usr/bin/readlink -f /sys/class/drm/card0/device) == $(/usr/bin/readlink -f /sys/bus/usb/devices/2-3.4.1:1.0) ]]
    printf '%s\n' 'Unbinding only trigger6 interface 2-3.4.1:1.0; hubs and other interfaces remain untouched.'
    /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/tee /sys/bus/usb/drivers/trigger6/unbind <<< '2-3.4.1:1.0'
else
    printf '%s\n' 'Previous probe left the interface unbound; no unbind write is needed.'
fi
[[ ! -L /sys/bus/usb/devices/2-3.4.1:1.0/driver ]]
[[ ! -e /sys/class/drm/card0 ]]
printf '%s\n' 'Exact interface is unbound and its DRM card is removed.'
for attempt in {1..20}; do
    [[ $(</sys/module/trigger6/refcnt) == 0 ]] && break
    /usr/bin/sleep 0.1
done
[[ $(</sys/module/trigger6/refcnt) == 0 ]]
/usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/rmmod trigger6
[[ ! -d /sys/module/trigger6 ]]
[[ $(</proc/sys/kernel/tainted) == "$initial_taint" ]]
printf '%s\n' 'Old module removed cleanly; revalidating device before explicit compatibility insertion.'

[[ $(</sys/bus/usb/devices/2-3.4.1/idVendor) == 0711 ]]
[[ $(</sys/bus/usb/devices/2-3.4.1/idProduct) == 5601 ]]
[[ $(</sys/bus/usb/devices/2-3.4.1/bcdDevice) == 1010 ]]
[[ $(</sys/bus/usb/devices/2-3.4.1/speed) == 5000 ]]
[[ ! -L /sys/bus/usb/devices/2-3.4.1:1.0/driver ]]
/usr/bin/timeout --signal=TERM --kill-after=2s 12s /usr/bin/insmod "${repo_root}/kernel/trigger6.ko" device_path=2-3.4.1 manual_only=0 output_mask=1 aquamarine_evdi_name=1
if [[ $(/usr/bin/readlink -f /sys/bus/usb/devices/2-3.4.1:1.0/driver) != /sys/bus/usb/drivers/trigger6 ]]; then
    printf '%s\n' 'Probe refused the device: module is resident, interface unbound. Inspect the raw status in the kernel journal.' >&2
    exit 1
fi
[[ $(</sys/module/trigger6/parameters/aquamarine_evdi_name) == Y ]]
/usr/bin/date --iso-8601=seconds
/usr/bin/head -c 16384 /sys/bus/usb/devices/2-3.4.1:1.0/t6_metrics
printf '%s\n' 'Temporary head-0 name-shim module is bound. Observe frames and kernel logs before calling it working.'
