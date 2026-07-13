"""Which bench cameras stay open during live feed.

Three CS165CU Thorcams on one USB controller cannot reliably stream full-rate
color simultaneously. The production rule is simple:

* **Primary (large) pane** — continuous live stream.
* **The other two roles** — one frozen snap each (refreshed on Start Live Feed
  and when you promote a different camera to primary).

Thin-lens placement math (``core/optics/image_camera.py``) is bench documentation
only; it does not gate acquisition or display.
"""

from __future__ import annotations

from enum import Enum

from core.camera_roles import ACTIVE_ROLES, CameraRole


class LivePolicy(str, Enum):
    """``single`` is the production default. Other values are legacy/debug only."""

    SINGLE = "single"
    DUAL_EFFICIENCY = "dual_efficiency"
    ALL = "all"

    @classmethod
    def coerce(cls, value: str | LivePolicy | None) -> LivePolicy:
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.SINGLE
        key = str(value).strip().lower()
        for member in cls:
            if member.value == key:
                return member
        return cls.SINGLE


def assigned_roles(cfg) -> list[CameraRole]:
    """Roles with a configured serial in app config."""
    out: list[CameraRole] = []
    for role in ACTIVE_ROLES:
        slot = cfg.camera_by_role(role)
        if slot is not None and slot.serial:
            out.append(role)
    return out


def streaming_roles(
    policy: LivePolicy | str,
    *,
    primary: CameraRole,
    popped: set[CameraRole] | frozenset[CameraRole],
    cfg,
) -> list[CameraRole]:
    """Roles that should hold an open continuous Thorcam worker.

    Production (``single``): only the primary camera streams. Thumbnails and
    even popped-out non-primary panes stay on frozen snaps so USB stays free.
    """
    pol = LivePolicy.coerce(policy)
    assigned = assigned_roles(cfg)
    if not assigned:
        return []

    if pol is LivePolicy.SINGLE:
        return [primary] if primary in assigned else []

    if pol is LivePolicy.DUAL_EFFICIENCY:
        want = {CameraRole.FAR_FIELD, CameraRole.OUTPUT, primary}
        roles = [r for r in ACTIVE_ROLES if r in want and r in assigned]
    else:
        roles = list(assigned)

    # Legacy dual/all: a popped-out pane may also stream.
    for role in ACTIVE_ROLES:
        if role in popped and role in assigned and role not in roles:
            roles.append(role)

    order = {r: i for i, r in enumerate(ACTIVE_ROLES)}
    roles.sort(key=lambda r: (0 if r == primary else 1, order.get(r, 99)))
    return roles


def thumb_roles(*, primary: CameraRole, cfg) -> list[CameraRole]:
    """Assigned roles that are not primary — get one frozen snap, not a live stream."""
    return [r for r in assigned_roles(cfg) if r != primary]


def policy_summary(policy: LivePolicy | str) -> str:
    pol = LivePolicy.coerce(policy)
    if pol is LivePolicy.SINGLE:
        return "Live: primary camera only (thumbs keep last frame)"
    if pol is LivePolicy.DUAL_EFFICIENCY:
        return "Live: Far Field + Output for η (Image: snap)"
    return "Live: all assigned cameras (may contend on USB)"
