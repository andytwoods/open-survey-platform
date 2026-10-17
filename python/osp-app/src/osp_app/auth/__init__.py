"""Auth core for osp-app (layer L5): roles and the permissions policy. No HTTP here.

Who the researcher is comes from the host (plan P, planning/pages-split.md): there are no
passwords, two-factor codes or sessions in this project. ``osp_app.identity`` checks what a
host sends and turns it into an :class:`Actor`."""

from .model import Role
from .permissions import (
    Action,
    Actor,
    PermissionDenied,
    Resource,
    ResourceKind,
    authorize,
    can,
    requires,
)
from .ports import Clock, SystemClock

__all__ = [
    "Action",
    "Actor",
    "Clock",
    "PermissionDenied",
    "Resource",
    "ResourceKind",
    "Role",
    "SystemClock",
    "authorize",
    "can",
    "requires",
]
