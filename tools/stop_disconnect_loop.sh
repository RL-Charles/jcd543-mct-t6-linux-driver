#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Stop the observed device reconnect loop without any USB/sysfs control write.
set -eu
export PATH=/usr/bin
if [[ $# != 1 || $1 != --run-reviewed-stop-loop || $EUID != 0 ]]; then
    printf '%s\n' 'Inert: requires explicit reviewed root invocation with --run-reviewed-stop-loop.' >&2
    exit 2
fi
[[ $(/usr/bin/uname -r) == 7.1.9-arch1-2 ]]
[[ $(</sys/module/trigger6/srcversion) == DC2FAAE96B693A6F3C47599 ]]
[[ $(</sys/module/trigger6/parameters/device_path) == 2-1.4.1 ]]
[[ $(</sys/module/trigger6/parameters/manual_only) == N ]]
[[ $(</sys/module/trigger6/parameters/output_mask) == 1 ]]
[[ $(</sys/module/trigger6/parameters/aquamarine_evdi_name) == Y ]]
/usr/bin/date --iso-8601=seconds
printf '%s\n' 'Waiting up to 15 seconds for physical/device disconnect and zero module references; never forcing removal.'
for attempt in {1..150}; do
    if [[ $(</sys/module/trigger6/refcnt) == 0 && ! -L /sys/bus/usb/devices/2-1.4.1:1.0/driver ]]; then
        /usr/bin/timeout --signal=TERM --kill-after=2s 8s /usr/bin/rmmod trigger6
        [[ ! -d /sys/module/trigger6 ]]
        /usr/bin/date --iso-8601=seconds
        printf '%s\n' 'Experimental module removed. Re-enumerations can no longer trigger its probe.'
        exit 0
    fi
    /usr/bin/sleep 0.1
done
printf '%s\n' 'No safe removal window occurred. Physically unplug dock USB-C; do not force or stack unload commands.' >&2
exit 1
