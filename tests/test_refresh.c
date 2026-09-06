/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>

#include "../kernel/trigger6_refresh.h"

int main(void)
{
	unsigned int flags;

	for (flags = 0; flags < 128; flags++) {
		bool allowed = t6_raw_refresh_allowed(flags & 1, flags & 2,
			flags & 4, flags & 8, flags & 16, flags & 32, flags & 64);

		/* Enabled, primary raw, active, connected, valid; neither manual nor fault. */
		assert(allowed == (flags == (1 | 2 | 8 | 16 | 32)));
	}
	puts("PASS: 128 raw idle-refresh policy combinations (host code only)");
	return 0;
}
