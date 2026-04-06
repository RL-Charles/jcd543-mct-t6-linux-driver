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
	struct drm_display_mode *mode;
	struct edid *edid = (struct edid *)head->edid_data;

	if (!t6_head_runtime_connected(head))
		return 0;

	/*
	 * We cache EDID for userspace visibility, but the reverse-engineered T6
	 * modeset path is still only validated for the Windows-captured 1080p60
	 * timing blob. Do not advertise monitor-native modes we cannot program.
	 */
	if (head->edid_len >= EDID_LENGTH && drm_edid_is_valid(edid))
		drm_connector_update_edid_property(connector, edid);
	else
		drm_connector_update_edid_property(connector, NULL);

	mode = drm_cvt_mode(connector->dev,
			    T6_SCANOUT_WIDTH,
			    T6_SCANOUT_HEIGHT,
			    T6_SCANOUT_REFRESH_HZ,
			    false, false, false);
	if (!mode)
		return 0;

	mode->type |= DRM_MODE_TYPE_PREFERRED | DRM_MODE_TYPE_DRIVER;
	drm_mode_probed_add(connector, mode);
	return 1;
}

/*
 * Reject modes too large for USB bandwidth.
 */
static enum drm_mode_status
t6_connector_mode_valid_common(const struct drm_display_mode *mode)
{
	if (mode->hdisplay != T6_SCANOUT_WIDTH ||
	    mode->vdisplay != T6_SCANOUT_HEIGHT)
		return MODE_BAD;
	if (drm_mode_vrefresh(mode) != T6_SCANOUT_REFRESH_HZ)
		return MODE_BAD;
	return MODE_OK;
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

	/*
	 * NO polling. Polling caused system freezes -- drm_kms_helper_poll
	 * workqueue takes mode_config.mutex which deadlocks during probe.
	 * Modes are force-populated in probe via t6_force_modes() instead.
	 */
	head->connector.polled = 0;

	return 0;
}
