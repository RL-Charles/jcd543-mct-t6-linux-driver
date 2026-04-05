// SPDX-License-Identifier: GPL-2.0-only
/*
 * trigger6_drv.c -- MCT Trigger 6 USB Display DRM Driver
 *
 * Architecture: udl (USB DisplayLink) pattern for proven stability.
 * Protocol: mcttrigger/triggerdm (GPL) + cyrozap reverse engineering.
 *
 * Key safety patterns from udl:
 * - drm_dev_enter/exit guards on ALL USB calls
 * - Async URB pool (never blocks atomic commit)
 * - Per-URB DMA-coherent buffers (no shared buffer races)
 * - Proper disconnect: poll_fini -> unplug -> shutdown -> drain URBs
 *
 * Copyright (C) 2026 Authentra / Ralph Friedman
 */

#include <linux/module.h>
#include <linux/slab.h>
#include <linux/usb.h>

#include <drm/drm_atomic_helper.h>
#include <drm/drm_damage_helper.h>
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

/* Init data from Windows captures */
static const u8 init_color[] = {
	0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x1f,
	0x00,0x00,0x00,0x1f,0x00,0x00,0x00,0x0f,
	0x00,0x00,0x00,0x0f,0x00,0x00,0x00,0x0f,
	0x00,0x00,0x00,0x0f,0x00,0x00,0x00,0x0f,
	0x00,0x00,0x00,0x0f,0x00,0x00,0x00,0x00,
};
static const u8 init_timing_pre[] = {
	0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
	0x80,0x25,0x00,0x00,0x00,0x00,0x02,0x00,
};
static const u8 init_timing_post[] = {
	0x01,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
	0x80,0x25,0x00,0x00,0x00,0x00,0x02,0x00,
};
static const u8 mode_1080p[] = {
	0x14,0x44,0x02,0x00,0x3c,0x00,0x98,0x08,
	0x80,0x07,0x18,0x07,0x2c,0x00,0x65,0x04,
	0x38,0x04,0xe8,0x03,0x1d,0x00,0xbb,0x02,
	0xe8,0x03,0x1d,0x01,0x01,0x01,0x00,0x00,
};

static const u32 t6_formats[] = { DRM_FORMAT_XRGB8888 };

/* ──────────────────────────────────────────────────────────────────
 * USB helpers -- ALL use kmalloc'd DMA-safe buffers
 * ────────────────────────────────────────────────────────────────── */

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

/* ──────────────────────────────────────────────────────────────────
 * URB pool -- async frame sending (from udl pattern)
 * ────────────────────────────────────────────────────────────────── */

static void t6_urb_completion(struct urb *urb)
{
	struct t6_urb_node *node = urb->context;
	struct t6_device *t6 = node->t6;
	unsigned long flags;

	/* Return URB to free pool */
	spin_lock_irqsave(&t6->urbs.lock, flags);
	list_add_tail(&node->entry, &t6->urbs.list);
	t6->urbs.available++;
	spin_unlock_irqrestore(&t6->urbs.lock, flags);

	wake_up(&t6->urbs.sleep);
}

int t6_alloc_urb_list(struct t6_device *t6, int count, size_t buf_size)
{
	struct usb_device *udev = t6->udev;
	int i;

	spin_lock_init(&t6->urbs.lock);
	INIT_LIST_HEAD(&t6->urbs.list);
	init_waitqueue_head(&t6->urbs.sleep);
	t6->urbs.count = 0;
	t6->urbs.available = 0;
	t6->urbs.buf_size = buf_size;

	for (i = 0; i < count; i++) {
		struct t6_urb_node *node;
		void *buf;

		node = kzalloc(sizeof(*node), GFP_KERNEL);
		if (!node)
			break;

		node->t6 = t6;
		node->urb = usb_alloc_urb(0, GFP_KERNEL);
		if (!node->urb) {
			kfree(node);
			break;
		}

		buf = usb_alloc_coherent(udev, buf_size, GFP_KERNEL,
					 &node->urb->transfer_dma);
		if (!buf) {
			usb_free_urb(node->urb);
			kfree(node);
			break;
		}

		usb_fill_bulk_urb(node->urb, udev,
				  usb_sndbulkpipe(udev, T6_EP_BULK_OUT),
				  buf, buf_size, t6_urb_completion, node);
		node->urb->transfer_flags |= URB_NO_TRANSFER_DMA_MAP;

		list_add_tail(&node->entry, &t6->urbs.list);
		t6->urbs.count++;
		t6->urbs.available++;
	}

	return t6->urbs.count;
}

