// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

#include "../kernel/trigger6_quiesce.h"

int main(void)
{
	unsigned int flags, mask;
	unsigned int cases = 0;
	int ret;

	for (flags = 0; flags < 8192; flags++) {
		for (mask = 0; mask < 5; mask++) {
			struct t6_final_off_state s = {
				.enabled = flags & 1,
				.manual_only = flags & 2,
				.query_only = flags & 4,
				.output_mask = mask,
				.profile_matches = flags & 8,
				.path_matches = flags & 16,
				.primary_raw = flags & 32,
				.was_active = flags & 64,
				.sink_valid = flags & 128,
				.edid_valid = flags & 256,
				.faulted = flags & 512,
				.usb_configured = flags & 1024,
				.unbinding = flags & 2048,
				.drained = flags & 4096,
			};
			bool expected = flags == (8191 & ~(2 | 4 | 512)) && mask == 1;

			assert(!t6_final_off_skip(&s) == expected);
			if (!s.enabled)
				assert(!strcmp(t6_final_off_skip(&s), "disabled"));
			cases++;
		}
	}
	for (ret = -4095; ret <= 4095; ret++)
		assert(t6_final_off_error(ret) == (ret > 0 ? -EIO : ret));
	assert(t6_final_off_error(INT_MIN) == INT_MIN);
	assert(t6_final_off_error(INT_MAX) == -EIO);
	assert(T6_FINAL_OFF_TYPE == 0x40 && T6_FINAL_OFF_REQUEST == 0x03);
	assert(!T6_FINAL_OFF_VALUE && !T6_FINAL_OFF_INDEX && !T6_FINAL_OFF_LENGTH);
	assert(T6_FINAL_OFF_TIMEOUT_MS == 250);
	printf("PASS: %u final-off policies, 8193 results, fixed EP0 tuple (host only)\n",
	       cases);
	return 0;
}
