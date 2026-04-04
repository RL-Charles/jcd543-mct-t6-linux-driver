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
	return connector_status_connected;
}

/*
 * Return a single mode matching the T6 chip's init timing.
 * No USB calls. No EDID parsing. Just a CVT mode.
 */
static int t6_connector_get_modes(struct drm_connector *connector)
{
	struct t6_device *t6 = to_t6(connector->dev);
	struct drm_display_mode *mode;

	mode = drm_cvt_mode(connector->dev, t6->width, t6->height,
			    60, false, false, false);
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
t6_connector_mode_valid(struct drm_connector *connector,
			const struct drm_display_mode *mode)
{
	if (mode->hdisplay > 1920 || mode->vdisplay > 1200)
		return MODE_BAD;
	if (mode->hdisplay < 640 || mode->vdisplay < 480)
		return MODE_BAD;
	return MODE_OK;
}

static const struct drm_connector_helper_funcs t6_conn_helper = {
	.get_modes = t6_connector_get_modes,
	.mode_valid = t6_connector_mode_valid,
};

static const struct drm_connector_funcs t6_conn_funcs = {
	.detect = t6_connector_detect,
	.fill_modes = drm_helper_probe_single_connector_modes,
	.destroy = drm_connector_cleanup,
	.reset = drm_atomic_helper_connector_reset,
	.atomic_duplicate_state = drm_atomic_helper_connector_duplicate_state,
	.atomic_destroy_state = drm_atomic_helper_connector_destroy_state,
};

int t6_connector_init(struct t6_device *t6)
{
	int ret;

	ret = drm_connector_init(&t6->drm, &t6->connector, &t6_conn_funcs,
				 DRM_MODE_CONNECTOR_HDMIA);
	if (ret)
		return ret;

	drm_connector_helper_add(&t6->connector, &t6_conn_helper);

	/*
	 * NO polling. Polling caused system freezes — drm_kms_helper_poll
	 * workqueue takes mode_config.mutex which deadlocks during probe.
	 * Modes are force-populated in probe via t6_force_modes() instead.
	 */
	t6->connector.polled = 0;

	return 0;
}
