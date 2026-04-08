// SPDX-License-Identifier: GPL-2.0-only
/*
 * trigger6_connector.c -- DRM connector for MCT T6 USB Display
 *
 * EDID is cached at probe time. ALL callbacks serve from memory.
 * ZERO USB calls from any DRM callback -- prevents deadlocks.
 *
 * Copyright (C) 2026 Authentra / Ralph Friedman
 */

#include <drm/drm_atomic_helper.h>
#include <drm/drm_connector.h>
#include <drm/drm_edid.h>
#include <drm/drm_modes.h>
#include <drm/drm_modeset_helper_vtables.h>
#include <drm/drm_probe_helper.h>

#include "trigger6.h"

/*
 * Always return connected. Verified at probe time.
 * No USB calls -- DRM polls this from contexts where USB deadlocks.
 */
static enum drm_connector_status
t6_connector_detect(struct drm_connector *connector, bool force)
{
	struct t6_head *head = t6_head_from_connector(connector);

	return t6_head_runtime_connected(head) ?
		connector_status_connected : connector_status_disconnected;
}

/*
 * Return a single mode matching the T6 chip's init timing.
 * No USB calls. No EDID parsing. Just a CVT mode.
 */
static int t6_connector_get_modes(struct drm_connector *connector)
{
	struct t6_head *head = t6_head_from_connector(connector);
	struct t6_device *t6 = head->t6;
	struct drm_display_mode *mode;
	struct edid *edid = (struct edid *)head->edid_data;
	int count = 0;
	int i;

	if (!t6_head_runtime_connected(head))
		return 0;

	if (head->edid_len >= EDID_LENGTH && drm_edid_is_valid(edid)) {
		drm_connector_update_edid_property(connector, edid);
		/* Extract physical size for HiDPI scaling (EDID bytes 0x15-0x16 = cm) */
		if (head->edid_data[0x15] && head->edid_data[0x16]) {
			connector->display_info.width_mm = head->edid_data[0x15] * 10;
			connector->display_info.height_mm = head->edid_data[0x16] * 10;
		}
	} else {
		drm_connector_update_edid_property(connector, NULL);
	}

	/*
	 * Advertise modes from the hardware resolution table (queried
	 * via vendor request 0x89 at probe time).  Each 32-byte entry
	 * encodes display timing; we extract width, height, refresh.
	 * Fallback to fixed 1080p60 if no table was returned.
	 */
	if (t6->res_count > 0) {
		for (i = 0; i < t6->res_count; i++) {
			const u8 *entry = &t6->res_table[i * T6_RES_ENTRY_SIZE];
			u16 width = le16_to_cpup((__le16 *)(entry + 8));
			u16 height = le16_to_cpup((__le16 *)(entry + 16));
			u16 refresh = le16_to_cpup((__le16 *)(entry + 4));

			if (!width || !height || !refresh)
				continue;

			mode = drm_cvt_mode(connector->dev,
					    width, height, refresh,
					    false, false, false);
			if (!mode)
				continue;

			mode->type |= DRM_MODE_TYPE_DRIVER;
			if (width == T6_SCANOUT_WIDTH &&
			    height == T6_SCANOUT_HEIGHT)
				mode->type |= DRM_MODE_TYPE_PREFERRED;
			drm_mode_probed_add(connector, mode);
			count++;
		}
	}

	/*
	 * Offer all hardware-validated built-in modes.  Each has a
	 * 32-byte timing blob that was tested on real T6 hardware.
	 */
	if (count == 0) {
		for (i = 0; i < t6_builtin_mode_count; i++) {
			mode = drm_cvt_mode(connector->dev,
					    t6_builtin_modes[i].width,
					    t6_builtin_modes[i].height,
					    t6_builtin_modes[i].refresh,
					    false, false, false);
			if (!mode)
				continue;
			mode->type |= DRM_MODE_TYPE_DRIVER;
			if (t6_builtin_modes[i].width == T6_SCANOUT_WIDTH &&
			    t6_builtin_modes[i].height == T6_SCANOUT_HEIGHT)
				mode->type |= DRM_MODE_TYPE_PREFERRED;
			drm_mode_probed_add(connector, mode);
			count++;
		}
	}

	return count;
}

