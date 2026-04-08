// SPDX-License-Identifier: GPL-2.0-only
/*
 * trigger6_drv.c -- MCT Trigger 6 USB Display DRM Driver
 *
 * Two-head USB display adapter with per-head transport selection:
 *   Head 0: raw XRGB8888 with row-level damage tracking and multi-write
 *           partial updates (only dirty rows are sent over USB).
 *   Head 1: NV12 by default (BGRX->NV12 conversion, ~3x bandwidth savings),
 *           or in-kernel JPEG with adaptive quality, or userspace JPEG
 *           injection, or experimental raw -- selected via module parameters.
 *
 * Adaptive per-head pacing: raw heads skip the pacing gate entirely (damage
 * tracking is the natural throttle); JPEG/NV12 heads pace adaptively based
 * on last encode time, capped by secondary_frame_min_interval_ms.
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
#include <linux/math64.h>
#include <linux/fs.h>
#include <linux/ktime.h>
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
#include <drm/drm_atomic.h>
#include <drm/drm_crtc.h>
#include <drm/drm_plane.h>
#include <drm/drm_encoder.h>
#include <drm/drm_gem_atomic_helper.h>

#include "trigger6.h"
#include "trigger6_codec.h"

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
		 "Force logical output 1 to use the raw XRGB8888 transport instead of the default NV12 path; uses double-buffered VRAM slots for tear-free display");

static bool t6_secondary_userspace_jpeg;
module_param_named(secondary_userspace_jpeg,
		   t6_secondary_userspace_jpeg,
		   bool,
		   0644);
MODULE_PARM_DESC(secondary_userspace_jpeg,
		 "Expose logical output 1 through DRM while userspace injects pre-encoded JPEG frames via /dev/trigger6-*-out1-jpeg");

static unsigned int t6_jpeg_quality = T6_JPEG_QUALITY_DEFAULT;

static int t6_jpeg_quality_set(const char *val, const struct kernel_param *kp)
{
	unsigned int v;
	int ret;

	ret = kstrtouint(val, 0, &v);
	if (ret)
		return ret;
	if (v < 1 || v > 100)
		return -EINVAL;
	WRITE_ONCE(t6_jpeg_quality, v);
	return 0;
}

static int t6_jpeg_quality_get(char *buf, const struct kernel_param *kp)
{
	return sysfs_emit(buf, "%u\n", READ_ONCE(t6_jpeg_quality));
}

static const struct kernel_param_ops t6_jpeg_quality_ops = {
	.set = t6_jpeg_quality_set,
	.get = t6_jpeg_quality_get,
};

module_param_cb(jpeg_quality, &t6_jpeg_quality_ops, NULL, 0644);
MODULE_PARM_DESC(jpeg_quality,
		 "Baseline JPEG quality for logical output 1 when using the native in-kernel encoder (range: 1-100, default: "
		 __stringify(T6_JPEG_QUALITY_DEFAULT) ")");

static unsigned int t6_frame_min_interval_ms =
	T6_FRAME_MIN_INTERVAL_MS_DEFAULT;

static int t6_frame_min_interval_ms_set(const char *val,
					const struct kernel_param *kp)
{
	unsigned int v;
	int ret;

	ret = kstrtouint(val, 0, &v);
	if (ret)
		return ret;
	if (v > 1000)
		return -EINVAL;
	WRITE_ONCE(t6_frame_min_interval_ms, v);
	return 0;
}

static int t6_frame_min_interval_ms_get(char *buf,
					const struct kernel_param *kp)
{
	return sysfs_emit(buf, "%u\n", READ_ONCE(t6_frame_min_interval_ms));
}

static const struct kernel_param_ops t6_frame_min_interval_ms_ops = {
	.set = t6_frame_min_interval_ms_set,
	.get = t6_frame_min_interval_ms_get,
};

module_param_cb(frame_min_interval_ms, &t6_frame_min_interval_ms_ops,
		NULL, 0644);
MODULE_PARM_DESC(frame_min_interval_ms,
		 "Legacy pacing gate in milliseconds (range: 0-1000, default: "
		 __stringify(T6_FRAME_MIN_INTERVAL_MS_DEFAULT)
		 "); ignored for raw heads (damage tracking throttles naturally) and for JPEG/NV12 heads (which use adaptive pacing capped by secondary_frame_min_interval_ms)");

static unsigned int t6_secondary_frame_min_interval_ms =
	T6_SECONDARY_FRAME_MIN_INTERVAL_MS_DEFAULT;

static int t6_secondary_frame_min_interval_ms_set(const char *val,
						  const struct kernel_param *kp)
{
	unsigned int v;
	int ret;

	ret = kstrtouint(val, 0, &v);
	if (ret)
		return ret;
	if (v > 5000)
		return -EINVAL;
	WRITE_ONCE(t6_secondary_frame_min_interval_ms, v);
	return 0;
}

static int t6_secondary_frame_min_interval_ms_get(char *buf,
						  const struct kernel_param *kp)
{
	return sysfs_emit(buf, "%u\n",
			  READ_ONCE(t6_secondary_frame_min_interval_ms));
}

static const struct kernel_param_ops t6_secondary_frame_min_interval_ms_ops = {
	.set = t6_secondary_frame_min_interval_ms_set,
	.get = t6_secondary_frame_min_interval_ms_get,
};

module_param_cb(secondary_frame_min_interval_ms,
		&t6_secondary_frame_min_interval_ms_ops, NULL, 0644);
MODULE_PARM_DESC(secondary_frame_min_interval_ms,
		 "Upper cap for adaptive pacing on JPEG/NV12 secondary heads in milliseconds (range: 0-5000, default: "
		 __stringify(T6_SECONDARY_FRAME_MIN_INTERVAL_MS_DEFAULT)
		 "; 0 removes the cap and lets adaptive pacing run unconstrained)");

static bool t6_manual_only;
module_param_named(manual_only,
		   t6_manual_only,
		   bool,
		   0644);
MODULE_PARM_DESC(manual_only,
		 "Keep DRM connectors disconnected and disable automatic scanout; allow only manual userspace JPEG injection and guarded probe logging. Default: false for full driver operation.");

static bool t6_serialize_usb_bus = true;
module_param_named(serialize_usb_bus,
		   t6_serialize_usb_bus,
		   bool,
		   0644);
MODULE_PARM_DESC(serialize_usb_bus,
		 "Serialize bulk USB writes across all T6 devices. Disable experimentally to allow parallel multi-adapter transfers on hosts that tolerate interleaved bulk traffic.");

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
/*
 * Built-in display timing blobs (32 bytes each).
 * Format: pixel_clock(u32 LE kHz), refresh(u16), htotal(u16), hdisplay(u16),
 *         hsync_start(u16), hsync_width(u16), vtotal(u16), vdisplay(u16),
 *         vsync_start(u16), vsync_width(u16), PLL FNUM(u16), FDEN(u16),
 *         IDIV(u8), OutputSelect(u8), hsync_pol(u8), vsync_pol(u8),
 *         reduced(u8), flags(u8)
 */
static const u8 t6_mode_1080p[] = {	/* 1920x1080@60 CEA */
	0x14, 0x44, 0x02, 0x00, 0x3c, 0x00, 0x98, 0x08,
	0x80, 0x07, 0x18, 0x07, 0x2c, 0x00, 0x65, 0x04,
	0x38, 0x04, 0xe8, 0x03, 0x1d, 0x00, 0xbb, 0x02,
	0xe8, 0x03, 0x1d, 0x01, 0x01, 0x01, 0x00, 0x00,
};

static const u8 t6_mode_720p[] = {	/* 1280x720@60 CEA */
	0x0a, 0x22, 0x01, 0x00, 0x3c, 0x00, 0x72, 0x06,
	0x00, 0x05, 0x6e, 0x05, 0x28, 0x00, 0xee, 0x02,
	0xd0, 0x02, 0xd5, 0x02, 0x05, 0x00, 0xbb, 0x02,
	0xe8, 0x03, 0x1d, 0x02, 0x01, 0x01, 0x00, 0x00,
};

static const u8 t6_mode_1024x768[] = {	/* 1024x768@60 VESA DMT */
	0xe8, 0xfd, 0x00, 0x00, 0x3c, 0x00, 0x40, 0x05,
	0x00, 0x04, 0x18, 0x04, 0x88, 0x00, 0x26, 0x03,
	0x00, 0x03, 0x03, 0x03, 0x06, 0x00, 0x00, 0x00,
	0xe8, 0x03, 0x1a, 0x02, 0x00, 0x00, 0x00, 0x00,
};

static const u8 t6_mode_1600x900[] = {	/* 1600x900@60 CVT RB */
	0xd6, 0x7d, 0x01, 0x00, 0x3c, 0x00, 0xe0, 0x06,
	0x40, 0x06, 0x70, 0x06, 0x20, 0x00, 0x9e, 0x03,
	0x84, 0x03, 0x87, 0x03, 0x05, 0x00, 0x64, 0x00,
	0xe8, 0x03, 0x27, 0x02, 0x01, 0x00, 0x01, 0x00,
};

static const u8 t6_mode_1080p30[] = {	/* 1920x1080@30 */
	0x0a, 0x22, 0x01, 0x00, 0x1e, 0x00, 0x98, 0x08,
	0x80, 0x07, 0x18, 0x07, 0x2c, 0x00, 0x65, 0x04,
	0x38, 0x04, 0xe8, 0x03, 0x1d, 0x00, 0xbb, 0x02,
	0xe8, 0x03, 0x1d, 0x02, 0x01, 0x01, 0x00, 0x00,
};

static const u8 t6_mode_1280x1024[] = {	/* 1280x1024@60 VESA */
	0xe0, 0xa5, 0x01, 0x00, 0x3c, 0x00, 0x98, 0x06,
	0x00, 0x05, 0x30, 0x05, 0x70, 0x00, 0x2a, 0x04,
	0x00, 0x04, 0x01, 0x04, 0x03, 0x00, 0x58, 0x02,
	0xe8, 0x03, 0x15, 0x01, 0x01, 0x01, 0x00, 0x00,
};

static const u8 t6_mode_1280x800[] = {	/* 1280x800@60 CVT */
	0x2c, 0x46, 0x01, 0x00, 0x3c, 0x00, 0x90, 0x06,
	0x00, 0x05, 0x48, 0x05, 0x80, 0x00, 0x3f, 0x03,
	0x20, 0x03, 0x23, 0x03, 0x06, 0x00, 0x90, 0x01,
	0xe8, 0x03, 0x21, 0x02, 0x00, 0x01, 0x00, 0x00,
};

static const u8 t6_mode_800x600[] = {	/* 800x600@60 VESA */
	0x40, 0x9c, 0x00, 0x00, 0x3c, 0x00, 0x20, 0x04,
	0x20, 0x03, 0x48, 0x03, 0x80, 0x00, 0x74, 0x02,
	0x58, 0x02, 0x59, 0x02, 0x04, 0x00, 0x00, 0x00,
	0xe8, 0x03, 0x20, 0x00, 0x01, 0x01, 0x00, 0x00,
};

static const u8 t6_mode_640x480[] = {	/* 640x480@60 VGA */
	0x57, 0x62, 0x00, 0x00, 0x3c, 0x00, 0x20, 0x03,
	0x80, 0x02, 0x90, 0x02, 0x60, 0x00, 0x0d, 0x02,
	0xe0, 0x01, 0xea, 0x01, 0x02, 0x00, 0x8c, 0x00,
	0xe8, 0x03, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00,
};

/* All hardware-validated built-in modes */
const struct t6_builtin_mode t6_builtin_modes[] = {
	{ 1920, 1080, 60, t6_mode_1080p },
	{ 1920, 1080, 30, t6_mode_1080p30 },
	{ 1600,  900, 60, t6_mode_1600x900 },
	{ 1280, 1024, 60, t6_mode_1280x1024 },
	{ 1280,  800, 60, t6_mode_1280x800 },
	{ 1280,  720, 60, t6_mode_720p },
	{ 1024,  768, 60, t6_mode_1024x768 },
	{  800,  600, 60, t6_mode_800x600 },
	{  640,  480, 60, t6_mode_640x480 },
};
const int t6_builtin_mode_count = ARRAY_SIZE(t6_builtin_modes);

static const u8 *t6_find_mode_blob(int width, int height, int refresh)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(t6_builtin_modes); i++) {
		if (t6_builtin_modes[i].width == width &&
		    t6_builtin_modes[i].height == height &&
		    t6_builtin_modes[i].refresh == refresh)
			return t6_builtin_modes[i].blob;
	}
	/* Fallback: match width+height ignoring refresh */
	for (i = 0; i < ARRAY_SIZE(t6_builtin_modes); i++) {
		if (t6_builtin_modes[i].width == width &&
		    t6_builtin_modes[i].height == height)
			return t6_builtin_modes[i].blob;
	}
	return NULL;
}

