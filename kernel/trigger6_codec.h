/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * trigger6_codec.h -- JPEG encoder and NV12 converter for T6 USB display
 *
 * Provides two pixel-format conversion paths used by trigger6_drv.c:
 *   1. XRGB8888 -> baseline JPEG (4:2:0) for the JPEG_CMD transport.
 *   2. XRGB8888 -> NV12 (BT.601 studio-range) for the NV12 transport.
 *
 * Copyright (C) 2026 Authentra / Ralph Friedman
 */

#ifndef _TRIGGER6_CODEC_H_
#define _TRIGGER6_CODEC_H_

#include <linux/types.h>

int t6_jpeg_encode_xrgb8888(const u8 *src,
			    unsigned int width,
			    unsigned int height,
			    unsigned int stride,
			    unsigned int quality,
			    u8 *dst,
			    size_t dst_size);

int t6_convert_xrgb8888_to_nv12(const u8 *src,
				 unsigned int width,
				 unsigned int height,
				 unsigned int src_stride,
				 u8 *dst_y,
				 u8 *dst_uv,
				 unsigned int dst_y_pitch,
				 unsigned int dst_uv_pitch);

#endif
