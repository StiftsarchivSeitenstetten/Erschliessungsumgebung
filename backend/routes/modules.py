"""Workspace module API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..models import User
from ..permissions import MODULE_FOTO_PAPIERABZUEGE
from .deps import require_module_access


router = APIRouter(prefix="/api/modules", tags=["modules"])


@router.get("/foto_papierabzuege")
def foto_papierabzuege_access(user: User = Depends(require_module_access(MODULE_FOTO_PAPIERABZUEGE))) -> dict[str, str]:
    return {"module": MODULE_FOTO_PAPIERABZUEGE, "user": user.username}
