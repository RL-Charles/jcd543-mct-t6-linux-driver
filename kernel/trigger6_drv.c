// SPDX-License-Identifier: GPL-2.0-only
/*
 * trigger6_drv.c -- MCT Trigger 6 USB Display DRM Driver
 *
 * Architecture: udl (USB DisplayLink) pattern for proven stability.
 * Protocol: mcttrigger/triggerdm (GPL) + cyrozap reverse engineering.
 *
 * Key safety patterns from udl:
 * - drm_dev_enter/exit guards on ALL USB calls
 * - Worker-based USB submission (never blocks atomic commit)
 * - Synchronous chunked bulk writes with centralized io_lock serialization
 * - Proper disconnect: poll_fini -> unplug -> shutdown
 *
 * Copyright (C) 2026 Authentra / Ralph Friedman
 */

#include <linux/module.h>
#include <linux/fs.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/usb.h>
#include <linux/timer.h>
#include <linux/poll.h>

#include <drm/drm_atomic_helper.h>
#include <drm/drm_drv.h>
#include <drm/drm_fourcc.h>
#include <drm/drm_framebuffer.h>
#include <drm/drm_gem_atomic_helper.h>
#include <drm/drm_gem_framebuffer_helper.h>
#include <drm/drm_gem_shmem_helper.h>
#include <drm/drm_managed.h>
#include <drm/drm_modeset_helper_vtables.h>
#include <drm/drm_probe_helper.h>
#include <drm/drm_simple_kms_helper.h>

#include "trigger6.h"

#define DRIVER_NAME	"trigger6"
#define DRIVER_DESC	"MCT Trigger 6 USB Display"

/*
 * Global mutex serialising USB bulk I/O across all T6 devices.
 * Two stations on the same hub can wedge the xHCI host controller
 * when both submit interleaved bulk URBs simultaneously.
 */
static DEFINE_MUTEX(t6_usb_bus_lock);

static bool t6_experimental_secondary_raw;
module_param_named(experimental_secondary_raw,
		   t6_experimental_secondary_raw,
		   bool,
		   0644);
MODULE_PARM_DESC(experimental_secondary_raw,
		 "Expose logical output 1 through the legacy raw transport for DRM scanout experiments");

static bool t6_secondary_userspace_jpeg;
module_param_named(secondary_userspace_jpeg,
		   t6_secondary_userspace_jpeg,
		   bool,
		   0644);
MODULE_PARM_DESC(secondary_userspace_jpeg,
		 "Expose logical output 1 through DRM while userspace injects pre-encoded JPEG frames via /dev/trigger6-*-out1-jpeg");

static bool t6_manual_only;
module_param_named(manual_only,
		   t6_manual_only,
		   bool,
		   0644);
MODULE_PARM_DESC(manual_only,
		 "Keep DRM connectors disconnected and disable automatic scanout; allow only manual userspace JPEG injection and guarded probe logging. Default: false for full driver operation.");

/*
 * Hardware init data captured from Windows USB traces.
 * These register blobs configure the T6 color pipeline, display timing,
 * and 1920x1080 @ 60 Hz mode during chip initialisation.
 */
static const u8 t6_init_color[] = {
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1f,
	0x00, 0x00, 0x00, 0x1f, 0x00, 0x00, 0x00, 0x0f,
	0x00, 0x00, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x0f,
	0x00, 0x00, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x0f,
	0x00, 0x00, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x00,
};
static const u8 t6_init_timing_pre[] = {
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
	0x80, 0x25, 0x00, 0x00, 0x00, 0x00, 0x02, 0x00,
};
static const u8 t6_init_timing_post[] = {
	0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
	0x80, 0x25, 0x00, 0x00, 0x00, 0x00, 0x02, 0x00,
};
static const u8 t6_mode_1080p[] = {
	0x14, 0x44, 0x02, 0x00, 0x3c, 0x00, 0x98, 0x08,
	0x80, 0x07, 0x18, 0x07, 0x2c, 0x00, 0x65, 0x04,
	0x38, 0x04, 0xe8, 0x03, 0x1d, 0x00, 0xbb, 0x02,
	0xe8, 0x03, 0x1d, 0x01, 0x01, 0x01, 0x00, 0x00,
};

static const u32 t6_formats[] = { DRM_FORMAT_XRGB8888 };

static const struct drm_mode_config_funcs t6_mode_config_funcs = {
	.fb_create = drm_gem_fb_create,
	.atomic_check = drm_atomic_helper_check,
	.atomic_commit = drm_atomic_helper_commit,
};

static const struct drm_mode_config_helper_funcs t6_mode_config_helper_funcs = {
	.atomic_commit_tail = drm_atomic_helper_commit_tail,
};

static const unsigned int t6_reprobe_delays_ms[] = {
	3000,
	10000,
	20000,
	30000,
	45000,
};

static int t6_ctrl_out(struct t6_device *t6, u8 req, u16 val,
		       u16 idx, const void *data, u16 size);
static int t6_ctrl_in(struct t6_device *t6, u8 req, u16 val,
		      u16 idx, void *data, u16 size);

static void t6_schedule_reprobe(struct t6_device *t6);
static void t6_trip_transport_fault(struct t6_device *t6,
					 struct t6_head *head,
					 int ret,
					 const char *source);

static const char *t6_transport_name(enum t6_head_transport transport)
{
	switch (transport) {
	case T6_HEAD_TRANSPORT_JPEG_CMD:
		return "jpeg-cmd";
	case T6_HEAD_TRANSPORT_USER_JPEG:
		return "user-jpeg";
	case T6_HEAD_TRANSPORT_RAW:
	default:
		return "raw";
	}
}

static bool t6_any_head_pending(struct t6_device *t6)
{
	unsigned int i;

	for (i = 0; i < T6_OUTPUT_COUNT; i++) {
		if (t6_get_head(t6, i)->tx_pending)
			return true;
	}
	return false;
}

static void t6_wake_all_export_waiters(struct t6_device *t6)
{
	unsigned int i;

	for (i = 0; i < T6_OUTPUT_COUNT; i++)
		wake_up_interruptible(&t6_get_head(t6, i)->fb_export_wq);
}

static void t6_reset_head_stream_state(struct t6_head *head)
{
	if (head->fb_slot_count > 1)
		head->fb_slot_index = 1;
	else
		head->fb_slot_index = 0;

	head->cmd_cursor_addr = head->cmd_base_addr;
	head->frame_seq = 0;
}

static void t6_init_head_addressing(struct t6_device *t6, struct t6_head *head)
{
	u32 tmp = t6->ram_mb - 18;

	memset(head->fb_slots, 0, sizeof(head->fb_slots));
	head->cmd_base_addr = 0;
	head->cmd_limit_addr = 0;

	if (head->output_idx == 0) {
		head->fb_addr = (tmp - 12) * 1024 * 1024;
		head->cmd_addr = 0;
		head->fb_slots[0] = head->fb_addr;
		head->fb_slot_count = 1;
	} else {
		head->cmd_addr = tmp * 1024 * 1024;
		head->fb_slots[0] = (t6->ram_mb - 12) * 1024 * 1024;
		head->fb_slots[1] = (t6->ram_mb - 8) * 1024 * 1024;
		head->fb_slots[2] = (t6->ram_mb - 4) * 1024 * 1024;
		head->fb_slot_count = T6_JPEG_FB_SLOT_COUNT;
		head->fb_addr = head->fb_slots[0];
		head->cmd_base_addr = head->cmd_addr;
		/*
		 * The vendor-style output-1 JPEG cmd ring stops at the first fb slot.
		 * Wrapping later than that walks command buckets into framebuffer space,
		 * which matches the observed "a few visible frames, then stop" failure.
		 */
		head->cmd_limit_addr = head->fb_slots[0];
	}

	t6_reset_head_stream_state(head);
}

