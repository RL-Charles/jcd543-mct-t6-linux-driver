#!/usr/bin/env bash
set -euo pipefail

VID="0711"
PID="5601"
MODULE="trigger6"
DEFAULT_MODULE_ARGS="${TRIGGER6_MODULE_ARGS:-jpeg_quality=85 manual_only=1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() {
	printf '%s\n' "$*"
}

warn() {
	printf 'warning: %s\n' "$*" >&2
}

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

host_exec() {
	if command -v host-spawn >/dev/null 2>&1; then
		host-spawn "$@"
	elif [[ -n "${FLATPAK_ID:-}" ]] && command -v flatpak-spawn >/dev/null 2>&1; then
		flatpak-spawn --host "$@"
	else
		"$@"
	fi
}

host_shell() {
	local script=$1
	shift || true
	host_exec env \
		REPO_ROOT="$REPO_ROOT" \
		VID="$VID" \
		PID="$PID" \
		MODULE="$MODULE" \
		DEFAULT_MODULE_ARGS="$DEFAULT_MODULE_ARGS" \
		"$@" \
		sh -lc "$script"
}

module_loaded() {
	host_shell 'lsmod | grep -q "^${MODULE}[[:space:]]"'
}

t6_attached() {
	host_shell 'lsusb -d "${VID}:${PID}" >/dev/null 2>&1'
}

list_t6_usb() {
	host_shell 'lsusb -d "${VID}:${PID}" 2>/dev/null || true'
}

