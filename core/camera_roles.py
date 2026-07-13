"""Camera roles for the three-camera wedge fiber-coupling bench.

The bench splits the main beam at the wedge into three diagnostic paths:

* ``FAR_FIELD`` - ghost reflected off the wedge, samples the beam ~500 mm out.
* ``IMAGE``     - second ghost (Ghost 2), live Thorcam near the fiber plane.
                  Thin-lens placement math is still pending mentor optics
                  (see ``docs/MENTOR_QUESTIONS.md``); the live feed itself is active.
* ``OUTPUT``    - camera after the fiber, measures transmitted power for eta.

The historical two-camera build used generic ``input``/``output`` slots; those
strings are kept in ``LEGACY_ALIASES`` so old config files still load.
"""

from __future__ import annotations

from enum import Enum


class CameraRole(str, Enum):
    """Fixed role a camera plays on the wedge bench."""

    FAR_FIELD = "far_field"
    IMAGE = "image"
    OUTPUT = "output"
    UNASSIGNED = "unassigned"

    @property
    def label(self) -> str:
        """Human-facing name for tiles, buttons, and telemetry."""
        return {
            CameraRole.FAR_FIELD: "Far Field",
            CameraRole.IMAGE: "Image",
            CameraRole.OUTPUT: "Output",
            CameraRole.UNASSIGNED: "Unassigned",
        }[self]

    @classmethod
    def coerce(cls, value: str | "CameraRole" | None) -> "CameraRole":
        """Best-effort parse from stored strings, including legacy aliases."""
        if isinstance(value, CameraRole):
            return value
        if value is None:
            return CameraRole.UNASSIGNED
        key = str(value).strip().lower()
        if key in LEGACY_ALIASES:
            return LEGACY_ALIASES[key]
        try:
            return cls(key)
        except ValueError:
            return CameraRole.UNASSIGNED


# Old two-camera builds stored "input"/"output". Map them onto the new roles so
# existing app_config.json files keep working: the input feed becomes Far Field.
LEGACY_ALIASES: dict[str, CameraRole] = {
    "input": CameraRole.FAR_FIELD,
    "output": CameraRole.OUTPUT,
    "far field": CameraRole.FAR_FIELD,
    "farfield": CameraRole.FAR_FIELD,
}

# Roles that carry a live diagnostic feed, in display order.
ACTIVE_ROLES: tuple[CameraRole, ...] = (
    CameraRole.FAR_FIELD,
    CameraRole.IMAGE,
    CameraRole.OUTPUT,
)