static void t6_keepalive_timeout(struct timer_list *t);

static void t6_head_defaults(struct t6_device *t6,
			     struct t6_head *head,
			     u8 output_idx)
{
	memset(head, 0, sizeof(*head));
	head->t6 = t6;
	head->output_idx = output_idx;
	head->width = 1920;
	head->height = 1080;
	strscpy(head->monitor_name, "T6 Display", sizeof(head->monitor_name));
	timer_setup(&head->keepalive_timer, t6_keepalive_timeout, 0);
	spin_lock_init(&head->fb_export_lock);
	init_waitqueue_head(&head->fb_export_wq);
	atomic_set(&head->fb_export_seq, 0);
	if (output_idx == 0)
		head->transport = T6_HEAD_TRANSPORT_RAW;
	else if (t6_secondary_userspace_jpeg)
		head->transport = T6_HEAD_TRANSPORT_USER_JPEG;
	else if (t6_experimental_secondary_raw)
		head->transport = T6_HEAD_TRANSPORT_RAW;
	else
		head->transport = T6_HEAD_TRANSPORT_JPEG_CMD;

	t6_init_head_addressing(t6, head);
}

/*
 * Extract the monitor name from an EDID descriptor block.
 * EDID descriptors at offsets 0x36..0x7E each span 18 bytes.
 * Tag 0xFC marks the "Monitor Name" string (up to 13 ASCII chars).
 */
static void t6_parse_edid_monitor_name(struct t6_head *head)
{
	int i, j, len;

	for (i = 0x36; i < 0x7E; i += 18) {
		if (head->edid_data[i] != 0 ||
		    head->edid_data[i + 1] != 0 ||
		    head->edid_data[i + 3] != 0xFC)
			continue;

		len = min(13, (int)sizeof(head->monitor_name) - 1);
		memcpy(head->monitor_name, &head->edid_data[i + 5], len);
		head->monitor_name[len] = '\0';

		/* Trim trailing whitespace / control characters */
		for (j = len - 1; j >= 0; j--) {
			if (head->monitor_name[j] <= ' ')
				head->monitor_name[j] = '\0';
			else
				break;
		}
		return;
	}
}

static int t6_probe_head(struct t6_device *t6, struct t6_head *head)
{
	u8 status = 0;
	int ret;

	ret = t6_ctrl_in(t6, T6_REQ_GET_STATUS, head->output_idx, 0, &status, 1);
	if (ret < 1)
		return ret < 0 ? ret : -EIO;

	head->status = status;
	WRITE_ONCE(head->connected, status == 1);
	if (!head->connected)
		return 0;

	head->edid_len = 0;
	ret = t6_ctrl_in(t6, T6_REQ_GET_EDID, 0, head->output_idx,
			 head->edid_data, 128);
	if (ret >= 128) {
		head->edid_len = 128;
		head->width = head->edid_data[0x38] |
			((head->edid_data[0x3A] & 0xF0) << 4);
		head->height = head->edid_data[0x3B] |
			 ((head->edid_data[0x3D] & 0xF0) << 4);
		if (head->width == 0 || head->height == 0) {
			head->width = 1920;
			head->height = 1080;
		}
		head->width = clamp(head->width, 640, 1920);
		head->height = clamp(head->height, 480, 1200);
		t6_parse_edid_monitor_name(head);
	}

	return 0;
}

static int t6_alloc_head_buffers(struct t6_device *t6)
{
	unsigned int idx;

	/* Pre-allocate shared USB bulk chunk buffer */
	t6->bulk_chunk = kmalloc(T6_USB_XFER_CHUNK_SIZE, GFP_KERNEL);
	if (!t6->bulk_chunk)
		return -ENOMEM;

	for (idx = 0; idx < T6_OUTPUT_COUNT; idx++) {
		struct t6_head *head = t6_get_head(t6, idx);
		u32 frame_size;

		head->tx_buf_size = head->width * head->height * 4;
		head->tx_front = kvzalloc(head->tx_buf_size, GFP_KERNEL);
		head->tx_back = kvzalloc(head->tx_buf_size, GFP_KERNEL);
		if (!head->tx_front || !head->tx_back)
			return -ENOMEM;

		/* Pre-allocate video staging for raw transport */
		if (head->transport == T6_HEAD_TRANSPORT_RAW) {
			frame_size = head->width * head->height * 4;
			head->video_staging_size =
				sizeof(struct t6_flip_header) + frame_size;
			head->video_staging =
				kvzalloc(head->video_staging_size, GFP_KERNEL);
			if (!head->video_staging)
				return -ENOMEM;
		}

		/* Pre-allocate JPEG staging for non-raw heads */
		if (head->transport != T6_HEAD_TRANSPORT_RAW) {
			head->jpeg_staging_size = 3 * 1024 * 1024;
			head->jpeg_staging =
				kvzalloc(head->jpeg_staging_size, GFP_KERNEL);
			if (!head->jpeg_staging)
				return -ENOMEM;
		}

		/* Framebuffer export buffer for hybrid JPEG compositor path */
		if (head->transport == T6_HEAD_TRANSPORT_USER_JPEG) {
			head->fb_export_buf =
				kvzalloc(head->tx_buf_size, GFP_KERNEL);
			if (!head->fb_export_buf)
				return -ENOMEM;
		}
	}

	return 0;
}

static void t6_free_head_buffers(struct t6_device *t6)
{
	unsigned int idx;

	for (idx = 0; idx < T6_OUTPUT_COUNT; idx++) {
		struct t6_head *head = t6_get_head(t6, idx);

		kvfree(head->tx_back);
		kvfree(head->tx_front);
		head->tx_back = NULL;
		head->tx_front = NULL;
		head->tx_buf_size = 0;
		head->tx_len = 0;
		head->tx_pending = false;

		kvfree(head->video_staging);
		head->video_staging = NULL;
		head->video_staging_size = 0;

		kvfree(head->jpeg_staging);
		head->jpeg_staging = NULL;
		head->jpeg_staging_size = 0;

		kvfree(head->fb_export_buf);
		head->fb_export_buf = NULL;
		head->fb_export_len = 0;

		timer_delete_sync(&head->keepalive_timer);
		kvfree(head->last_jpeg_data);
		head->last_jpeg_data = NULL;
		head->last_jpeg_len = 0;
	}

	kfree(t6->bulk_chunk);
	t6->bulk_chunk = NULL;
}

static struct t6_head *t6_pop_pending_head_locked(struct t6_device *t6,
						       size_t *len)
{
	unsigned int count;

	for (count = 0; count < T6_OUTPUT_COUNT; count++) {
		unsigned int idx = (t6->tx_next_head + count) % T6_OUTPUT_COUNT;
		struct t6_head *head = t6_get_head(t6, idx);
		u8 *front;

		if (!head->tx_pending || !head->tx_front || !head->tx_back)
			continue;

		front = head->tx_front;
		head->tx_front = head->tx_back;
		head->tx_back = front;
		*len = head->tx_len;
		head->tx_pending = false;
		t6->tx_next_head = (idx + 1) % T6_OUTPUT_COUNT;
		return head;
	}

	return NULL;
}

