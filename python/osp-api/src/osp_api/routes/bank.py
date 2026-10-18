"""Question bank API (task QB4, planning/question-bank.md §3). Thin: HTTP <-> ``osp_app.bank``.

Every route is tenant-scoped: the lab is ``tenantId`` (query or body), or the caller's only
lab; saving from a survey works in that survey's lab. Members may list, search and read;
owners and editors save, version, edit, delete, import, export and copy; owners share with
the host and relicense. Inserting an item into a survey is a survey op (QB3).

- ``GET    /api/bank``                      search: lab + host-shared + bundled, one list
- ``GET    /api/bank/library``              the bundled instruments
- ``GET    /api/bank/stubs``                instrument stubs for the licensed-copy wizard (QB5)
- ``POST   /api/bank/preview``              what a save would keep and cut (QB5)
- ``POST   /api/bank/licensed``             a private licensed-to-lab item from pasted items (QB5)
- ``POST   /api/bank``                      save from a survey target (201)
- ``POST   /api/bank/import``               a ``*.osp-bank.json`` file (201)
- ``GET    /api/bank/{id}?version=``        one version's document
- ``GET    /api/bank/{id}/versions``        the versions
- ``POST   /api/bank/{id}/versions``        a new version from a survey target (201)
- ``PATCH  /api/bank/{id}``                 metadata only
- ``POST   /api/bank/{id}/share``           ``{visibility, licenceClass?}`` (owner)
- ``DELETE /api/bank/{id}``                 soft delete (204)
- ``GET    /api/bank/{id}/export?version=`` the portable file
- ``POST   /api/bank/{id}/copy``            an editable lab copy (201)
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from osp_app import (
    BankImportResult,
    BankItemView,
    BankListView,
    BankPreview,
    BankSaveResult,
    BankSummary,
    BankVersionInfo,
)
from osp_spec import Diagnostic
from pydantic import BaseModel, ConfigDict, Field

from .common import Auth, Services, errors

router = APIRouter(prefix="/api/bank", tags=["bank"])

_TENANT = Field(None, description="The lab; needed only if you belong to several labs")
Source = Literal["lab", "host", "bundled"]
Kind = Literal["question", "page", "block"]
Visibility = Literal["lab", "host"]


class BankSummaryOut(BaseModel):
    id: str
    source: Source = Field(description="lab: this lab's; host: another lab's shared; bundled")
    kind: Kind
    title: str
    abbreviation: str | None
    description: str | None
    tags: list[str]
    languages: list[str]
    licenceClass: str
    version: int = Field(description="The current version")
    itemCount: int
    visibility: Visibility | None = Field(description="null for a bundled item")
    labId: str | None = Field(description="The owning lab; null for a bundled item")
    canEdit: bool = Field(description="The caller may change this item (own lab, manage)")
    createdBy: str | None = None
    createdAt: datetime | None = None
    updatedBy: str | None = None
    updatedAt: datetime | None = None
    deletedAt: datetime | None = None


class BankList(BaseModel):
    tenantId: str
    items: list[BankSummaryOut]
    total: int
    page: int
    pageSize: int
    canManage: bool = Field(description="The caller may save, edit, delete, import, export")
    canShare: bool = Field(description="The caller may share items with the host (owner)")
    hostSharing: bool = Field(description="This host allows sharing between labs")


class BankItemOut(BaseModel):
    summary: BankSummaryOut
    document: dict[str, Any] = Field(description="The osp-bank-item/0.1 document")
    version: int = Field(description="The version this document is")
    checksum: str | None = Field(description="sha256 of the fragment; null for bundled")


class BankVersionOut(BaseModel):
    version: int
    title: str
    checksum: str
    createdBy: str
    createdAt: datetime


class BankSaveOut(BaseModel):
    item: BankItemOut
    diagnostics: list[Diagnostic] = Field(
        description="Warnings from the extraction (references outside the saved part cut)"
    )


class BankImportOut(BaseModel):
    items: list[BankSummaryOut]
    diagnostics: list[Diagnostic]


class BankFile(BaseModel):
    bankFile: str
    exportedAt: str
    private: bool = Field(description="Holds a licensed-to-lab item: the lab's own backup")
    items: list[dict[str, Any]]


class SaveBankItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surveyId: str
    targetId: str = Field(description="The question, page or block id to save")
    title: str = Field(min_length=1, max_length=200)
    abbreviation: str | None = Field(None, max_length=40)
    description: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    licence: dict[str, Any] | None = Field(None, description="Default: {class: unknown}")
    citation: dict[str, Any] | None = None
    scoring: dict[str, Any] | None = None


class NewVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surveyId: str
    targetId: str
    title: str | None = Field(None, min_length=1, max_length=200)
    abbreviation: str | None = Field(None, max_length=40)
    description: str | None = None
    tags: list[str] | None = Field(None, max_length=20)
    licence: dict[str, Any] | None = None
    citation: dict[str, Any] | None = None
    scoring: dict[str, Any] | None = None


class UpdateBankItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, min_length=1, max_length=200)
    abbreviation: str | None = Field(None, max_length=40)
    description: str | None = None
    tags: list[str] | None = Field(None, max_length=20)
    tenantId: str | None = _TENANT


class ShareBankItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visibility: Visibility
    licenceClass: str | None = Field(
        None, description="Relicense as you share, e.g. cc-by-4.0 for the lab's own words"
    )
    tenantId: str | None = _TENANT


class ImportBankFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: dict[str, Any] = Field(description="The *.osp-bank.json document")
    attestLicensed: bool = Field(
        False, description="Owner's attestation that the lab holds the licence (licensed-to-lab)"
    )
    tenantId: str | None = _TENANT


class CopyBankItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int | None = None
    tenantId: str | None = _TENANT


# -- QB5: preview, stubs, licensed copies -------------------------------------------------


class BankPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surveyId: str
    targetId: str = Field(description="The question, page or block id that would be saved")


class BankPreviewOut(BaseModel):
    kind: Kind
    itemCount: int
    languages: list[str]
    choiceLists: list[str] = Field(description="Shared choice lists that travel with it")
    variables: list[str] = Field(description="Computed (scoring) variables that travel with it")
    diagnostics: list[Diagnostic] = Field(
        description="Warnings: references outside the saved part that would be cut"
    )


class StubHolderOut(BaseModel):
    name: str
    url: str | None


class StubCitationOut(BaseModel):
    text: str
    doi: str | None


class StubResponseOut(BaseModel):
    kind: Literal["shared", "per-item"] = Field(
        description="shared: one scale for every item; per-item: each item has its own options"
    )
    min: int
    max: int


class StubScoringOut(BaseModel):
    aggregate: Literal["sum", "mean"] | None
    reversed: list[int] = Field(description="1-based item numbers scored (min + max - value)")
    subscales: dict[str, list[int]]
    total: bool
    offset: int
    factor: str | None
    text: str


class InstrumentStubOut(BaseModel):
    """An instrument the project may not bundle: metadata, response format and scoring
    recipe for the lab's own licensed copy. Never any item text."""

    stubVersion: str
    id: str
    title: str
    abbreviation: str
    description: str
    tags: list[str]
    terms: Literal["ask", "licensed"] = Field(
        description="ask: free for research, redistribution not granted; licensed: proprietary"
    )
    holder: StubHolderOut
    citation: StubCitationOut
    itemCount: int
    response: StubResponseOut
    scoring: StubScoringOut
    note: str | None


class ScaleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: int
    max: int


class ScoringIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aggregate: Literal["sum", "mean"] | None = "sum"
    reversed: list[int] = Field(default_factory=list, max_length=200)
    subscales: dict[str, list[int]] = Field(default_factory=dict)
    total: bool = True
    offset: int = 0
    factor: str | None = Field(None, max_length=20)


class ComposeLicensedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[str] = Field(
        min_length=1,
        max_length=200,
        description="One line per item: `text` or `text | option | option ...` (per-item wording)",
    )
    attest: bool = Field(
        description="Owner's attestation: the lab holds a licence; the item stays private"
    )
    stubId: str | None = Field(None, max_length=64)
    title: str | None = Field(None, max_length=200)
    abbreviation: str | None = Field(None, max_length=40)
    prefix: str | None = Field(
        None, max_length=40, description="Id prefix (default: from the abbreviation)"
    )
    layout: Literal["matrix", "single"] = "matrix"
    stem: str | None = Field(None, max_length=2000, description="The instruction above the items")
    labels: list[str] | None = Field(None, max_length=21, description="One per scale point")
    scale: ScaleIn | None = Field(None, description="Required without a stub")
    scoring: ScoringIn | None = Field(None, description="Without a stub; default: a plain sum")
    description: str | None = None
    tags: list[str] | None = Field(None, max_length=20)
    language: str | None = Field(None, max_length=12, description="Store texts as {lang: text}")
    tenantId: str | None = _TENANT


