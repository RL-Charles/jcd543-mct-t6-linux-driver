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
#include <linux/mutex.h>
#include <linux/miscdevice.h>
#include <linux/workqueue.h>
#include <linux/timer.h>
#include <linux/atomic.h>
#include <linux/spinlock.h>
#include <linux/wait.h>
#include <drm/drm_connector.h>
#include <drm/drm_device.h>
#include <drm/drm_simple_kms_helper.h>

#define T6_JPEG_QUALITY_DEFAULT	95

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

#define T6_OUTPUT_COUNT		2

/* Secondary JPEG path */
#define T6_FMT_NV12		6
#define T6_FMT_JPEG		13
#define T6_JPEG_PADDING_SIZE	1024
#define T6_JPEG_FB_SLOT_COUNT	3

/* Pixel format */
#define T6_FMT_RGB32		8   /* BGRX 32-bit */

/* JPEG reset flag */
#define T6_FLAG_RESET		0x80

/* USB bulk transfer tuning */
#define T6_USB_XFER_CHUNK_SIZE	(512 * 1024)
#define T6_USB_XFER_TIMEOUT_MS	2000
#define T6_FRAME_MIN_INTERVAL_MS	66	/* ~15 fps max */

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
	u8 padding[11];
	u8 flag;
} __packed;

enum t6_head_transport {
	T6_HEAD_TRANSPORT_RAW = 0,
	T6_HEAD_TRANSPORT_JPEG_CMD = 1,
	T6_HEAD_TRANSPORT_USER_JPEG = 2,
};

struct t6_head {
	struct t6_device *t6;
	u8 output_idx;
	bool connected;
	u8 status;
	u32 fb_addr;
	u32 cmd_addr;
	u32 fb_slots[T6_JPEG_FB_SLOT_COUNT];
	u8 fb_slot_count;
	u8 fb_slot_index;
	u32 cmd_base_addr;
	u32 cmd_limit_addr;
	u32 cmd_cursor_addr;
	int width;
	int height;
	char monitor_name[16];
	u32 frame_seq;
	u8 edid_data[256];
	int edid_len;
	enum t6_head_transport transport;

	struct drm_simple_display_pipe pipe;
	struct drm_connector connector;
	u8 *tx_front;
	u8 *tx_back;
	size_t tx_buf_size;
	size_t tx_len;
	u32 tx_stride;
	bool tx_pending;
	unsigned long tx_last_jiffies;
	struct miscdevice jpeg_miscdev;
	char jpeg_dev_name[48];
	bool jpeg_misc_registered;

	/* Pre-allocated staging buffer for raw frame sends */
	u8 *video_staging;
	size_t video_staging_size;

	/* Pre-allocated staging buffer for JPEG frame sends */
	u8 *jpeg_staging;
	size_t jpeg_staging_size;

	/* Framebuffer export for hybrid JPEG path (compositor → userspace encode) */
	u8 *fb_export_buf;
	spinlock_t fb_export_lock;
	wait_queue_head_t fb_export_wq;
	atomic_t fb_export_seq;
	size_t fb_export_len;

	/* Keepalive for monitor stability */
	struct timer_list keepalive_timer;
	u8 *last_jpeg_data;
	size_t last_jpeg_len;
};

/*
 * Per-device state.
 */
struct t6_device {
	struct drm_device drm;
	struct usb_device *udev;
	struct usb_interface *intf;
	struct device *dmadev;

	/* Shared chip info */
	u32 ram_mb;
	struct t6_head heads[T6_OUTPUT_COUNT];

	/* Serialize frame staging and USB submission across both heads. */
	struct work_struct tx_work;
	struct work_struct keepalive_work;
	struct delayed_work tx_defer_work;
	struct delayed_work reprobe_work;
	struct mutex tx_lock;
	struct mutex io_lock;
	unsigned int tx_next_head;
	unsigned int reprobe_attempt;
	bool manual_only;
	bool io_faulted;
	atomic_t tx_sending;
	int io_last_error;

	/* Pre-allocated USB bulk transfer chunk buffer */
	u8 *bulk_chunk;
};

static inline struct t6_device *to_t6(struct drm_device *drm)
{
	return container_of(drm, struct t6_device, drm);
}

static inline struct t6_head *t6_get_head(struct t6_device *t6,
					       unsigned int idx)
{
	return &t6->heads[idx];
}

static inline struct t6_head *t6_head_from_pipe(struct drm_simple_display_pipe *pipe)
{
	return container_of(pipe, struct t6_head, pipe);
}

static inline struct t6_head *t6_head_from_connector(struct drm_connector *connector)
{
	return container_of(connector, struct t6_head, connector);
}

static inline bool t6_head_scanout_supported(const struct t6_head *head)
{
	return head->transport == T6_HEAD_TRANSPORT_RAW ||
	       head->transport == T6_HEAD_TRANSPORT_JPEG_CMD ||
	       head->transport == T6_HEAD_TRANSPORT_USER_JPEG;
}

static inline bool t6_head_drm_scanout_enabled(const struct t6_head *head)
{
	return t6_head_scanout_supported(head) && !head->t6->manual_only;
}

static inline bool t6_head_runtime_connected(const struct t6_head *head)
{
	return READ_ONCE(head->connected) &&
	       t6_head_drm_scanout_enabled(head) &&
	       !READ_ONCE(head->t6->io_faulted);
}

/* connector */
int t6_connector_init(struct t6_device *t6, struct t6_head *head);

#endif