static const u32 t6_formats[] = { DRM_FORMAT_XRGB8888 };

static const struct drm_mode_config_funcs t6_mode_config_funcs = {
	.fb_create = drm_gem_fb_create,
	.atomic_check = drm_atomic_helper_check,
	.atomic_commit = drm_atomic_helper_commit,
};

static const struct drm_mode_config_helper_funcs t6_mode_config_helper_funcs = {
	.atomic_commit_tail = drm_atomic_helper_commit_tail_rpm,
};

static const unsigned int t6_reprobe_delays_ms[] = {
	200,
	500,
	1000,
	3000,
	5000,
};

static int t6_ctrl_out(struct t6_device *t6, u8 req, u16 val,
		       u16 idx, const void *data, u16 size);
static int t6_ctrl_in(struct t6_device *t6, u8 req, u16 val,
		      u16 idx, void *data, u16 size);
static bool t6_edid_base_block_valid(const u8 *edid);

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
	case T6_HEAD_TRANSPORT_NV12:
		return "nv12";
	case T6_HEAD_TRANSPORT_RAW:
	default:
		return "raw";
	}
}

static void t6_metrics_update_last_max(u64 *last, u64 *max, u64 value)
{
	u64 prev_max;

	WRITE_ONCE(*last, value);
	prev_max = READ_ONCE(*max);
	if (value > prev_max)
		WRITE_ONCE(*max, value);
}

static void t6_metrics_record_timing(atomic64_t *samples,
				     atomic64_t *total,
				     u64 *last,
				     u64 *max,
				     u64 value)
{
	if (!value)
		return;

	atomic64_inc(samples);
	atomic64_add(value, total);
	t6_metrics_update_last_max(last, max, value);
}

static u64 t6_metrics_avg_ns(const atomic64_t *total, const atomic64_t *samples)
{
	u64 sample_count = (u64)atomic64_read(samples);

	if (!sample_count)
		return 0;

	return div64_u64((u64)atomic64_read(total), sample_count);
}

static void t6_reset_head_metrics(struct t6_head *head)
{
	memset(&head->metrics, 0, sizeof(head->metrics));
	WRITE_ONCE(head->tx_queued_ns, 0);
}

static void t6_reset_device_metrics(struct t6_device *t6)
{
	memset(&t6->metrics, 0, sizeof(t6->metrics));
}

static void t6_head_set_error(struct t6_head *head, int error,
			      const char *source)
{
	WRITE_ONCE(head->metrics.last_error, error);
	if (source)
		strscpy(head->metrics.last_error_source, source,
			sizeof(head->metrics.last_error_source));
	else
		head->metrics.last_error_source[0] = '\0';
}

static void t6_head_record_send_error(struct t6_head *head, int error,
				      const char *source)
{
	atomic64_inc(&head->metrics.send_errors);
	t6_head_set_error(head, error, source);
}

static ssize_t t6_metrics_show(struct device *dev,
			       struct device_attribute *attr,
			       char *buf)
{
	struct usb_interface *intf = to_usb_interface(dev);
	struct t6_device *t6 = usb_get_intfdata(intf);
	ssize_t len = 0;
	unsigned int i;
	(void)attr;

	if (!t6)
		return sysfs_emit(buf, "trigger6=disconnected\n");

	len += sysfs_emit_at(buf, len,
		"trigger6 bus=%03u dev=%03u interface=%s manual_only=%u io_faulted=%u io_last_error=%d\n",
		t6->udev->bus->busnum,
		t6->udev->devnum,
		dev_name(dev),
		t6->manual_only,
		READ_ONCE(t6->io_faulted),
		t6->io_last_error);
	if (len >= PAGE_SIZE - 256)
		return len;
	len += sysfs_emit_at(buf, len,
		"device bulk_calls=%lld bulk_chunks=%lld bulk_bytes=%lld bulk_errors=%lld bulk_short_writes=%lld tx_work_runs=%lld tx_work_empty=%lld tx_adapter_defers=%lld last_bulk_us=%llu max_bulk_us=%llu last_bulk_bytes=%zu\n",
		(long long)atomic64_read(&t6->metrics.bulk_calls),
		(long long)atomic64_read(&t6->metrics.bulk_chunks),
		(long long)atomic64_read(&t6->metrics.bulk_bytes),
		(long long)atomic64_read(&t6->metrics.bulk_errors),
		(long long)atomic64_read(&t6->metrics.bulk_short_writes),
		(long long)atomic64_read(&t6->metrics.tx_work_runs),
		(long long)atomic64_read(&t6->metrics.tx_work_empty),
		(long long)atomic64_read(&t6->metrics.tx_adapter_defers),
		div64_u64(READ_ONCE(t6->metrics.last_bulk_ns), 1000),
		div64_u64(READ_ONCE(t6->metrics.max_bulk_ns), 1000),
		READ_ONCE(t6->metrics.last_bulk_bytes));

	for (i = 0; i < T6_OUTPUT_COUNT; i++) {
		struct t6_head *head = t6_get_head(t6, i);

		if (len >= PAGE_SIZE - 256)
			return len;
		len += sysfs_emit_at(buf, len,
			"head%u transport=%s connected=%u io_faulted=%u status=%u pending=%u width=%d height=%d frame_seq=%u\n",
			head->output_idx,
			t6_transport_name(head->transport),
			READ_ONCE(head->connected),
			READ_ONCE(head->io_faulted),
			head->status,
			head->tx_pending,
			head->width,
			head->height,
			head->frame_seq);
		len += sysfs_emit_at(buf, len,
			"head%u queue_attempts=%lld queued_frames=%lld coalesced_overwrites=%lld skipped_frames=%lld pacing_defers=%lld transport_faults=%lld jpeg_quality=%u\n",
			head->output_idx,
			(long long)atomic64_read(&head->metrics.queue_attempts),
			(long long)atomic64_read(&head->metrics.queued_frames),
			(long long)atomic64_read(&head->metrics.coalesced_overwrites),
			(long long)atomic64_read(&head->metrics.skipped_frames),
			(long long)atomic64_read(&head->metrics.pacing_defers),
			(long long)atomic64_read(&head->metrics.transport_faults),
			READ_ONCE(head->jpeg_adaptive_quality));
		len += sysfs_emit_at(buf, len,
			"head%u sent_frames=%lld sent_bytes=%lld send_errors=%lld keepalive_sent=%lld keepalive_errors=%lld last_payload_bytes=%zu\n",
			head->output_idx,
			(long long)atomic64_read(&head->metrics.sent_frames),
			(long long)atomic64_read(&head->metrics.sent_bytes),
			(long long)atomic64_read(&head->metrics.send_errors),
			(long long)atomic64_read(&head->metrics.keepalive_sent),
			(long long)atomic64_read(&head->metrics.keepalive_errors),
			READ_ONCE(head->metrics.last_payload_bytes));
		if (len >= PAGE_SIZE - 256)
			return len;
		len += sysfs_emit_at(buf, len,
			"head%u stage_avg_us=%llu stage_last_us=%llu stage_max_us=%llu queue_wait_avg_us=%llu queue_wait_last_us=%llu queue_wait_max_us=%llu\n",
			head->output_idx,
			div64_u64(t6_metrics_avg_ns(&head->metrics.stage_ns_total,
						    &head->metrics.stage_samples), 1000),
			div64_u64(READ_ONCE(head->metrics.last_stage_ns), 1000),
			div64_u64(READ_ONCE(head->metrics.max_stage_ns), 1000),
			div64_u64(t6_metrics_avg_ns(&head->metrics.queue_wait_ns_total,
						    &head->metrics.queue_wait_samples), 1000),
			div64_u64(READ_ONCE(head->metrics.last_queue_wait_ns), 1000),
			div64_u64(READ_ONCE(head->metrics.max_queue_wait_ns), 1000));
		len += sysfs_emit_at(buf, len,
			"head%u encode_avg_us=%llu encode_last_us=%llu encode_max_us=%llu usb_avg_us=%llu usb_last_us=%llu usb_max_us=%llu send_avg_us=%llu send_last_us=%llu send_max_us=%llu\n",
			head->output_idx,
			div64_u64(t6_metrics_avg_ns(&head->metrics.encode_ns_total,
						    &head->metrics.encode_samples), 1000),
			div64_u64(READ_ONCE(head->metrics.last_encode_ns), 1000),
			div64_u64(READ_ONCE(head->metrics.max_encode_ns), 1000),
			div64_u64(t6_metrics_avg_ns(&head->metrics.usb_ns_total,
						    &head->metrics.usb_samples), 1000),
			div64_u64(READ_ONCE(head->metrics.last_usb_ns), 1000),
			div64_u64(READ_ONCE(head->metrics.max_usb_ns), 1000),
			div64_u64(t6_metrics_avg_ns(&head->metrics.send_ns_total,
						    &head->metrics.send_samples), 1000),
			div64_u64(READ_ONCE(head->metrics.last_send_ns), 1000),
			div64_u64(READ_ONCE(head->metrics.max_send_ns), 1000));
		len += sysfs_emit_at(buf, len,
			"head%u last_error=%d last_error_source=%s\n",
			head->output_idx,
			READ_ONCE(head->metrics.last_error),
			head->metrics.last_error_source[0] ?
				head->metrics.last_error_source : "none");
	}

	return len;
}

static ssize_t t6_metrics_reset_store(struct device *dev,
				      struct device_attribute *attr,
				      const char *buf,
				      size_t count)
{
	struct usb_interface *intf = to_usb_interface(dev);
	struct t6_device *t6 = usb_get_intfdata(intf);
	unsigned int i;
	(void)attr;

	if (!t6)
		return -ENODEV;
	if (!sysfs_streq(buf, "1") && !sysfs_streq(buf, "reset"))
		return -EINVAL;

	t6_reset_device_metrics(t6);
	for (i = 0; i < T6_OUTPUT_COUNT; i++)
		t6_reset_head_metrics(t6_get_head(t6, i));

	return count;
}

static DEVICE_ATTR_RO(t6_metrics);
static DEVICE_ATTR_WO(t6_metrics_reset);

static ssize_t t6_head_enable_show(struct device *dev,
				   struct device_attribute *attr, char *buf)
{
	struct usb_interface *intf = to_usb_interface(dev);
	struct t6_device *t6 = usb_get_intfdata(intf);

	if (!t6)
		return -ENODEV;
	return sysfs_emit(buf, "%u %u\n",
			  READ_ONCE(t6_get_head(t6, 0)->connected) ? 1 : 0,
			  READ_ONCE(t6_get_head(t6, 1)->connected) ? 1 : 0);
}

static ssize_t t6_head_enable_store(struct device *dev,
				    struct device_attribute *attr,
				    const char *buf, size_t count)
{
	struct usb_interface *intf = to_usb_interface(dev);
	struct t6_device *t6 = usb_get_intfdata(intf);
	unsigned int head_idx, enable;
	struct t6_head *head;
	int idx, ret;

	if (!t6)
		return -ENODEV;
	if (sscanf(buf, "%u %u", &head_idx, &enable) != 2 ||
	    head_idx >= T6_OUTPUT_COUNT || enable > 1)
		return -EINVAL;

	head = t6_get_head(t6, head_idx);
	if (!drm_dev_enter(&t6->drm, &idx))
		return -ENODEV;

	ret = t6_ctrl_out(t6, T6_REQ_MONITOR_CTRL, head->output_idx,
			  enable, NULL, 0);
	drm_dev_exit(idx);

	if (ret < 0)
		return ret;

	if (!enable) {
		timer_delete_sync(&head->keepalive_timer);
		cancel_delayed_work_sync(&head->boot_keepalive_work);
	}

	return count;
}

static DEVICE_ATTR_RW(t6_head_enable);

static struct attribute *t6_attrs[] = {
	&dev_attr_t6_metrics.attr,
	&dev_attr_t6_metrics_reset.attr,
	&dev_attr_t6_head_enable.attr,
	NULL,
};

static const struct attribute_group t6_group = {
	.attrs = t6_attrs,
};

static int t6_pack_xrgb8888_tight(struct t6_head *head,
				 const void *src,
				 u32 src_stride,
				 u8 *dst,
				 size_t dst_size)
{
	const u8 *src_base = src;
	u32 row_bytes = head->width * 4;
	u32 y;

	if (!src || !dst || src_stride < row_bytes)
		return -EINVAL;

	if ((size_t)row_bytes * head->height > dst_size)
		return -E2BIG;

	if (src_stride == row_bytes) {
		memcpy(dst, src_base, (size_t)row_bytes * head->height);
		return 0;
	}

	for (y = 0; y < head->height; y++) {
		const u8 *src_row = src_base + (size_t)y * src_stride;
		u8 *dst_row = dst + (size_t)y * row_bytes;

		memcpy(dst_row, src_row, row_bytes);
	}

	return 0;
}

