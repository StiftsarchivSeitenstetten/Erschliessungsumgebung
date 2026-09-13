"""Workspace module API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..models import User
from ..modules import get_module
from ..permissions import has_module_access
from .deps import require_authenticated_user


router = APIRouter(prefix="/api/modules", tags=["modules"])


@router.get("/{module_key}")
def module_access(module_key: str, user: User = Depends(require_authenticated_user)) -> dict[str, object]:
    try:
        module = get_module(module_key)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arbeitsbereich nicht bekannt.") from exc
    if not has_module_access(user, module.access_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Arbeitsbereich nicht freigegeben.")
    return {**module.public_metadata(), "user": user.username}
