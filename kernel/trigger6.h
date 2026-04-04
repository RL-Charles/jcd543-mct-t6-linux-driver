/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * trigger6.h -- MCT Trigger 6 USB Display DRM Driver
 *
 * Based on udl (USB DisplayLink) architecture for proven stability.
 * Protocol from mcttrigger/triggerdm + cyrozap reverse engineering.
 *
 * Copyright (C) 2026 Authentra / Ralph Friedman
 */

#ifndef _TRIGGER6_H_
#define _TRIGGER6_H_

#include <linux/usb.h>
#include <linux/spinlock.h>
#include <linux/wait.h>
#include <drm/drm_connector.h>
#include <drm/drm_device.h>
#include <drm/drm_simple_kms_helper.h>

/* USB IDs */
#define T6_VID			0x0711
#define T6_PID			0x5601

/* USB endpoint */
#define T6_EP_BULK_OUT		0x02

/* Vendor requests */
#define T6_REQ_MONITOR_CTRL	0x03
#define T6_REQ_SET_RESOLUTION	0x12
#define T6_REQ_SET_COLOR	0x23
#define T6_REQ_SET_TIMING	0x24
#define T6_REQ_SET_READY	0x31
#define T6_REQ_GET_EDID		0x80
#define T6_REQ_GET_STATUS	0x87
#define T6_REQ_GET_RAM		0x88
#define T6_REQ_RESET_LO		0x1C  /* wValue=0x0000 */
#define T6_REQ_RESET_HI		0x1C  /* wValue=0x0100 */
#define T6_REQ_FINALIZE		0x1C  /* wValue=0x0002 */

/* Video commands */
#define T6_CMD_FLIP_PRIMARY	3
#define T6_CMD_FLIP_SECONDARY	4

/* Pixel format */
#define T6_FMT_RGB32		8   /* BGRX 32-bit */

/* JPEG reset flag */
#define T6_FLAG_RESET		0x80

/* URB pool config (from udl: proven stable) */
#define T6_MAX_URBS		20
#define T6_URB_TIMEOUT		HZ  /* 1 second */

/*
 * Per-URB node in the pool. Each has a pre-allocated DMA-coherent buffer.
 */
struct t6_urb_node {
	struct list_head entry;
	struct t6_device *t6;
	struct urb *urb;
};

/*
 * URB pool -- copied from udl architecture.
 * Pre-allocated pool of USB Request Blocks for async frame sending.
 */
struct t6_urb_pool {
	struct list_head list;		/* free URBs */
	spinlock_t lock;
	wait_queue_head_t sleep;
	int available;
	int count;
	size_t buf_size;		/* per-URB buffer size */
};

/*
 * Bulk command header (32 bytes).
 */
struct t6_bulk_header {
	__le32 signature;
	__le32 payload_length;
	__le32 payload_address;
	__le32 packet_length;
	__le32 bytes_written;
	__le32 output_index;
	__le32 reserved[2];
} __packed;

/*
 * Video flip header (48 bytes).
 */
struct t6_flip_header {
	__le32 command;
	__le32 payload_size;
	__le32 fence_id;
	__le32 target_format;
	__le16 y_pitch;
	__le16 uv_pitch;
	__le32 y_fb_offset;
	__le32 u_offset;
	__le32 v_offset;
	__le32 source_format;
	u8 padding[7];
	u8 flag;
} __packed;

/*
 * Per-device state.
 */
struct t6_device {
	struct drm_device drm;
	struct usb_device *udev;
	struct usb_interface *intf;
	struct device *dmadev;

	/* Display info */
	u32 ram_mb;
	u32 fb_addr;		/* framebuffer address in T6 VRAM */
	int width, height;
	char monitor_name[16];
	int frame_seq;

	/* Cached EDID (read at probe, served from memory) */
	u8 edid_data[256];
	int edid_len;

	/* URB pool for async frame sending */
	struct t6_urb_pool urbs;

	/* DRM objects */
	struct drm_simple_display_pipe pipe;
	struct drm_connector connector;
};

static inline struct t6_device *to_t6(struct drm_device *drm)
{
	return container_of(drm, struct t6_device, drm);
}

/* connector */
int t6_connector_init(struct t6_device *t6);

/* URB pool */
int t6_alloc_urb_list(struct t6_device *t6, int count, size_t buf_size);
void t6_free_urb_list(struct t6_device *t6);
struct urb *t6_get_urb(struct t6_device *t6);
int t6_submit_urb(struct t6_device *t6, struct urb *urb, size_t len);

#endif
