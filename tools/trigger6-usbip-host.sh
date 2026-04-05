#!/usr/bin/env bash
set -euo pipefail

VID="0711"
PID="5601"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST_TOOLS_DIR="$REPO_ROOT/tools/.host-tools/usbip"
SRC_CACHE_DIR="$HOST_TOOLS_DIR/cache"
SRC_DIR="$HOST_TOOLS_DIR/src"
PREFIX_DIR="$HOST_TOOLS_DIR/prefix"
RUN_DIR="$HOST_TOOLS_DIR/run"

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
		VID="$VID" \
		PID="$PID" \
		REPO_ROOT="$REPO_ROOT" \
		HOST_TOOLS_DIR="$HOST_TOOLS_DIR" \
		SRC_CACHE_DIR="$SRC_CACHE_DIR" \
		SRC_DIR="$SRC_DIR" \
		PREFIX_DIR="$PREFIX_DIR" \
		RUN_DIR="$RUN_DIR" \
		"$@" \
		sh -lc "$script"
}

host_kernel_base_version() {
	host_shell 'uname -r | sed -E "s/^([0-9]+\.[0-9]+\.[0-9]+).*/\1/"'
}

usbip_tarball_url() {
	local version=$1
	local major=${version%%.*}
	printf 'https://cdn.kernel.org/pub/linux/kernel/v%s.x/linux-%s.tar.xz\n' "$major" "$version"
}

usbip_prefix() {
	local version=$1
	printf '%s/%s\n' "$PREFIX_DIR" "$version"
}

usbip_bin() {
	local version=$1
	printf '%s/sbin/usbip\n' "$(usbip_prefix "$version")"
}

usbipd_bin() {
	local version=$1
	printf '%s/sbin/usbipd\n' "$(usbip_prefix "$version")"
}

pidfile_path() {
	printf '%s/usbipd.pid\n' "$RUN_DIR"
}

logfile_path() {
	printf '%s/usbipd.log\n' "$RUN_DIR"
}

