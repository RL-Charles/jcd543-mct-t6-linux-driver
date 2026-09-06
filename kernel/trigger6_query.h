/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _TRIGGER6_QUERY_H_
#define _TRIGGER6_QUERY_H_

#ifdef __KERNEL__
#include <linux/types.h>
#else
#include <stdbool.h>
#endif

/* Display EP0 IN requests; MCT triggerdm t6.h, commit 63cecc7ef330. */
#define T6_REQ_GET_EDID		0x80
#define T6_REQ_GET_RES_COUNT	0x84
#define T6_REQ_GET_STATUS	0x87
#define T6_REQ_GET_RAM		0x88
#define T6_REQ_GET_RES_TABLE	0x89

#define T6_RES_ENTRY_SIZE	32
#define T6_RES_MAX_ENTRIES	16
#define T6_RES_TABLE_SIZE	(T6_RES_ENTRY_SIZE * T6_RES_MAX_ENTRIES)

/* Bound before multiplying an untrusted little-endian firmware count. */
static inline unsigned int t6_timing_query_entries(unsigned int count)
{
	return count < T6_RES_MAX_ENTRIES ? count : T6_RES_MAX_ENTRIES;
}

/* Shared with host tests; no audio, reset, paging, OUT, or endpoint selection. */
static inline bool t6_query_in_allowed(unsigned int output_mask, bool timings,
				       bool page1,
				       unsigned int req, unsigned int value,
				       unsigned int index, unsigned int size)
{
	unsigned int head;

	if (output_mask != 1 && output_mask != 2)
		return false;
	if (timings && output_mask != 1)
		return false;
	if (page1 && !timings)
		return false;
	head = output_mask == 1 ? 0 : 1;

	switch (req) {
	case T6_REQ_GET_RAM:
		/* Existing measured RAM request, not a new diagnostic request. */
		return value == 0 && index == 0 && size == 4;
	case T6_REQ_GET_STATUS:
		return value == head && index == 0 && size == 1;
	case T6_REQ_GET_EDID:
		return value == 0 && index == head && size == 128;
	case T6_REQ_GET_RES_COUNT:
		return timings && value == 0 && index == 0 && size == 4;
	case T6_REQ_GET_RES_TABLE:
		if (page1)
			return timings && value == 0 && index == 512 && size == 512;
		return timings && value == 0 && index == 0 && size != 0 &&
		       size <= T6_RES_TABLE_SIZE && size % T6_RES_ENTRY_SIZE == 0;
	default:
		return false;
	}
}

#endif