void t6_free_urb_list(struct t6_device *t6)
{
	struct t6_urb_node *node;
	struct list_head *entry;
	int count = t6->urbs.count;

	/* Wait for ALL in-flight URBs to complete and return to pool */
	while (count--) {
		/* Block until a URB is available */
		if (!wait_event_timeout(t6->urbs.sleep,
					!list_empty(&t6->urbs.list),
					T6_URB_TIMEOUT * 3)) {
			dev_warn(&t6->udev->dev,
				 "Timed out waiting for URB %d\n", count);
			break;
		}

		spin_lock_irq(&t6->urbs.lock);
		entry = t6->urbs.list.next;
		list_del_init(entry);
		spin_unlock_irq(&t6->urbs.lock);

		node = list_entry(entry, struct t6_urb_node, entry);

		usb_free_coherent(t6->udev, t6->urbs.buf_size,
				  node->urb->transfer_buffer,
				  node->urb->transfer_dma);
		usb_free_urb(node->urb);
		kfree(node);
	}

	t6->urbs.count = 0;
	t6->urbs.available = 0;
	wake_up_all(&t6->urbs.sleep);
}

struct urb *t6_get_urb(struct t6_device *t6)
{
	struct t6_urb_node *node = NULL;
	int ret;

	/* Wait for a free URB with timeout */
	ret = wait_event_interruptible_timeout(t6->urbs.sleep,
		({
			unsigned long flags;
			spin_lock_irqsave(&t6->urbs.lock, flags);
			if (!list_empty(&t6->urbs.list)) {
				node = list_first_entry(&t6->urbs.list,
							struct t6_urb_node,
							entry);
				list_del_init(&node->entry);
				t6->urbs.available--;
			}
			spin_unlock_irqrestore(&t6->urbs.lock, flags);
			node != NULL;
		}),
		T6_URB_TIMEOUT);

	if (!node)
		return NULL;

	return node->urb;
}

int t6_submit_urb(struct t6_device *t6, struct urb *urb, size_t len)
{
	int ret;

	urb->transfer_buffer_length = len;
	ret = usb_submit_urb(urb, GFP_ATOMIC);
	if (ret) {
		/* Submit failed -- return URB to pool immediately */
		t6_urb_completion(urb);
	}
	return ret;
}

/* ──────────────────────────────────────────────────────────────────
 * T6 chip init (probe context only -- no drm_dev_enter needed)
 * ────────────────────────────────────────────────────────────────── */

static int t6_chip_init(struct t6_device *t6)
{
	int ret;

	ret = t6_ctrl_out(t6, T6_REQ_RESET_LO, 0x0000, 0, NULL, 0);
	if (ret < 0) return ret;
	ret = t6_ctrl_out(t6, T6_REQ_RESET_HI, 0x0100, 0, NULL, 0);
	if (ret < 0) return ret;
	ret = t6_ctrl_out(t6, T6_REQ_SET_COLOR, 0, 0,
			  init_color, sizeof(init_color));
	if (ret < 0) return ret;
	ret = t6_ctrl_out(t6, T6_REQ_SET_TIMING, 0, 0,
			  init_timing_pre, sizeof(init_timing_pre));
	if (ret < 0) return ret;

	/* Output 0: resolution + software_ready + enable */
	ret = t6_ctrl_out(t6, T6_REQ_SET_RESOLUTION, 0, 0,
			  mode_1080p, sizeof(mode_1080p));
	if (ret < 0) return ret;
	ret = t6_ctrl_out(t6, T6_REQ_SET_READY, 0, 0, NULL, 0);
	if (ret < 0) return ret;
	ret = t6_ctrl_out(t6, T6_REQ_MONITOR_CTRL, 0, 1, NULL, 0);
	if (ret < 0) return ret;

	ret = t6_ctrl_out(t6, T6_REQ_SET_TIMING, 0, 0,
			  init_timing_post, sizeof(init_timing_post));
	if (ret < 0) return ret;
	ret = t6_ctrl_out(t6, T6_REQ_FINALIZE, 0x0002, 0, NULL, 0);
	if (ret < 0) return ret;

	return 0;
}

/* ──────────────────────────────────────────────────────────────────
 * Frame sending -- async URB (udl pattern)
 * ────────────────────────────────────────────────────────────────── */