list_t6_busids() {
	host_shell '
		for path in /sys/bus/usb/devices/*; do
			[ -f "$path/idVendor" ] || continue
			[ -f "$path/idProduct" ] || continue
			[ "$(cat "$path/idVendor")" = "$VID" ] || continue
			[ "$(cat "$path/idProduct")" = "$PID" ] || continue
			printf "%s\n" "$(basename "$path")"
		done | sort
	'
}

ensure_host_dirs() {
	host_exec mkdir -p "$SRC_CACHE_DIR" "$SRC_DIR" "$PREFIX_DIR" "$RUN_DIR"
}

ensure_build_deps() {
	say "Installing host USB/IP build dependencies"
	host_exec sudo apt-get update
	host_exec sudo apt-get install -y autoconf automake libtool pkg-config libudev-dev curl xz-utils tar
}

ensure_usbip_build() {
	local version source_root tarball url prefix usbip_path usbipd_path

	version=$(host_kernel_base_version)
	source_root="$SRC_DIR/linux-$version"
	tarball="$SRC_CACHE_DIR/linux-$version.tar.xz"
	url=$(usbip_tarball_url "$version")
	prefix=$(usbip_prefix "$version")
	usbip_path=$(usbip_bin "$version")
	usbipd_path=$(usbipd_bin "$version")

	ensure_host_dirs

	if host_shell '[ -x "$USBIP_BIN" ] && [ -x "$USBIPD_BIN" ]' USBIP_BIN="$usbip_path" USBIPD_BIN="$usbipd_path"; then
		say "Reusing built host usbip tools from $prefix"
		return 0
	fi

	if ! host_shell '[ -f "$TARBALL" ]' TARBALL="$tarball"; then
		say "Downloading Linux source for usbip userspace tools: $url"
		host_exec curl -fL "$url" -o "$tarball"
	fi

	if ! host_shell '[ -d "$SRC_ROOT" ]' SRC_ROOT="$source_root"; then
		say "Extracting Linux source into $source_root"
		host_exec tar -C "$SRC_DIR" -xf "$tarball"
	fi

	say "Building host usbip and usbipd"
	host_shell '
		set -e
		cd "$SRC_ROOT/tools/usb/usbip"
		autoreconf -i -f -v
		./configure --prefix="$PREFIX" >/tmp/trigger6-usbip-configure.log 2>&1
		make -j"$(nproc)" >/tmp/trigger6-usbip-make.log 2>&1
		make install >/tmp/trigger6-usbip-install.log 2>&1
	' SRC_ROOT="$source_root" PREFIX="$prefix"
}

daemon_pid() {
	local pidfile

	pidfile=$(pidfile_path)
	if host_shell '[ -f "$PIDFILE" ]' PIDFILE="$pidfile"; then
		host_shell '
		if [ -f "$PIDFILE" ]; then
			cat "$PIDFILE"
		fi
	' PIDFILE="$pidfile"
		return 0
	fi

	host_shell '
		pgrep -f "^$USBIPD_PATH( .*)?$" | head -n 1
	' USBIPD_PATH="$(usbipd_bin "$(host_kernel_base_version)")"
}

daemon_running() {
	local pid

	pid=$(daemon_pid || true)
	if [[ -n "$pid" ]] && host_shell 'kill -0 "$PID" >/dev/null 2>&1' PID="$pid"; then
		return 0
	fi

	host_shell 'ss -ltn | awk "NR > 1 { print \$4 }" | grep -Eq "(^|:)3240$"'
}

start_daemon() {
	local version usbipd_path pidfile logfile

	version=$(host_kernel_base_version)
	usbipd_path=$(usbipd_bin "$version")
	pidfile=$(pidfile_path)
	logfile=$(logfile_path)

	ensure_usbip_build
	host_exec sudo modprobe usbip-core
	host_exec sudo modprobe usbip-host

	if daemon_running; then
		say "usbipd is already running (pid $(daemon_pid))"
		return 0
	fi

	say "Starting host usbipd"
	host_shell '
		sudo "$USBIPD" -D -P "$PIDFILE" >>"$LOGFILE" 2>&1
	' USBIPD="$usbipd_path" PIDFILE="$pidfile" LOGFILE="$logfile"
	sleep 1
	if ! daemon_running; then
		die "usbipd failed to start; inspect $(logfile_path)"
	fi
	}

stop_daemon() {
	local pid pidfile

	pidfile=$(pidfile_path)
	if ! daemon_running; then
		say "usbipd is not running"
		host_exec rm -f "$pidfile"
		return 0
	fi

	pid=$(daemon_pid)
	if [[ -n "$pid" ]]; then
		say "Stopping host usbipd (pid $pid)"
		host_exec sudo kill "$pid"
	else
		warn "usbipd is listening on port 3240 but no matching pid was found"
	fi
	sleep 1
	host_exec rm -f "$pidfile"
}

list_local() {
	local version usbip_path

	version=$(host_kernel_base_version)
	usbip_path=$(usbip_bin "$version")
	ensure_usbip_build
	host_exec sudo "$usbip_path" list -l
}

bind_busids() {
	local version usbip_path busids

	version=$(host_kernel_base_version)
	usbip_path=$(usbip_bin "$version")
	ensure_usbip_build
	start_daemon

	if [[ $# -gt 0 ]]; then
		busids=("$@")
	else
		mapfile -t busids < <(list_t6_busids)
	fi

	[[ ${#busids[@]} -gt 0 ]] || die "no T6 USB devices found to bind"

	for busid in "${busids[@]}"; do
		if host_shell '
			link=$(readlink -f "/sys/bus/usb/devices/$BUSID/driver" 2>/dev/null || true)
			[ "$link" = "/sys/bus/usb/drivers/usbip-host" ]
		' BUSID="$busid"; then
			say "$busid is already bound to usbip-host"
			continue
		fi
		say "Binding $busid to usbip-host"
		host_exec sudo "$usbip_path" bind -b "$busid"
	done
}

unbind_busids() {
	local version usbip_path busids

	version=$(host_kernel_base_version)
	usbip_path=$(usbip_bin "$version")
	ensure_usbip_build

	if [[ $# -gt 0 ]]; then
		busids=("$@")
	else
		mapfile -t busids < <(list_t6_busids)
	fi

	[[ ${#busids[@]} -gt 0 ]] || die "no T6 USB devices found to unbind"

	for busid in "${busids[@]}"; do
		say "Unbinding $busid from usbip-host"
		host_exec sudo "$usbip_path" unbind -b "$busid" || true
	done
}

status() {
	local version prefix

	version=$(host_kernel_base_version)
	prefix=$(usbip_prefix "$version")
	say "Host kernel base version: $version"
	say "Host usbip prefix: $prefix"
	if daemon_running; then
		say "usbipd: running (pid $(daemon_pid))"
	else
		say "usbipd: stopped"
	fi
	say
	say "Current T6 busids:"
	list_t6_busids || true
	say
	say "Local exportable USB devices:"
	list_local || true
}

usage() {
	cat <<'EOF'
Usage: tools/trigger6-usbip-host.sh <command> [busid ...]

Commands:
  ensure-deps    Install host build dependencies for usbip
  build          Download Linux source and build usbip/usbipd locally
  start          Load host usbip modules and start usbipd
  stop           Stop usbipd
  list-busids    Print current T6 USB busids
  list           Show host exportable USB devices via usbip
  bind [busid]   Bind one or all T6 devices to usbip-host
  unbind [busid] Unbind one or all T6 devices from usbip-host
  ready          Build, start usbipd, and bind all attached T6 devices
  status         Show current host usbip state
EOF
}

command=${1:-}
shift || true

case "$command" in
	ensure-deps)
		ensure_build_deps
		;;
	build)
		ensure_usbip_build
		;;
	start)
		start_daemon
		;;
	stop)
		stop_daemon
		;;
	list-busids)
		list_t6_busids
		;;
	list)
		list_local
		;;
	bind)
		bind_busids "$@"
		;;
	unbind)
		unbind_busids "$@"
		;;
	ready)
		ensure_usbip_build
		start_daemon
		bind_busids
		;;
	status)
		status
		;;
	""|-h|--help|help)
		usage
		;;
	*)
		usage >&2
		die "unknown command: $command"
		;;
esac