def _summary(s: BankSummary) -> BankSummaryOut:
    return BankSummaryOut(
        id=s.id,
        source=s.source,  # type: ignore[arg-type]
        kind=s.kind,  # type: ignore[arg-type]
        title=s.title,
        abbreviation=s.abbreviation,
        description=s.description,
        tags=s.tags,
        languages=s.languages,
        licenceClass=s.licence_class,
        version=s.version,
        itemCount=s.item_count,
        visibility=s.visibility,  # type: ignore[arg-type]
        labId=s.lab_id,
        canEdit=s.can_edit,
        createdBy=s.created_by,
        createdAt=s.created_at,
        updatedBy=s.updated_by,
        updatedAt=s.updated_at,
        deletedAt=s.deleted_at,
    )


def _item(v: BankItemView) -> BankItemOut:
    return BankItemOut(
        summary=_summary(v.summary), document=v.document, version=v.version, checksum=v.checksum
    )


def _saved(r: BankSaveResult) -> BankSaveOut:
    return BankSaveOut(item=_item(r.item), diagnostics=r.diagnostics)


def _version(v: BankVersionInfo) -> BankVersionOut:
    return BankVersionOut(
        version=v.version,
        title=v.title,
        checksum=v.checksum,
        createdBy=v.created_by,
        createdAt=v.created_at,
    )


def _list(v: BankListView) -> BankList:
    return BankList(
        tenantId=v.tenant_id,
        items=[_summary(s) for s in v.items],
        total=v.total,
        page=v.page,
        pageSize=v.page_size,
        canManage=v.can_manage,
        canShare=v.can_share,
        hostSharing=v.host_sharing,
    )


def _imported(r: BankImportResult) -> BankImportOut:
    return BankImportOut(items=[_summary(s) for s in r.items], diagnostics=r.diagnostics)


@router.get("", operation_id="searchBank", responses=errors(401, 403, 422))
def search_bank(
    auth: Auth,
    services: Services,
    q: Annotated[str | None, Query(max_length=200, description="Every word must match")] = None,
    kind: Kind | None = None,
    source: Source | None = None,
    lang: Annotated[str | None, Query(max_length=40)] = None,
    licence: Annotated[str | None, Query(max_length=40, description="A licence class")] = None,
    tag: Annotated[list[str] | None, Query(description="Every tag must be present")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=200)] = 50,
    tenantId: str | None = None,
) -> BankList:
    return _list(
        services.builder.run(
            "bank.list",
            auth.actor,
            q=q,
            kind=kind,
            source=source,
            language=lang,
            licence=licence,
            tags=tuple(tag or ()),
            page=page,
            page_size=pageSize,
            tenant_id=tenantId,
        )
    )


@router.get("/library", operation_id="getBankLibrary", responses=errors(401, 403))
def get_library(auth: Auth, services: Services) -> list[BankSummaryOut]:
    """The bundled instruments (read-only; `GET /api/bank/{id}` gives the document)."""
    return [_summary(s) for s in services.builder.run("bank.library", auth.actor)]


