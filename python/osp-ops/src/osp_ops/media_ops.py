"""`set_choice_media`: set or remove the image / audio clip on one choice (planning/media.md
§2.2). A question's or note's own `media` list is an ordinary property, edited as a whole
with `set_property(target, "media", [...])`; a choice has no id of its own, so its media
needs this op (addressed by owner + code, like `set_choice`)."""

from __future__ import annotations

import copy
from typing import Any

from .choice_ops import ChoiceValue, find_choice, owner_choices
from .registry import Ctx, Invocation, Params, op

MEDIA = "media"


class SetChoiceMedia(Params):
    owner: str  # a choice list id, or a single/multi/matrix question with inline choices
    value: ChoiceValue  # the choice's code
    media: dict[str, Any] | None = None  # an `osp_spec.media.Media` object
    unset: bool = False  # remove the media


@op("set_choice_media", SetChoiceMedia, label="Set choice media", area="choices")
def set_choice_media(ctx: Ctx, p: SetChoiceMedia) -> Invocation:
    """Set (or with `unset`, remove) the media shown with one choice: an image or an audio
    clip (the survey model refuses a video on a choice). Replaces any media the choice had;
    the inverse restores it."""
    choices, _, ptr = owner_choices(ctx, p.owner)
    i = find_choice(choices, p.value, ptr)
    c = choices[i]
    old = copy.deepcopy(c.get(MEDIA))
    if p.unset or p.media is None:
        c.pop(MEDIA, None)
    else:
        c[MEDIA] = copy.deepcopy(p.media)
    ctx.touch()
    inverse: dict[str, Any] = {"owner": p.owner, "value": p.value}
    if old is None:
        inverse["unset"] = True
    else:
        inverse["media"] = old
    return Invocation(op="set_choice_media", params=inverse)
