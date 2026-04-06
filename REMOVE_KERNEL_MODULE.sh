#!/bin/bash
# Completely remove the trigger6 kernel module from this system.
# After running this, the adapter will no longer auto-load the
# kernel driver.  The userspace Python driver still works standalone.
echo "Removing trigger6 kernel module..."
sudo rm -f /lib/modules/$(uname -r)/extra/trigger6.ko
sudo rm -f /etc/modules-load.d/trigger6.conf
echo "blacklist trigger6" | sudo tee /etc/modprobe.d/trigger6-blacklist.conf
sudo depmod -a
sudo rmmod trigger6 2>/dev/null
echo "Done. The adapter will no longer auto-load the kernel driver."
echo "The userspace Python driver (userspace/mct_t6_display.py) still works."
