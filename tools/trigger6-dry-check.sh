#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() {
	printf '%s\n' "$*"
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

find_python() {
	local candidate

	for candidate in "$REPO_ROOT/.venv/bin/python" python3 python; do
		if ! command -v "$candidate" >/dev/null 2>&1 && [[ "$candidate" != /* ]]; then
			continue
		fi
		if "$candidate" -c 'import PIL' >/dev/null 2>&1; then
			printf '%s\n' "$candidate"
			return 0
		fi
	done

	return 1
}

say "Dry check: host guard syntax"
bash -n "$REPO_ROOT/tools/trigger6-host-guard.sh"

say
say "Dry check: host conflict scan"
if ! "$REPO_ROOT/tools/trigger6-host-guard.sh" conflicts; then
	die "active host-side driver or udev conflicts remain; clear them before another live test"
fi

say
say "Dry check: current guarded host state"
"$REPO_ROOT/tools/trigger6-host-guard.sh" status

say
say "Dry check: kernel build against host headers"
host_exec bash -lc "cd '$REPO_ROOT/kernel' && make -j\"\$(nproc)\""

say
say "Dry check: offline output-1 JPEG benchmark"
PYTHON_BIN=$(find_python || true)
[[ -n "$PYTHON_BIN" ]] || die "no Python interpreter with Pillow is available for userspace/benchmark_output1_jpeg.py"
"$PYTHON_BIN" "$REPO_ROOT/userspace/benchmark_output1_jpeg.py" --source synthetic --repeats 1

say
say "Dry check complete"