static int t6_send_frame(struct t6_device *t6, const void *pixels,
			 size_t pixel_len)
{
	u32 stride = t6->width * 4;
	u32 frame_size = stride * t6->height;
	u32 total_payload = sizeof(struct t6_flip_header) + frame_size;
	const u8 *src = pixels;
	struct t6_bulk_header bch;
	struct t6_flip_header fh;
	size_t first_data, off, written, cs;
	struct urb *urb;
	u8 *buf;
	int ret;

	if (pixel_len < frame_size)
		return -EINVAL;

	/* Build video flip header (reused for all chunks) */
	memset(&fh, 0, sizeof(fh));
	fh.command = cpu_to_le32(T6_CMD_FLIP_PRIMARY);
	fh.payload_size = cpu_to_le32(frame_size);
	fh.target_format = cpu_to_le32(T6_FMT_RGB32);
	fh.y_pitch = cpu_to_le16(stride);
	fh.y_fb_offset = cpu_to_le32(t6->fb_addr);
	fh.source_format = cpu_to_le32(T6_FMT_RGB32);
	if (t6->frame_seq < 10)
		fh.flag = T6_FLAG_RESET;

	/* First chunk: bulk header + flip header + pixel data */
	first_data = t6->urbs.buf_size - sizeof(bch) - sizeof(fh);
	if (first_data > frame_size)
		first_data = frame_size;

	urb = t6_get_urb(t6);
	if (!urb)
		return -ENOMEM;

	buf = urb->transfer_buffer;

	/* Bulk command header */
	memset(&bch, 0, sizeof(bch));
	bch.payload_length = cpu_to_le32(total_payload);
	bch.payload_address = cpu_to_le32(t6->fb_addr);
	bch.packet_length = cpu_to_le32(sizeof(fh) + first_data);
	bch.output_index = cpu_to_le32(0);

	memcpy(buf, &bch, sizeof(bch));
	memcpy(buf + sizeof(bch), &fh, sizeof(fh));
	memcpy(buf + sizeof(bch) + sizeof(fh), src, first_data);

	ret = t6_submit_urb(t6, urb,
			    sizeof(bch) + sizeof(fh) + first_data);
	if (ret)
		return ret;

	/* Remaining chunks */
	off = first_data;
	written = sizeof(fh) + first_data;
	while (off < frame_size) {
		cs = min_t(size_t,
			   t6->urbs.buf_size - sizeof(bch),
			   frame_size - off);

		urb = t6_get_urb(t6);
		if (!urb)
			return -ENOMEM;

		buf = urb->transfer_buffer;

		memset(&bch, 0, sizeof(bch));
		bch.payload_length = cpu_to_le32(total_payload);
		bch.payload_address = cpu_to_le32(t6->fb_addr);
		bch.packet_length = cpu_to_le32(cs);
		bch.bytes_written = cpu_to_le32(written);
		bch.output_index = cpu_to_le32(0);

		memcpy(buf, &bch, sizeof(bch));
		memcpy(buf + sizeof(bch), src + off, cs);

		ret = t6_submit_urb(t6, urb, sizeof(bch) + cs);
		if (ret)
			return ret;

		off += cs;
		written += cs;
	}

	t6->frame_seq++;
	return 0;
}

/* ──────────────────────────────────────────────────────────────────
 * DRM pipe callbacks
 * ────────────────────────────────────────────────────────────────── */

static void t6_pipe_enable(struct drm_simple_display_pipe *pipe,
			   struct drm_crtc_state *crtc_state,
			   struct drm_plane_state *plane_state)
{
	/* T6 chip was initialized at probe. Nothing to do here. */
}

static void t6_pipe_disable(struct drm_simple_display_pipe *pipe)
{
	/* Optional: could send monitor power off */
}

static void t6_pipe_update(struct drm_simple_display_pipe *pipe,
			   struct drm_plane_state *old_state)
{
	struct drm_plane_state *state = pipe->plane.state;
	struct drm_shadow_plane_state *shadow;
	struct drm_framebuffer *fb;
	struct t6_device *t6;
	struct drm_rect rect;
	void *vaddr;
	int idx;

	if (!state)
		return;

	fb = state->fb;
	if (!fb)
		return;

