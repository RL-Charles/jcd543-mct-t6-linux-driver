# SPDX-License-Identifier: GPL-2.0-only
KVER ?= $(shell uname -r)
KSRC ?= /usr/lib/modules/$(KVER)/build
MODULE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.DEFAULT_GOAL := modules
.PHONY: modules check-headers clean install modules_install uninstall

check-headers:
	@test "$$(id -u)" -ne 0 || { echo 'Build as an ordinary user.' >&2; exit 1; }
	@test -r "$(KSRC)/Makefile" -a -r "$(KSRC)/include/generated/autoconf.h" -a -r "$(KSRC)/Module.symvers" || { echo 'BLOCKED: prepared headers and Module.symvers for $(KVER) are required at $(KSRC).' >&2; echo 'On Arch, obtain matching linux-headers through a separately authorized system update.' >&2; exit 1; }
	@test "$$(head -n 1 "$(KSRC)/include/config/kernel.release")" = "$(KVER)" || { echo 'BLOCKED: header release does not match KVER=$(KVER).' >&2; exit 1; }

modules: check-headers
	$(MAKE) -C "$(KSRC)" M="$(MODULE_DIR)" W=1 modules

clean: check-headers
	$(MAKE) -C "$(KSRC)" M="$(MODULE_DIR)" clean

install modules_install uninstall:
	@echo 'Permanent installation/removal is deliberately unavailable. See docs/MANUAL_TEST.md.' >&2
	@exit 1
