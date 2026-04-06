/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * trigger6_jpeg.h -- Minimal baseline JPEG encoder for T6 output 1
 *
 * The T6 secondary output accepts vendor-formatted JPEG payloads that are
 * later unpacked into NV12 in device RAM. This helper keeps encoding isolated
 * from the transport code in trigger6_drv.c.
 */

#ifndef _TRIGGER6_JPEG_H_
#define _TRIGGER6_JPEG_H_

#include <linux/types.h>

int t6_jpeg_encode_xrgb8888(const u8 *src,
			    unsigned int width,
			    unsigned int height,
			    unsigned int stride,
			    unsigned int quality,
			    u8 *dst,
			    size_t dst_size);

#endif