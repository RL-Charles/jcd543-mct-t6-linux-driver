/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _TRIGGER6_REFRESH_H_
#define _TRIGGER6_REFRESH_H_

#ifdef __KERNEL__
#include <linux/types.h>
#else
#include <stdbool.h>
#endif

/* Shared by the live refresh path and exhaustive host policy tests. */
static inline bool t6_raw_refresh_allowed(bool enabled, bool primary_raw,
					 bool manual_only, bool active,
					 bool connected, bool valid_frame,
					 bool faulted)
{
	return enabled && primary_raw && !manual_only && active && connected &&
	       valid_frame && !faulted;
}

#endif