@router.get("/stubs", operation_id="getBankStubs", responses=errors(401, 403))
def get_stubs(auth: Auth, services: Services) -> list[InstrumentStubOut]:
    """Instrument stubs for "Add a licensed instrument privately": metadata, response
    format and scoring recipe, no item text (planning/question-bank.md section 1.7)."""
    return [
        InstrumentStubOut.model_validate(s) for s in services.builder.run("bank.stubs", auth.actor)
    ]


@router.post("/preview", operation_id="previewBankSave", responses=errors(401, 403, 404, 422))
def preview_save(body: BankPreviewRequest, auth: Auth, services: Services) -> BankPreviewOut:
    """What saving a question, page or block to the bank would keep (shared choice lists,
    scoring variables) and cut (references outside it). Nothing is saved. 422 with
    `bank.*` diagnostics when the part can't be cut out."""
    p: BankPreview = services.builder.run(
        "bank.preview", auth.actor, survey_id=body.surveyId, target_id=body.targetId
    )
    return BankPreviewOut(
        kind=p.kind,  # type: ignore[arg-type]
        itemCount=p.item_count,
        languages=p.languages,
        choiceLists=p.choice_lists,
        variables=p.variables,
        diagnostics=p.diagnostics,
    )


@router.post(
    "/licensed",
    operation_id="composeLicensedBankItem",
    status_code=201,
    responses=errors(401, 403, 422),
)
def compose_licensed(body: ComposeLicensedRequest, auth: Auth, services: Services) -> BankItemOut:
    """Owner only. The lab's own copy of an instrument (pasted items) becomes a private
    `licensed-to-lab` bank item with the stub's scoring recipe; `attest` must be true
    (422 `bank.licensed_attestation` otherwise). Item lines must match the stub's count
    (422 `bank.stub_items`)."""
    return _item(
        services.builder.run(
            "bank.compose_licensed",
            auth.actor,
            items=body.items,
            attest=body.attest,
            stub_id=body.stubId,
            title=body.title,
            abbreviation=body.abbreviation,
            prefix=body.prefix,
            layout=body.layout,
            stem=body.stem,
            labels=body.labels,
            scale=None if body.scale is None else body.scale.model_dump(),
            scoring=None if body.scoring is None else body.scoring.model_dump(),
            description=body.description,
            tags=body.tags,
            language=body.language,
            tenant_id=body.tenantId,
        )
    )


@router.post("", operation_id="saveBankItem", status_code=201, responses=errors(401, 403, 404, 422))
def save_item(body: SaveBankItemRequest, auth: Auth, services: Services) -> BankSaveOut:
    """Save a question, page or block of a survey draft as a new bank item in that lab.
    422 with `bank.*` diagnostics when it can't be cut out or isn't a valid item."""
    return _saved(
        services.builder.run(
            "bank.save",
            auth.actor,
            survey_id=body.surveyId,
            target_id=body.targetId,
            title=body.title,
            abbreviation=body.abbreviation,
            description=body.description,
            tags=body.tags,
            licence=body.licence,
            citation=body.citation,
            scoring=body.scoring,
        )
    )


@router.post(
    "/import", operation_id="importBankFile", status_code=201, responses=errors(401, 403, 422)
)
def import_file(body: ImportBankFileRequest, auth: Auth, services: Services) -> BankImportOut:
    """Every item of the file becomes a new lab item (all or nothing)."""
    return _imported(
        services.builder.run(
            "bank.import",
            auth.actor,
            file=body.file,
            attest_licensed=body.attestLicensed,
            tenant_id=body.tenantId,
        )
    )


@router.get("/{item_id}", operation_id="getBankItem", responses=errors(401, 403, 404, 422))
def get_item(
    item_id: str,
    auth: Auth,
    services: Services,
    version: Annotated[int | None, Query(ge=1, description="Default: the current version")] = None,
    tenantId: str | None = None,
) -> BankItemOut:
    return _item(
        services.builder.run(
            "bank.get", auth.actor, item_id=item_id, version=version, tenant_id=tenantId
        )
    )


