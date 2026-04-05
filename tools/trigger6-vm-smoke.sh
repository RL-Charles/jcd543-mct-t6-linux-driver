#!/usr/bin/env bash
set -euo pipefail

VID="0711"
PID="5601"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVERLAY_DIR="$REPO_ROOT/tools/.vm-overlays"
LOG_DIR="$REPO_ROOT/tools/.vm-logs"

DISK_IMAGE=""
DISK_FORMAT="qcow2"
SEED_DISK=""
OVERLAY_SIZE="40G"
VM_NAME="trigger6-smoke"
MEMORY_MB=8192
CPU_COUNT=4
SSH_PORT=2222
EPHEMERAL=1
USE_KVM=auto
USB_CONTROLLER="xhci"
USB_PASSTHROUGH=1
SHARE_REPO=1
REPO_SHARE_MODE="ro"
DRY_RUN=0
EXTRA_QEMU_ARGS=()

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
		"$@" \
		sh -lc "$script"
}

canonicalize_path() {
	local path=$1

	if [[ "$path" = /* ]]; then
		printf '%s\n' "$path"
	else
		printf '%s\n' "$(pwd)/$path"
	fi
}

usage() {
	cat <<'EOF'
Usage: tools/trigger6-vm-smoke.sh --disk /path/to/guest.qcow2 [options]

Launch a disposable QEMU or KVM guest with the currently attached T6 USB devices
passed through, so probe, bind, and unload paths can be smoke-tested away from
the live COSMIC session.

Required:
  --disk PATH              Base guest disk image

Options:
  --disk-format fmt        Base image format when not using an overlay (default: qcow2)
	--seed-disk PATH         Optional cloud-init or seed disk to attach as a second virtio drive
	--overlay-size SIZE      Virtual size for disposable overlays (default: 40G)
  --name NAME              VM name (default: trigger6-smoke)
  --memory MB              Guest RAM in MiB (default: 8192)
  --cpus N                 Guest vCPU count (default: 4)
  --ssh-port PORT          Forward guest ssh to localhost:PORT (default: 2222)
	--usb-controller MODE    USB controller for passthrough: xhci or ehci (default: xhci)
	--no-usb-passthrough    Do not attach the local T6 devices with QEMU usb-host
  --persistent             Boot the base image directly instead of making an overlay
  --share-mode ro|rw       Share this repo into the guest as mount tag 'repo' (default: ro)
  --no-share-repo          Do not expose the repo through virtfs
  --kvm                    Require KVM acceleration
  --no-kvm                 Force TCG emulation
  --dry-run                Print the QEMU command without starting the guest
  --extra-arg ARG          Append one raw QEMU argument; repeat as needed
  -h, --help               Show this help

Examples:
  tools/trigger6-vm-smoke.sh --disk ~/vm/ubuntu-24.04.qcow2
  tools/trigger6-vm-smoke.sh --disk ~/vm/ubuntu-24.04.qcow2 --share-mode rw --ssh-port 2201
	tools/trigger6-vm-smoke.sh --disk tools/.vm-images/noble-server-cloudimg-amd64.img --seed-disk tools/.vm-seeds/trigger6-smoke-seed.img

Guest notes:
  - Repo share mount tag: repo
  - Read-only mount example:
      sudo mkdir -p /mnt/repo
      sudo mount -t 9p -o trans=virtio,version=9p2000.L repo /mnt/repo
	- The T6 adapters expose 1024-byte bulk endpoints, so EHCI is only useful for
		descriptor/debugging experiments. Real T6 frame traffic needs xHCI-class USB.
	- Current QEMU usb-host passthrough enumerates the T6 adapters, but guest bulk
		writes still fail under xHCI. Without host IOMMU support, investigate USB/IP
		if you need the guest to drive real frame traffic.
  - This isolates USB passthrough and module load/unload smoke tests, but it will
    not reproduce host COSMIC compositor behavior exactly.
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--disk)
			DISK_IMAGE=${2:?missing value for --disk}
			shift 2
			;;
		--disk-format)
			DISK_FORMAT=${2:?missing value for --disk-format}
			shift 2
			;;
		--seed-disk)
			SEED_DISK=${2:?missing value for --seed-disk}
			shift 2
			;;
		--overlay-size)
			OVERLAY_SIZE=${2:?missing value for --overlay-size}
			shift 2
			;;
		--name)
			VM_NAME=${2:?missing value for --name}
			shift 2
			;;
		--memory)
			MEMORY_MB=${2:?missing value for --memory}
			shift 2
			;;
		--cpus)
			CPU_COUNT=${2:?missing value for --cpus}
			shift 2
			;;
		--ssh-port)
			SSH_PORT=${2:?missing value for --ssh-port}
			shift 2
			;;
		--usb-controller)
			USB_CONTROLLER=${2:?missing value for --usb-controller}
			shift 2
			;;
		--no-usb-passthrough)
			USB_PASSTHROUGH=0
			shift
			;;
		--persistent)
			EPHEMERAL=0
			shift
			;;
		--share-mode)
			REPO_SHARE_MODE=${2:?missing value for --share-mode}
			shift 2
			;;
		--no-share-repo)
			SHARE_REPO=0
			shift
			;;
		--kvm)
			USE_KVM=yes
			shift
			;;
		--no-kvm)
			USE_KVM=no
			shift
			;;
		--dry-run)
			DRY_RUN=1
			shift
			;;
		--extra-arg)
			EXTRA_QEMU_ARGS+=("${2:?missing value for --extra-arg}")
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			usage >&2
			die "unknown argument: $1"
			;;
	esac
done

[[ -n "$DISK_IMAGE" ]] || {
	usage >&2
	die "--disk is required"
}

DISK_IMAGE=$(canonicalize_path "$DISK_IMAGE")
if [[ -n "$SEED_DISK" ]]; then
	SEED_DISK=$(canonicalize_path "$SEED_DISK")
fi

[[ -f "$DISK_IMAGE" ]] || die "disk image not found: $DISK_IMAGE"
[[ -z "$SEED_DISK" || -f "$SEED_DISK" ]] || die "seed disk not found: $SEED_DISK"
[[ "$REPO_SHARE_MODE" = "ro" || "$REPO_SHARE_MODE" = "rw" ]] || die "--share-mode must be ro or rw"
[[ "$USB_CONTROLLER" = "xhci" || "$USB_CONTROLLER" = "ehci" ]] || die "--usb-controller must be xhci or ehci"

QEMU_BIN=$(host_shell 'command -v qemu-system-x86_64 || true')
[[ -n "$QEMU_BIN" ]] || die "qemu-system-x86_64 not found on the host"

QEMU_IMG_BIN=$(host_shell 'command -v qemu-img || true')

find_ovmf_code() {
	host_shell '
		for path in \
			/usr/share/OVMF/OVMF_CODE.fd \
			/usr/share/OVMF/OVMF_CODE_4M.fd \
			/usr/share/edk2/x64/OVMF_CODE.fd \
			/usr/share/edk2-ovmf/x64/OVMF_CODE.fd \
			/usr/share/qemu/OVMF_CODE.fd; do
			[ -f "$path" ] && { printf "%s\n" "$path"; exit 0; }
		done
	'
}

find_ovmf_vars() {
	host_shell '
		for path in \
			/usr/share/OVMF/OVMF_VARS.fd \
			/usr/share/OVMF/OVMF_VARS_4M.fd \
			/usr/share/edk2/x64/OVMF_VARS.fd \
			/usr/share/edk2-ovmf/x64/OVMF_VARS.fd \
			/usr/share/qemu/OVMF_VARS.fd; do
			[ -f "$path" ] && { printf "%s\n" "$path"; exit 0; }
		done
	'
}

collect_t6_devices() {
	host_shell '
		lsusb -d "${VID}:${PID}" 2>/dev/null |
		awk "{gsub(\":\", \"\", \$4); printf \"%s %s\\n\", \$2 + 0, \$4 + 0}"
	'
}

mkdir -p "$OVERLAY_DIR" "$LOG_DIR"

runtime_disk=$DISK_IMAGE
if [[ $EPHEMERAL -eq 1 ]]; then
	[[ -n "$QEMU_IMG_BIN" ]] || die "qemu-img is required for overlay mode; use --persistent to skip overlays"
	overlay_path="$OVERLAY_DIR/${VM_NAME}-$(date +%Y%m%d-%H%M%S).qcow2"
	say "Creating disposable overlay: $overlay_path"
	host_exec "$QEMU_IMG_BIN" create -f qcow2 -F "$DISK_FORMAT" -b "$DISK_IMAGE" "$overlay_path" >/dev/null
	host_exec "$QEMU_IMG_BIN" resize "$overlay_path" "$OVERLAY_SIZE" >/dev/null
	runtime_disk=$overlay_path
	DISK_FORMAT=qcow2
fi

SERIAL_LOG="$LOG_DIR/${VM_NAME}-$(date +%Y%m%d-%H%M%S).serial.log"

QEMU_CMD=(
	"$QEMU_BIN"
	-name "$VM_NAME"
	-machine q35
	-smp "$CPU_COUNT"
	-m "$MEMORY_MB"
	-drive "if=virtio,format=${DISK_FORMAT},file=${runtime_disk}"
	-nic "user,model=virtio-net-pci,hostfwd=tcp::${SSH_PORT}-:22"
	-serial "file:${SERIAL_LOG}"
)

USB_BUS_ID="t6usb.0"
case "$USB_CONTROLLER" in
	xhci)
		QEMU_CMD+=( -device qemu-xhci,id=t6usb )
		;;
	ehci)
		QEMU_CMD+=( -device usb-ehci,id=t6usb )
		;;
esac

if [[ -n "$SEED_DISK" ]]; then
	QEMU_CMD+=( -drive "if=virtio,format=raw,file=${SEED_DISK}" )
fi

if [[ "$USE_KVM" = yes ]]; then
	[[ -e /dev/kvm ]] || die "--kvm was requested but /dev/kvm is not available"
	QEMU_CMD+=( -enable-kvm -cpu host )
elif [[ "$USE_KVM" = auto ]]; then
	if [[ -e /dev/kvm ]]; then
		QEMU_CMD+=( -enable-kvm -cpu host )
	else
		warn "/dev/kvm is not available; falling back to TCG emulation"
		QEMU_CMD+=( -cpu max )
	fi
else
	QEMU_CMD+=( -cpu max )
fi

OVMF_CODE=$(find_ovmf_code || true)
OVMF_VARS=$(find_ovmf_vars || true)
if [[ -n "$OVMF_CODE" && -n "$OVMF_VARS" ]]; then
	OVMF_VARS_COPY="$OVERLAY_DIR/${VM_NAME}-ovmf-vars-$(date +%Y%m%d-%H%M%S).fd"
	host_exec cp "$OVMF_VARS" "$OVMF_VARS_COPY"
	QEMU_CMD+=(
		-drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}"
		-drive "if=pflash,format=raw,file=${OVMF_VARS_COPY}"
	)
else
	warn "OVMF firmware not found; falling back to default QEMU firmware"
fi

if [[ $SHARE_REPO -eq 1 ]]; then
	readonly_flag="on"
	if [[ "$REPO_SHARE_MODE" = rw ]]; then
		readonly_flag="off"
	fi
	QEMU_CMD+=(
		-virtfs "local,path=${REPO_ROOT},mount_tag=repo,security_model=none,readonly=${readonly_flag}"
	)
fi

if [[ $USB_PASSTHROUGH -eq 1 ]]; then
	while read -r hostbus hostaddr; do
		[[ -n "$hostbus" && -n "$hostaddr" ]] || continue
		QEMU_CMD+=( -device "usb-host,bus=${USB_BUS_ID},hostbus=${hostbus},hostaddr=${hostaddr}" )
	done < <(collect_t6_devices)
fi

if [[ ${#EXTRA_QEMU_ARGS[@]} -gt 0 ]]; then
	QEMU_CMD+=( "${EXTRA_QEMU_ARGS[@]}" )
fi

say "VM name: $VM_NAME"
say "Disk: $runtime_disk"
say "USB controller: $USB_CONTROLLER"
say "USB passthrough: $( [[ $USB_PASSTHROUGH -eq 1 ]] && printf 'qemu-usb-host' || printf 'disabled' )"
if [[ -n "$SEED_DISK" ]]; then
	say "Seed disk: $SEED_DISK"
fi
say "Serial log: $SERIAL_LOG"
say "SSH: ssh -p $SSH_PORT <guest-user>@127.0.0.1"
if [[ $SHARE_REPO -eq 1 ]]; then
	say "Repo share: mount tag 'repo' (${REPO_SHARE_MODE})"
fi

if [[ $DRY_RUN -eq 1 ]]; then
	printf '%q ' "${QEMU_CMD[@]}"
	printf '\n'
	exit 0
fi

say "Launching QEMU guest"
	host_exec "${QEMU_CMD[@]}"