/* ------------------------------------------------------------------
 * USB helpers -- ALL use kmalloc'd DMA-safe buffers
 * ------------------------------------------------------------------
 */

static int t6_ctrl_out(struct t6_device *t6, u8 req, u16 val,
		       u16 idx, const void *data, u16 size)
{
	void *buf = NULL;
	int ret;

	if (size && data) {
		buf = kmemdup(data, size, GFP_KERNEL);
		if (!buf)
			return -ENOMEM;
	}
	ret = usb_control_msg(t6->udev, usb_sndctrlpipe(t6->udev, 0),
			      req, USB_TYPE_VENDOR | USB_DIR_OUT,
			      val, idx, buf, size, 3000);
	kfree(buf);
	return ret;
}

static int t6_ctrl_in(struct t6_device *t6, u8 req, u16 val,
		      u16 idx, void *data, u16 size)
{
	void *buf;
	int ret;

	buf = kmalloc(size, GFP_KERNEL);
	if (!buf)
		return -ENOMEM;
	ret = usb_control_msg(t6->udev, usb_rcvctrlpipe(t6->udev, 0),
			      req, USB_TYPE_VENDOR | USB_DIR_IN,
			      val, idx, buf, size, 3000);
	if (ret >= 0)
		memcpy(data, buf, min_t(int, ret, size));
	kfree(buf);
	return ret;
}

static int t6_bulk_write(struct t6_device *t6, const void *src, size_t len)
{
	u8 *chunk_buf = t6->bulk_chunk;
	const u8 *cursor = src;
	size_t remaining = len;
	int ret = 0;

	if (!len)
		return 0;
	if (!chunk_buf)
		return -ENOMEM;

	mutex_lock(&t6_usb_bus_lock);
	while (remaining) {
		size_t chunk = min_t(size_t, T6_USB_XFER_CHUNK_SIZE, remaining);
		int actual = 0;

		memcpy(chunk_buf, cursor, chunk);
		ret = usb_bulk_msg(t6->udev,
				   usb_sndbulkpipe(t6->udev, T6_EP_BULK_OUT),
				   chunk_buf,
				   chunk,
				   &actual,
				   T6_USB_XFER_TIMEOUT_MS);
		if (ret < 0)
			break;
		if (actual != chunk) {
			ret = -EIO;
			break;
		}

		cursor += chunk;
		remaining -= chunk;
	}
	mutex_unlock(&t6_usb_bus_lock);

	return ret;
}

/* ------------------------------------------------------------------
 * T6 chip init (probe context only -- no drm_dev_enter needed)
 * ------------------------------------------------------------------
 */

static int t6_chip_init(struct t6_device *t6)
{
	bool init_head[T6_OUTPUT_COUNT] = { false };
	unsigned int idx;
	int ret;
	bool any_connected = false;

	for (idx = 0; idx < T6_OUTPUT_COUNT; idx++) {
		if (t6_get_head(t6, idx)->connected) {
			init_head[idx] = true;
			any_connected = true;
		}
	}
	if (!any_connected)
		init_head[0] = true;

	ret = t6_ctrl_out(t6, T6_REQ_RESET_LO, 0x0000, 0, NULL, 0);
	if (ret < 0)
		return ret;
	ret = t6_ctrl_out(t6, T6_REQ_RESET_HI, 0x0100, 0, NULL, 0);
	if (ret < 0)
		return ret;
	ret = t6_ctrl_out(t6, T6_REQ_SET_COLOR, 0, 0,
			  t6_init_color, sizeof(t6_init_color));
	if (ret < 0)
		return ret;
	ret = t6_ctrl_out(t6, T6_REQ_SET_TIMING, 0, 0,
			  t6_init_timing_pre, sizeof(t6_init_timing_pre));
	if (ret < 0)
		return ret;

	for (idx = 0; idx < T6_OUTPUT_COUNT; idx++) {
		struct t6_head *head = t6_get_head(t6, idx);

		if (!init_head[idx])
			continue;

		ret = t6_ctrl_out(t6, T6_REQ_SET_RESOLUTION, head->output_idx, 0,
				  t6_mode_1080p, sizeof(t6_mode_1080p));
		if (ret < 0)
			return ret;
		ret = t6_ctrl_out(t6, T6_REQ_SET_READY, head->output_idx, 0,
				  NULL, 0);
		if (ret < 0)
			return ret;
		ret = t6_ctrl_out(t6, T6_REQ_MONITOR_CTRL, head->output_idx, 1,
				  NULL, 0);
		if (ret < 0)
			return ret;
		t6_reset_head_stream_state(head);
	}

	ret = t6_ctrl_out(t6, T6_REQ_SET_TIMING, 0, 0,
			  t6_init_timing_post, sizeof(t6_init_timing_post));
	if (ret < 0)
		return ret;
	ret = t6_ctrl_out(t6, T6_REQ_FINALIZE, 0x0002, 0, NULL, 0);
	if (ret < 0)
		return ret;

	return 0;
}

/* ------------------------------------------------------------------
 * Frame sending -- synchronous bulk transfers
 * ------------------------------------------------------------------
 */

static int t6_send_frame_raw(struct t6_device *t6, struct t6_head *head,
			     const void *pixels,
			     size_t pixel_len)
{
	u32 stride = head->width * 4;
	u32 frame_size = stride * head->height;
	u32 total_payload = sizeof(struct t6_flip_header) + frame_size;
	const u8 *src = pixels;
	struct t6_bulk_header bch;
	struct t6_flip_header fh;
	u8 *video_payload;
	int ret;

	if (pixel_len < frame_size)
		return -EINVAL;

	/* Use pre-allocated staging buffer when possible */
	if (head->video_staging && total_payload <= head->video_staging_size)
		video_payload = head->video_staging;
	else
		return -ENOMEM;

	/* Build video flip header (reused for all chunks) */
	memset(&fh, 0, sizeof(fh));
	fh.command = cpu_to_le32(head->output_idx == 0 ?
				T6_CMD_FLIP_PRIMARY : T6_CMD_FLIP_SECONDARY);
	fh.payload_size = cpu_to_le32(frame_size);
	fh.target_format = cpu_to_le32(T6_FMT_RGB32);
	fh.y_pitch = cpu_to_le16(stride);
	fh.y_fb_offset = cpu_to_le32(head->fb_addr + sizeof(fh));
	fh.source_format = cpu_to_le32(T6_FMT_RGB32);
	if (head->frame_seq < 10)
		fh.flag = T6_FLAG_RESET;

	/* Bulk command header */
	memset(&bch, 0, sizeof(bch));
	bch.payload_length = cpu_to_le32(total_payload);
	bch.payload_address = cpu_to_le32(head->fb_addr);
	bch.packet_length = cpu_to_le32(total_payload);

	memcpy(video_payload, &fh, sizeof(fh));
	memcpy(video_payload + sizeof(fh), src, frame_size);

	ret = t6_bulk_write(t6, &bch, sizeof(bch));
	if (ret)
		goto out;

	ret = t6_bulk_write(t6, video_payload, total_payload);
	if (ret)
		goto out;

	head->frame_seq++;

out:
	return ret;
}

