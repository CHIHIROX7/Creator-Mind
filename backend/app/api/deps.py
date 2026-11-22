from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.csrf import require_csrf
from app.db.session import get_db
from app.services.auth import Identity, authenticate

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def current_identity(request: Request, db: DbSession) -> Identity:
    return await authenticate(db, request.cookies.get(settings.session_cookie_name))


CurrentIdentity = Annotated[Identity, Depends(current_identity)]
CsrfProtected = Depends(require_csrf)
