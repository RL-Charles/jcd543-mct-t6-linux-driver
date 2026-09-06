/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include "../kernel/trigger6_match.h"

static const struct t6_usb_profile observed = {
	.vendor = 0x0711, .product = 0x5601, .revision = 0x1010,
	.device_class = 0xff, .configurations = 1, .configuration = 1,
	.interfaces = 1, .alternate_settings = 1, .interface_class = 0xff,
	.superspeed = 1, .endpoint_count = 3,
	.endpoints = {{0x81, 2, 1024, 0}, {0x02, 2, 1024, 0}, {0x83, 3, 64, 5}},
};

int main(void)
{
	struct t6_usb_profile p;
	unsigned int checks = 0;
	const size_t fields[] = {
		offsetof(struct t6_usb_profile, vendor),
		offsetof(struct t6_usb_profile, product),
		offsetof(struct t6_usb_profile, revision),
		offsetof(struct t6_usb_profile, device_class),
		offsetof(struct t6_usb_profile, device_subclass),
		offsetof(struct t6_usb_profile, device_protocol),
		offsetof(struct t6_usb_profile, configurations),
		offsetof(struct t6_usb_profile, configuration),
		offsetof(struct t6_usb_profile, interfaces),
		offsetof(struct t6_usb_profile, interface_number),
		offsetof(struct t6_usb_profile, alternate_setting),
		offsetof(struct t6_usb_profile, alternate_settings),
		offsetof(struct t6_usb_profile, interface_class),
		offsetof(struct t6_usb_profile, interface_subclass),
		offsetof(struct t6_usb_profile, interface_protocol),
		offsetof(struct t6_usb_profile, superspeed),
		offsetof(struct t6_usb_profile, endpoint_count),
	};

	assert(t6_profile_matches(&observed));
	checks++;
	for (size_t i = 0; i < sizeof(fields) / sizeof(fields[0]); i++) {
		unsigned int *field;

		p = observed;
		field = (unsigned int *)((unsigned char *)&p + fields[i]);
		(*field)++;
		assert(!t6_profile_matches(&p));
		checks++;
	}
	for (unsigned int i = 0; i < 3; i++) {
		for (unsigned int j = 0; j < 4; j++) {
			p = observed;
			switch (j) {
			case 0: p.endpoints[i].address ^= 0x80; break;
			case 1: p.endpoints[i].attributes ^= 1; break;
			case 2: p.endpoints[i].max_packet /= 2; break;
			case 3: p.endpoints[i].interval++; break;
			}
			assert(!t6_profile_matches(&p));
			checks++;
		}
	}
	p = observed;
	p.endpoints[0] = p.endpoints[1];
	assert(!t6_profile_matches(&p));
	checks++;
	p = observed;
	p.endpoints[0] = observed.endpoints[2];
	p.endpoints[2] = observed.endpoints[0];
	assert(t6_profile_matches(&p));
	checks++;
	for (unsigned int mask = 0; mask < 32; mask++) {
		assert(t6_output_mask_valid(mask) == (mask == 1 || mask == 2));
		checks++;
	}
	printf("PASS: %u descriptor and single-output policy cases (host code only)\n", checks);
	return 0;
}
