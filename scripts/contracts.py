"""Accept both the project-neutral contract names and legacy vendor-prefixed ones.

Some viewers still publish legacy vendor-prefixed schemas. This module
normalises them to the neutral ``spatial-fengshui.*`` names so callers never
hand-edit captured files.
"""

from __future__ import annotations

CONTEXT_SCHEMAS = ("spatial-fengshui.active-vr", "realsee.active-vr")
CAPTURE_SCHEMAS = ("spatial-fengshui.vr-capture", "realsee.vr-capture")
CAMERA_SCHEMAS = ("spatial-fengshui.camera-projection", "realsee.camera-projection")
SNAPSHOT_SCHEMAS = ("spatial-fengshui.browser-snapshot", "realsee.browser-work-snapshot")


def normalize_context(value):
    """Return the context with the neutral schema name, or the input unchanged."""
    if not isinstance(value, dict) or value.get("schema") not in CONTEXT_SCHEMAS:
        return value
    normalized = dict(value)
    normalized["schema"] = CONTEXT_SCHEMAS[0]
    return normalized


def normalize_camera(camera):
    if not isinstance(camera, dict) or camera.get("schema") not in CAMERA_SCHEMAS:
        return camera
    normalized = dict(camera)
    normalized["schema"] = CAMERA_SCHEMAS[0]
    return normalized


def normalize_capture(capture):
    """Normalise schema names on a capture and its nested context/camera."""
    if not isinstance(capture, dict):
        return capture
    normalized = dict(capture)
    if normalized.get("schema") in CAPTURE_SCHEMAS:
        normalized["schema"] = CAPTURE_SCHEMAS[0]
    normalized["context"] = normalize_context(normalized.get("context"))
    if normalized.get("camera") is not None:
        normalized["camera"] = normalize_camera(normalized["camera"])
    return normalized


def schema_matches(value, schemas):
    return isinstance(value, dict) and value.get("schema") in schemas
