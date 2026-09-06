/* SPDX-License-Identifier: GPL-2.0-only */
/* Descriptor-only JCD543 development profile; also exercised by host tests. */
#ifndef _TRIGGER6_MATCH_H_
#define _TRIGGER6_MATCH_H_

#define T6_VID 0x0711
#define T6_PID 0x5601
#define T6_BCD_DEVICE 0x1010
#define T6_EP_BULK_OUT 0x02

struct t6_endpoint_profile {
	unsigned int address;
	unsigned int attributes;
	unsigned int max_packet;
	unsigned int interval;
};

struct t6_usb_profile {
	unsigned int vendor;
	unsigned int product;
	unsigned int revision;
	unsigned int device_class;
	unsigned int device_subclass;
	unsigned int device_protocol;
	unsigned int configurations;
	unsigned int configuration;
	unsigned int interfaces;
	unsigned int interface_number;
	unsigned int alternate_setting;
	unsigned int alternate_settings;
	unsigned int interface_class;
	unsigned int interface_subclass;
	unsigned int interface_protocol;
	unsigned int superspeed;
	unsigned int endpoint_count;
	struct t6_endpoint_profile endpoints[3];
};

/* Integers keep this small policy independent of kernel-only headers. */
static inline int t6_profile_matches(const struct t6_usb_profile *p)
{
	unsigned int i, seen = 0;

	if (p->vendor != T6_VID || p->product != T6_PID ||
	    p->revision != T6_BCD_DEVICE || p->device_class != 0xff ||
	    p->device_subclass || p->device_protocol ||
	    p->configurations != 1 || p->configuration != 1 ||
	    p->interfaces != 1 || p->interface_number ||
	    p->alternate_setting || p->alternate_settings != 1 ||
	    p->interface_class != 0xff || p->interface_subclass ||
	    p->interface_protocol || p->superspeed != 1 ||
	    p->endpoint_count != 3)
		return 0;

	for (i = 0; i < 3; i++) {
		const struct t6_endpoint_profile *ep = &p->endpoints[i];
		unsigned int bit;

		if (ep->address == 0x81 && ep->attributes == 2 &&
		    ep->max_packet == 1024 && !ep->interval)
			bit = 1;
		else if (ep->address == T6_EP_BULK_OUT &&
			 ep->attributes == 2 && ep->max_packet == 1024 &&
			 !ep->interval)
			bit = 2;
		else if (ep->address == 0x83 && ep->attributes == 3 &&
			 ep->max_packet == 64 && ep->interval == 5)
			bit = 4;
		else
			return 0;
		if (seen & bit)
			return 0;
		seen |= bit;
	}
	return seen == 7;
}

static inline int t6_output_mask_valid(unsigned int mask)
{
	/* One logical output per experiment, selected at module insertion. */
	return mask == 1 || mask == 2;
}

#endif
