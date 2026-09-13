"""Workspace module API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..github.errors import RepositoryNotFoundError
from ..github.repository import DataRepository
from ..models import User
from ..modules import get_module, list_modules
from ..permissions import has_module_access
from ..records.generic_read import list_generic_records, list_values_for_role, read_generic_record
from ..records.runtime import RecordRuntime, RecordValidationError
from .deps import require_authenticated_user
from .records import get_data_repository


router = APIRouter(prefix="/api/modules", tags=["modules"])


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


@router.get("/{module_key}")
def module_access(module_key: str, user: User = Depends(require_authenticated_user)) -> dict[str, object]:
    module = load_authorized_module(module_key, user)
    return {**module.descriptor_for_role(user.role), "user": user.username}