static int t6_send_jpeg_blob(struct t6_device *t6, struct t6_head *head,
			     const void *jpg_data,
			     size_t jpg_len)
{
	struct t6_bulk_header bch;
	struct t6_flip_header fh;
	u8 *video_payload;
	u8 flag;
	u8 fb_slot_index;
	u16 y_pitch;
	u32 cmd_addr;
	u32 cmd_step;
	u32 fb_addr;
	u32 y_block_size;
	u32 total_payload;
	bool wrapped = false;
	int ret = 0;

	if (!jpg_len)
		return -EINVAL;

	total_payload = sizeof(fh) + jpg_len + T6_JPEG_PADDING_SIZE;
	if (total_payload <= 1024 * 1024u)
		cmd_step = 1024 * 1024u;
	else if (total_payload <= 2 * 1024 * 1024u)
		cmd_step = 2 * 1024 * 1024u;
	else if (total_payload <= 3 * 1024 * 1024u)
		cmd_step = 3 * 1024 * 1024u;
	else
		return -E2BIG;

	cmd_addr = head->cmd_cursor_addr;
	if (head->cmd_limit_addr > head->cmd_base_addr &&
	    cmd_addr + cmd_step > head->cmd_limit_addr) {
		cmd_addr = head->cmd_base_addr;
		wrapped = true;
	}
	if (head->fb_slot_count > 1)
		fb_slot_index = (head->fb_slot_index + 1) % head->fb_slot_count;
	else
		fb_slot_index = 0;
	fb_addr = head->fb_slots[fb_slot_index] ?
		head->fb_slots[fb_slot_index] : head->fb_addr;
	flag = head->frame_seq < 10 || wrapped ? T6_FLAG_RESET : 0;

	y_pitch = ALIGN(head->width, 32);
	y_block_size = y_pitch * ALIGN(head->height, 32) + T6_JPEG_PADDING_SIZE;

	if (total_payload > head->jpeg_staging_size)
		return -E2BIG;
	video_payload = head->jpeg_staging;
	memset(video_payload, 0, total_payload);

	memset(&fh, 0, sizeof(fh));
	fh.command = cpu_to_le32(head->output_idx == 0 ?
				T6_CMD_FLIP_PRIMARY : T6_CMD_FLIP_SECONDARY);
	fh.payload_size = cpu_to_le32(total_payload - sizeof(fh));
	fh.target_format = cpu_to_le32(T6_FMT_NV12);
	fh.y_pitch = cpu_to_le16(y_pitch);
	fh.uv_pitch = cpu_to_le16(y_pitch);
	fh.y_fb_offset = cpu_to_le32(fb_addr);
	fh.u_offset = cpu_to_le32(fb_addr + y_block_size);
	fh.source_format = cpu_to_le32(T6_FMT_JPEG);
	fh.flag = flag;
	memcpy(video_payload, &fh, sizeof(fh));
	memcpy(video_payload + sizeof(fh), jpg_data, jpg_len);

	memset(&bch, 0, sizeof(bch));
	bch.payload_length = cpu_to_le32(total_payload);
	bch.payload_address = cpu_to_le32(cmd_addr);
	bch.packet_length = cpu_to_le32(total_payload);

	ret = t6_bulk_write(t6, &bch, sizeof(bch));
	if (ret)
		goto out;
	ret = t6_bulk_write(t6, video_payload, total_payload);
	if (ret)
		goto out;

	head->frame_seq++;
	head->cmd_cursor_addr = cmd_addr + cmd_step;
	head->fb_slot_index = fb_slot_index;

	/* Store last JPEG data for keepalive */
	if (!head->last_jpeg_data || head->last_jpeg_len < jpg_len) {
		kvfree(head->last_jpeg_data);
		head->last_jpeg_data = NULL;
		head->last_jpeg_len = 0;
		head->last_jpeg_data = kvmalloc(jpg_len, GFP_KERNEL);
	}
	if (head->last_jpeg_data) {
		memcpy(head->last_jpeg_data, jpg_data, jpg_len);
		head->last_jpeg_len = jpg_len;
	}

	/* Start or reset keepalive timer */
	mod_timer(&head->keepalive_timer, jiffies + msecs_to_jiffies(2000));

out:
	return ret;
}

static void t6_keepalive_work(struct work_struct *work);

/*
 * The T6 chip blanks JPEG-decoded outputs that stop receiving frames
 * after roughly 2-3 seconds.  Re-send the last JPEG blob every 2 s
 * to keep the display alive when the compositor has no new content.
 */
static void t6_keepalive_timeout(struct timer_list *t)
{
	struct t6_head *head = container_of(t, struct t6_head, keepalive_timer);
	struct t6_device *t6 = head->t6;

	if (!READ_ONCE(head->connected) || !head->last_jpeg_data)
		return;

	/* Schedule work -- timer context cannot take mutexes or do USB I/O */
	schedule_work(&t6->keepalive_work);
}

static void t6_keepalive_work(struct work_struct *work)
{
	struct t6_device *t6 = container_of(work, struct t6_device, keepalive_work);
	unsigned int i;

	for (i = 0; i < T6_OUTPUT_COUNT; i++) {
		struct t6_head *head = t6_get_head(t6, i);
		int idx;
		int ret;

		if (!READ_ONCE(head->connected) || !head->last_jpeg_data)
			continue;

		mutex_lock(&t6->io_lock);
		if (!drm_dev_enter(&t6->drm, &idx)) {
			mutex_unlock(&t6->io_lock);
			return;
		}

		ret = t6_send_jpeg_blob(t6, head,
					head->last_jpeg_data,
					head->last_jpeg_len);
		drm_dev_exit(idx);
		mutex_unlock(&t6->io_lock);

		if (!ret)
			mod_timer(&head->keepalive_timer,
				  jiffies + msecs_to_jiffies(2000));
	}
}

static int t6_send_frame_jpeg_cmd(struct t6_device *t6, struct t6_head *head,
				  const void *pixels,
				  size_t pixel_len)
{
	/*
	 * The stable secondary transport discovered in userspace sends JPEG through
	 * cmd_addr with vendor-specific layout. Keep the interface isolated here so
	 * the eventual in-kernel encoder/packer lands without rewriting the worker.
	 */
	if (head->transport == T6_HEAD_TRANSPORT_USER_JPEG)
		return 0;

	return -EOPNOTSUPP;
}

static int t6_send_frame(struct t6_device *t6, struct t6_head *head,
			 const void *pixels,
			 size_t pixel_len)
{
	switch (head->transport) {
	case T6_HEAD_TRANSPORT_RAW:
		return t6_send_frame_raw(t6, head, pixels, pixel_len);
	case T6_HEAD_TRANSPORT_USER_JPEG:
	case T6_HEAD_TRANSPORT_JPEG_CMD:
		return t6_send_frame_jpeg_cmd(t6, head, pixels, pixel_len);
	default:
		return -EINVAL;
	}
}

