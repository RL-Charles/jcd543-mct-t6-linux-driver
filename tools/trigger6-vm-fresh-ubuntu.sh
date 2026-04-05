#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_DIR="$REPO_ROOT/tools/.vm-images"
SEED_DIR="$REPO_ROOT/tools/.vm-seeds"
KEY_DIR="$REPO_ROOT/tools/.vm-keys"
TMP_DIR="$REPO_ROOT/tools/.vm-tmp"

UBUNTU_RELEASE="noble"
UBUNTU_IMAGE_NAME="${UBUNTU_RELEASE}-server-cloudimg-amd64.img"
UBUNTU_BASE_URL="https://cloud-images.ubuntu.com/${UBUNTU_RELEASE}/current"
UBUNTU_IMAGE_URL="${UBUNTU_BASE_URL}/${UBUNTU_IMAGE_NAME}"
UBUNTU_SHA_URL="${UBUNTU_BASE_URL}/SHA256SUMS"

VM_NAME="trigger6-smoke"
GUEST_USER="trigger6"
SSH_PORT=2222
MEMORY_MB=8192
CPU_COUNT=4
DISK_SIZE="40G"
SSH_PUBLIC_KEY=""
AUTO_INSTALL_DEPS=0
AUTO_LAUNCH=0
PASS_THROUGH_ARGS=()

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
		"$@" \
		sh -lc "$script"
}

usage() {
	cat <<'EOF'
Usage: tools/trigger6-vm-fresh-ubuntu.sh [options]

Prepare a fresh Ubuntu 24.04 cloud-image guest for trigger6 smoke tests.
It downloads the official cloud image, verifies its SHA256, generates a
cloud-init seed with SSH access, and optionally launches the VM through the
main tools/trigger6-vm-smoke.sh wrapper.

Options:
  --install-host-deps      Install qemu-system-x86, qemu-utils, ovmf, and cloud-image-utils
  --launch                 Launch the VM after preparing the image and seed
  --name NAME              VM name prefix (default: trigger6-smoke)
  --user NAME              Guest username (default: trigger6)
  --ssh-port PORT          Forward guest ssh to localhost:PORT (default: 2222)
  --memory MB              Guest RAM for --launch (default: 8192)
  --cpus N                 Guest vCPU count for --launch (default: 4)
	--disk-size SIZE         Disposable overlay size for the launched guest (default: 40G)
  --ssh-key PATH           Public SSH key to inject; defaults to ~/.ssh/id_ed25519.pub or an auto-generated key
  --pass-arg ARG           Extra argument forwarded to tools/trigger6-vm-smoke.sh when using --launch
  -h, --help               Show this help

Outputs:
  tools/.vm-images/noble-server-cloudimg-amd64.img
  tools/.vm-seeds/<name>-seed.img
  tools/.vm-keys/<name>-ed25519(.pub) when no existing SSH public key is supplied
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--install-host-deps)
			AUTO_INSTALL_DEPS=1
			shift
			;;
		--launch)
			AUTO_LAUNCH=1
			shift
			;;
		--name)
			VM_NAME=${2:?missing value for --name}
			shift 2
			;;
		--user)
			GUEST_USER=${2:?missing value for --user}
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
		--disk-size)
			DISK_SIZE=${2:?missing value for --disk-size}
			shift 2
			;;
		--ssh-key)
			SSH_PUBLIC_KEY=${2:?missing value for --ssh-key}
			shift 2
			;;
		--pass-arg)
			PASS_THROUGH_ARGS+=("${2:?missing value for --pass-arg}")
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

mkdir -p "$IMAGE_DIR" "$SEED_DIR" "$KEY_DIR" "$TMP_DIR"

install_host_deps() {
	say "Installing host VM dependencies"
	host_exec sudo apt-get update
	host_exec sudo apt-get install -y --no-install-recommends \
		qemu-system-x86 qemu-utils ovmf cloud-image-utils
}

require_host_tool() {
	local tool=$1
	host_shell "command -v ${tool} >/dev/null 2>&1" || die "missing host tool: ${tool}"
}

if [[ $AUTO_INSTALL_DEPS -eq 1 ]]; then
	install_host_deps
fi

require_host_tool curl
require_host_tool sha256sum
require_host_tool qemu-system-x86_64
require_host_tool qemu-img
require_host_tool cloud-localds

download_if_missing() {
	local url=$1
	local path=$2
	if host_shell '[ -f "$TARGET" ]' TARGET="$path"; then
		say "Reusing existing file: $path"
		return 0
	fi
	
	say "Downloading $url"
	host_exec curl -fL "$url" -o "$path"
}