	/*
	 * Guard against stale old_state from drm_mode_config_reset.
	 * On kernel 6.17, drm_dev_register triggers an atomic flush
	 * with old_state pointing to freed memory. If old_state has
	 * no fb, this is the synthetic reset commit — skip damage merge
	 * and send the full frame instead.
	 */
	if (!old_state || !old_state->fb) {
		rect.x1 = 0;
		rect.y1 = 0;
		rect.x2 = fb->width;
		rect.y2 = fb->height;
	} else {
		if (!drm_atomic_helper_damage_merged(old_state, state, &rect))
			return;
	}

	t6 = to_t6(pipe->crtc.dev);

	/* CRITICAL: drm_dev_enter prevents USB after disconnect */
	if (!drm_dev_enter(&t6->drm, &idx))
		return;

	shadow = to_drm_shadow_plane_state(state);

	vaddr = shadow->data[0].vaddr;
	if (!vaddr)
		goto exit;

	/*
	 * XRGB8888 in memory is BGRX (little-endian).
	 * T6 format=8 (RGB32) expects exactly this.
	 * No pixel conversion needed.
	 */
	t6_send_frame(t6, vaddr, fb->pitches[0] * fb->height);

exit:
	drm_dev_exit(idx);
}

static const struct drm_simple_display_pipe_funcs t6_pipe_funcs = {
	.enable = t6_pipe_enable,
	.disable = t6_pipe_disable,
	.update = t6_pipe_update,
	DRM_GEM_SIMPLE_DISPLAY_PIPE_SHADOW_PLANE_FUNCS,
};

/* ──────────────────────────────────────────────────────────────────
 * DRM driver
 * ────────────────────────────────────────────────────────────────── */

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

/* ──────────────────────────────────────────────────────────────────
 * USB probe / disconnect
 * ────────────────────────────────────────────────────────────────── */