static ssize_t t6_jpeg_misc_write(struct file *file, const char __user *buf,
				  size_t len, loff_t *ppos)
{
	struct miscdevice *misc = file->private_data;
	struct t6_head *head = container_of(misc, struct t6_head, jpeg_miscdev);
	struct t6_device *t6 = head->t6;
	void *jpg_data;
	int idx;
	int ret;

	if (*ppos != 0)
		return -ESPIPE;
	if (!len || len > head->tx_buf_size)
		return -EINVAL;
	if (!READ_ONCE(head->connected))
		return -ENODEV;
	if (READ_ONCE(t6->io_faulted))
		return t6->io_last_error ? t6->io_last_error : -EIO;
	if (head->transport != T6_HEAD_TRANSPORT_USER_JPEG)
		return -EOPNOTSUPP;

	jpg_data = memdup_user(buf, len);
	if (IS_ERR(jpg_data))
		return PTR_ERR(jpg_data);

	mutex_lock(&t6->io_lock);
	if (!drm_dev_enter(&t6->drm, &idx)) {
		ret = -ENODEV;
		goto out_unlock;
	}

	ret = t6_send_jpeg_blob(t6, head, jpg_data, len);
	drm_dev_exit(idx);

out_unlock:
	mutex_unlock(&t6->io_lock);
	kvfree(jpg_data);
	if (ret) {
		t6_trip_transport_fault(t6, head, ret, "userspace-jpeg");
		return ret;
	}
	return len;
}

static ssize_t t6_jpeg_misc_read(struct file *file, char __user *buf,
				 size_t len, loff_t *ppos)
{
	struct miscdevice *misc = file->private_data;
	struct t6_head *head = container_of(misc, struct t6_head, jpeg_miscdev);
	struct t6_device *t6 = head->t6;
	int last_seq, ret;
	u8 *src;
	size_t frame_len;

	if (*ppos != 0)
		return -ESPIPE;
	if (head->transport != T6_HEAD_TRANSPORT_USER_JPEG)
		return -EOPNOTSUPP;
	if (!head->fb_export_buf)
		return -ENODEV;

	/* Wait for a new frame from the compositor */
	last_seq = atomic_read(&head->fb_export_seq);
	ret = wait_event_interruptible(head->fb_export_wq,
		atomic_read(&head->fb_export_seq) != last_seq ||
		drm_dev_is_unplugged(&t6->drm));
	if (ret)
		return ret;
	if (drm_dev_is_unplugged(&t6->drm))
		return -ENODEV;

	/* Pairs with smp_wmb() in t6_pipe_update() after buffer swap */
	smp_rmb();

	/* Grab the export buffer pointer under spinlock */
	spin_lock(&head->fb_export_lock);
	src = head->fb_export_buf;
	frame_len = head->fb_export_len;
	spin_unlock(&head->fb_export_lock);

	if (!src || !frame_len)
		return -EAGAIN;
	if (len < frame_len)
		return -EINVAL;

	if (copy_to_user(buf, src, frame_len))
		return -EFAULT;

	return frame_len;
}

static __poll_t t6_jpeg_misc_poll(struct file *file,
				  struct poll_table_struct *wait)
{
	struct miscdevice *misc = file->private_data;
	struct t6_head *head = container_of(misc, struct t6_head, jpeg_miscdev);
	struct t6_device *t6 = head->t6;
	__poll_t mask = 0;

	poll_wait(file, &head->fb_export_wq, wait);

	/* Always writable (for JPEG injection) */
	mask |= EPOLLOUT | EPOLLWRNORM;

	/* Readable when a frame is available */
	if (atomic_read(&head->fb_export_seq) > 0)
		mask |= EPOLLIN | EPOLLRDNORM;

	if (drm_dev_is_unplugged(&t6->drm))
		mask |= EPOLLHUP;

	return mask;
}

static const struct file_operations t6_jpeg_misc_fops = {
	.owner = THIS_MODULE,
	.read = t6_jpeg_misc_read,
	.write = t6_jpeg_misc_write,
	.poll = t6_jpeg_misc_poll,
	.llseek = noop_llseek,
};

static int t6_register_jpeg_device(struct t6_head *head)
{
	int ret;

	if (!head->connected || head->output_idx != 1 ||
	    head->transport != T6_HEAD_TRANSPORT_USER_JPEG)
		return 0;

	snprintf(head->jpeg_dev_name, sizeof(head->jpeg_dev_name),
		 "trigger6-%03u-%03u-out%u-jpeg",
		 head->t6->udev->bus->busnum,
		 head->t6->udev->devnum,
		 head->output_idx);
	head->jpeg_miscdev.minor = MISC_DYNAMIC_MINOR;
	head->jpeg_miscdev.name = head->jpeg_dev_name;
	head->jpeg_miscdev.fops = &t6_jpeg_misc_fops;
	head->jpeg_miscdev.mode = 0666;

	ret = misc_register(&head->jpeg_miscdev);
	if (ret)
		return ret;

	head->jpeg_misc_registered = true;
	dev_info(&head->t6->udev->dev,
		 "Registered userspace JPEG injection device /dev/%s for output %u\n",
		 head->jpeg_dev_name,
		 head->output_idx);
	return 0;
}

static void t6_unregister_jpeg_device(struct t6_head *head)
{
	if (!head->jpeg_misc_registered)
		return;

	misc_deregister(&head->jpeg_miscdev);
	head->jpeg_misc_registered = false;
}

static void t6_unregister_jpeg_devices(struct t6_device *t6)
{
	unsigned int idx;

	for (idx = 0; idx < T6_OUTPUT_COUNT; idx++) {
		struct t6_head *head = t6_get_head(t6, idx);

		t6_unregister_jpeg_device(head);
	}
}

static void t6_trip_transport_fault(struct t6_device *t6,
					 struct t6_head *head,
					 int ret,
					 const char *source)
{
	unsigned int idx;
	bool already_faulted;

	mutex_lock(&t6->tx_lock);
	already_faulted = t6->io_faulted;
	if (!already_faulted) {
		WRITE_ONCE(t6->io_faulted, true);
		t6->io_last_error = ret;
		for (idx = 0; idx < T6_OUTPUT_COUNT; idx++) {
			struct t6_head *fault_head = t6_get_head(t6, idx);

			fault_head->tx_pending = false;
			fault_head->tx_len = 0;
		}
	}
	mutex_unlock(&t6->tx_lock);

	if (already_faulted)
		return;

	dev_err(&t6->udev->dev,
		"Halting T6 frame traffic after %s transport error on output %u: %d\n",
		source, head->output_idx, ret);
	dev_err(&t6->udev->dev,
		"Further scanout stays disabled until the module is reloaded or the adapter is unplugged/replugged\n");

	if (!drm_dev_is_unplugged(&t6->drm))
		drm_kms_helper_hotplug_event(&t6->drm);
}

static void t6_update_connector_status(struct t6_head *head)
{
	head->connector.status = t6_head_runtime_connected(head) ?
		connector_status_connected : connector_status_disconnected;
}