/*
 * Accept any mode that the hardware reported in its resolution table,
 * or the fixed 1080p60 fallback.  Reject anything else to prevent
 * sending timing data the T6 chip can't handle.
 */
static enum drm_mode_status
t6_connector_mode_valid_common(const struct drm_display_mode *mode)
{
	/* Always accept 1080p60 (the validated fallback) */
	if (mode->hdisplay == T6_SCANOUT_WIDTH &&
	    mode->vdisplay == T6_SCANOUT_HEIGHT &&
	    drm_mode_vrefresh(mode) == T6_SCANOUT_REFRESH_HZ)
		return MODE_OK;

	/*
	 * Accept any mode we advertised from the hardware table.
	 * Modes only reach mode_valid if they passed get_modes,
	 * and we only add modes from the hardware resolution table
	 * or the 1080p60 fallback — so accept DRM_MODE_TYPE_DRIVER.
	 */
	if (mode->type & DRM_MODE_TYPE_DRIVER)
		return MODE_OK;

	return MODE_BAD;
}

static enum drm_mode_status
t6_connector_mode_valid_mutable(struct drm_connector *connector,
				struct drm_display_mode *mode)
{
	return t6_connector_mode_valid_common(mode);
}

static enum drm_mode_status
t6_connector_mode_valid_const(struct drm_connector *connector,
			      const struct drm_display_mode *mode)
{
	return t6_connector_mode_valid_common(mode);
}

/*
 * Kernel API compatibility: the mode_valid callback signature changed from
 * mutable to const struct drm_display_mode * between kernel versions.
 * Use __builtin_types_compatible_p to select the matching variant at compile
 * time so the driver builds cleanly on both old and new kernels.
 */
#define T6_CONNECTOR_MODE_VALID \
	__builtin_choose_expr(\
		__builtin_types_compatible_p(\
			typeof(((struct drm_connector_helper_funcs *)0)->mode_valid), \
			enum drm_mode_status (*)(struct drm_connector *, \
						 const struct drm_display_mode *)), \
		t6_connector_mode_valid_const, \
		t6_connector_mode_valid_mutable)

static const struct drm_connector_helper_funcs t6_conn_helper = {
	.get_modes = t6_connector_get_modes,
	.mode_valid = T6_CONNECTOR_MODE_VALID,
};

static const struct drm_connector_funcs t6_conn_funcs = {
	.detect = t6_connector_detect,
	.fill_modes = drm_helper_probe_single_connector_modes,
	.destroy = drm_connector_cleanup,
	.reset = drm_atomic_helper_connector_reset,
	.atomic_duplicate_state = drm_atomic_helper_connector_duplicate_state,
	.atomic_destroy_state = drm_atomic_helper_connector_destroy_state,
};

int t6_connector_init(struct t6_device *t6, struct t6_head *head)
{
	int ret;

	ret = drm_connector_init(&t6->drm, &head->connector, &t6_conn_funcs,
				 DRM_MODE_CONNECTOR_HDMIA);
	if (ret)
		return ret;

	drm_connector_helper_add(&head->connector, &t6_conn_helper);

	/* Standard HDMI subpixel layout for text rendering optimization */
	head->connector.display_info.subpixel_order = SubPixelHorizontalRGB;

	/*
	 * NO polling. Polling caused system freezes -- drm_kms_helper_poll
	 * workqueue takes mode_config.mutex which deadlocks during probe.
	 * Modes are force-populated in probe via t6_force_modes() instead.
	 */
	head->connector.polled = 0;
	head->connector.interlace_allowed = 0;
	head->connector.doublescan_allowed = 0;

	return 0;
}
