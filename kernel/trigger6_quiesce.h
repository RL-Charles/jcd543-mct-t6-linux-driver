/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _TRIGGER6_QUIESCE_H_
#define _TRIGGER6_QUIESCE_H_

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/types.h>
#else
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#endif

/* MCT GPL t6.h: primary monitor off, no payload; never audio or reset. */
#define T6_FINAL_OFF_TYPE		0x40
#define T6_FINAL_OFF_REQUEST	0x03
#define T6_FINAL_OFF_VALUE	0
#define T6_FINAL_OFF_INDEX	0
#define T6_FINAL_OFF_LENGTH	0
#define T6_FINAL_OFF_TIMEOUT_MS	250

struct t6_final_off_state {
	bool enabled;
	bool manual_only;
	bool query_only;
	unsigned int output_mask;
	bool profile_matches;
	bool path_matches;
	bool primary_raw;
	bool was_active;
	bool sink_valid;
	bool edid_valid;
	bool faulted;
	bool usb_configured;
	bool unbinding;
	bool drained;
};

/* Shared with host tests; NULL alone permits the single private request. */
static inline const char *t6_final_off_skip(const struct t6_final_off_state *s)
{
	if (!s->enabled)
		return "disabled";
	if (s->manual_only || s->query_only)
		return "read-only-mode";
	if (s->output_mask != 1 || !s->primary_raw)
		return "not-primary-raw";
	if (!s->profile_matches || !s->path_matches)
		return "device-mismatch";
	if (!s->was_active)
		return "already-inactive";
	if (!s->sink_valid || !s->edid_valid)
		return "invalid-cached-sink";
	if (s->faulted)
		return "prior-io-fault";
	if (!s->usb_configured || !s->unbinding)
		return "not-configured-unbind";
	if (!s->drained)
		return "activity-not-drained";
	return NULL;
}

/* A zero-length control request succeeds only at zero; preserve raw ret too. */
static inline int t6_final_off_error(int ret)
{
	return ret > 0 ? -EIO : ret;
}

#endif /* _TRIGGER6_QUIESCE_H_ */
