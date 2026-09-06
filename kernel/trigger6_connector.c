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
 * Return cached connection state, including the selected output and fault latch.
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
 * Fixed CEA mode, matching the live firmware's verified 32-byte timing record.
 * The upstream dynamic mode table could exceed preallocated frame buffers.
 */
static const struct drm_display_mode t6_1080p_mode = {
	DRM_MODE("1920x1080", DRM_MODE_TYPE_DRIVER | DRM_MODE_TYPE_PREFERRED,
		 148500, 1920, 2008, 2052, 2200, 0,
		 1080, 1084, 1089, 1125, 0,
		 DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_PVSYNC),
};

bool t6_mode_supported(const struct drm_display_mode *mode)
{
	return drm_mode_equal(mode, &t6_1080p_mode);
}

static int t6_connector_get_modes(struct drm_connector *connector)
{
	struct t6_head *head = t6_head_from_connector(connector);
	struct drm_display_mode *mode;
	struct edid *edid = (struct edid *)head->edid_data;

	if (!t6_head_runtime_connected(head))
		return 0;
	if (head->edid_len == EDID_LENGTH && drm_edid_is_valid(edid)) {
		drm_connector_update_edid_property(connector, edid);
		connector->display_info.width_mm = head->edid_data[0x15] * 10;
		connector->display_info.height_mm = head->edid_data[0x16] * 10;
	} else {
		drm_connector_update_edid_property(connector, NULL);
	}
	mode = drm_mode_duplicate(connector->dev, &t6_1080p_mode);
	if (!mode)
		return 0;
	drm_mode_probed_add(connector, mode);
	return 1;
}

static enum drm_mode_status
t6_connector_mode_valid_common(const struct drm_display_mode *mode)
{
	return t6_mode_supported(mode) ? MODE_OK : MODE_BAD;
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
	 * Reconnect the device deliberately between experiments.
	 */
	head->connector.polled = 0;
	head->connector.interlace_allowed = 0;
	head->connector.doublescan_allowed = 0;

	return 0;
}
