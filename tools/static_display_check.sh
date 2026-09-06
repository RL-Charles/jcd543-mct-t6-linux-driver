#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# No device/configuration access. Hide the cursor to avoid animated damage.
set -eu
trap 'printf "\033[?25h\033[0m"' EXIT
printf '\033[40m\033[97m\033[2J\033[H\033[?25l'
printf '\n  JCD543 / HP X27q\n\n  STATIC DISPLAY CHECK\n\n'
printf '  White text on black should be readable.\n'
printf '  The image below should stay still.\n\n'
printf '  \033[41m       RED       \033[42m      GREEN      \033[44m       BLUE      \033[40m\n\n'
printf '  1920 x 1080 @ 60 Hz\n\n'
printf '  Tell us if this is blank, corrupted, or readable.\n\n'
printf '  Press Enter in this window to close it.\n'
read -r display_ack
