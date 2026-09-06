/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <limits.h>
#include <stdio.h>

#include "../kernel/trigger6_query.h"

int main(void)
{
	unsigned int mask, timing, page1, req, value, index_slot, index, size;
	const unsigned int indices[] = { 0, 1, 2, 512, 1024 };
	unsigned int checked = 0;

	/* Independent tuple oracle, including every request byte and nearby lengths. */
	for (mask = 0; mask <= 4; mask++) {
		for (timing = 0; timing < 2; timing++) {
		  for (page1 = 0; page1 < 2; page1++) {
			for (req = 0; req < 256; req++) {
				for (value = 0; value < 3; value++) {
					for (index_slot = 0; index_slot < 5; index_slot++) {
						index = indices[index_slot];
						for (size = 0; size <= 513; size++) {
							unsigned int head = mask == 1 ? 0 : 1;
							bool valid_config = (mask == 1 || mask == 2) &&
								(!timing || mask == 1) && (!page1 || timing);
							bool expected = valid_config && (
								(req == 0x88 && !value && !index && size == 4) ||
								(req == 0x87 && value == head && !index && size == 1) ||
								(req == 0x80 && !value && index == head && size == 128) ||
								(timing && !value && (
									(req == 0x84 && !index && size == 4) ||
									(req == 0x89 && (page1 ? (index == 512 && size == 512) :
										(!index && size >= 32 && size <= 512 && size % 32 == 0))))));

							assert(t6_query_in_allowed(mask, timing, page1, req,
								value, index, size) == expected);
							checked++;
						}
					}
				}
			}
		  }
		}
	}
	assert(t6_timing_query_entries(0) == 0);
	assert(t6_timing_query_entries(1) == 1);
	assert(t6_timing_query_entries(15) == 15);
	assert(t6_timing_query_entries(16) == 16);
	assert(t6_timing_query_entries(17) == 16);
	assert(t6_timing_query_entries(UINT_MAX) == 16);
	assert(!t6_query_in_allowed(1, true, false, 0x89, 0, 0, UINT_MAX));
	assert(!t6_query_in_allowed(1, true, false, 0x89, UINT_MAX, 0, 32));
	assert(!t6_query_in_allowed(1, true, false, 0x89, 0, UINT_MAX, 32));
	printf("PASS: %u query-IN tuple cases plus 9 count/overflow bounds (host code only)\n",
		checked);
	return 0;
}
