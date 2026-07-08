"""Image camera (Ghost 2) thin-lens helper. STUB, blocked on mentor optics.

The Image camera images some plane along the second ghost path. To place it we
need the thin-lens inputs that are NOT yet defined (see docs/MENTOR_QUESTIONS.md):

  1. which plane we are imaging (fiber waist, wedge face, Mirror 5, ...),
  2. the total Ghost 2 path length (object distance d_o),
  3. which element acts as the lens and its focal length f.

Until those exist, ``spec_available()`` is False and the math refuses to run so
nobody ships a guessed d_i. Once the mentor provides values, fill an
``ImageCameraSpec`` and ``image_distance_mm`` computes d_i from 1/f = 1/d_o + 1/d_i.
"""

from __future__ import annotations

from dataclasses import dataclass


class ImageSpecPendingError(RuntimeError):
    """Raised when Image-camera math is requested before the mentor spec exists."""


@dataclass
class ImageCameraSpec:
    """Thin-lens inputs for the Ghost 2 imaging path (all mentor-provided)."""

    imaged_plane: str | None = None       # e.g. "fiber waist"
    object_distance_mm: float | None = None   # d_o
    focal_length_mm: float | None = None      # f of the effective lens element

    def is_complete(self) -> bool:
        return (
            self.object_distance_mm is not None
            and self.focal_length_mm is not None
            and self.object_distance_mm > 0
            and self.focal_length_mm != 0
        )


# No mentor data yet. Replace with a filled ImageCameraSpec once optics are known.
CURRENT_SPEC = ImageCameraSpec()


def spec_available(spec: ImageCameraSpec | None = None) -> bool:
    """True only when we have real optical inputs to compute d_i."""
    return (spec or CURRENT_SPEC).is_complete()


def image_distance_mm(spec: ImageCameraSpec | None = None) -> float:
    """Sensor distance d_i from the thin-lens equation 1/f = 1/d_o + 1/d_i.

    Raises ImageSpecPendingError until the mentor provides plane, d_o, and f.
    """
    spec = spec or CURRENT_SPEC
    if not spec.is_complete():
        raise ImageSpecPendingError(
            "Image camera optics undefined. Need imaged plane, object distance, "
            "and focal length from the mentor (docs/MENTOR_QUESTIONS.md)."
        )
    inv = 1.0 / spec.focal_length_mm - 1.0 / spec.object_distance_mm
    if inv == 0:
        raise ImageSpecPendingError("Degenerate optics: object at focal length (d_i -> infinity).")
    return 1.0 / inv