static void t6_log_head(struct t6_head *head)
{
	const char *scanout_state;

	if (!t6_head_scanout_supported(head))
		scanout_state = "blocked";
	else if (head->t6->manual_only)
		scanout_state = "manual-only";
	else if (READ_ONCE(head->t6->io_faulted))
		scanout_state = "halted";
	else
		scanout_state = "enabled";

	dev_info(&head->t6->udev->dev,
		 "Head %u: %s (%dx%d) transport=%s scanout=%s fb=0x%08x cmd=0x%08x cmd-cursor=0x%08x\n",
		 head->output_idx,
		 head->monitor_name,
		 head->width,
		 head->height,
		 t6_transport_name(head->transport),
		 scanout_state,
		 head->fb_addr,
		 head->cmd_addr,
		 head->cmd_cursor_addr);
	if (head->connected && !t6_head_scanout_supported(head))
		dev_warn(&head->t6->udev->dev,
			 "Head %u is detected but DRM scanout is disabled until JPEG/cmd transport exists in-kernel\n",
			 head->output_idx);
	else if (head->connected && head->transport == T6_HEAD_TRANSPORT_USER_JPEG)
		dev_info(&head->t6->udev->dev,
			 "Head %u is compositor-managed; a userspace daemon must read() raw frames and write() JPEG data to /dev/trigger6-*-out1-jpeg\n",
			 head->output_idx);
	else if (head->connected && head->t6->manual_only)
		dev_info(&head->t6->udev->dev,
			 "Head %u is in manual-only mode; DRM connectors stay disconnected until the module is reloaded with manual_only=0\n",
			 head->output_idx);
}

static bool t6_any_head_disconnected(struct t6_device *t6)
{
	unsigned int idx;

	for (idx = 0; idx < T6_OUTPUT_COUNT; idx++) {
		if (!t6_get_head(t6, idx)->connected)
			return true;
	}

	return false;
}

static void t6_reprobe_work(struct work_struct *work)
{
	struct t6_device *t6 = container_of(to_delayed_work(work),
					   struct t6_device,
					   reprobe_work);
	bool any_new_connection = false;
	bool changed = false;
	unsigned int idx;
	int enter_idx;
	int ret;

	if (READ_ONCE(t6->io_faulted))
		return;

	if (!drm_dev_enter(&t6->drm, &enter_idx))
		return;

	mutex_lock(&t6->io_lock);
	for (idx = 0; idx < T6_OUTPUT_COUNT; idx++) {
		struct t6_head *head = t6_get_head(t6, idx);
		bool was_connected = head->connected;
		int old_width = head->width;
		int old_height = head->height;
		char old_name[sizeof(head->monitor_name)];

		memcpy(old_name, head->monitor_name, sizeof(old_name));
		ret = t6_probe_head(t6, head);
		if (ret < 0) {
			dev_warn(&t6->udev->dev,
				 "Deferred head %u probe failed: %d\n",
				 head->output_idx, ret);
			continue;
		}

		if (!was_connected && head->connected)
			any_new_connection = true;

		if (was_connected != head->connected ||
		    old_width != head->width ||
		    old_height != head->height ||
		    strncmp(old_name, head->monitor_name, sizeof(old_name)))
			changed = true;
	}

	if (any_new_connection) {
		ret = t6_chip_init(t6);
		if (ret < 0)
			dev_warn(&t6->udev->dev,
				 "Deferred chip re-init failed after late head detection: %d\n",
				 ret);
		else
			changed = true;
	}

	for (idx = 0; idx < T6_OUTPUT_COUNT; idx++) {
		struct t6_head *head = t6_get_head(t6, idx);

		t6_update_connector_status(head);
		if (head->connected) {
			if (!head->jpeg_misc_registered) {
				ret = t6_register_jpeg_device(head);
				if (ret < 0)
					dev_warn(&t6->udev->dev,
						 "Failed to register deferred JPEG device for output %u: %d\n",
						 head->output_idx, ret);
			}
			if (changed)
				t6_log_head(head);
		} else {
			t6_unregister_jpeg_device(head);
		}
	}
	mutex_unlock(&t6->io_lock);
	drm_dev_exit(enter_idx);

	if (drm_dev_is_unplugged(&t6->drm))
		return;

	if (changed)
		drm_kms_helper_hotplug_event(&t6->drm);

	if (t6_any_head_disconnected(t6))
		t6_schedule_reprobe(t6);
}

static void t6_schedule_reprobe(struct t6_device *t6)
{
	unsigned int delay_ms;

	if (t6->reprobe_attempt >= ARRAY_SIZE(t6_reprobe_delays_ms))
		return;

	delay_ms = t6_reprobe_delays_ms[t6->reprobe_attempt++];
	schedule_delayed_work(&t6->reprobe_work,
			      msecs_to_jiffies(delay_ms));
}

static void t6_frame_defer_work(struct work_struct *work)
{
	struct t6_device *t6 = container_of(to_delayed_work(work),
					    struct t6_device, tx_defer_work);
	queue_work(system_unbound_wq, &t6->tx_work);
}

static void t6_frame_work(struct work_struct *work)
{
	struct t6_device *t6 = container_of(work, struct t6_device, tx_work);
	struct t6_head *head;
	size_t len;
	int ret, idx;
	bool more;
	unsigned long elapsed;

	if (READ_ONCE(t6->io_faulted))
		return;

	atomic_set(&t6->tx_sending, 1);

	mutex_lock(&t6->tx_lock);
	head = t6_pop_pending_head_locked(t6, &len);
	if (!head) {
		mutex_unlock(&t6->tx_lock);
		atomic_set(&t6->tx_sending, 0);
		return;
	}
	/* Check if another head also has a pending frame */
	more = t6_any_head_pending(t6);
	mutex_unlock(&t6->tx_lock);

	/*
	 * Rate-limit: don't send frames faster than USB can handle.
	 * Skip this frame if we're within the minimum interval.
	 */
	elapsed = jiffies - head->tx_last_jiffies;
	if (head->tx_last_jiffies &&
	    elapsed < msecs_to_jiffies(T6_FRAME_MIN_INTERVAL_MS)) {
		atomic_set(&t6->tx_sending, 0);
		/* Reschedule after the remaining cooling period */
		queue_delayed_work(system_unbound_wq, &t6->tx_defer_work,
				   msecs_to_jiffies(T6_FRAME_MIN_INTERVAL_MS) - elapsed);
		return;
	}

	if (!drm_dev_enter(&t6->drm, &idx)) {
		atomic_set(&t6->tx_sending, 0);
		return;
	}

	mutex_lock(&t6->io_lock);
	ret = t6_send_frame(t6, head, head->tx_front, len);
	mutex_unlock(&t6->io_lock);
	drm_dev_exit(idx);

	head->tx_last_jiffies = jiffies;
	atomic_set(&t6->tx_sending, 0);

	if (ret) {
		t6_trip_transport_fault(t6, head, ret, "drm");
		dev_warn_ratelimited(&t6->udev->dev,
				     "Frame send failed on output %u: %d\n",
				     head->output_idx, ret);
		return;
	}

	/* If more heads have pending frames, reschedule rather than loop */
	if (more)
		queue_work(system_unbound_wq, &t6->tx_work);
}

/* ------------------------------------------------------------------
 * DRM pipe callbacks
 * ------------------------------------------------------------------
 */

static void t6_pipe_enable(struct drm_simple_display_pipe *pipe,
			   struct drm_crtc_state *crtc_state,
			   struct drm_plane_state *plane_state)
{
	struct t6_head *head = t6_head_from_pipe(pipe);
	struct t6_device *t6 = head->t6;
	int idx;

	if (!drm_dev_enter(&t6->drm, &idx))
		return;

	t6_ctrl_out(t6, T6_REQ_MONITOR_CTRL, head->output_idx, 1, NULL, 0);
	drm_dev_exit(idx);
}