@router.get(
    "/{item_id}/versions", operation_id="listBankItemVersions", responses=errors(401, 403, 404, 422)
)
def list_versions(
    item_id: str, auth: Auth, services: Services, tenantId: str | None = None
) -> list[BankVersionOut]:
    return [
        _version(v)
        for v in services.builder.run(
            "bank.versions", auth.actor, item_id=item_id, tenant_id=tenantId
        )
    ]


@router.post(
    "/{item_id}/versions",
    operation_id="newBankItemVersion",
    status_code=201,
    responses=errors(401, 403, 404, 409, 422),
)
def new_version(
    item_id: str, body: NewVersionRequest, auth: Auth, services: Services
) -> BankSaveOut:
    """Version n+1 of the lab's own item from a survey target; metadata not given is kept."""
    return _saved(
        services.builder.run(
            "bank.new_version",
            auth.actor,
            item_id=item_id,
            survey_id=body.surveyId,
            target_id=body.targetId,
            title=body.title,
            abbreviation=body.abbreviation,
            description=body.description,
            tags=body.tags,
            licence=body.licence,
            citation=body.citation,
            scoring=body.scoring,
        )
    )


@router.patch(
    "/{item_id}", operation_id="updateBankItem", responses=errors(401, 403, 404, 409, 422)
)
def update_item(
    item_id: str, body: UpdateBankItemRequest, auth: Auth, services: Services
) -> BankItemOut:
    """Metadata only (title, abbreviation, description, tags); a field sent as null is
    cleared, a field not sent is kept. The fragment is version-bound."""
    fields = {k: getattr(body, k) for k in body.model_fields_set if k != "tenantId"}
    return _item(
        services.builder.run(
            "bank.update", auth.actor, item_id=item_id, fields=fields, tenant_id=body.tenantId
        )
    )


@router.post(
    "/{item_id}/share", operation_id="shareBankItem", responses=errors(401, 403, 404, 409, 422)
)
def share_item(
    item_id: str, body: ShareBankItemRequest, auth: Auth, services: Services
) -> BankItemOut:
    """Owner only. `host` shares with every lab on the host (unknown and licensed-to-lab
    items are refused: 422 `bank.not_shareable`); `lab` takes it back."""
    return _item(
        services.builder.run(
            "bank.share",
            auth.actor,
            item_id=item_id,
            visibility=body.visibility,
            licence_class=body.licenceClass,
            tenant_id=body.tenantId,
        )
    )


@router.delete(
    "/{item_id}",
    operation_id="deleteBankItem",
    status_code=204,
    responses=errors(401, 403, 404, 409, 422),
)
def delete_item(item_id: str, auth: Auth, services: Services, tenantId: str | None = None) -> None:
    services.builder.run("bank.delete", auth.actor, item_id=item_id, tenant_id=tenantId)


@router.get(
    "/{item_id}/export", operation_id="exportBankItem", responses=errors(401, 403, 404, 422)
)
def export_item(
    item_id: str,
    auth: Auth,
    services: Services,
    response: Response,
    version: Annotated[int | None, Query(ge=1)] = None,
    tenantId: str | None = None,
) -> BankFile:
    """The portable `*.osp-bank.json` file (one item, one version)."""
    file = services.builder.run(
        "bank.export", auth.actor, item_id=item_id, version=version, tenant_id=tenantId
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{item_id[:36]}.osp-bank.json"'
    return BankFile.model_validate(file)


@router.post(
    "/{item_id}/copy",
    operation_id="copyBankItem",
    status_code=201,
    responses=errors(401, 403, 404, 422),
)
def copy_item(
    item_id: str, body: CopyBankItemRequest, auth: Auth, services: Services
) -> BankItemOut:
    """An editable lab copy of a bundled or host-shared item, remembering its origin."""
    return _item(
        services.builder.run(
            "bank.copy", auth.actor, item_id=item_id, version=body.version, tenant_id=body.tenantId
        )
    )
