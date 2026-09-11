"""Photo record API backed by the configured data repository."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..github.errors import RepositoryConflictError, RepositoryNotFoundError
from ..github.github_repository import GitHubDataRepository
from ..github.repository import DataRepository, InMemoryGitRepository
from ..models import User
from ..permissions import MODULE_FOTO_PAPIERABZUEGE
from ..records.photos import (
    RecordPermissionError,
    RecordRevisionConflictError,
    RecordValidationError,
    create_photo_record,
    find_photo_by_signature,
    list_photo_records,
    read_photo_record,
    update_photo_record,
)
from .deps import get_app_settings, require_authenticated_user, require_csrf, require_module_access


router = APIRouter(prefix="/api/records/photos", tags=["photo-records"])


class PhotoRecordPayload(BaseModel):
    format: str | None = None
    erschliessung: dict = Field(default_factory=dict)
    korrespondenzstueck: bool = False
    datierung: dict = Field(default_factory=dict)
    base_revision: str | None = None


def get_data_repository(request: Request) -> DataRepository:
    repository = getattr(request.app.state, "data_repository", None)
    if repository is not None:
        return repository
    settings = get_app_settings()
    try:
        repository = GitHubDataRepository(settings)
    except RuntimeError:
        repository = InMemoryGitRepository()
    request.app.state.data_repository = repository
    return repository


def record_response(stored) -> dict:
    return {"record": stored.data, "base_revision": stored.revision}


@router.get("", dependencies=[Depends(require_module_access(MODULE_FOTO_PAPIERABZUEGE))])
def list_photos(repository: DataRepository = Depends(get_data_repository)) -> dict:
    return {
        "records": [
            {
                "id": entry.get("id"),
                "signatur": entry.get("signatur"),
                "format": entry.get("format"),
                "nummer": entry.get("nummer"),
                "zusatz": entry.get("zusatz"),
            }
            for entry in list_photo_records(repository)
        ]
    }


@router.get("/signatures/{signature}", dependencies=[Depends(require_module_access(MODULE_FOTO_PAPIERABZUEGE))])
def get_photo_by_signature(signature: str, repository: DataRepository = Depends(get_data_repository)) -> dict:
    try:
        return record_response(find_photo_by_signature(repository, signature))
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Datensatz nicht gefunden.") from exc


@router.get("/{record_id}", dependencies=[Depends(require_module_access(MODULE_FOTO_PAPIERABZUEGE))])
def get_photo(record_id: str, repository: DataRepository = Depends(get_data_repository)) -> dict:
    try:
        return record_response(read_photo_record(repository, record_id))
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Datensatz nicht gefunden.") from exc


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf), Depends(require_module_access(MODULE_FOTO_PAPIERABZUEGE))],
)
def create_photo(
    payload: PhotoRecordPayload,
    user: User = Depends(require_authenticated_user),
    repository: DataRepository = Depends(get_data_repository),
) -> dict:
    try:
        stored = create_photo_record(repository, payload.model_dump(), user)
        return record_response(stored)
    except RecordValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except RepositoryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put(
    "/{record_id}",
    dependencies=[Depends(require_csrf), Depends(require_module_access(MODULE_FOTO_PAPIERABZUEGE))],
)
def update_photo(
    record_id: str,
    payload: PhotoRecordPayload,
    user: User = Depends(require_authenticated_user),
    repository: DataRepository = Depends(get_data_repository),
) -> dict:
    try:
        stored = update_photo_record(repository, record_id, payload.model_dump(), user)
        return record_response(stored)
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Datensatz nicht gefunden.") from exc
    except RecordPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RecordRevisionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RecordValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