static void t6_pipe_disable(struct drm_simple_display_pipe *pipe)
{
	struct t6_head *head = t6_head_from_pipe(pipe);
	struct t6_device *t6 = head->t6;
	int idx;

	timer_delete_sync(&head->keepalive_timer);

	if (!drm_dev_enter(&t6->drm, &idx))
		return;

	t6_ctrl_out(t6, T6_REQ_MONITOR_CTRL, head->output_idx, 0, NULL, 0);
	drm_dev_exit(idx);
}

/*
 * USB displays have no hardware vblank interrupt. Tell the atomic helper to
 * fake vblank events so drm_atomic_helper_wait_for_flip_done() doesn't block
 * indefinitely.
 */
static int t6_pipe_check(struct drm_simple_display_pipe *pipe,
			 struct drm_plane_state *plane_state,
			 struct drm_crtc_state *crtc_state)
{
	crtc_state->no_vblank = true;
	return 0;
}

static void t6_pipe_update(struct drm_simple_display_pipe *pipe,
			   struct drm_plane_state *old_state)
{
	struct drm_plane_state *state = pipe->plane.state;
	struct drm_shadow_plane_state *shadow;
	struct drm_framebuffer *fb;
	struct t6_head *head = t6_head_from_pipe(pipe);
	struct t6_device *t6;
	void *vaddr;
	size_t frame_len;
	int idx;

	(void)old_state;

	if (!state)
		return;

	fb = state->fb;
	if (!fb)
		return;

	/* Userspace owns frame injection for the hybrid secondary JPEG path.
	 * Capture the compositor's framebuffer and make it available to the
	 * userspace daemon via read() on the JPEG misc device.
	 */
	if (head->transport == T6_HEAD_TRANSPORT_USER_JPEG) {
		struct drm_shadow_plane_state *export_shadow;
		void *export_vaddr;
		size_t export_len;
		u8 *tmp;

		export_shadow = to_drm_shadow_plane_state(state);
		export_vaddr = export_shadow->data[0].vaddr;
		if (!export_vaddr)
			return;

		export_len = fb->pitches[0] * fb->height;
		if (export_len > head->tx_buf_size || !head->fb_export_buf)
			return;

		/* Write framebuffer into tx_back (no lock needed — only we write here) */
		memcpy(head->tx_back, export_vaddr, export_len);

		/* Swap tx_back and fb_export_buf so the reader gets the fresh frame
		 * while the next pipe_update writes to the other buffer.
		 */
		spin_lock(&head->fb_export_lock);
		tmp = head->fb_export_buf;
		head->fb_export_buf = head->tx_back;
		head->fb_export_len = export_len;
		head->tx_back = tmp;
		spin_unlock(&head->fb_export_lock);

		/* Ensure buffer contents visible before bumping sequence */
		smp_wmb();
		atomic_inc(&head->fb_export_seq);
		wake_up_interruptible(&head->fb_export_wq);
		return;
	}

	t6 = to_t6(pipe->crtc.dev);
	if (t6->manual_only)
		return;
	if (READ_ONCE(t6->io_faulted))
		return;

	shadow = to_drm_shadow_plane_state(state);

	vaddr = shadow->data[0].vaddr;
	if (!vaddr)
		return;

	/*
	 * Drop frames if USB I/O is still in progress from a previous frame.
	 * The compositor sends frames much faster than USB can drain them.
	 * Latest-wins: the next frame will pick up whatever is current.
	 */
	if (atomic_read(&t6->tx_sending))
		return;

	/*
	 * Kernel 6.17 can hand us a stale old_state during drm_dev_register().
	 * Queue the latest full frame and let the worker perform USB I/O outside
	 * the atomic commit path.
	 */
	frame_len = fb->pitches[0] * fb->height;
	if (frame_len > head->tx_buf_size)
		return;

	if (!drm_dev_enter(&t6->drm, &idx))
		return;

	if (!mutex_trylock(&t6->tx_lock))
		goto out_exit;
	memcpy(head->tx_back, vaddr, frame_len);
	head->tx_len = frame_len;
	head->tx_pending = true;
	mutex_unlock(&t6->tx_lock);

	queue_work(system_unbound_wq, &t6->tx_work);

out_exit:
	drm_dev_exit(idx);
}

static const struct drm_simple_display_pipe_funcs t6_pipe_funcs = {
	.enable = t6_pipe_enable,
	.disable = t6_pipe_disable,
	.check = t6_pipe_check,
	.update = t6_pipe_update,
	DRM_GEM_SIMPLE_DISPLAY_PIPE_SHADOW_PLANE_FUNCS,
};

/* ------------------------------------------------------------------
 * DRM driver
 * ------------------------------------------------------------------
 */

DEFINE_DRM_GEM_FOPS(t6_fops);

static const struct drm_driver t6_drm_driver = {
	.driver_features = DRIVER_MODESET | DRIVER_GEM | DRIVER_ATOMIC,
	.name = DRIVER_NAME,
	.desc = DRIVER_DESC,
	.major = 1,
	.minor = 0,
	.fops = &t6_fops,
	DRM_GEM_SHMEM_DRIVER_OPS,
};

/* ------------------------------------------------------------------
 * USB probe / disconnect
 * ------------------------------------------------------------------
 */

