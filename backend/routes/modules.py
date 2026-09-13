"""Workspace module API routes."""

from __future__ import annotations

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
from ..records.runtime import RecordPermissionError, RecordRuntime, RecordUnknownFieldError, RecordValidationError
from .deps import require_authenticated_user, require_csrf
from .records import get_data_repository


router = APIRouter(prefix="/api/modules", tags=["modules"])


class GenericRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: dict[str, Any] = Field(default_factory=dict)
    base_revision: str | None = None


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


@router.get("/{module_key}/records")
def list_module_records(
    module_key: str,
    user: User = Depends(require_authenticated_user),
    repository: DataRepository = Depends(get_data_repository),
) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    runtime = RecordRuntime(module)
    try:
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
    return {"module": module.access_key, "records": items}


@router.get("/{module_key}/records/{record_id}")
def get_module_record(
    module_key: str,
    record_id: str,
    user: User = Depends(require_authenticated_user),
    repository: DataRepository = Depends(get_data_repository),
) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    runtime = RecordRuntime(module)
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
    payload: GenericRecordRequest,
    request: Request,
    user: User = Depends(require_authenticated_user),
) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    require_generic_write_enabled(request)
    if payload.base_revision is not None:
        raise HTTPException(status_code=422, detail="base_revision ist nur fuer PUT vorgesehen.")
    provider = getattr(request.app.state, "generic_server_values_provider", None)
    try:
        defaults = provider(module, user, payload.record) if provider else {}
        stored = create_generic_record(get_data_repository(request), module, payload.record, user, defaults)
    except (RecordPermissionError, RecordValidationError, RepositoryError) as exc:
        raise_write_error(exc)
    return write_response(stored, module, user)


@router.put(
    "/{module_key}/records/{record_id}",
    dependencies=[Depends(require_csrf)],
)
def update_module_record(
    module_key: str,
    record_id: str,
    payload: GenericRecordRequest,
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
def module_access(module_key: str, user: User = Depends(require_authenticated_user)) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    return {**module.descriptor_for_role(user.role), "user": user.username}