static int t6_usb_probe(struct usb_interface *intf,
			const struct usb_device_id *id)
{
	struct usb_device *udev = interface_to_usbdev(intf);
	struct t6_device *t6;
	struct drm_device *drm;
	__le32 ram_le;
	u8 status;
	int ret, retries;

	t6 = devm_drm_dev_alloc(&intf->dev, &t6_drm_driver,
				struct t6_device, drm);
	if (IS_ERR(t6))
		return PTR_ERR(t6);

	drm = &t6->drm;
	t6->udev = usb_get_dev(udev);
	t6->intf = intf;
	t6->frame_seq = 0;
	t6->width = 1920;
	t6->height = 1080;

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
	dev_info(&intf->dev, "T6 RAM: %u MB\n", t6->ram_mb);

	/* Compute framebuffer address */
	t6->fb_addr = (t6->ram_mb - 18 - 12) * 1024 * 1024;

	/* Wait for monitor to connect (HDMI needs time after USB enum) */
	for (retries = 0; retries < 10; retries++) {
		ret = t6_ctrl_in(t6, T6_REQ_GET_STATUS, 0, 0, &status, 1);
		if (ret >= 1 && status == 1)
			break;
		msleep(500);
	}
	if (retries >= 10) {
		dev_warn(&intf->dev, "No monitor detected, using defaults\n");
	} else {
		if (retries > 0)
			dev_info(&intf->dev, "Monitor connected after %d retries\n",
				 retries);
	}

	/* Read and cache EDID */
	t6->edid_len = 0;
	ret = t6_ctrl_in(t6, T6_REQ_GET_EDID, 0, 0, t6->edid_data, 128);
	if (ret >= 128) {
		t6->edid_len = 128;
		/* Parse resolution */
		t6->width = t6->edid_data[0x38] |
			    ((t6->edid_data[0x3A] & 0xF0) << 4);
		t6->height = t6->edid_data[0x3B] |
			     ((t6->edid_data[0x3D] & 0xF0) << 4);
		if (t6->width == 0 || t6->height == 0) {
			t6->width = 1920;
			t6->height = 1080;
		}
		/* Parse monitor name */
		strscpy(t6->monitor_name, "T6 Display",
			sizeof(t6->monitor_name));
		{
			int i;
			for (i = 0x36; i < 0x7E; i += 18) {
				if (t6->edid_data[i] == 0 &&
				    t6->edid_data[i + 1] == 0 &&
				    t6->edid_data[i + 3] == 0xFC) {
					int j, len = min(13,
						(int)sizeof(t6->monitor_name) - 1);
					memcpy(t6->monitor_name,
					       &t6->edid_data[i + 5], len);
					t6->monitor_name[len] = '\0';
					for (j = len - 1; j >= 0; j--) {
						if (t6->monitor_name[j] <= ' ')
							t6->monitor_name[j] = '\0';
						else
							break;
					}
					break;
				}
			}
		}
	}
	dev_info(&intf->dev, "Display: %s (%dx%d) fb=0x%08x\n",
		 t6->monitor_name, t6->width, t6->height, t6->fb_addr);

	/* Allocate URB pool -- 20 URBs of 128KB each */
	ret = t6_alloc_urb_list(t6, T6_MAX_URBS, 128 * 1024);
	if (ret < 1) {
		dev_err(&intf->dev, "URB pool alloc failed\n");
		ret = -ENOMEM;
		goto err_put;
	}
	dev_info(&intf->dev, "URB pool: %d URBs x %zuKB\n",
		 ret, t6->urbs.buf_size / 1024);

	/* Initialize T6 chip */
	ret = t6_chip_init(t6);
	if (ret < 0) {
		dev_err(&intf->dev, "Chip init failed: %d\n", ret);
		goto err_urbs;
	}

	/* DRM mode config */
	ret = drmm_mode_config_init(drm);
	if (ret)
		goto err_urbs;

	drm->mode_config.min_width = 640;
	drm->mode_config.min_height = 480;
	drm->mode_config.max_width = 1920;
	drm->mode_config.max_height = 1200;
	drm->mode_config.preferred_depth = 32;

	/* Connector */
	ret = t6_connector_init(t6);
	if (ret)
		goto err_urbs;

	/* Simple display pipe */
	ret = drm_simple_display_pipe_init(drm, &t6->pipe,
					   &t6_pipe_funcs,
					   t6_formats,
					   ARRAY_SIZE(t6_formats),
					   NULL, &t6->connector);
	if (ret)
		goto err_urbs;

	drm_plane_enable_fb_damage_clips(&t6->pipe.plane);
	drm_mode_config_reset(drm);

	/*
	 * Force connector status to connected and trigger an initial
	 * mode probe BEFORE registering. This populates the modes list
	 * so the compositor sees modes immediately on drm_dev_register.
	 * NO polling — polling workqueue deadlocks on mode_config.mutex.
	 */
	t6->connector.status = connector_status_connected;

	/* Register DRM device */
	ret = drm_dev_register(drm, 0);
	if (ret)
		goto err_urbs;

	dev_info(&intf->dev, "T6 display ready: %s (%dx%d)\n",
		 t6->monitor_name, t6->width, t6->height);
	return 0;

err_urbs:
	t6_free_urb_list(t6);
err_put:
	if (t6->dmadev)
		put_device(t6->dmadev);
	usb_put_dev(t6->udev);
	return ret;
}

static void t6_usb_disconnect(struct usb_interface *intf)
{
	struct t6_device *t6 = usb_get_intfdata(intf);

	if (!t6)
		return;

	dev_info(&intf->dev, "T6 disconnecting\n");

	/*
	 * Disconnect ordering:
	 * 1. Unplug — waits for in-progress drm_dev_enter, blocks new ones
	 * 2. Shutdown — disables outputs (pipe_update guarded by drm_dev_enter)
	 * 3. Free URBs — waits for in-flight USB to complete
	 * No poll_fini needed — polling is disabled.
	 */
	drm_dev_unplug(&t6->drm);
	drm_atomic_helper_shutdown(&t6->drm);
	t6_free_urb_list(t6);

	if (t6->dmadev) {
		put_device(t6->dmadev);
		t6->dmadev = NULL;
	}
	usb_put_dev(t6->udev);
}

/* ──────────────────────────────────────────────────────────────────
 * USB driver
 * ────────────────────────────────────────────────────────────────── */

static const struct usb_device_id t6_ids[] = {
	{ USB_DEVICE(T6_VID, T6_PID) },
	{ }
};
MODULE_DEVICE_TABLE(usb, t6_ids);

static struct usb_driver t6_usb_driver = {
	.name = DRIVER_NAME,
	.probe = t6_usb_probe,
	.disconnect = t6_usb_disconnect,
	.id_table = t6_ids,
};
module_usb_driver(t6_usb_driver);

MODULE_AUTHOR("Authentra / Ralph Friedman");
MODULE_DESCRIPTION(DRIVER_DESC);
MODULE_LICENSE("GPL");