static int t6_usb_probe(struct usb_interface *intf,
			const struct usb_device_id *id)
{
	struct usb_device *udev = interface_to_usbdev(intf);
	struct t6_device *t6;
	struct drm_device *drm;
	__le32 ram_le;
	int ret;
	unsigned int head_idx;

	t6 = devm_drm_dev_alloc(&intf->dev, &t6_drm_driver,
				struct t6_device, drm);
	if (IS_ERR(t6))
		return PTR_ERR(t6);

	drm = &t6->drm;
	t6->udev = usb_get_dev(udev);
	t6->intf = intf;
	t6->manual_only = t6_manual_only;
	t6->io_faulted = false;
	t6->io_last_error = 0;

	/* DMA device for GEM */
	t6->dmadev = usb_intf_get_dma_device(intf);
	if (t6->dmadev)
		drm_dev_set_dma_dev(drm, t6->dmadev);

	usb_set_intfdata(intf, t6);

	/* Query RAM */
	ret = t6_ctrl_in(t6, T6_REQ_GET_RAM, 0, 0, &ram_le, 4);
	if (ret < 4) {
		dev_err(&intf->dev, "RAM query failed: %d\n", ret);
		ret = -EIO;
		goto err_put;
	}
	t6->ram_mb = le32_to_cpu(ram_le);
	if (t6->ram_mb < 32 || t6->ram_mb > 512) {
		dev_err(&intf->dev, "Unexpected T6 RAM size: %u MB\n",
			t6->ram_mb);
		ret = -ENODEV;
		goto err_put;
	}
	dev_info(&intf->dev, "T6 RAM: %u MB\n", t6->ram_mb);

	for (head_idx = 0; head_idx < T6_OUTPUT_COUNT; head_idx++) {
		struct t6_head *head = t6_get_head(t6, head_idx);

		t6_head_defaults(t6, head, head_idx);
		ret = t6_probe_head(t6, head);
		if (ret < 0)
			dev_warn(&intf->dev,
				 "Head %u probe failed, using defaults: %d\n",
				 head_idx, ret);
	}

	for (head_idx = 0; head_idx < T6_OUTPUT_COUNT; head_idx++) {
		struct t6_head *head = t6_get_head(t6, head_idx);

		if (!head->connected)
			continue;

		t6_log_head(head);
	}

	mutex_init(&t6->tx_lock);
	mutex_init(&t6->io_lock);
	INIT_WORK(&t6->tx_work, t6_frame_work);
	INIT_WORK(&t6->keepalive_work, t6_keepalive_work);
	INIT_DELAYED_WORK(&t6->tx_defer_work, t6_frame_defer_work);
	INIT_DELAYED_WORK(&t6->reprobe_work, t6_reprobe_work);
	t6->reprobe_attempt = 0;
	ret = t6_alloc_head_buffers(t6);
	if (ret < 0) {
		ret = -ENOMEM;
		goto err_buffers;
	}

	/* Initialize T6 chip */
	ret = t6_chip_init(t6);
	if (ret < 0) {
		dev_err(&intf->dev, "Chip init failed: %d\n", ret);
		goto err_buffers;
	}

	/* DRM mode config */
	ret = drmm_mode_config_init(drm);
	if (ret)
		goto err_buffers;
	drm->mode_config.funcs = &t6_mode_config_funcs;
	drm->mode_config.helper_private = &t6_mode_config_helper_funcs;

	drm->mode_config.min_width = 640;
	drm->mode_config.min_height = 480;
	drm->mode_config.max_width = 1920;
	drm->mode_config.max_height = 1200;
	drm->mode_config.preferred_depth = 32;

	for (head_idx = 0; head_idx < T6_OUTPUT_COUNT; head_idx++) {
		struct t6_head *head = t6_get_head(t6, head_idx);

		ret = t6_connector_init(t6, head);
		if (ret)
			goto err_buffers;

		ret = drm_simple_display_pipe_init(drm, &head->pipe,
					   &t6_pipe_funcs,
					   t6_formats,
					   ARRAY_SIZE(t6_formats),
					   NULL, &head->connector);
		if (ret)
			goto err_buffers;
	}

	drm_mode_config_reset(drm);

	/*
	 * Advertise only heads with a currently supported transport as connected
	 * until the in-kernel JPEG/cmd path exists for the secondary output.
	 */
	for (head_idx = 0; head_idx < T6_OUTPUT_COUNT; head_idx++) {
		struct t6_head *head = t6_get_head(t6, head_idx);

		t6_update_connector_status(head);
	}

	if (t6_experimental_secondary_raw)
		dev_warn(&intf->dev,
			 "experimental_secondary_raw=1 exposes logical output 1 through the unstable raw transport; expect flicker or corruption until the in-kernel JPEG path exists\n");
	if (t6_secondary_userspace_jpeg)
		dev_warn(&intf->dev,
			 "secondary_userspace_jpeg=1 requires a userspace feeder to write JPEG frames into /dev/trigger6-*-out1-jpeg for logical output 1\n");
	if (t6->manual_only)
		dev_warn(&intf->dev,
			 "manual_only=1 keeps DRM connectors disconnected and blocks automatic scanout; use this for the safest guarded live probes\n");

	for (head_idx = 0; head_idx < T6_OUTPUT_COUNT; head_idx++) {
		ret = t6_register_jpeg_device(t6_get_head(t6, head_idx));
		if (ret)
			goto err_jpeg;
	}

	/* Register DRM device */
	ret = drm_dev_register(drm, 0);
	if (ret)
		goto err_jpeg;

	dev_info(&intf->dev,
		 "T6 display ready with %u logical heads modeled\n",
		 T6_OUTPUT_COUNT);
	if (t6_any_head_disconnected(t6))
		t6_schedule_reprobe(t6);
	return 0;

err_jpeg:
	t6_unregister_jpeg_devices(t6);
err_buffers:
	cancel_delayed_work_sync(&t6->reprobe_work);
	cancel_delayed_work_sync(&t6->tx_defer_work);
	cancel_work_sync(&t6->tx_work);
	cancel_work_sync(&t6->keepalive_work);
	t6_free_head_buffers(t6);
err_put:
	if (t6->dmadev)
		put_device(t6->dmadev);
	usb_put_dev(t6->udev);
	return ret;
}

static void t6_usb_disconnect(struct usb_interface *intf)
{
	struct t6_device *t6 = usb_get_intfdata(intf);

	usb_set_intfdata(intf, NULL);

	if (!t6)
		return;

	dev_info(&intf->dev, "T6 disconnecting\n");

	/*
	 * Disconnect ordering:
	 * 1. Unplug -- waits for in-progress drm_dev_enter, blocks new ones
	 * 2. Cancel async work -- reprobe/hotplug must not run after unplug
	 * 3. Shutdown -- disables outputs (pipe_update guarded by drm_dev_enter)
	 * 4. Tear down userspace-visible state and buffers
	 * No poll_fini needed -- polling is disabled.
	 */
	drm_dev_unplug(&t6->drm);
	/* Wake any userspace readers blocked on framebuffer export */
	t6_wake_all_export_waiters(t6);
	cancel_delayed_work_sync(&t6->reprobe_work);
	cancel_delayed_work_sync(&t6->tx_defer_work);
	cancel_work_sync(&t6->tx_work);
	cancel_work_sync(&t6->keepalive_work);
	drm_atomic_helper_shutdown(&t6->drm);
	t6_unregister_jpeg_devices(t6);
	t6_free_head_buffers(t6);

	if (t6->dmadev) {
		put_device(t6->dmadev);
		t6->dmadev = NULL;
	}
	usb_put_dev(t6->udev);
}

/* ------------------------------------------------------------------
 * USB suspend / resume
 * ------------------------------------------------------------------
 */

static int t6_usb_suspend(struct usb_interface *intf, pm_message_t message)
{
	struct t6_device *t6 = usb_get_intfdata(intf);
	unsigned int i;

	if (!t6)
		return 0;

	for (i = 0; i < T6_OUTPUT_COUNT; i++)
		timer_delete_sync(&t6_get_head(t6, i)->keepalive_timer);

	cancel_delayed_work_sync(&t6->reprobe_work);
	cancel_delayed_work_sync(&t6->tx_defer_work);
	cancel_work_sync(&t6->tx_work);
	cancel_work_sync(&t6->keepalive_work);

	return 0;
}

static int t6_usb_resume(struct usb_interface *intf)
{
	struct t6_device *t6 = usb_get_intfdata(intf);

	if (!t6)
		return 0;

	/*
	 * Re-initialise the chip -- the T6 loses all state across
	 * a USB suspend cycle.  The DRM atomic state machine will
	 * call pipe_enable/pipe_update to resume scanout.
	 */
	return t6_chip_init(t6);
}

/* ------------------------------------------------------------------
 * USB driver
 * ------------------------------------------------------------------
 */

static const struct usb_device_id t6_ids[] = {
	{ USB_DEVICE(T6_VID, T6_PID) },
	{ }
};
MODULE_DEVICE_TABLE(usb, t6_ids);

static struct usb_driver t6_usb_driver = {
	.name = DRIVER_NAME,
	.probe = t6_usb_probe,
	.disconnect = t6_usb_disconnect,
	.suspend = t6_usb_suspend,
	.resume = t6_usb_resume,
	.reset_resume = t6_usb_resume,
	.id_table = t6_ids,
};
module_usb_driver(t6_usb_driver);

MODULE_AUTHOR("Authentra / Ralph Friedman");
MODULE_DESCRIPTION(DRIVER_DESC);
MODULE_LICENSE("GPL");