download_if_missing "$UBUNTU_IMAGE_URL" "$IMAGE_DIR/$UBUNTU_IMAGE_NAME"
host_exec curl -fL "$UBUNTU_SHA_URL" -o "$TMP_DIR/${UBUNTU_RELEASE}-SHA256SUMS"

EXPECTED_SHA=$(awk -v target="$UBUNTU_IMAGE_NAME" '$2 ~ target {print $1; exit}' "$TMP_DIR/${UBUNTU_RELEASE}-SHA256SUMS")
[[ -n "$EXPECTED_SHA" ]] || die "failed to find expected SHA256 for $UBUNTU_IMAGE_NAME"
ACTUAL_SHA=$(host_exec sha256sum "$IMAGE_DIR/$UBUNTU_IMAGE_NAME" | awk '{print $1}')
[[ "$EXPECTED_SHA" = "$ACTUAL_SHA" ]] || die "SHA256 mismatch for $UBUNTU_IMAGE_NAME"

KEY_PATH="$KEY_DIR/${VM_NAME}-ed25519"
if [[ -z "$SSH_PUBLIC_KEY" ]]; then
	if [[ ! -f "$KEY_PATH.pub" ]]; then
		require_host_tool ssh-keygen
		say "Generating SSH keypair for the guest at $KEY_PATH"
		host_exec ssh-keygen -t ed25519 -N "" -f "$KEY_PATH" -C "${VM_NAME}@trigger6"
	fi
	SSH_PUBLIC_KEY="$KEY_PATH.pub"
fi

[[ -f "$SSH_PUBLIC_KEY" ]] || die "SSH public key not found: $SSH_PUBLIC_KEY"
SSH_KEY_CONTENT=$(cat "$SSH_PUBLIC_KEY")
USBUTILS_YAML_LINE='  - usbutils'

USER_DATA_PATH="$TMP_DIR/${VM_NAME}-user-data.yaml"
META_DATA_PATH="$TMP_DIR/${VM_NAME}-meta-data.yaml"
SEED_IMAGE_PATH="$SEED_DIR/${VM_NAME}-seed.img"

cat > "$USER_DATA_PATH" <<EOF
#cloud-config
users:
  - default
  - name: ${GUEST_USER}
    gecos: Trigger6 Smoke User
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: [adm, sudo]
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - ${SSH_KEY_CONTENT}
package_update: true
package_upgrade: false
packages:
  - build-essential
  - git
${USBUTILS_YAML_LINE}
runcmd:
  - [ mkdir, -p, /mnt/repo ]
EOF

cat > "$META_DATA_PATH" <<EOF
instance-id: ${VM_NAME}-$(date +%s)
local-hostname: ${VM_NAME}
EOF

say "Creating cloud-init seed: $SEED_IMAGE_PATH"
	host_exec cloud-localds "$SEED_IMAGE_PATH" "$USER_DATA_PATH" "$META_DATA_PATH"

say "Fresh Ubuntu image: $IMAGE_DIR/$UBUNTU_IMAGE_NAME"
say "Cloud-init seed: $SEED_IMAGE_PATH"
say "SSH user: $GUEST_USER"
say "SSH port: $SSH_PORT"
say "SSH key: $SSH_PUBLIC_KEY"
say "Overlay size for launches: $DISK_SIZE"

if [[ $AUTO_LAUNCH -eq 1 ]]; then
	CMD=(
		"$REPO_ROOT/tools/trigger6-vm-smoke.sh"
		--disk "$IMAGE_DIR/$UBUNTU_IMAGE_NAME"
		--seed-disk "$SEED_IMAGE_PATH"
		--overlay-size "$DISK_SIZE"
		--name "$VM_NAME"
		--ssh-port "$SSH_PORT"
		--memory "$MEMORY_MB"
		--cpus "$CPU_COUNT"
	)
	if [[ ${#PASS_THROUGH_ARGS[@]} -gt 0 ]]; then
		for arg in "${PASS_THROUGH_ARGS[@]}"; do
			CMD+=( --extra-arg "$arg" )
		done
	fi
	
	say "Launching fresh Ubuntu trigger6 smoke VM"
	"${CMD[@]}"
	else
	cat <<EOF

Launch when ready with:
	tools/trigger6-vm-smoke.sh --disk $IMAGE_DIR/$UBUNTU_IMAGE_NAME --seed-disk $SEED_IMAGE_PATH --overlay-size $DISK_SIZE --name $VM_NAME --ssh-port $SSH_PORT --memory $MEMORY_MB --cpus $CPU_COUNT

After SSH login, install exact running-kernel headers inside the guest with:
	sudo apt-get update && sudo apt-get install -y linux-headers-\$(uname -r) libdrm-tests
EOF
fi