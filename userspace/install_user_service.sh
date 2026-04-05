#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="$UNIT_DIR/mct-t6-display.service"
TEMPLATE="$SCRIPT_DIR/mct-t6-display.service"
PYTHON_BIN="/usr/bin/env python3"

if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
	PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
fi

mkdir -p "$UNIT_DIR"

if command -v systemctl >/dev/null 2>&1; then
	set +e
	systemctl --user import-environment \
		DBUS_SESSION_BUS_ADDRESS DISPLAY WAYLAND_DISPLAY XAUTHORITY \
		XDG_RUNTIME_DIR XDG_SESSION_TYPE
	set -e
fi

if command -v dbus-update-activation-environment >/dev/null 2>&1; then
	set +e
	dbus-update-activation-environment --systemd \
		DBUS_SESSION_BUS_ADDRESS DISPLAY WAYLAND_DISPLAY XAUTHORITY \
		XDG_RUNTIME_DIR XDG_SESSION_TYPE
	set -e
fi

sed \
	-e "s|REPO_ROOT|$REPO_ROOT|g" \
	-e "s|PYTHON_BIN|$PYTHON_BIN|g" \
	"$TEMPLATE" > "$UNIT_PATH"

systemctl --user daemon-reload
systemctl --user enable --now mct-t6-display.service

echo "Installed $UNIT_PATH"
echo "Current status:"
systemctl --user --no-pager --full status mct-t6-display.service || true