static void t6_wake_all_export_waiters(struct t6_device *t6)
{
	unsigned int i;

	for (i = 0; i < T6_OUTPUT_COUNT; i++)
		wake_up_interruptible(&t6_get_head(t6, i)->fb_export_wq);
}

static void t6_cancel_head_activity(struct t6_device *t6)
{
	unsigned int i;

	for (i = 0; i < T6_OUTPUT_COUNT; i++) {
		struct t6_head *head = t6_get_head(t6, i);

		timer_delete_sync(&head->keepalive_timer);
		cancel_delayed_work_sync(&head->boot_keepalive_work);
		cancel_delayed_work_sync(&head->tx_defer_work);
		cancel_work_sync(&head->tx_work);
		WRITE_ONCE(head->keepalive_due, false);
	}
}

static void t6_reset_head_stream_state(struct t6_head *head)
{
	if (head->fb_slot_count > 1)
		head->fb_slot_index = 1;
	else
		head->fb_slot_index = 0;

	head->cmd_cursor_addr = head->cmd_base_addr;
	head->frame_seq = 0;
	head->tx_last_jiffies = 0;
	WRITE_ONCE(head->keepalive_due, false);
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
	} else if (head->transport == T6_HEAD_TRANSPORT_RAW) {
		/*
		 * Secondary raw: double-buffer with two 8 MB+ VRAM slots
		 * so the display reads from one while the host writes the
		 * other.  Without this, the display scans the same buffer
		 * we are writing to and visible tearing results.
		 *
		 * Layout (ram_mb=58, tmp=40):
		 *   cmd ring:    40 MB – 42 MB  (2 MB, 2 × 1 MB slots)
		 *   fb_slots[0]: 42 MB – 50 MB  (8.3 MB frame fits in 8 MB gap)
		 *   fb_slots[1]: 50 MB – 58 MB  (8.3 MB frame fits in 8 MB gap)
		 */
		head->cmd_addr = tmp * 1024 * 1024;
		head->fb_slots[0] = (tmp + 2) * 1024 * 1024;
		head->fb_slots[1] = (tmp + 10) * 1024 * 1024;
		head->fb_slots[2] = 0;
		head->fb_slot_count = 2;
		head->fb_addr = head->fb_slots[0];
		head->cmd_base_addr = head->cmd_addr;
		head->cmd_limit_addr = head->fb_slots[0];
	} else {
		/* Secondary JPEG/NV12/userspace: triple-buffer with 3 × 4 MB slots */
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
static void t6_boot_keepalive_fn(struct work_struct *work);
static void t6_frame_defer_work(struct work_struct *work);
static void t6_frame_work(struct work_struct *work);

static void t6_head_defaults(struct t6_device *t6,
			     struct t6_head *head,
			     u8 output_idx)
{
	memset(head, 0, sizeof(*head));
	head->t6 = t6;
	head->output_idx = output_idx;
	head->width = T6_SCANOUT_WIDTH;
	head->height = T6_SCANOUT_HEIGHT;
	strscpy(head->monitor_name, "T6 Display", sizeof(head->monitor_name));
	timer_setup(&head->keepalive_timer, t6_keepalive_timeout, 0);
	INIT_WORK(&head->tx_work, t6_frame_work);
	INIT_DELAYED_WORK(&head->tx_defer_work, t6_frame_defer_work);
	INIT_DELAYED_WORK(&head->boot_keepalive_work, t6_boot_keepalive_fn);
	spin_lock_init(&head->fb_export_lock);
	init_waitqueue_head(&head->fb_export_wq);
	atomic_set(&head->fb_export_seq, 0);
	t6_reset_head_metrics(head);
	if (output_idx == 0)
		head->transport = T6_HEAD_TRANSPORT_RAW;
	else if (t6_secondary_userspace_jpeg)
		head->transport = T6_HEAD_TRANSPORT_USER_JPEG;
	else if (t6_experimental_secondary_raw)
		head->transport = T6_HEAD_TRANSPORT_RAW;
	else
		head->transport = T6_HEAD_TRANSPORT_NV12;

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

	if (head->edid_len < 128)
		return;
	for (i = 0x36; i + 18 <= 128; i += 18) {
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
	int preferred_width = T6_SCANOUT_WIDTH;
	int preferred_height = T6_SCANOUT_HEIGHT;
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
	if (ret >= 128 && t6_edid_base_block_valid(head->edid_data)) {
		head->edid_len = 128;
		preferred_width = head->edid_data[0x38] |
			((head->edid_data[0x3A] & 0xF0) << 4);
		preferred_height = head->edid_data[0x3B] |
			 ((head->edid_data[0x3D] & 0xF0) << 4);
		if (preferred_width == 0 || preferred_height == 0) {
			preferred_width = T6_SCANOUT_WIDTH;
			preferred_height = T6_SCANOUT_HEIGHT;
		}
		preferred_width = clamp(preferred_width, 640, 1920);
		preferred_height = clamp(preferred_height, 480, 1200);
		t6_parse_edid_monitor_name(head);
		if (preferred_width != T6_SCANOUT_WIDTH ||
		    preferred_height != T6_SCANOUT_HEIGHT)
			dev_info(&t6->udev->dev,
				 "Head %u monitor reports preferred mode %dx%d, but the current reverse-engineered modeset path is fixed to %dx%d@%d\n",
				 head->output_idx,
				 preferred_width,
				 preferred_height,
				 T6_SCANOUT_WIDTH,
				 T6_SCANOUT_HEIGHT,
				 T6_SCANOUT_REFRESH_HZ);
	} else if (ret >= 128) {
		dev_warn(&t6->udev->dev,
			 "Head %u returned an EDID block with invalid checksum; using fixed %dx%d mode assumptions\n",
			 head->output_idx,
			 T6_SCANOUT_WIDTH,
			 T6_SCANOUT_HEIGHT);
	}

	head->width = T6_SCANOUT_WIDTH;
	head->height = T6_SCANOUT_HEIGHT;

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
			/* Damage tracking: last-sent reference frame */
			head->last_sent_frame =
				kvzalloc(frame_size, GFP_KERNEL);
			if (!head->last_sent_frame)
				return -ENOMEM;
			head->last_sent_valid = false;
		}

		/* Pre-allocate JPEG/NV12 staging for non-raw heads */
		if (head->transport != T6_HEAD_TRANSPORT_RAW) {
			head->jpeg_staging_size = 3 * 1024 * 1024;
			head->jpeg_staging =
				kvzalloc(head->jpeg_staging_size, GFP_KERNEL);
			if (!head->jpeg_staging)
				return -ENOMEM;
		}

		/* NV12 heads: allocate damage reference for zero-skip */
		if (head->transport == T6_HEAD_TRANSPORT_NV12) {
			frame_size = head->width * head->height * 4;
			head->last_sent_frame =
				kvzalloc(frame_size, GFP_KERNEL);
			if (!head->last_sent_frame)
				return -ENOMEM;
			head->last_sent_valid = false;
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
		head->tx_stride = 0;
		head->tx_pending = false;

		kvfree(head->video_staging);
		head->video_staging = NULL;
		head->video_staging_size = 0;

		kvfree(head->last_sent_frame);
		head->last_sent_frame = NULL;
		head->last_sent_valid = false;

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

enum t6_tx_defer_reason {
	T6_TX_DEFER_NONE = 0,
	T6_TX_DEFER_ADAPTER,
	T6_TX_DEFER_HEAD,
};

static bool t6_head_has_pending_activity_locked(struct t6_head *head)
{
	return head->tx_pending || READ_ONCE(head->keepalive_due);
}

static bool t6_pop_pending_frame_locked(struct t6_head *head,
					size_t *len,
					u64 *queued_ns)
{
	u8 *front;

	if (!head->tx_pending || !head->tx_front || !head->tx_back)
		return false;

	front = head->tx_front;
	head->tx_front = head->tx_back;
	head->tx_back = front;
	*len = head->tx_len;
	*queued_ns = READ_ONCE(head->tx_queued_ns);
	head->tx_pending = false;
	WRITE_ONCE(head->tx_queued_ns, 0);
	return true;
}

static void t6_requeue_popped_head_locked(struct t6_head *head,
					  size_t len,
					  u64 queued_ns)
{
	u8 *front = head->tx_front;

	head->tx_front = head->tx_back;
	head->tx_back = front;
	head->tx_pending = true;
	head->tx_len = len;
	if (queued_ns)
		WRITE_ONCE(head->tx_queued_ns, queued_ns);
}

static unsigned long t6_head_tx_delay_jiffies(struct t6_device *t6,
					      struct t6_head *head,
					      enum t6_tx_defer_reason *reason)
{
	unsigned int gate_ms = 0;
	unsigned long elapsed;
	unsigned long required;

	*reason = T6_TX_DEFER_NONE;

	if (head->transport == T6_HEAD_TRANSPORT_RAW) {
		/*
		 * Raw heads: zero pacing gate.  Damage tracking is
		 * the natural throttle — unchanged frames are skipped
		 * entirely, and dirty frames send only the changed
		 * rows.  No artificial delay needed.
		 */
		return 0;
	}

	/*
	 * JPEG/NV12 heads: adaptive gate based on last encode/convert
	 * time.  Send as fast as the encoder allows, bounded by the
	 * secondary_frame_min_interval_ms cap for safety.
	 */
	if (head->transport == T6_HEAD_TRANSPORT_JPEG_CMD ||
	    head->transport == T6_HEAD_TRANSPORT_NV12) {
		u64 last_encode = READ_ONCE(head->metrics.last_encode_ns);
		unsigned int cap = READ_ONCE(t6_secondary_frame_min_interval_ms);

		if (last_encode)
			gate_ms = (unsigned int)(last_encode / 1000000ULL);
		else
			gate_ms = cap ? cap : 50;

		/* Floor of 5ms, cap at secondary param (0 = no cap) */
		gate_ms = max(gate_ms, 5U);
		if (cap)
			gate_ms = min(gate_ms, cap);
	}

	if (gate_ms && head->tx_last_jiffies) {
		required = msecs_to_jiffies(gate_ms);
		elapsed = jiffies - head->tx_last_jiffies;
		if (elapsed < required) {
			*reason = T6_TX_DEFER_HEAD;
			return required - elapsed;
		}
	}

	return 0;
}

static struct t6_head *t6_pick_next_pending_head_locked(struct t6_device *t6,
							bool skip_head_deferred)
{
	unsigned int i;

	for (i = 0; i < T6_OUTPUT_COUNT; i++) {
		struct t6_head *candidate;
		enum t6_tx_defer_reason reason;

		candidate = t6_get_head(t6, (t6->tx_next_head + i) % T6_OUTPUT_COUNT);
		if (!t6_head_has_pending_activity_locked(candidate))
			continue;
		if (skip_head_deferred &&
		    t6_head_tx_delay_jiffies(t6, candidate, &reason) &&
		    reason == T6_TX_DEFER_HEAD)
			continue;
		return candidate;
	}

	return NULL;
}

static void t6_queue_head_tx_work(struct t6_head *head)
{
	struct t6_device *t6 = head->t6;

	if (t6->wq)
		queue_work(t6->wq, &head->tx_work);
}

static void t6_queue_next_pending_head(struct t6_device *t6)
{
	struct t6_head *next;

	mutex_lock(&t6->tx_lock);
	next = t6_pick_next_pending_head_locked(t6, false);
	mutex_unlock(&t6->tx_lock);

	if (next)
		t6_queue_head_tx_work(next);
}

static void t6_requeue_head_activity(struct t6_head *head,
				     size_t len,
				     u64 queued_ns,
				     bool keepalive_due)
{
	struct t6_device *t6 = head->t6;

	mutex_lock(&t6->tx_lock);
	if (!keepalive_due) {
		if (!head->tx_pending)
			t6_requeue_popped_head_locked(head, len, queued_ns);
	} else if (!head->tx_pending) {
		WRITE_ONCE(head->keepalive_due, true);
	}
	mutex_unlock(&t6->tx_lock);
}

static void t6_defer_head_activity(struct t6_head *head,
				   size_t len,
				   u64 queued_ns,
				   bool keepalive_due,
				   unsigned long delay,
				   enum t6_tx_defer_reason reason)
{
	struct t6_device *t6 = head->t6;

	t6_requeue_head_activity(head, len, queued_ns, keepalive_due);
	if (reason == T6_TX_DEFER_ADAPTER)
		atomic64_inc(&t6->metrics.tx_adapter_defers);
	else if (reason == T6_TX_DEFER_HEAD)
		atomic64_inc(&head->metrics.pacing_defers);
	if (t6->wq)
		mod_delayed_work(t6->wq, &head->tx_defer_work, delay);
}

static bool t6_should_yield_turn(struct t6_head *head,
				 size_t len,
				 u64 queued_ns,
				 bool keepalive_due)
{
	struct t6_device *t6 = head->t6;
	struct t6_head *next;

	if (head->transport != T6_HEAD_TRANSPORT_JPEG_CMD &&
	    head->transport != T6_HEAD_TRANSPORT_NV12)
		return false;

	mutex_lock(&t6->tx_lock);
	next = t6_pick_next_pending_head_locked(t6, true);
	if (next && next != head && next->transport == T6_HEAD_TRANSPORT_RAW) {
		if (!keepalive_due) {
			if (!head->tx_pending)
				t6_requeue_popped_head_locked(head, len, queued_ns);
		} else if (!head->tx_pending) {
			WRITE_ONCE(head->keepalive_due, true);
		}
	} else {
		next = NULL;
	}
	mutex_unlock(&t6->tx_lock);

	if (next)
		t6_queue_head_tx_work(next);

	return next != NULL;
}

static void t6_stage_pending_head_locked(struct t6_head *head,
					 size_t len,
					 u32 stride,
					 u64 queued_ns)
{
	if (head->tx_pending)
		atomic64_inc(&head->metrics.coalesced_overwrites);
	else
		atomic64_inc(&head->metrics.queued_frames);

	head->tx_len = len;
	head->tx_stride = stride;
	head->tx_pending = true;
	WRITE_ONCE(head->tx_queued_ns, queued_ns);
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
			      val, idx, buf, size,
			      T6_USB_CTRL_TIMEOUT_MS);
	kfree(buf);
	if (ret < 0) {
		if (++t6->ctrl_error_count > T6_CTRL_ERROR_THRESHOLD) {
			dev_err(&t6->udev->dev,
				"Wedged: %u consecutive ctrl errors; scheduling USB reset\n",
				t6->ctrl_error_count);
			usb_queue_reset_device(t6->intf);
		}
	} else {
		t6->ctrl_error_count = 0;
	}
	return ret;
}

static int t6_ctrl_in(struct t6_device *t6, u8 req, u16 val,
		      u16 idx, void *data, u16 size)
{
	void *buf;
	int ret;

	buf = kzalloc(size, GFP_KERNEL);
	if (!buf)
		return -ENOMEM;
	memset(data, 0, size); /* zero caller's buffer in case of short read */
	ret = usb_control_msg(t6->udev, usb_rcvctrlpipe(t6->udev, 0),
			      req, USB_TYPE_VENDOR | USB_DIR_IN,
			      val, idx, buf, size,
			      T6_USB_CTRL_TIMEOUT_MS);
	if (ret >= 0) {
		memcpy(data, buf, min_t(int, ret, size));
		t6->ctrl_error_count = 0;
	} else {
		if (++t6->ctrl_error_count > T6_CTRL_ERROR_THRESHOLD) {
			dev_err(&t6->udev->dev,
				"Wedged: %u consecutive ctrl errors; scheduling USB reset\n",
				t6->ctrl_error_count);
			usb_queue_reset_device(t6->intf);
		}
	}
	kfree(buf);
	return ret;
}

static bool t6_edid_base_block_valid(const u8 *edid)
{
	u8 checksum = 0;
	unsigned int idx;

	for (idx = 0; idx < 128; idx++)
		checksum += edid[idx];

	return checksum == 0;
}

static int t6_bulk_write(struct t6_device *t6, const void *src, size_t len)
{
	u8 *chunk_buf = t6->bulk_chunk;
	const u8 *cursor = src;
	size_t remaining = len;
	u64 bulk_start_ns;
	bool serialize_usb_bus;
	int ret = 0;

	if (!len)
		return 0;
	if (!chunk_buf)
		return -ENOMEM;

	atomic64_inc(&t6->metrics.bulk_calls);
	atomic64_add(len, &t6->metrics.bulk_bytes);
	WRITE_ONCE(t6->metrics.last_bulk_bytes, len);
	bulk_start_ns = ktime_get_ns();
	serialize_usb_bus = READ_ONCE(t6_serialize_usb_bus);

	if (serialize_usb_bus)
		mutex_lock(&t6_usb_bus_lock);
	while (remaining) {
		size_t chunk = min_t(size_t, T6_USB_XFER_CHUNK_SIZE, remaining);
		int actual = 0;

		atomic64_inc(&t6->metrics.bulk_chunks);
		memcpy(chunk_buf, cursor, chunk);
		ret = usb_bulk_msg(t6->udev,
				   usb_sndbulkpipe(t6->udev, T6_EP_BULK_OUT),
				   chunk_buf,
				   chunk,
				   &actual,
				   T6_USB_XFER_TIMEOUT_MS);
		if (ret < 0) {
			atomic64_inc(&t6->metrics.bulk_errors);
			if (ret == -ETIMEDOUT) {
				dev_err(&t6->udev->dev,
					"USB bulk write timed out; scheduling device reset\n");
				usb_queue_reset_device(t6->intf);
			}
			break;
		}
		if (actual != chunk) {
			atomic64_inc(&t6->metrics.bulk_short_writes);
			ret = -EIO;
			break;
		}

		cursor += chunk;
		remaining -= chunk;
	}
	if (serialize_usb_bus)
		mutex_unlock(&t6_usb_bus_lock);
	t6_metrics_update_last_max(&t6->metrics.last_bulk_ns,
				   &t6->metrics.max_bulk_ns,
				   ktime_get_ns() - bulk_start_ns);

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

/*
 * Scan the incoming frame against the last-sent frame, row by row,
 * and return a damage descriptor listing dirty row ranges.  If no
 * last-sent reference exists (first frame, mode change) or the damage
 * exceeds T6_MAX_DIRTY_RANGES, the caller falls back to a full frame.
 */
static void t6_compute_frame_damage(struct t6_head *head,
				    const void *pixels,
				    struct t6_frame_damage *dmg)
{
	u32 stride = head->width * 4;
	const u8 *cur = pixels;
	const u8 *ref = head->last_sent_frame;
	u32 row;
	bool in_dirty = false;

	dmg->num_ranges = 0;
	dmg->full_frame = true;

	if (!ref || !head->last_sent_valid)
		return;

	dmg->full_frame = false;

	for (row = 0; row < head->height; row++) {
		bool dirty = memcmp(cur + (size_t)row * stride,
				    ref + (size_t)row * stride,
				    stride) != 0;
		if (dirty && !in_dirty) {
			if (dmg->num_ranges >= T6_MAX_DIRTY_RANGES) {
				dmg->full_frame = true;
				return;
			}
			dmg->ranges[dmg->num_ranges].y_start = row;
			dmg->ranges[dmg->num_ranges].y_count = 1;
			in_dirty = true;
		} else if (dirty && in_dirty) {
			dmg->ranges[dmg->num_ranges].y_count++;
		} else if (!dirty && in_dirty) {
			dmg->num_ranges++;
			in_dirty = false;
		}
	}

	if (in_dirty)
		dmg->num_ranges++;
}

static int t6_send_frame_raw(struct t6_device *t6, struct t6_head *head,
			     const void *pixels, size_t pixel_len,
			     const struct t6_frame_damage *dmg)
{
	u32 stride = head->width * 4;
	u32 frame_size = stride * head->height;
	const u8 *src = pixels;
	struct t6_bulk_header bch;
	struct t6_flip_header fh;
	u64 send_start_ns;
	size_t total_sent = 0;
	int ret;
	int i;

	if (!READ_ONCE(head->connected))
		return -ENODEV;

	if (pixel_len < frame_size)
		return -EINVAL;

	/*
	 * If damage tracking says nothing changed, skip the send entirely.
	 * The monitor continues showing the previous frame from VRAM.
	 */
	if (dmg && !dmg->full_frame && dmg->num_ranges == 0) {
		atomic64_inc(&head->metrics.skipped_frames);
		return 0;
	}

	send_start_ns = ktime_get_ns();

	/* Build flip header */
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

	if (head->output_idx == 0 && dmg && !dmg->full_frame) {
		/*
		 * Primary head, partial damage: write only dirty row
		 * ranges to VRAM, then the flip header.  The firmware
		 * reads the flip directly from VRAM for the primary
		 * head, and VRAM retains unchanged rows from prior
		 * frames.  This is the fast path — sub-ms USB for
		 * typical desktop updates.
		 */
		for (i = 0; i < dmg->num_ranges; i++) {
			u32 offset = dmg->ranges[i].y_start * stride;
			u32 size = dmg->ranges[i].y_count * stride;

			memset(&bch, 0, sizeof(bch));
			bch.payload_length = cpu_to_le32(size);
			bch.payload_address = cpu_to_le32(
				head->fb_addr + sizeof(fh) + offset);
			bch.packet_length = cpu_to_le32(size);

			ret = t6_bulk_write(t6, &bch, sizeof(bch));
			if (ret)
				goto out;
			ret = t6_bulk_write(t6, src + offset, size);
			if (ret)
				goto out;
			total_sent += size;
		}

		/* Flip header last — triggers display after all rows written */
		memset(&bch, 0, sizeof(bch));
		bch.payload_length = cpu_to_le32(sizeof(fh));
		bch.payload_address = cpu_to_le32(head->fb_addr);
		bch.packet_length = cpu_to_le32(sizeof(fh));

		ret = t6_bulk_write(t6, &bch, sizeof(bch));
		if (ret)
			goto out;
		ret = t6_bulk_write(t6, &fh, sizeof(fh));
		if (ret)
			goto out;
		total_sent += sizeof(fh);
	} else if (head->output_idx == 0) {
		/*
		 * Primary head, full frame: first 10 frames (RESET),
		 * or damage exceeded T6_MAX_DIRTY_RANGES.
		 */
		u32 total_payload = sizeof(fh) + frame_size;

		if (!head->video_staging ||
		    total_payload > head->video_staging_size)
			return -ENOMEM;

		memcpy(head->video_staging, &fh, sizeof(fh));
		memcpy(head->video_staging + sizeof(fh), src, frame_size);

		memset(&bch, 0, sizeof(bch));
		bch.payload_length = cpu_to_le32(total_payload);
		bch.payload_address = cpu_to_le32(head->fb_addr);
		bch.packet_length = cpu_to_le32(total_payload);

		ret = t6_bulk_write(t6, &bch, sizeof(bch));
		if (ret)
			goto out;
		ret = t6_bulk_write(t6, head->video_staging, total_payload);
		if (ret)
			goto out;
		total_sent = total_payload;
	} else {
		/*
		 * Secondary head (experimental raw): cmd ring + fb slot
		 * rotation for double-buffered display.  Only reached
		 * when experimental_secondary_raw=1.
		 */
		u8 next_slot = (head->fb_slot_count > 1) ?
			(head->fb_slot_index + 1) % head->fb_slot_count : 0;
		u32 fb_dest = head->fb_slots[next_slot] ?
			      head->fb_slots[next_slot] : head->fb_addr;
		u32 cmd_addr = head->cmd_cursor_addr;
		u32 cmd_step = 1024 * 1024u;

		if (head->cmd_limit_addr > head->cmd_base_addr &&
		    cmd_addr + cmd_step > head->cmd_limit_addr)
			cmd_addr = head->cmd_base_addr;

		if (!head->video_staging)
			return -ENOMEM;
		memcpy(head->video_staging + sizeof(fh), src, frame_size);

		memset(&bch, 0, sizeof(bch));
		bch.payload_length = cpu_to_le32(frame_size);
		bch.payload_address = cpu_to_le32(fb_dest);
		bch.packet_length = cpu_to_le32(frame_size);

		ret = t6_bulk_write(t6, &bch, sizeof(bch));
		if (ret)
			goto out;
		ret = t6_bulk_write(t6, head->video_staging + sizeof(fh),
				    frame_size);
		if (ret)
			goto out;

		fh.y_fb_offset = cpu_to_le32(fb_dest);
		memset(&bch, 0, sizeof(bch));
		bch.payload_length = cpu_to_le32(sizeof(fh));
		bch.payload_address = cpu_to_le32(cmd_addr);
		bch.packet_length = cpu_to_le32(sizeof(fh));

		ret = t6_bulk_write(t6, &bch, sizeof(bch));
		if (ret)
			goto out;
		ret = t6_bulk_write(t6, &fh, sizeof(fh));
		if (ret)
			goto out;

		head->cmd_cursor_addr = cmd_addr + cmd_step;
		head->fb_slot_index = next_slot;
		total_sent = frame_size + sizeof(fh);
	}

	/* Update the damage reference frame */
	if (head->last_sent_frame) {
		if (dmg && !dmg->full_frame) {
			for (i = 0; i < dmg->num_ranges; i++) {
				u32 offset = dmg->ranges[i].y_start * stride;
				u32 size = dmg->ranges[i].y_count * stride;

				memcpy(head->last_sent_frame + offset,
				       src + offset, size);
			}
		} else {
			memcpy(head->last_sent_frame, src, frame_size);
		}
		head->last_sent_valid = true;
	}

	head->frame_seq++;
	atomic64_inc(&head->metrics.sent_frames);
	atomic64_add(total_sent, &head->metrics.sent_bytes);
	WRITE_ONCE(head->metrics.last_payload_bytes, total_sent);
	t6_metrics_record_timing(&head->metrics.usb_samples,
				 &head->metrics.usb_ns_total,
				 &head->metrics.last_usb_ns,
				 &head->metrics.max_usb_ns,
				 ktime_get_ns() - send_start_ns);
	t6_metrics_record_timing(&head->metrics.send_samples,
				 &head->metrics.send_ns_total,
				 &head->metrics.last_send_ns,
				 &head->metrics.max_send_ns,
				 ktime_get_ns() - send_start_ns);

out:
	if (ret)
		t6_head_record_send_error(head, ret, "raw");
	return ret;
}

static int t6_send_jpeg_blob(struct t6_device *t6, struct t6_head *head,
			     const void *jpg_data,
			     size_t jpg_len)
{
	struct t6_bulk_header bch;
	struct t6_flip_header fh;
	u8 *video_payload;
	const u8 *jpeg_payload;
	u8 flag;
	u8 fb_slot_index;
	u16 y_pitch;
	u32 cmd_addr;
	u32 cmd_step;
	u32 fb_addr;
	u32 y_block_size;
	u32 total_payload;
	bool wrapped = false;
	u64 usb_start_ns;
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
	usb_start_ns = ktime_get_ns();

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

	/*
	 * Three cases for placing JPEG data at video_payload + sizeof(fh):
	 *
	 * 1. Pre-placed (native kernel encode path): jpg_data already points to
	 *    video_payload + sizeof(fh) because t6_prepare_frame_jpeg_cmd encodes
	 *    directly into that offset.  No copy needed.
	 *
	 * 2. External buffer (userspace injection, keepalive): completely disjoint
	 *    allocation -- use memcpy.
	 *
	 * 3. Legacy base-pointer alias (jpg_data == video_payload): data starts at
	 *    offset 0 and needs shifting -- use memmove.  Kept for safety but not
	 *    hit by any current caller.
	 */
	if (jpg_data == video_payload + sizeof(fh)) {
		/* Case 1: data already in place, nothing to move */
	} else if (jpg_data != video_payload) {
		memcpy(video_payload + sizeof(fh), jpg_data, jpg_len);
	} else {
		memmove(video_payload + sizeof(fh), jpg_data, jpg_len);
	}
	jpeg_payload = video_payload + sizeof(fh);
	memset(video_payload + sizeof(fh) + jpg_len, 0, T6_JPEG_PADDING_SIZE);
	memcpy(video_payload, &fh, sizeof(fh));

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
	atomic64_inc(&head->metrics.sent_frames);
	atomic64_add(total_payload, &head->metrics.sent_bytes);
	WRITE_ONCE(head->metrics.last_payload_bytes, total_payload);
	t6_metrics_record_timing(&head->metrics.usb_samples,
				 &head->metrics.usb_ns_total,
				 &head->metrics.last_usb_ns,
				 &head->metrics.max_usb_ns,
				 ktime_get_ns() - usb_start_ns);

	/* Store last JPEG data for keepalive */
	if (!head->last_jpeg_data || head->last_jpeg_len < jpg_len) {
		kvfree(head->last_jpeg_data);
		head->last_jpeg_data = NULL;
		head->last_jpeg_len = 0;
		head->last_jpeg_data = kvmalloc(jpg_len, GFP_KERNEL);
	}
	if (head->last_jpeg_data) {
		memcpy(head->last_jpeg_data, jpeg_payload, jpg_len);
		head->last_jpeg_len = jpg_len;
	}

	/* Start or reset keepalive timer */
	mod_timer(&head->keepalive_timer, jiffies + msecs_to_jiffies(T6_KEEPALIVE_INTERVAL_MS));

out:
	return ret;
}

/*
 * The T6 chip blanks JPEG-decoded outputs that stop receiving frames
 * after roughly 2-3 seconds.  Re-send the last JPEG blob every 2 s
 * to keep the display alive when the compositor has no new content.
 */
static void t6_keepalive_timeout(struct timer_list *t)
{
	struct t6_head *head = container_of(t, struct t6_head, keepalive_timer);

	if (!READ_ONCE(head->connected) || READ_ONCE(head->io_faulted) ||
	    !head->last_jpeg_data)
		return;

	WRITE_ONCE(head->keepalive_due, true);
	t6_queue_head_tx_work(head);
}

/*
 * Boot keepalive: sends cached black frame directly via bulk write,
 * bypassing t6_frame_work and its drm_dev_enter guard.  This keeps
 * the HDMI signal alive during the gap between priming and compositor
 * startup, when drm_dev_enter would fail (DRM not yet registered).
 */
static void t6_boot_keepalive_fn(struct work_struct *work)
{
	struct t6_head *head = container_of(to_delayed_work(work),
					    struct t6_head,
					    boot_keepalive_work);
	struct t6_device *t6 = head->t6;
	struct t6_bulk_header bch;

	if (!READ_ONCE(head->connected) || READ_ONCE(head->io_faulted) ||
	    READ_ONCE(t6->io_faulted))
		return;
	if (!head->last_jpeg_data || !head->last_jpeg_len)
		return;

	mutex_lock(&t6->io_lock);
	memset(&bch, 0, sizeof(bch));
	bch.payload_length = cpu_to_le32(head->last_jpeg_len);
	bch.payload_address = cpu_to_le32(head->fb_addr);
	bch.packet_length = cpu_to_le32(head->last_jpeg_len);
	t6_bulk_write(t6, &bch, sizeof(bch));
	t6_bulk_write(t6, head->last_jpeg_data, head->last_jpeg_len);
	mutex_unlock(&t6->io_lock);

	atomic64_inc(&head->metrics.keepalive_sent);

	if (t6->wq && READ_ONCE(head->connected))
		mod_delayed_work(t6->wq, &head->boot_keepalive_work,
				 msecs_to_jiffies(T6_BOOT_KEEPALIVE_INTERVAL_MS));
}

static int t6_prepare_frame_jpeg_cmd(struct t6_head *head,
				     const void *pixels,
				     size_t pixel_len)
{
	unsigned int quality;
	size_t tight_len = (size_t)head->width * head->height * 4;
	u64 encode_start_ns;
	int ret;

	if (head->transport == T6_HEAD_TRANSPORT_USER_JPEG)
		return 0;
	if (!READ_ONCE(head->connected))
		return -ENODEV;
	if (!pixels || !pixel_len)
		return -EINVAL;
	if (pixel_len < tight_len)
		return -EINVAL;
	if (!head->jpeg_staging || !head->jpeg_staging_size)
		return -ENOMEM;

	/* Use per-head adaptive quality if active, else global param */
	quality = head->jpeg_adaptive_quality ?
		  head->jpeg_adaptive_quality :
		  READ_ONCE(t6_jpeg_quality);

	encode_start_ns = ktime_get_ns();
	/*
	 * Encode directly into jpeg_staging[sizeof(flip_header)..] so that
	 * t6_send_jpeg_blob can detect the pre-placed case and skip the memmove
	 * that would otherwise shift up to several MB of JPEG data by 48 bytes.
	 * Reserve sizeof(flip_header) at the front and T6_JPEG_PADDING_SIZE at
	 * the end so the total_payload always fits within jpeg_staging_size.
	 */
	ret = t6_jpeg_encode_xrgb8888(pixels,
				     head->width,
				     head->height,
				     head->tx_stride ? head->tx_stride : head->width * 4,
				     quality,
				     head->jpeg_staging + sizeof(struct t6_flip_header),
				     head->jpeg_staging_size -
					sizeof(struct t6_flip_header) -
					T6_JPEG_PADDING_SIZE);
	if (ret < 0) {
		t6_head_record_send_error(head, ret, "jpeg-encode");
		return ret;
	}

	{
		u64 encode_ns = ktime_get_ns() - encode_start_ns;
		u64 encode_ms = encode_ns / 1000000ULL;
		unsigned int target_ms = 30;
		unsigned int q = quality;

		t6_metrics_record_timing(&head->metrics.encode_samples,
					 &head->metrics.encode_ns_total,
					 &head->metrics.last_encode_ns,
					 &head->metrics.max_encode_ns,
					 encode_ns);

		/*
		 * Adaptive quality feedback: if encode is too slow,
		 * drop quality aggressively.  If encode has headroom,
		 * raise quality gently.  Asymmetric steps prevent
		 * oscillation.
		 */
		if (encode_ms > target_ms && q > 25)
			q -= 5;
		else if (encode_ms < target_ms * 7 / 10 && q < 93)
			q += 2;
		head->jpeg_adaptive_quality = clamp(q, 20U, 95U);
	}

	return ret;
}

static int t6_send_prepared_jpeg_cmd(struct t6_device *t6,
				     struct t6_head *head,
				     size_t jpeg_len)
{
	u64 send_start_ns = ktime_get_ns();
	int ret;

	ret = t6_send_jpeg_blob(t6, head,
				head->jpeg_staging + sizeof(struct t6_flip_header),
				jpeg_len);
	if (ret < 0) {
		t6_head_record_send_error(head, ret, "jpeg-cmd");
		return ret;
	}
	t6_metrics_record_timing(&head->metrics.send_samples,
				 &head->metrics.send_ns_total,
				 &head->metrics.last_send_ns,
				 &head->metrics.max_send_ns,
				 ktime_get_ns() - send_start_ns);

	return 0;
}

/*
 * NV12 transport for secondary heads: convert BGRX→NV12 in kernel,
 * send to triple-buffered VRAM fb_slots, flip via direct write.
 * Same protocol as triggerdm's raw YV12/NV12 — single contiguous
 * write of flip_header + NV12 data to fbAddr, with slot rotation.
 *
 * Performance: ~2-3ms conversion + ~3-5ms USB = 5-8ms per frame
 * vs JPEG: ~52ms encode + ~1ms USB = 53ms per frame (10x faster)
 */
static int t6_prepare_frame_nv12(struct t6_head *head,
				 const void *pixels,
				 size_t pixel_len)
{
	u16 y_pitch = ALIGN(head->width, 16);
	u16 uv_pitch = ALIGN(head->width, 16);
	u32 y_size = (u32)y_pitch * head->height;
	u32 uv_size = (u32)uv_pitch * (head->height / 2);
	u32 nv12_size = y_size + uv_size;
	u32 total = sizeof(struct t6_flip_header) + nv12_size +
		    T6_JPEG_PADDING_SIZE;
	u8 *staging;
	u64 encode_start_ns;
	int ret;

	if (!head->jpeg_staging || total > head->jpeg_staging_size)
		return -ENOMEM;
	if (!READ_ONCE(head->connected))
		return -ENODEV;

	staging = head->jpeg_staging;
	encode_start_ns = ktime_get_ns();

	ret = t6_convert_xrgb8888_to_nv12(pixels,
					   head->width, head->height,
					   head->tx_stride ? head->tx_stride :
					   head->width * 4,
					   staging + sizeof(struct t6_flip_header),
					   staging + sizeof(struct t6_flip_header) +
					   y_size,
					   y_pitch, uv_pitch);
	if (ret < 0)
		return ret;

	/* Zero padding after NV12 data */
	memset(staging + sizeof(struct t6_flip_header) + nv12_size,
	       0, T6_JPEG_PADDING_SIZE);

	t6_metrics_record_timing(&head->metrics.encode_samples,
				 &head->metrics.encode_ns_total,
				 &head->metrics.last_encode_ns,
				 &head->metrics.max_encode_ns,
				 ktime_get_ns() - encode_start_ns);

	return (int)nv12_size;
}

static int t6_send_prepared_nv12(struct t6_device *t6,
				 struct t6_head *head,
				 size_t nv12_len)
{
	u16 y_pitch = ALIGN(head->width, 16);
	u16 uv_pitch = ALIGN(head->width, 16);
	u32 y_size = (u32)y_pitch * head->height;
	struct t6_bulk_header bch;
	struct t6_flip_header fh;
	u32 total_payload;
	u8 fb_slot_index;
	u32 fb_addr;
	u64 send_start_ns = ktime_get_ns();
	int ret;

	total_payload = sizeof(fh) + nv12_len + T6_JPEG_PADDING_SIZE;

	/* Triple-buffer rotation — same as JPEG path */
	if (head->fb_slot_count > 1)
		fb_slot_index = (head->fb_slot_index + 1) % head->fb_slot_count;
	else
		fb_slot_index = 0;

	fb_addr = head->fb_slots[fb_slot_index] ?
		  head->fb_slots[fb_slot_index] : head->fb_addr;

	/* Build flip header for NV12 display */
	memset(&fh, 0, sizeof(fh));
	fh.command = cpu_to_le32(head->output_idx == 0 ?
				T6_CMD_FLIP_PRIMARY : T6_CMD_FLIP_SECONDARY);
	fh.payload_size = cpu_to_le32(total_payload - sizeof(fh));
	fh.target_format = cpu_to_le32(T6_FMT_NV12);
	fh.y_pitch = cpu_to_le16(y_pitch);
	fh.uv_pitch = cpu_to_le16(uv_pitch);
	fh.y_fb_offset = cpu_to_le32(fb_addr + sizeof(fh));
	fh.u_offset = cpu_to_le32(fb_addr + sizeof(fh) + y_size);
	fh.source_format = cpu_to_le32(T6_FMT_NV12);
	fh.flag = (head->frame_seq < 10) ? T6_FLAG_RESET : 0;

	memcpy(head->jpeg_staging, &fh, sizeof(fh));

	/* Single contiguous write: flip_header + NV12 data to fbAddr */
	memset(&bch, 0, sizeof(bch));
	bch.payload_length = cpu_to_le32(total_payload);
	bch.payload_address = cpu_to_le32(fb_addr);
	bch.packet_length = cpu_to_le32(total_payload);

	ret = t6_bulk_write(t6, &bch, sizeof(bch));
	if (ret)
		goto out;
	ret = t6_bulk_write(t6, head->jpeg_staging, total_payload);
	if (ret)
		goto out;

	head->frame_seq++;
	head->fb_slot_index = fb_slot_index;
	atomic64_inc(&head->metrics.sent_frames);
	atomic64_add(total_payload, &head->metrics.sent_bytes);
	WRITE_ONCE(head->metrics.last_payload_bytes, total_payload);
	t6_metrics_record_timing(&head->metrics.usb_samples,
				 &head->metrics.usb_ns_total,
				 &head->metrics.last_usb_ns,
				 &head->metrics.max_usb_ns,
				 ktime_get_ns() - send_start_ns);
	t6_metrics_record_timing(&head->metrics.send_samples,
				 &head->metrics.send_ns_total,
				 &head->metrics.last_send_ns,
				 &head->metrics.max_send_ns,
				 ktime_get_ns() - send_start_ns);

	/* Keepalive: stash last frame for re-send */
	if (head->last_jpeg_data &&
	    total_payload <= head->tx_buf_size) {
		memcpy(head->last_jpeg_data, head->jpeg_staging, total_payload);
		head->last_jpeg_len = total_payload;
	}
	mod_timer(&head->keepalive_timer, jiffies + msecs_to_jiffies(T6_KEEPALIVE_INTERVAL_MS));

out:
	if (ret)
		t6_head_record_send_error(head, ret, "nv12");
	return ret;
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
	u64 send_start_ns;

	if (*ppos != 0)
		return -ESPIPE;
	if (!len || len > head->tx_buf_size)
		return -EINVAL;
	if (!READ_ONCE(head->connected))
		return -ENODEV;
	if (READ_ONCE(head->io_faulted))
		return head->io_last_error ? head->io_last_error : -EIO;
	if (READ_ONCE(t6->io_faulted))
		return t6->io_last_error ? t6->io_last_error : -EIO;
	if (head->transport != T6_HEAD_TRANSPORT_USER_JPEG)
		return -EOPNOTSUPP;

	jpg_data = memdup_user(buf, len);
	if (IS_ERR(jpg_data))
		return PTR_ERR(jpg_data);
	send_start_ns = ktime_get_ns();

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
		t6_head_record_send_error(head, ret, "userspace-jpeg");
		t6_trip_transport_fault(t6, head, ret, "userspace-jpeg");
		return ret;
	}
	t6_metrics_record_timing(&head->metrics.send_samples,
				 &head->metrics.send_ns_total,
				 &head->metrics.last_send_ns,
				 &head->metrics.max_send_ns,
				 ktime_get_ns() - send_start_ns);
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

	/* Pairs with smp_wmb() in t6_plane_atomic_update() after buffer swap */
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
	head->jpeg_miscdev.mode = 0660;

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
	bool already_faulted;

	mutex_lock(&t6->tx_lock);
	already_faulted = head->io_faulted;
	if (!already_faulted) {
		WRITE_ONCE(head->io_faulted, true);
		head->io_last_error = ret;
		atomic64_inc(&head->metrics.transport_faults);
		t6_head_set_error(head, ret, source);
		head->tx_pending = false;
		head->tx_len = 0;
		WRITE_ONCE(head->tx_queued_ns, 0);
	}
	mutex_unlock(&t6->tx_lock);

	if (already_faulted)
		return;

	dev_err(&t6->udev->dev,
		"Halting T6 frame traffic on output %u after %s transport error: %d\n",
		head->output_idx, source, ret);
	dev_err(&t6->udev->dev,
		"Output %u disabled; auto-recovery scheduled in 60s\n",
		head->output_idx);

	if (!drm_dev_is_unplugged(&t6->drm)) {
		drm_kms_helper_hotplug_event(&t6->drm);
		/* Schedule auto-recovery reprobe after 60 seconds */
		schedule_delayed_work(&t6->reprobe_work,
				      msecs_to_jiffies(T6_FAULT_RECOVERY_DELAY_MS));
	}
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
	else if (READ_ONCE(head->io_faulted))
		scanout_state = "halted";
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
			 "Head %u is detected but DRM scanout is disabled (no supported transport configured)\n",
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

	/*
	 * Auto-recover from transport faults: clear io_faulted on all
	 * heads and retry.  This allows the driver to resume after
	 * transient USB errors without requiring a module reload.
	 */
	if (READ_ONCE(t6->io_faulted)) {
		WRITE_ONCE(t6->io_faulted, false);
		for (idx = 0; idx < T6_OUTPUT_COUNT; idx++)
			WRITE_ONCE(t6_get_head(t6, idx)->io_faulted, false);
		dev_info(&t6->udev->dev,
			 "Auto-clearing transport faults; attempting recovery\n");
	}

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
		t6->reprobe_attempt = 0;

	if (changed)
		drm_kms_helper_hotplug_event(&t6->drm);

	if (t6_any_head_disconnected(t6))
		t6_schedule_reprobe(t6);
}

static void t6_schedule_reprobe(struct t6_device *t6)
{
	unsigned int delay_ms;

	if (t6->reprobe_attempt >= ARRAY_SIZE(t6_reprobe_delays_ms) - 1) {
		delay_ms = t6_reprobe_delays_ms[ARRAY_SIZE(t6_reprobe_delays_ms) - 1];
		t6->reprobe_attempt = ARRAY_SIZE(t6_reprobe_delays_ms) - 1;
	} else {
		delay_ms = t6_reprobe_delays_ms[t6->reprobe_attempt++];
	}
	schedule_delayed_work(&t6->reprobe_work,
			      msecs_to_jiffies(delay_ms));
}

static void t6_frame_defer_work(struct work_struct *work)
{
	struct t6_head *head = container_of(to_delayed_work(work),
				   struct t6_head, tx_defer_work);

	t6_queue_head_tx_work(head);
}

static void t6_frame_work(struct work_struct *work)
{
	struct t6_head *head = container_of(work, struct t6_head, tx_work);
	struct t6_device *t6 = head->t6;
	size_t len = 0;
	int ret = 0;
	int idx;
	int encoded_len = 0;
	bool keepalive_due = false;
	enum t6_tx_defer_reason reason;
	unsigned long delay;
	u64 queued_ns = 0;
	u64 queue_wait_ns;
	struct t6_frame_damage damage;

	atomic64_inc(&t6->metrics.tx_work_runs);
	if (READ_ONCE(t6->io_faulted) || READ_ONCE(head->io_faulted))
		return;

	mutex_lock(&t6->tx_lock);
	if (!t6_pop_pending_frame_locked(head, &len, &queued_ns)) {
		if (READ_ONCE(head->keepalive_due) && head->last_jpeg_data) {
			WRITE_ONCE(head->keepalive_due, false);
			keepalive_due = true;
		} else {
			mutex_unlock(&t6->tx_lock);
			atomic64_inc(&t6->metrics.tx_work_empty);
			return;
		}
	}
	mutex_unlock(&t6->tx_lock);

	if (!t6_head_runtime_connected(head))
		return;

	if (t6_should_yield_turn(head, len, queued_ns, keepalive_due))
		return;

	delay = t6_head_tx_delay_jiffies(t6, head, &reason);
	if (delay) {
		t6_defer_head_activity(head, len, queued_ns, keepalive_due,
				      delay, reason);
		return;
	}

	if (!keepalive_due && head->transport == T6_HEAD_TRANSPORT_JPEG_CMD) {
		encoded_len = t6_prepare_frame_jpeg_cmd(head, head->tx_front, len);
		if (encoded_len < 0) {
			t6_trip_transport_fault(t6, head, encoded_len, "drm");
			dev_warn_ratelimited(&t6->udev->dev,
					     "Frame prepare failed on output %u: %d\n",
					     head->output_idx, encoded_len);
			return;
		}
	}

	/* Compute damage before io_lock — this is pure CPU work */
	if (!keepalive_due && (head->transport == T6_HEAD_TRANSPORT_RAW ||
			       head->transport == T6_HEAD_TRANSPORT_NV12))
		t6_compute_frame_damage(head, head->tx_front, &damage);

	/* NV12: skip conversion entirely when zero damage */
	if (!keepalive_due && head->transport == T6_HEAD_TRANSPORT_NV12) {
		if (!damage.full_frame && damage.num_ranges == 0) {
			atomic64_inc(&head->metrics.skipped_frames);
			return;
		}
		encoded_len = t6_prepare_frame_nv12(head, head->tx_front, len);
		if (encoded_len < 0) {
			t6_trip_transport_fault(t6, head, encoded_len, "drm");
			dev_warn_ratelimited(&t6->udev->dev,
					     "NV12 convert failed on output %u: %d\n",
					     head->output_idx, encoded_len);
			return;
		}
	}

	mutex_lock(&t6->io_lock);
	delay = t6_head_tx_delay_jiffies(t6, head, &reason);
	if (delay) {
		mutex_unlock(&t6->io_lock);
		t6_defer_head_activity(head, len, queued_ns, keepalive_due,
				      delay, reason);
		return;
	}

	if (!drm_dev_enter(&t6->drm, &idx)) {
		mutex_unlock(&t6->io_lock);
		return;
	}
	if (!keepalive_due && queued_ns) {
		queue_wait_ns = ktime_get_ns() - queued_ns;
		t6_metrics_record_timing(&head->metrics.queue_wait_samples,
					 &head->metrics.queue_wait_ns_total,
					 &head->metrics.last_queue_wait_ns,
					 &head->metrics.max_queue_wait_ns,
					 queue_wait_ns);
	}

	if (keepalive_due) {
		if (head->transport == T6_HEAD_TRANSPORT_RAW) {
			/* Raw keepalive: re-send cached frame to fb_addr */
			struct t6_bulk_header ka_bch;

			memset(&ka_bch, 0, sizeof(ka_bch));
			ka_bch.payload_length = cpu_to_le32(head->last_jpeg_len);
			ka_bch.payload_address = cpu_to_le32(head->fb_addr);
			ka_bch.packet_length = cpu_to_le32(head->last_jpeg_len);
			ret = t6_bulk_write(t6, &ka_bch, sizeof(ka_bch));
			if (!ret)
				ret = t6_bulk_write(t6, head->last_jpeg_data,
						    head->last_jpeg_len);
		} else if (head->transport == T6_HEAD_TRANSPORT_NV12) {
			/* NV12 keepalive: re-send cached frame to fb slot */
			struct t6_bulk_header ka_bch;
			u8 si = head->fb_slot_index % head->fb_slot_count;
			u32 fb = head->fb_slots[si] ?
				 head->fb_slots[si] : head->fb_addr;

			memset(&ka_bch, 0, sizeof(ka_bch));
			ka_bch.payload_length = cpu_to_le32(head->last_jpeg_len);
			ka_bch.payload_address = cpu_to_le32(fb);
			ka_bch.packet_length = cpu_to_le32(head->last_jpeg_len);
			ret = t6_bulk_write(t6, &ka_bch, sizeof(ka_bch));
			if (!ret)
				ret = t6_bulk_write(t6, head->last_jpeg_data,
						    head->last_jpeg_len);
		} else {
			ret = t6_send_jpeg_blob(t6, head,
					       head->last_jpeg_data,
					       head->last_jpeg_len);
		}
		if (!ret)
			atomic64_inc(&head->metrics.keepalive_sent);
		else {
			atomic64_inc(&head->metrics.keepalive_errors);
			t6_head_record_send_error(head, ret, "keepalive");
		}
	} else if (head->transport == T6_HEAD_TRANSPORT_RAW) {
		ret = t6_send_frame_raw(t6, head, head->tx_front, len, &damage);
	} else if (head->transport == T6_HEAD_TRANSPORT_NV12) {
		ret = t6_send_prepared_nv12(t6, head, encoded_len);
	} else {
		ret = t6_send_prepared_jpeg_cmd(t6, head, encoded_len);
	}
	mutex_unlock(&t6->io_lock);
	drm_dev_exit(idx);

	head->tx_last_jiffies = jiffies;
	t6->tx_next_head = (head->output_idx + 1) % T6_OUTPUT_COUNT;

	if (ret) {
		if (keepalive_due)
			return;
		t6_trip_transport_fault(t6, head, ret, "drm");
		dev_warn_ratelimited(&t6->udev->dev,
				     "Frame send failed on output %u: %d\n",
				     head->output_idx, ret);
		return;
	}

	/* Update NV12 damage reference after successful send */
	if (!keepalive_due && head->transport == T6_HEAD_TRANSPORT_NV12 &&
	    head->last_sent_frame) {
		u32 stride = head->width * 4;
		u32 frame_size = stride * head->height;

		memcpy(head->last_sent_frame, head->tx_front, frame_size);
		head->last_sent_valid = true;
	}

	/* New frames can arrive while USB or JPEG work is in flight, so pick the next head now. */
	t6_queue_next_pending_head(t6);
}

/* ------------------------------------------------------------------
 * DRM pipe callbacks
 * ------------------------------------------------------------------
 */

static void t6_crtc_atomic_enable(struct drm_crtc *crtc,
				  struct drm_atomic_state *state)
{
	struct t6_head *head = t6_head_from_crtc(crtc);
	struct drm_crtc_state *crtc_state = drm_atomic_get_new_crtc_state(state, crtc);
	struct t6_device *t6 = head->t6;
	int idx;

	if (!crtc_state)
		return;
	if (!t6_head_runtime_connected(head))
		return;

	/* Cancel boot keepalive — compositor is taking over */
	cancel_delayed_work_sync(&head->boot_keepalive_work);
	timer_delete_sync(&head->keepalive_timer);

	if (!drm_dev_enter(&t6->drm, &idx))
		return;

	/*
	 * Switch resolution if compositor requested a different mode.
	 * The T6 chip requires the full timing sequence around any
	 * resolution change — SET_TIMING pre, per-head SET_RESOLUTION
	 * for ALL heads, SET_TIMING post, FINALIZE.  Sending only
	 * SET_RESOLUTION crashes the sibling head on the same chip.
	 */
	{
		struct drm_display_mode *mode = &crtc_state->mode;
		int new_w = mode->hdisplay;
		int new_h = mode->vdisplay;

		if (new_w && new_h &&
		    (new_w != head->width || new_h != head->height)) {
			const u8 *blob = t6_find_mode_blob(new_w, new_h,
					drm_mode_vrefresh(mode));

			if (blob) {
				unsigned int hi;
				int ret;

				/* Full chip timing sequence */
				t6_ctrl_out(t6, T6_REQ_SET_TIMING, 0, 0,
					    t6_init_timing_pre,
					    sizeof(t6_init_timing_pre));

				/* Re-send resolution for ALL heads */
				for (hi = 0; hi < T6_OUTPUT_COUNT; hi++) {
					struct t6_head *h =
						t6_get_head(t6, hi);
					const u8 *hblob;

					if (h == head)
						hblob = blob;
					else
						hblob = t6_find_mode_blob(
							h->width, h->height,
							T6_SCANOUT_REFRESH_HZ);
					if (!hblob)
						continue;
					t6_ctrl_out(t6,
						    T6_REQ_SET_RESOLUTION,
						    h->output_idx, 0,
						    hblob, T6_RES_ENTRY_SIZE);
					t6_ctrl_out(t6, T6_REQ_SET_READY,
						    h->output_idx, 0,
						    NULL, 0);
				}

				t6_ctrl_out(t6, T6_REQ_SET_TIMING, 0, 0,
					    t6_init_timing_post,
					    sizeof(t6_init_timing_post));
				ret = t6_ctrl_out(t6, T6_REQ_FINALIZE,
						  0x0002, 0, NULL, 0);

				if (ret >= 0) {
					mutex_lock(&t6->tx_lock);
					head->width = new_w;
					head->height = new_h;
					head->last_sent_valid = false;
					mutex_unlock(&t6->tx_lock);
					dev_info(&t6->udev->dev,
						 "Output %u: mode changed to %dx%d\n",
						 head->output_idx,
						 new_w, new_h);
				} else {
					dev_warn(&t6->udev->dev,
						 "Mode set %dx%d failed on output %u: %d\n",
						 new_w, new_h,
						 head->output_idx, ret);
				}
			}
		}
	}

	{
		int ret = t6_ctrl_out(t6, T6_REQ_MONITOR_CTRL,
				      head->output_idx, 1, NULL, 0);
		if (ret < 0)
			dev_warn(&t6->udev->dev,
				 "Monitor enable failed on output %u: %d\n",
				 head->output_idx, ret);
	}
	drm_dev_exit(idx);
}

static void t6_crtc_atomic_disable(struct drm_crtc *crtc,
				   struct drm_atomic_state *state)
{
	struct t6_head *head = t6_head_from_crtc(crtc);
	struct t6_device *t6 = head->t6;
	int idx;

	/*
	 * Stop ALL frame activity before turning the output off.
	 * Without this, the keepalive timer re-sends frames which
	 * wakes the monitor back up in a power-on/off cycle.
	 */
	cancel_delayed_work_sync(&head->boot_keepalive_work);
	timer_delete_sync(&head->keepalive_timer);
	cancel_delayed_work_sync(&head->tx_defer_work);
	cancel_work_sync(&head->tx_work);
	WRITE_ONCE(head->keepalive_due, false);

	/* Clear cached keepalive data so no stale resend can occur */
	kvfree(head->last_jpeg_data);
	head->last_jpeg_data = NULL;
	head->last_jpeg_len = 0;

	if (!READ_ONCE(head->connected))
		return;

	if (!drm_dev_enter(&t6->drm, &idx))
		return;

	{
		int ret = t6_ctrl_out(t6, T6_REQ_MONITOR_CTRL,
				      head->output_idx, 0, NULL, 0);
		if (ret < 0)
			dev_warn(&t6->udev->dev,
				 "Monitor disable failed on output %u: %d\n",
				 head->output_idx, ret);
	}
	drm_dev_exit(idx);
}

/*
 * USB displays have no hardware vblank interrupt. Tell the atomic helper to
 * fake vblank events so drm_atomic_helper_wait_for_flip_done() doesn't block
 * indefinitely.
 */
static int t6_crtc_atomic_check(struct drm_crtc *crtc,
				struct drm_atomic_state *state)
{
	struct drm_crtc_state *crtc_state =
		drm_atomic_get_new_crtc_state(state, crtc);

	if (!crtc_state)
		return 0;
	crtc_state->no_vblank = true;
	return 0;
}

static int t6_plane_atomic_check(struct drm_plane *plane,
				 struct drm_atomic_state *state)
{
	struct drm_plane_state *new_plane_state =
		drm_atomic_get_new_plane_state(state, plane);
	struct drm_crtc_state *new_crtc_state = NULL;

	if (!new_plane_state)
		return 0;
	if (new_plane_state->crtc)
		new_crtc_state = drm_atomic_get_new_crtc_state(
			state, new_plane_state->crtc);

	return drm_atomic_helper_check_plane_state(new_plane_state,
						   new_crtc_state,
						   DRM_PLANE_NO_SCALING,
						   DRM_PLANE_NO_SCALING,
						   false,
						   new_crtc_state &&
						   new_crtc_state->enable);
}

static void t6_plane_atomic_update(struct drm_plane *plane,
				   struct drm_atomic_state *atomic_state)
{
	struct drm_plane_state *state = drm_atomic_get_new_plane_state(atomic_state, plane);
	struct drm_shadow_plane_state *shadow;
	struct drm_framebuffer *fb;
	struct t6_head *head = t6_head_from_plane(plane);
	struct t6_device *t6;
	void *vaddr;
	size_t frame_len;
	int idx;
	int ret;

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
		u32 export_stride;
		size_t export_len;
		u8 *tmp;
		u64 stage_start_ns;

		export_shadow = to_drm_shadow_plane_state(state);
		export_vaddr = export_shadow->data[0].vaddr;
		if (!export_vaddr)
			return;
		export_stride = fb->pitches[0];

		export_len = (size_t)head->width * head->height * 4;
		if (export_len > head->tx_buf_size || !head->fb_export_buf)
			return;

		/* Write tightly packed XRGB8888 into tx_back for userspace export. */
		stage_start_ns = ktime_get_ns();
		if (t6_pack_xrgb8888_tight(head,
					  export_vaddr,
					  export_stride,
					  head->tx_back,
					  head->tx_buf_size))
			return;
		t6_metrics_record_timing(&head->metrics.stage_samples,
					 &head->metrics.stage_ns_total,
					 &head->metrics.last_stage_ns,
					 &head->metrics.max_stage_ns,
					 ktime_get_ns() - stage_start_ns);

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

	t6 = head->t6;
	if (t6->manual_only)
		return;
	if (READ_ONCE(t6->io_faulted))
		return;
	if (!t6_head_runtime_connected(head))
		return;

	shadow = to_drm_shadow_plane_state(state);

	vaddr = shadow->data[0].vaddr;
	if (!vaddr)
		return;

	/*
	 * Kernel 6.17 can hand us a stale old_state during drm_dev_register().
	 * Queue the latest full frame and let the worker perform USB I/O outside
	 * the atomic commit path.
	 *
	 * Queue depth stays bounded to one pending frame per head: tx_front may be
	 * in flight on the worker while tx_back remains the pending slot. A newer
	 * update overwrites the previous pending contents instead of getting dropped.
	 */
	{
		int w = READ_ONCE(head->width);
		int h = READ_ONCE(head->height);

		if (!w || !h)
			return;
		frame_len = (size_t)w * h * 4;
	}
	if (!fb->pitches[0] || frame_len > head->tx_buf_size)
		return;

	if (!drm_dev_enter(&t6->drm, &idx))
		return;

	atomic64_inc(&head->metrics.queue_attempts);
	/*
	 * Use a blocking lock rather than trylock.  The double-buffer design
	 * (tx_front in flight, tx_back as the pending slot) exists precisely so
	 * that a new frame can overwrite the pending slot while the worker sends
	 * from tx_front.  Dropping frames at this point defeats that design and
	 * was the source of the high busy-drop counts observed on both the raw
	 * and JPEG heads.  tx_lock is held for only microseconds by the worker
	 * (pointer swaps), so contention here is negligible.
	 */
	mutex_lock(&t6->tx_lock);
	{
		u64 stage_start_ns = ktime_get_ns();

		ret = t6_pack_xrgb8888_tight(head,
				   vaddr,
				   fb->pitches[0],
				   head->tx_back,
				   head->tx_buf_size);
		if (!ret)
			t6_metrics_record_timing(&head->metrics.stage_samples,
						 &head->metrics.stage_ns_total,
						 &head->metrics.last_stage_ns,
						 &head->metrics.max_stage_ns,
						 ktime_get_ns() - stage_start_ns);
	}
	if (ret) {
		mutex_unlock(&t6->tx_lock);
		goto out_exit;
	}
	t6_stage_pending_head_locked(head,
					 frame_len,
					 head->width * 4,
					 ktime_get_ns());
	mutex_unlock(&t6->tx_lock);

	t6_queue_head_tx_work(head);

out_exit:
	drm_dev_exit(idx);
}

static const struct drm_crtc_helper_funcs t6_crtc_helper_funcs = {
	.atomic_enable = t6_crtc_atomic_enable,
	.atomic_disable = t6_crtc_atomic_disable,
	.atomic_check = t6_crtc_atomic_check,
};

static const struct drm_crtc_funcs t6_crtc_funcs = {
	.reset = drm_atomic_helper_crtc_reset,
	.destroy = drm_crtc_cleanup,
	.set_config = drm_atomic_helper_set_config,
	.page_flip = drm_atomic_helper_page_flip,
	.atomic_duplicate_state = drm_atomic_helper_crtc_duplicate_state,
	.atomic_destroy_state = drm_atomic_helper_crtc_destroy_state,
};

static const struct drm_plane_helper_funcs t6_plane_helper_funcs = {
	DRM_GEM_SHADOW_PLANE_HELPER_FUNCS,
	.atomic_check = t6_plane_atomic_check,
	.atomic_update = t6_plane_atomic_update,
};

static const struct drm_plane_funcs t6_plane_funcs = {
	.update_plane = drm_atomic_helper_update_plane,
	.disable_plane = drm_atomic_helper_disable_plane,
	.destroy = drm_plane_cleanup,
	DRM_GEM_SHADOW_PLANE_FUNCS,
};

static const struct drm_encoder_funcs t6_encoder_funcs = {
	.destroy = drm_encoder_cleanup,
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
	t6_reset_device_metrics(t6);

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

	/*
	 * Retry undetected heads in a tight poll loop before DRM
	 * registration so the compositor sees all monitors in one
	 * hotplug event instead of staggered appearances.
	 */
	if (t6_any_head_disconnected(t6)) {
		unsigned long deadline = jiffies +
			msecs_to_jiffies(T6_INITIAL_PROBE_WINDOW_MS);

		while (time_before(jiffies, deadline) &&
		       t6_any_head_disconnected(t6)) {
			msleep(T6_INITIAL_PROBE_RETRY_MS);
			for (head_idx = 0; head_idx < T6_OUTPUT_COUNT;
			     head_idx++) {
				struct t6_head *head =
					t6_get_head(t6, head_idx);
				if (head->connected)
					continue;
				ret = t6_probe_head(t6, head);
				if (ret >= 0 && head->connected)
					dev_info(&intf->dev,
						 "Head %u detected during probe window\n",
						 head_idx);
			}
		}
	}

	for (head_idx = 0; head_idx < T6_OUTPUT_COUNT; head_idx++) {
		struct t6_head *head = t6_get_head(t6, head_idx);

		if (!head->connected)
			continue;

		t6_log_head(head);
	}

	mutex_init(&t6->tx_lock);
	mutex_init(&t6->io_lock);
	t6->tx_next_head = 0;

	t6->wq = alloc_workqueue("t6_io", WQ_UNBOUND | WQ_MEM_RECLAIM, 0);
	if (!t6->wq) {
		ret = -ENOMEM;
		goto err_buffers;
	}

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

	/* Query hardware resolution table AFTER chip init (non-fatal) */
	{
		u8 count = 0;

		ret = t6_ctrl_in(t6, T6_REQ_GET_RES_COUNT, 0, 0, &count, 1);
		if (ret >= 1 && count > 0 && count <= T6_RES_MAX_ENTRIES) {
			t6->res_count = count;
			ret = t6_ctrl_in(t6, T6_REQ_GET_RES_TABLE, 0, 0,
					 t6->res_table, T6_RES_TABLE_SIZE);
			if (ret >= (int)(count * T6_RES_ENTRY_SIZE))
				dev_info(&intf->dev,
					 "T6 reports %u hardware display modes\n",
					 count);
			else {
				dev_info(&intf->dev,
					 "T6 resolution table query returned short response\n");
				t6->res_count = 0;
			}
		} else {
			dev_dbg(&intf->dev,
				"T6 resolution table not available (count=%d ret=%d)\n",
				count, ret);
			t6->res_count = 0;
		}
		ret = 0; /* non-fatal */
	}

	/*
	 * Prime connected heads with black frames to stabilize the HDMI
	 * signal.  Multi-output chips need a few frames to clear internal
	 * buffers and lock the signal before real content arrives.
	 * Prime secondary heads FIRST — they typically take longer to
	 * lock the HDMI signal, so starting them earlier balances the
	 * visual appearance (both monitors come up closer together).
	 * Matches the triggerdm reference implementation.
	 */
	for (head_idx = T6_OUTPUT_COUNT; head_idx-- > 0; ) {
		struct t6_head *head = t6_get_head(t6, head_idx);
		struct t6_flip_header fh;
		struct t6_bulk_header bch;
		u32 stride = head->width * 4;
		u32 frame_size = stride * head->height;
		u32 total = sizeof(fh) + frame_size;
		u8 *staging;
		int frame;

		if (!head->connected)
			continue;

		/* Pick the staging buffer for this head's transport */
		staging = head->video_staging ? head->video_staging :
			  head->jpeg_staging;
		if (!staging || total > (head->video_staging ?
					head->video_staging_size :
					head->jpeg_staging_size))
			continue;

		/* Build a valid flip header for black frames */
		memset(&fh, 0, sizeof(fh));
		fh.command = cpu_to_le32(head->output_idx == 0 ?
					T6_CMD_FLIP_PRIMARY :
					T6_CMD_FLIP_SECONDARY);
		fh.payload_size = cpu_to_le32(frame_size);
		fh.target_format = cpu_to_le32(T6_FMT_RGB32);
		fh.y_pitch = cpu_to_le16(stride);
		fh.y_fb_offset = cpu_to_le32(head->fb_addr + sizeof(fh));
		fh.source_format = cpu_to_le32(T6_FMT_RGB32);
		fh.flag = T6_FLAG_RESET;
		memset(staging, 0, total);
		memcpy(staging, &fh, sizeof(fh));

		for (frame = 0; frame < T6_PRIME_FRAME_COUNT; frame++) {
			int bret;

			memset(&bch, 0, sizeof(bch));
			bch.payload_length = cpu_to_le32(total);
			bch.payload_address = cpu_to_le32(head->fb_addr);
			bch.packet_length = cpu_to_le32(total);
			bret = t6_bulk_write(t6, &bch, sizeof(bch));
			if (bret)
				break;
			bret = t6_bulk_write(t6, staging, total);
			if (bret)
				break;
		}

		/*
		 * Cache the black frame for keepalive so the HDMI signal
		 * stays alive until the compositor starts rendering.
		 * Without this, the T6 chip blanks the output after ~2s
		 * and the monitor loses signal for 20-30s.
		 */
		if (!head->last_jpeg_data)
			head->last_jpeg_data = kvmalloc(total, GFP_KERNEL);
		if (head->last_jpeg_data) {
			memcpy(head->last_jpeg_data, staging, total);
			head->last_jpeg_len = total;
			/* Use boot keepalive (bypasses DRM state checks) */
			if (t6->wq)
				queue_delayed_work(t6->wq,
					&head->boot_keepalive_work,
					msecs_to_jiffies(
						T6_BOOT_KEEPALIVE_INTERVAL_MS));
		}
	}

	/* DRM mode config */
	ret = drmm_mode_config_init(drm);
	if (ret)
		goto err_buffers;
	drm->mode_config.funcs = &t6_mode_config_funcs;
	drm->mode_config.helper_private = &t6_mode_config_helper_funcs;

	drm->mode_config.min_width = 640;
	drm->mode_config.min_height = 480;
	drm->mode_config.max_width = 3840;
	drm->mode_config.max_height = 2160;
	drm->mode_config.preferred_depth = 32;

	for (head_idx = 0; head_idx < T6_OUTPUT_COUNT; head_idx++) {
		struct t6_head *head = t6_get_head(t6, head_idx);

		ret = t6_connector_init(t6, head);
		if (ret)
			goto err_buffers;

		/* Primary plane */
		ret = drm_universal_plane_init(drm, &head->primary_plane,
					       0, &t6_plane_funcs,
					       t6_formats,
					       ARRAY_SIZE(t6_formats),
					       NULL,
					       DRM_PLANE_TYPE_PRIMARY,
					       "t6-plane-%u",
					       head->output_idx);
		if (ret)
			goto err_buffers;
		drm_plane_helper_add(&head->primary_plane,
				     &t6_plane_helper_funcs);

		/* CRTC */
		ret = drm_crtc_init_with_planes(drm, &head->crtc,
						&head->primary_plane,
						NULL, &t6_crtc_funcs,
						"t6-crtc-%u",
						head->output_idx);
		if (ret)
			goto err_buffers;
		drm_crtc_helper_add(&head->crtc, &t6_crtc_helper_funcs);

		/* Set plane's possible_crtcs now that CRTC is initialized */
		head->primary_plane.possible_crtcs = drm_crtc_mask(&head->crtc);

		/* Encoder */
		ret = drm_encoder_init(drm, &head->encoder,
				       &t6_encoder_funcs,
				       DRM_MODE_ENCODER_VIRTUAL,
				       "t6-encoder-%u",
				       head->output_idx);
		if (ret)
			goto err_buffers;
		head->encoder.possible_crtcs = drm_crtc_mask(&head->crtc);

		/* Attach encoder to connector */
		ret = drm_connector_attach_encoder(&head->connector,
						   &head->encoder);
		if (ret)
			goto err_buffers;
	}

	drm_mode_config_reset(drm);

	for (head_idx = 0; head_idx < T6_OUTPUT_COUNT; head_idx++) {
		struct t6_head *head = t6_get_head(t6, head_idx);

		t6_update_connector_status(head);
	}

	if (t6_experimental_secondary_raw)
		dev_warn(&intf->dev,
			 "experimental_secondary_raw=1 forces logical output 1 to raw XRGB8888 transport instead of the default NV12; uses more USB bandwidth but avoids colour-space conversion\n");
	if (t6_secondary_userspace_jpeg)
		dev_warn(&intf->dev,
			 "secondary_userspace_jpeg=1 forces the deprecated userspace JPEG feeder path for logical output 1\n");
	else if (!t6_experimental_secondary_raw)
		dev_info(&intf->dev,
			 "Logical output 1 uses native NV12 transport (BGRX->NV12 conversion with zero-damage skip)\n");
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
	ret = devm_device_add_group(&intf->dev, &t6_group);
	if (ret)
		dev_warn(&intf->dev, "Failed to create sysfs group: %d\n", ret);

	dev_info(&intf->dev,
		 "T6 display ready with %u logical heads modeled\n",
		 T6_OUTPUT_COUNT);
	if (t6_any_head_disconnected(t6))
		t6_schedule_reprobe(t6);
	return 0;

err_jpeg:
	t6_unregister_jpeg_devices(t6);
err_buffers:
	/* Clean up any partially-initialized DRM objects */
	for (head_idx = 0; head_idx < T6_OUTPUT_COUNT; head_idx++) {
		struct t6_head *head = t6_get_head(t6, head_idx);

		drm_encoder_cleanup(&head->encoder);
		drm_crtc_cleanup(&head->crtc);
		drm_plane_cleanup(&head->primary_plane);
	}
	cancel_delayed_work_sync(&t6->reprobe_work);
	t6_cancel_head_activity(t6);
	if (t6->wq) {
		destroy_workqueue(t6->wq);
		t6->wq = NULL;
	}
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
	/* sysfs group removed automatically by devm */

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
	t6_cancel_head_activity(t6);
	if (t6->wq) {
		flush_workqueue(t6->wq);
		destroy_workqueue(t6->wq);
		t6->wq = NULL;
	}
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

	if (!t6)
		return 0;

	cancel_delayed_work_sync(&t6->reprobe_work);
	t6_cancel_head_activity(t6);

	return 0;
}

static int t6_usb_resume(struct usb_interface *intf)
{
	struct t6_device *t6 = usb_get_intfdata(intf);
	unsigned int hi;
	int ret;

	if (!t6)
		return 0;

	/* Clear stale error state from before suspend */
	WRITE_ONCE(t6->io_faulted, false);
	t6->ctrl_error_count = 0;
	for (hi = 0; hi < T6_OUTPUT_COUNT; hi++) {
		struct t6_head *head = t6_get_head(t6, hi);

		WRITE_ONCE(head->io_faulted, false);
		head->last_sent_valid = false;
	}

	/* Re-init chip — T6 loses all state across USB suspend */
	ret = t6_chip_init(t6);
	if (ret < 0)
		return ret;

	/* Restart boot keepalive so monitors stay alive until
	 * the compositor resumes rendering.
	 */
	for (hi = 0; hi < T6_OUTPUT_COUNT; hi++) {
		struct t6_head *head = t6_get_head(t6, hi);

		if (!READ_ONCE(head->connected) || !head->last_jpeg_data)
			continue;
		if (t6->wq)
			queue_delayed_work(t6->wq,
					   &head->boot_keepalive_work,
					   msecs_to_jiffies(
						T6_BOOT_KEEPALIVE_INTERVAL_MS));
	}

	/* Notify compositor to re-evaluate connectors */
	if (!drm_dev_is_unplugged(&t6->drm))
		drm_kms_helper_hotplug_event(&t6->drm);

	return 0;
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
