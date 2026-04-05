#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_NAME="trigger6-smoke"
DISK_IMAGE=""
SEED_DISK=""
SSH_PORT=2222
MEMORY_MB=8192
CPU_COUNT=4
REPO_SHARE_MODE="rw"
GUEST_USER="trigger6"
HOST_IP="10.0.2.2"
SSH_KEY=""
WAIT_TIMEOUT=180
EXTRA_VM_ARGS=()

say() {
	printf '%s\n' "$*"
}

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

usage() {
	cat <<'EOF'
Usage: tools/trigger6-vm-usbip.sh --disk PATH --seed-disk PATH [options]

Launch a VM without direct QEMU USB passthrough, export the attached T6 devices
from the host via USB/IP, then attach them inside the guest.

Required:
  --disk PATH              Base guest disk image
  --seed-disk PATH         Cloud-init or seed disk for the guest

Options:
  --name NAME              VM name (default: trigger6-smoke)
  --ssh-port PORT          Guest ssh forward port (default: 2222)
  --memory MB              Guest RAM in MiB (default: 8192)
  --cpus N                 Guest vCPU count (default: 4)
  --share-mode ro|rw       Repo share mode passed to trigger6-vm-smoke.sh (default: rw)
  --guest-user USER        SSH user inside the guest (default: trigger6)
  --ssh-key PATH           SSH private key for guest login (default: tools/.vm-keys/<name>-ed25519)
  --host-ip IP             Host address as seen from the guest (default: 10.0.2.2)
  --wait-seconds N         SSH readiness timeout (default: 180)
  --pass-arg ARG           Extra argument forwarded to trigger6-vm-smoke.sh; repeat as needed
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--disk)
			DISK_IMAGE=${2:?missing value for --disk}
			shift 2
			;;
		--seed-disk)
			SEED_DISK=${2:?missing value for --seed-disk}
			shift 2
			;;
		--name)
			VM_NAME=${2:?missing value for --name}
			shift 2
			;;
		--ssh-port)
			SSH_PORT=${2:?missing value for --ssh-port}
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
		--share-mode)
			REPO_SHARE_MODE=${2:?missing value for --share-mode}
			shift 2
			;;
		--guest-user)
			GUEST_USER=${2:?missing value for --guest-user}
			shift 2
			;;
		--ssh-key)
			SSH_KEY=${2:?missing value for --ssh-key}
			shift 2
			;;
		--host-ip)
			HOST_IP=${2:?missing value for --host-ip}
			shift 2
			;;
		--wait-seconds)
			WAIT_TIMEOUT=${2:?missing value for --wait-seconds}
			shift 2
			;;
		--pass-arg)
			EXTRA_VM_ARGS+=("${2:?missing value for --pass-arg}")
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

[[ -n "$DISK_IMAGE" ]] || die "--disk is required"
[[ -n "$SEED_DISK" ]] || die "--seed-disk is required"

if [[ -z "$SSH_KEY" ]]; then
	SSH_KEY="$REPO_ROOT/tools/.vm-keys/${VM_NAME}-ed25519"
fi

[[ -f "$SSH_KEY" ]] || die "SSH key not found: $SSH_KEY"

HOST_HELPER="$REPO_ROOT/tools/trigger6-usbip-host.sh"
VM_HELPER="$REPO_ROOT/tools/trigger6-vm-smoke.sh"

[[ -x "$HOST_HELPER" ]] || die "host USB/IP helper is missing or not executable: $HOST_HELPER"
[[ -x "$VM_HELPER" ]] || die "VM smoke helper is missing or not executable: $VM_HELPER"

say "Preparing host USB/IP export"
"$HOST_HELPER" ready

mapfile -t BUSIDS < <("$HOST_HELPER" list-busids)
[[ ${#BUSIDS[@]} -gt 0 ]] || die "no T6 devices are available for USB/IP export"

say "Launching VM without direct QEMU USB passthrough"
VM_CMD=(
	"$VM_HELPER"
	--disk "$DISK_IMAGE"
	--seed-disk "$SEED_DISK"
	--name "$VM_NAME"
	--ssh-port "$SSH_PORT"
	--memory "$MEMORY_MB"
	--cpus "$CPU_COUNT"
	--share-mode "$REPO_SHARE_MODE"
	--no-usb-passthrough
)

if [[ ${#EXTRA_VM_ARGS[@]} -gt 0 ]]; then
	for arg in "${EXTRA_VM_ARGS[@]}"; do
		VM_CMD+=( --extra-arg "$arg" )
	done
fi

"${VM_CMD[@]}" &
VM_WRAPPER_PID=$!

trap 'kill "$VM_WRAPPER_PID" >/dev/null 2>&1 || true' EXIT

say "Waiting for guest SSH on localhost:$SSH_PORT"
for ((i = 0; i < WAIT_TIMEOUT; i++)); do
	if ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p "$SSH_PORT" "$GUEST_USER@127.0.0.1" 'true' >/dev/null 2>&1; then
		break
	fi
	sleep 1
	if (( i == WAIT_TIMEOUT - 1 )); then
		die "guest SSH did not become ready within ${WAIT_TIMEOUT}s"
	fi
done

say "Preparing guest USB/IP client support"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p "$SSH_PORT" "$GUEST_USER@127.0.0.1" \
	'cloud-init status --wait && \
	 if ! sudo modprobe vhci-hcd; then \
	   sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "linux-modules-extra-$(uname -r)"; \
	   sudo modprobe vhci-hcd; \
	 fi && \
	 sudo mkdir -p /mnt/repo && \
	 { mountpoint -q /mnt/repo || sudo mount -t 9p -o trans=virtio,version=9p2000.L repo /mnt/repo; } && \
	 if [ -f /mnt/repo/userspace/99-mct-t6-display.rules ]; then \
	   sudo install -m 0644 /mnt/repo/userspace/99-mct-t6-display.rules /etc/udev/rules.d/99-mct-t6-display.rules && \
	   sudo udevadm control --reload-rules; \
	 fi'

say "Attaching T6 devices over USB/IP inside the guest"

for busid in "${BUSIDS[@]}"; do
	say "Guest attach: $busid"
	ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p "$SSH_PORT" "$GUEST_USER@127.0.0.1" \
		"if sudo usbip port | grep -q 'usbip://$HOST_IP:3240/$busid'; then echo '$busid already attached'; else sudo usbip attach -r $HOST_IP -b $busid; fi"
done

say "Guest USB/IP attachment complete"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p "$SSH_PORT" "$GUEST_USER@127.0.0.1" \
	'lsusb -d 0711:5601 || true; usbip port || true'

wait "$VM_WRAPPER_PID"