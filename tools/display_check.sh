#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Unprivileged terminal-only visual check. No device/configuration access.
set -eu
printf '\033[2J\033[H\033[1;36mJCD543 / HP X27q display check\033[0m\n\n'
printf 'This window should be readable on the external HP monitor.\n'
printf '1920 x 1080 at 60 Hz is the fixed test mode.\n'
printf '\033[41m RED \033[42m GREEN \033[44m BLUE \033[0m  black / white text\n\n'
for frame in {1..10}; do
    printf '\rLive update: %2d / 10' "$frame"
    /usr/bin/sleep 1
done
printf '\n\nCheck text, colors, and updates; report any blanking or corruption.\n'
printf 'Press Enter to close this temporary test window.\n'
read -r display_ack