list_t6_sysfs() {
	host_shell '
		for path in /sys/bus/usb/devices/*; do
			[ -f "$path/idVendor" ] || continue
			[ -f "$path/idProduct" ] || continue
			[ "$(cat "$path/idVendor")" = "$VID" ] || continue
			[ "$(cat "$path/idProduct")" = "$PID" ] || continue
			authorized=$(cat "$path/authorized" 2>/dev/null || echo "?")
			printf "%s authorized=%s\n" "$path" "$authorized"
		done
	'
}

host_conflicts_active() {
	host_shell '
		if lsmod | grep -Eq "^(evdi|udl|udlfb)[[:space:]]"; then
			exit 0
		fi
		if [ -f /etc/udev/rules.d/99-displaylink-mct.rules ]; then
			exit 0
		fi
		exit 1
	'
}

list_host_conflicts() {
	host_shell '
		if lsmod | grep -Eq "^(evdi|udl|udlfb)[[:space:]]"; then
			echo "active kernel modules:";
			lsmod | grep -E "^(evdi|udl|udlfb)[[:space:]]";
		fi
		if [ -f /etc/udev/rules.d/99-displaylink-mct.rules ]; then
			echo "active udev rule: /etc/udev/rules.d/99-displaylink-mct.rules";
			sed -n "1,20p" /etc/udev/rules.d/99-displaylink-mct.rules;
		fi
		if [ -f /etc/modprobe.d/trigger6-blacklist.conf ]; then
			echo "note: /etc/modprobe.d/trigger6-blacklist.conf is present (explicit modprobe still works)";
		fi
		if [ -f /etc/udev/rules.d/99-displaylink-mct.rules.disabled ]; then
			echo "note: stale DisplayLink rule is present but disabled at /etc/udev/rules.d/99-displaylink-mct.rules.disabled";
		fi
	'
}

any_t6_authorized() {
	host_shell '
		for path in /sys/bus/usb/devices/*; do
			[ -f "$path/idVendor" ] || continue
			[ -f "$path/idProduct" ] || continue
			[ "$(cat "$path/idVendor")" = "$VID" ] || continue
			[ "$(cat "$path/idProduct")" = "$PID" ] || continue
			[ -f "$path/authorized" ] || continue
			[ "$(cat "$path/authorized")" = "1" ] || continue
			exit 0
		done
		exit 1
	'
}

list_t6_drm_outputs() {
	host_shell '
		for path in /sys/class/drm/card*-*; do
			[ -e "$path" ] || continue
			module_path=$(readlink -f "$path/device/driver/module" 2>/dev/null || true)
			[ "$(basename "$module_path")" = "$MODULE" ] || continue
			base=$(basename "$path")
			printf "%s\n" "${base#*-}"
		done
	'
}

list_t6_device_nodes() {
	host_shell '
		{
			for path in /sys/class/drm/card*-*; do
				[ -e "$path" ] || continue
				module_path=$(readlink -f "$path/device/driver/module" 2>/dev/null || true)
				[ "$(basename "$module_path")" = "$MODULE" ] || continue
				base=$(basename "$path")
				card=${base%%-*}
				node="/dev/dri/$card"
				[ -e "$node" ] && printf "%s\n" "$node"
			done
			for path in /dev/trigger6-*-out*-jpeg; do
				[ -e "$path" ] || continue
				printf "%s\n" "$path"
			done
		} | sort -u
	'
}

fd_inspector_available() {
	host_shell 'command -v fuser >/dev/null 2>&1 || command -v lsof >/dev/null 2>&1'
}

t6_open_fds_present() {
	host_shell '
		nodes=$(
			{
				for path in /sys/class/drm/card*-*; do
					[ -e "$path" ] || continue
					module_path=$(readlink -f "$path/device/driver/module" 2>/dev/null || true)
					[ "$(basename "$module_path")" = "$MODULE" ] || continue
					base=$(basename "$path")
					card=${base%%-*}
					node="/dev/dri/$card"
					[ -e "$node" ] && printf "%s\n" "$node"
				done
				for path in /dev/trigger6-*-out*-jpeg; do
					[ -e "$path" ] || continue
					printf "%s\n" "$path"
				done
			} | sort -u
		)
		[ -n "$nodes" ] || exit 1
		if command -v fuser >/dev/null 2>&1; then
			sudo fuser $nodes >/dev/null 2>&1
		elif command -v lsof >/dev/null 2>&1; then
			sudo lsof $nodes >/dev/null 2>&1
		else
			exit 2
		fi
	'
}

list_t6_open_fds() {
	host_shell '
		nodes=$(
			{
				for path in /sys/class/drm/card*-*; do
					[ -e "$path" ] || continue
					module_path=$(readlink -f "$path/device/driver/module" 2>/dev/null || true)
					[ "$(basename "$module_path")" = "$MODULE" ] || continue
					base=$(basename "$path")
					card=${base%%-*}
					node="/dev/dri/$card"
					[ -e "$node" ] && printf "%s\n" "$node"
				done
				for path in /dev/trigger6-*-out*-jpeg; do
					[ -e "$path" ] || continue
					printf "%s\n" "$path"
				done
			} | sort -u
		)
		[ -n "$nodes" ] || exit 0
		if command -v fuser >/dev/null 2>&1; then
			sudo fuser -v $nodes 2>/dev/null || true
		elif command -v lsof >/dev/null 2>&1; then
			sudo lsof $nodes 2>/dev/null || true
		else
			printf "%s\n" "fuser/lsof not available on the host"
		fi
	'
}

disable_t6_outputs() {
	local output

	if ! host_shell 'command -v cosmic-randr >/dev/null 2>&1'; then
		return 0
	fi

	while IFS= read -r output; do
		[ -n "$output" ] || continue
		host_exec cosmic-randr disable "$output" >/dev/null 2>&1 || true
	done < <(list_t6_drm_outputs)
}

stop_userspace_service() {
	host_shell 'systemctl --user disable --now mct-t6-display.service >/dev/null 2>&1 || true'
}

quarantine_t6_usb() {
	disable_t6_outputs
	say "Quarantining attached T6 USB devices"
	host_shell '
		changed=0
		for path in /sys/bus/usb/devices/*; do
			[ -f "$path/idVendor" ] || continue
			[ -f "$path/idProduct" ] || continue
			[ "$(cat "$path/idVendor")" = "$VID" ] || continue
			[ "$(cat "$path/idProduct")" = "$PID" ] || continue
			if [ -f "$path/authorized" ] && [ "$(cat "$path/authorized")" != "0" ]; then
				printf 0 | sudo tee "$path/authorized" >/dev/null
				printf "%s\n" "$path"
				changed=1
			fi
		done
		[ "$changed" -eq 1 ] || printf "%s\n" "already quarantined or not present"
	'
}

unquarantine_t6_usb() {
	say "Reauthorizing quarantined T6 USB devices"
	host_shell '
		changed=0
		for path in /sys/bus/usb/devices/*; do
			[ -f "$path/idVendor" ] || continue
			[ -f "$path/idProduct" ] || continue
			[ "$(cat "$path/idVendor")" = "$VID" ] || continue
			[ "$(cat "$path/idProduct")" = "$PID" ] || continue
			if [ -f "$path/authorized" ] && [ "$(cat "$path/authorized")" = "0" ]; then
				printf 1 | sudo tee "$path/authorized" >/dev/null
				printf "%s\n" "$path"
				changed=1
			fi
		done
		[ "$changed" -eq 1 ] || printf "%s\n" "already authorized or not present"
	'
}

build_module() {
	say "Building trigger6 on the host"
	host_shell 'cd "$REPO_ROOT/kernel" && make -j"$(nproc)"'
}

stage_module() {
	build_module
	say "Installing trigger6.ko into /lib/modules/$(host_exec uname -r)/extra"
	host_shell '
		cd "$REPO_ROOT/kernel"
		sudo mkdir -p "/lib/modules/$(uname -r)/extra"
		sudo install -m 0644 trigger6.ko "/lib/modules/$(uname -r)/extra/trigger6.ko"
		sudo depmod -a
	'
}

load_module() {
	if module_loaded; then
		say "trigger6 is already loaded"
		return 0
	fi

	if [[ "$DEFAULT_MODULE_ARGS" != *"manual_only=1"* ]]; then
		if [[ "${TRIGGER6_ALLOW_LIVE_SCANOUT:-0}" != "1" ]]; then
			die "refusing to load trigger6 without manual_only=1. Set TRIGGER6_ALLOW_LIVE_SCANOUT=1 only when you intentionally want compositor-driven DRM scanout risk"
		fi
		warn "Loading trigger6 with live DRM scanout enabled; host instability is still possible"
	fi

	stop_userspace_service
	say "Loading trigger6 with: ${DEFAULT_MODULE_ARGS}"
	host_shell 'sudo modprobe "$MODULE" ${DEFAULT_MODULE_ARGS}'
}

safe_unload() {
	if ! module_loaded; then
		say "trigger6 is not loaded"
		return 0
	fi

	disable_t6_outputs

	if fd_inspector_available && t6_open_fds_present; then
		say "Processes still hold trigger6 device nodes open:"
		list_t6_open_fds || true
		die "Refusing to unload trigger6 while compositor or helper processes still hold trigger6 device nodes open. Stop them first or reboot."
	fi

	if t6_attached; then
		die "Refusing to unload trigger6 while a T6 adapter is attached. Unplug the dongle or reboot, then retry."
	fi

	if ! host_shell 'sudo modprobe -r "$MODULE"'; then
		die "trigger6 is still in use. Reboot before attempting another live kernel test."
	fi
}

safe_reload() {
	stage_module
	safe_unload
	load_module
}

arm_quarantined() {
	quarantine_t6_usb
	if any_t6_authorized; then
		die "T6 USB quarantine did not take effect; refusing to load trigger6 against live attached devices."
	fi
	stage_module
	load_module
}

status() {
	say "Kernel:"
	host_exec uname -r

	say
	say "Default guarded module args:"
	say "$DEFAULT_MODULE_ARGS"

	say
	say "Module:"
	if module_loaded; then
		host_shell 'lsmod | grep "^${MODULE}[[:space:]]"'
		say
		say "Active trigger6 parameters:"
		host_shell '
			for name in manual_only secondary_userspace_jpeg experimental_secondary_raw jpeg_quality; do
				path="/sys/module/${MODULE}/parameters/$name"
				[ -f "$path" ] || continue
				printf "%s=%s\n" "$name" "$(cat "$path")"
			done
		'
	else
		say "not loaded"
	fi

	say
	say "Attached T6 USB devices:"
	list_t6_usb

	say
	say "Potential host conflicts:"
	list_host_conflicts || true

	say
	say "T6 USB sysfs state:"
	list_t6_sysfs || true

	say
	say "Trigger6-backed DRM outputs:"
	list_t6_drm_outputs || true

	say
	say "Trigger6 device nodes:"
	list_t6_device_nodes || true

	say
	say "Trigger6 open file descriptors:"
	if fd_inspector_available; then
		if t6_open_fds_present; then
			list_t6_open_fds || true
		else
			say "none"
		fi
	else
		say "fuser/lsof not available on the host"
	fi

	if host_shell 'command -v cosmic-randr >/dev/null 2>&1'; then
		say
		say "COSMIC outputs:"
		host_exec cosmic-randr list || true
	fi
}

collect_logs() {
	local stamp report_path
	stamp=$(date +%Y%m%d-%H%M%S)
	report_path="${1:-$REPO_ROOT/tools/trigger6-host-report-${stamp}.log}"

	say "Writing host report to ${report_path}"
	host_shell '
		{
			echo "== uname -a =="
			uname -a
			echo
			echo "== lsmod | grep trigger6 =="
			lsmod | grep "^${MODULE}[[:space:]]" || true
			echo
			echo "== lsusb -d ${VID}:${PID} =="
			lsusb -d "${VID}:${PID}" || true
			echo
			echo "== trigger6-backed DRM outputs =="
			for path in /sys/class/drm/card*-*; do
				[ -e "$path" ] || continue
				module_path=$(readlink -f "$path/device/driver/module" 2>/dev/null || true)
				[ "$(basename "$module_path")" = "$MODULE" ] || continue
				status=$(cat "$path/status" 2>/dev/null || true)
				printf "%s %s\n" "$(basename "$path")" "$status"
			done
			echo
			echo "== trigger6 device nodes =="
			{
				for path in /sys/class/drm/card*-*; do
					[ -e "$path" ] || continue
					module_path=$(readlink -f "$path/device/driver/module" 2>/dev/null || true)
					[ "$(basename "$module_path")" = "$MODULE" ] || continue
					base=$(basename "$path")
					card=${base%%-*}
					node="/dev/dri/$card"
					[ -e "$node" ] && printf "%s\n" "$node"
				done
				for path in /dev/trigger6-*-out*-jpeg; do
					[ -e "$path" ] || continue
					printf "%s\n" "$path"
				done
			} | sort -u
			echo
			echo "== trigger6 open file descriptors =="
			nodes=$(
				{
					for path in /sys/class/drm/card*-*; do
						[ -e "$path" ] || continue
						module_path=$(readlink -f "$path/device/driver/module" 2>/dev/null || true)
						[ "$(basename "$module_path")" = "$MODULE" ] || continue
						base=$(basename "$path")
						card=${base%%-*}
						node="/dev/dri/$card"
						[ -e "$node" ] && printf "%s\n" "$node"
					done
					for path in /dev/trigger6-*-out*-jpeg; do
						[ -e "$path" ] || continue
						printf "%s\n" "$path"
					done
				} | sort -u
			)
			if [ -z "$nodes" ]; then
				echo "none"
			elif command -v fuser >/dev/null 2>&1; then
				sudo fuser -v $nodes 2>/dev/null || true
			elif command -v lsof >/dev/null 2>&1; then
				sudo lsof $nodes 2>/dev/null || true
			else
				echo "fuser/lsof not available on the host"
			fi
			echo
			echo "== recent dmesg =="
			sudo dmesg | tail -n 300
		} > "$REPORT_PATH"
	' REPORT_PATH="$report_path"
}

usage() {
	cat <<'EOF'
Usage: tools/trigger6-host-guard.sh <command>

Commands:
  status        Show the live host trigger6 state
  build         Build trigger6.ko against the real host headers
  stage         Build and install trigger6.ko into /lib/modules/.../extra
	load          Load trigger6 with TRIGGER6_MODULE_ARGS or jpeg_quality=85
	quarantine    Deauthorize attached T6 USB devices without physically unplugging them
	unquarantine  Reauthorize previously quarantined T6 USB devices
	arm           Quarantine attached T6 USB devices, then stage and load trigger6 safely
  safe-unload   Disable COSMIC trigger6 outputs, then unload only if the T6 dongle is detached
  safe-reload   Stage the module, then perform the guarded unload and reload sequence
	conflicts     Print known host-side driver/rule conflicts and exit nonzero if any active conflict remains
  collect [p]   Save a host diagnostics report to the optional path p

Notes:
  - This wrapper intentionally refuses live reloads while a T6 USB adapter is attached.
	- `safe-unload` also refuses if any process still has a trigger6 DRM or JPEG node open.
	- `arm` is the lowest-risk live prep path: the module loads, but the attached T6 devices stay logically detached until you explicitly `unquarantine` them.
	- The default guarded module arguments are `jpeg_quality=85 manual_only=1`, which keeps DRM connectors disconnected and exercises the native in-kernel JPEG path.
  - If trigger6 is already wedged in teardown, reboot instead of forcing another reload.
	- Override the module arguments with TRIGGER6_MODULE_ARGS='jpeg_quality=85 manual_only=0 foo=bar' only when you intentionally want live DRM scanout risk.
	- The wrapper refuses `manual_only=0` unless you also export TRIGGER6_ALLOW_LIVE_SCANOUT=1 for that command.
EOF
}

command=${1:-}
case "$command" in
	status)
		status
		;;
	build)
		build_module
		;;
	stage)
		stage_module
		;;
	load)
		load_module
		;;
	quarantine)
		quarantine_t6_usb
		;;
	unquarantine)
		unquarantine_t6_usb
		;;
	arm)
		arm_quarantined
		;;
	safe-unload)
		safe_unload
		;;
	safe-reload)
		safe_reload
		;;
	collect)
		shift || true
		collect_logs "${1:-}"
		;;
	conflicts)
		list_host_conflicts
		if host_conflicts_active; then
			exit 1
		fi
		;;
	""|-h|--help|help)
		usage
		;;
	*)
		usage >&2
		exit 1
		;;
esac