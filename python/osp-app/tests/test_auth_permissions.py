"""Full permission matrix: every role x action x same/other tenant, plus fail-closed cases."""

from __future__ import annotations

import itertools

import pytest
from osp_app.auth import (
    Action,
    Actor,
    PermissionDenied,
    Resource,
    ResourceKind,
    Role,
    authorize,
    can,
    requires,
)

A = Action
# The policy, written out independently of osp_app.auth.permissions.POLICY.
EXPECTED: dict[Role, set[Action]] = {
    Role.OWNER: {
        A.SURVEY_READ,
        A.SURVEY_EDIT,
        A.SURVEY_PUBLISH,
        A.SURVEY_EXPORT,
        A.SURVEY_DELETE,
        A.RESPONSE_DELETE,
        A.MEMBERS_VIEW,
        A.MEMBERS_MANAGE,
        A.THEMES_VIEW,
        A.THEMES_MANAGE,
        A.PROFILE_VIEW,
        A.PROFILE_MANAGE,
        A.BANK_VIEW,
        A.BANK_MANAGE,
        A.BANK_SHARE,
    },
    Role.EDITOR: {
        A.SURVEY_READ,
        A.SURVEY_EDIT,
        A.SURVEY_PUBLISH,
        A.SURVEY_EXPORT,
        A.RESPONSE_DELETE,
        A.MEMBERS_VIEW,
        A.THEMES_VIEW,
        A.THEMES_MANAGE,
        A.PROFILE_VIEW,
        A.BANK_VIEW,
        A.BANK_MANAGE,
    },
    Role.VIEWER: {A.SURVEY_READ, A.THEMES_VIEW, A.PROFILE_VIEW, A.BANK_VIEW},
}

HOME, OTHER = "tenant-home", "tenant-other"


def resource_for(action: Action, tenant_id: str) -> Resource:
    if action.value.startswith(("members.", "themes.", "profile.", "bank.")):
        return Resource.tenant(tenant_id)
    return Resource.survey(tenant_id, "s1")


def test_expected_covers_every_role_and_action():
    assert set(EXPECTED) == set(Role)
    assert set().union(*EXPECTED.values()) <= set(Action)


@pytest.mark.parametrize(
    ("role", "action", "where"),
    list(itertools.product(Role, Action, ["same", "other"])),
    ids=lambda v: str(v),
)
def test_matrix(role, action, where):
    actor = Actor("u1", {HOME: role})
    tenant = HOME if where == "same" else OTHER
    expected = where == "same" and action in EXPECTED[role]
    assert can(actor, action, resource_for(action, tenant)) is expected
    # string form of the action behaves identically
    assert can(actor, action.value, resource_for(action, tenant)) is expected


@pytest.mark.parametrize("action", list(Action))
def test_member_of_both_tenants_uses_each_tenants_role(action):
    actor = Actor("u1", {HOME: Role.OWNER, OTHER: Role.VIEWER})
    assert can(actor, action, resource_for(action, HOME)) is True
    assert can(actor, action, resource_for(action, OTHER)) is (action in EXPECTED[Role.VIEWER])


# --- fail closed --------------------------------------------------------------

owner = Actor("u1", {HOME: Role.OWNER})


@pytest.mark.parametrize(
    "action", ["survey.destroy", "SURVEY.READ", "", "*", None, 3, Role.OWNER, object()]
)
def test_unknown_action(action):
    assert can(owner, action, Resource.survey(HOME, "s1")) is False


@pytest.mark.parametrize("role", ["admin", "superuser", "", "OWNER", None, 1])
@pytest.mark.parametrize("action", list(Action))
def test_unknown_role(role, action):
    actor = Actor("u1", {HOME: role})
    assert can(actor, action, resource_for(action, HOME)) is False


@pytest.mark.parametrize("action", list(Action))
def test_no_membership(action):
    assert can(Actor("u1", {}), action, resource_for(action, HOME)) is False


@pytest.mark.parametrize("actor", [None, "u1", {"user_id": "u1"}, object()])
def test_no_actor(actor):
    assert can(actor, Action.SURVEY_READ, Resource.survey(HOME, "s1")) is False


@pytest.mark.parametrize(
    "resource",
    [None, "survey", {"tenant_id": HOME}, Resource.survey("", "s1"), Resource("widget", HOME)],
)
def test_bad_resource(resource):
    assert can(owner, Action.SURVEY_READ, resource) is False


@pytest.mark.parametrize("action", list(Action))
def test_action_on_wrong_resource_kind(action):
    wrong = (
        Resource.survey(HOME, "s1")
        if action.value.startswith(("members.", "themes.", "profile.", "bank."))
        else Resource.tenant(HOME)
    )
    assert can(owner, action, wrong) is False


def test_hostile_roles_mapping_does_not_raise():
    class Boom(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")

    assert can(Actor("u1", Boom()), Action.SURVEY_READ, Resource.survey(HOME, "s1")) is False


def test_resource_kinds_cover_all_actions():
    kinds = {resource_for(a, HOME).kind for a in Action}
    assert kinds == set(ResourceKind)


# --- authorize / requires -------------------------------------------------------


def test_authorize():
    authorize(owner, Action.SURVEY_DELETE, Resource.survey(HOME, "s1"))
    with pytest.raises(PermissionDenied) as exc:
        authorize(owner, Action.SURVEY_DELETE, Resource.survey(OTHER, "s1"))
    assert str(exc.value) == "Not permitted."


@requires(Action.SURVEY_PUBLISH)
def publish(actor: Actor, resource: Resource, note: str = "") -> str:
    return f"published {resource.id}{note}"


def test_requires_decorator():
    editor = Actor("u2", {HOME: Role.EDITOR})
    viewer = Actor("u3", {HOME: Role.VIEWER})
    survey = Resource.survey(HOME, "s1")
    assert publish(editor, survey, note="!") == "published s1!"
    assert publish(actor=editor, resource=survey) == "published s1"
    assert publish.required_action is Action.SURVEY_PUBLISH
    with pytest.raises(PermissionDenied):
        publish(viewer, survey)
    with pytest.raises(PermissionDenied):
        publish(editor, Resource.survey(OTHER, "s1"))
    with pytest.raises(PermissionDenied):
        publish()  # type: ignore[call-arg]
