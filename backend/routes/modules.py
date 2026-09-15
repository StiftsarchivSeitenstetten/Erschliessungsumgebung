"""Workspace module API routes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ..github.errors import RepositoryConflictError, RepositoryError, RepositoryNotFoundError
from ..github.repository import DataRepository
from ..models import User
from ..modules import get_module, list_modules
from ..permissions import has_module_access
from ..records.generic_read import list_generic_records, list_values_for_role, read_generic_record
from ..records.generic_write import create_generic_record, update_generic_record
from ..records.identity import reserve_generic_identity
from ..records.module_index import index_path, query_index, read_module_index
from ..records.runtime import RecordPermissionError, RecordRuntime, RecordUnknownFieldError, RecordValidationError
from ..vocabularies import (
    VocabularyError,
    VocabularyPermissionError,
    VocabularyTermExistsError,
    VocabularyTermNotFound,
    VocabularyValidationError,
    add_term,
    deactivate_term,
    load_vocabulary,
    read_repository_vocabulary,
    rename_term,
)
from .deps import require_authenticated_user, require_csrf
from .records import get_data_repository


router = APIRouter(prefix="/api/modules", tags=["modules"])
vocabulary_router = APIRouter(prefix="/api/vocabularies", tags=["vocabularies"])


class GenericUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: dict[str, Any] = Field(default_factory=dict)
    base_revision: str | None = None


class GenericCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    record: dict[str, Any] = Field(default_factory=dict)
    identity: dict[str, Any] | None = None


class IdentityReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    record: dict[str, Any] = Field(default_factory=dict)


class VocabularyTermRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    active: bool = True
    description: str | None = None
    aliases: list[str] | None = None
    sort_order: int | None = None


class VocabularyAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: str
    term: VocabularyTermRequest


class VocabularyPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: str
    label: str | None = None
    active: bool | None = None


def require_generic_write_enabled(request: Request) -> None:
    if not getattr(request.app.state, "generic_writes_enabled", False):
        raise HTTPException(status_code=503, detail="Generische Schreib-API ist noch nicht freigeschaltet.")


def write_response(stored, module, user: User) -> dict[str, object]:
    return {
        "module": module.access_key,
        "record_id": stored.record_id,
        "record": RecordRuntime(module).filter_for_view(stored.data, user.role),
        "meta": {"revision": stored.revision},
    }


def raise_write_error(exc: Exception) -> None:
    if isinstance(exc, RecordUnknownFieldError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, RecordPermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, RecordValidationError):
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    if isinstance(exc, RepositoryConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, RepositoryNotFoundError):
        raise HTTPException(status_code=404, detail="Datensatz nicht gefunden.") from exc
    if isinstance(exc, RepositoryError):
        raise HTTPException(status_code=500, detail="Datensatz konnte nicht gespeichert werden.") from exc
    raise exc


def load_authorized_module(module_key: str, user: User):
    try:
        module = get_module(module_key)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arbeitsbereich nicht bekannt.") from exc
    if not has_module_access(user, module.access_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Arbeitsbereich nicht freigegeben.")
    return module


@router.get("")
def module_catalog(user: User = Depends(require_authenticated_user)) -> list[dict[str, object]]:
    modules = [
        module.catalog_metadata()
        for module in list_modules()
        if has_module_access(user, module.access_key)
    ]
    modules.sort(key=lambda item: (item.get("order") if item.get("order") is not None else 1000, item["label"]))
    return modules


def vocabulary_reference(vocabulary_id: str) -> dict[str, str]:
    references = [module.vocabularies[vocabulary_id] for module in list_modules() if vocabulary_id in module.vocabularies]
    if not references:
        raise HTTPException(status_code=404, detail="Vokabular nicht gefunden.")
    return references[0]


def vocabulary_response(stored) -> dict[str, object]:
    return {
        "vocabulary": stored.vocabulary.descriptor(),
        "meta": {"revision": stored.revision},
    }


def raise_vocabulary_write_error(exc: Exception) -> None:
    if isinstance(exc, VocabularyPermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, VocabularyTermNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (VocabularyTermExistsError, RepositoryConflictError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, VocabularyValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, RepositoryNotFoundError):
        raise HTTPException(status_code=404, detail="Vokabular nicht im Datenrepository gefunden.") from exc
    if isinstance(exc, RepositoryError):
        raise HTTPException(status_code=500, detail="Vokabular konnte nicht gespeichert werden.") from exc
    raise exc


@vocabulary_router.get("/{vocabulary_id}")
def vocabulary_access(
    vocabulary_id: str,
    user: User = Depends(require_authenticated_user),
    repository: DataRepository = Depends(get_data_repository),
) -> dict[str, object]:
    reference = vocabulary_reference(vocabulary_id)
    try:
        try:
            stored = read_repository_vocabulary(repository, reference["repository_path"], vocabulary_id)
            vocabulary = stored.vocabulary
            revision = stored.revision
        except RepositoryNotFoundError:
            vocabulary = load_vocabulary(reference["path"], vocabulary_id)
            content = Path(reference["path"]).read_text(encoding="utf-8").encode("utf-8")
            revision = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if not vocabulary.allows(user.role, "use"):
            raise HTTPException(status_code=403, detail="Keine Berechtigung fuer dieses Vokabular.")
        return {**vocabulary.descriptor(), "meta": {"revision": revision}}
    except VocabularyError as exc:
        raise HTTPException(status_code=500, detail="Vokabular ist ungueltig.") from exc
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail="Vokabular ist derzeit nicht verfuegbar.") from exc


@vocabulary_router.post(
    "/{vocabulary_id}/terms",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def add_vocabulary_term(
    vocabulary_id: str,
    payload: VocabularyAddRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
) -> dict[str, object]:
    reference = vocabulary_reference(vocabulary_id)
    term = payload.term.model_dump(exclude_none=True)
    try:
        stored = add_term(
            get_data_repository(request), reference["repository_path"], vocabulary_id,
            payload.base_revision, user.role, term,
        )
    except (VocabularyError, RepositoryError) as exc:
        raise_vocabulary_write_error(exc)
    return vocabulary_response(stored)


@vocabulary_router.patch(
    "/{vocabulary_id}/terms/{term_id}",
    dependencies=[Depends(require_csrf)],
)
def patch_vocabulary_term(
    vocabulary_id: str,
    term_id: str,
    payload: VocabularyPatchRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
) -> dict[str, object]:
    reference = vocabulary_reference(vocabulary_id)
    try:
        if payload.label is not None and payload.active is None:
            stored = rename_term(
                get_data_repository(request), reference["repository_path"], vocabulary_id,
                payload.base_revision, user.role, term_id, payload.label,
            )
        elif payload.label is None and payload.active is False:
            stored = deactivate_term(
                get_data_repository(request), reference["repository_path"], vocabulary_id,
                payload.base_revision, user.role, term_id,
            )
        else:
            raise VocabularyValidationError("PATCH muss genau Label-Aenderung oder active=false enthalten.")
    except (VocabularyError, RepositoryError) as exc:
        raise_vocabulary_write_error(exc)
    return vocabulary_response(stored)


@router.get("/{module_key}/records")
def list_module_records(
    module_key: str,
    q: str = "",
    lookup_field: str | None = None,
    lookup_value: str | None = None,
    user: User = Depends(require_authenticated_user),
    repository: DataRepository = Depends(get_data_repository),
) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    runtime = RecordRuntime(module, repository)
    try:
        if index_path(module):
            index = read_module_index(repository, module)
            try:
                items = query_index(module, index, user.role, q=q, lookup_field=lookup_field, lookup_value=lookup_value)
            except RecordValidationError as exc:
                raise HTTPException(status_code=422, detail=exc.errors) from exc
            return {"module": module.access_key, "records": items}
        if q or lookup_field is not None or lookup_value is not None:
            raise HTTPException(status_code=422, detail="Suche benoetigt einen konfigurierten Modulindex.")
        records = list_generic_records(repository, module)
        items = []
        for stored in records:
            runtime.validate(stored.data)
            items.append({
                "record_id": stored.record_id,
                "values": list_values_for_role(stored.data, module, user.role),
                "meta": {"revision": stored.revision},
            })
    except RecordValidationError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=exc.errors) from exc
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail="Modulindex nicht verfuegbar; Rebuild erforderlich.") from exc
    return {"module": module.access_key, "records": items}


@router.get("/{module_key}/records/{record_id}")
def get_module_record(
    module_key: str,
    record_id: str,
    user: User = Depends(require_authenticated_user),
    repository: DataRepository = Depends(get_data_repository),
) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    runtime = RecordRuntime(module, repository)
    try:
        stored = read_generic_record(repository, module, record_id)
        runtime.validate(stored.data)
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Datensatz nicht gefunden.") from exc
    except RecordValidationError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=exc.errors) from exc
    return {
        "module": module.access_key,
        "record_id": stored.record_id,
        "record": runtime.filter_for_view(stored.data, user.role),
        "meta": {"revision": stored.revision},
    }


@router.post(
    "/{module_key}/records",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_module_record(
    module_key: str,
    payload: GenericCreateRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    require_generic_write_enabled(request)
    provider = getattr(request.app.state, "generic_server_values_provider", None)
    try:
        defaults = provider(module, user, payload.record) if provider else {}
        stored = create_generic_record(
            get_data_repository(request), module, payload.record, user, defaults,
            operation_id=payload.operation_id, reserved_identity=payload.identity,
        )
    except (RecordPermissionError, RecordValidationError, RepositoryError) as exc:
        raise_write_error(exc)
    return {**write_response(stored, module, user), "operation_id": payload.operation_id}


@router.post(
    "/{module_key}/reservations",
    dependencies=[Depends(require_csrf)],
)
def reserve_module_identity(
    module_key: str,
    payload: IdentityReservationRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    require_generic_write_enabled(request)
    try:
        RecordRuntime(module).filter_for_edit(payload.record, user.role)
        reservation = reserve_generic_identity(
            get_data_repository(request), module, payload.operation_id, payload.record,
        )
    except (RecordPermissionError, RecordValidationError, RepositoryError) as exc:
        raise_write_error(exc)
    return {
        "module": module.access_key,
        "operation_id": reservation.operation_id,
        "record_id": reservation.record_id,
        "identity": reservation.identity,
    }


@router.put(
    "/{module_key}/records/{record_id}",
    dependencies=[Depends(require_csrf)],
)
def update_module_record(
    module_key: str,
    record_id: str,
    payload: GenericUpdateRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    require_generic_write_enabled(request)
    try:
        stored = update_generic_record(get_data_repository(request), module, record_id, payload.record, payload.base_revision or "", user)
    except (RecordPermissionError, RecordValidationError, RepositoryError) as exc:
        raise_write_error(exc)
    return write_response(stored, module, user)


@router.get("/{module_key}")
def module_access(
    module_key: str,
    user: User = Depends(require_authenticated_user),
    repository: DataRepository = Depends(get_data_repository),
) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    return {
        **module.descriptor_for_role(user.role),
        "empty_record": RecordRuntime(module, repository).empty_record(user.role),
        "user": user.username,
    }
