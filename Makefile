# SPDX-License-Identifier: GPL-2.0-only
.DEFAULT_GOAL := help
.PHONY: help preflight check build build-staged install uninstall

STAGED_KVER := $(shell uname -r)
STAGED_KSRC := $(CURDIR)/artifacts/headers-$(STAGED_KVER)/root/usr/lib/modules/$(STAGED_KVER)/build

help:
	@echo 'make preflight  - inspect cached USB/DRM state and build prerequisites'
	@echo 'make check      - offline source-policy and host C tests (no USB I/O)'
	@echo 'make build      - build only; requires prepared matching kernel headers'
	@echo 'make build-staged - build with repo-local headers, omitting optional module BTF'
	@echo 'Manual hardware testing is documented in docs/MANUAL_TEST.md.'

preflight:
	python3 tools/preflight.py

check:
	python3 tests/check_source.py
	$(MAKE) -C tests check

build:
	$(MAKE) -C kernel modules

# Explicit opt-in to a previously verified/extracted package; never downloads.
# No pahole is installed on this host. Empty (not "n") disables optional module BTF.
build-staged:
	$(MAKE) -C kernel KVER="$(STAGED_KVER)" KSRC="$(STAGED_KSRC)" CONFIG_DEBUG_INFO_BTF_MODULES= modules

install uninstall:
	@echo 'No installation target is provided for this experimental tree.' >&2
	@exit 1
