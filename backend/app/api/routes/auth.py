from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import CurrentIdentity, DbSession
from app.core.config import settings
from app.core.csrf import (
    check_origin,
    clear_auth_cookies,
    issue_csrf,
    require_csrf,
    set_auth_cookie,
)
from app.schemas.auth import (
    CsrfOut,
    IdentityOut,
    LoginIn,
    LoginOut,
    PasswordIn,
    SessionOut,
    UserOut,
)
from app.services import auth as service

router = APIRouter(prefix="/auth", tags=["auth"])


def identity_out(identity: service.Identity) -> IdentityOut:
    return IdentityOut(
        user=UserOut.model_validate(identity.user),
        session=SessionOut(expires_at=identity.session.expires_at),
    )


def login_out(response: Response, identity: service.Identity, token: str) -> LoginOut:
    set_auth_cookie(response, settings.session_cookie_name, token)
    csrf_token, csrf_expires_at = issue_csrf(response, token)
    return LoginOut(
        **identity_out(identity).model_dump(),
        csrf_token=csrf_token,
        csrf_expires_at=csrf_expires_at,
    )


@router.get("/csrf", response_model=CsrfOut)
async def csrf(request: Request, response: Response) -> CsrfOut:
    check_origin(request, allow_referer=True)
    token, expires_at = issue_csrf(response, request.cookies.get(settings.session_cookie_name))
    return CsrfOut(csrf_token=token, expires_at=expires_at)


@router.post("/login", response_model=LoginOut, dependencies=[Depends(require_csrf)])
async def login(payload: LoginIn, request: Request, response: Response, db: DbSession) -> LoginOut:
    identity, token = await service.login(
        db,
        payload.username,
        payload.password.get_secret_value(),
        request.cookies.get(settings.session_cookie_name),
        request.client.host if request.client else "unknown",
    )
    return login_out(response, identity, token)


@router.get("/me", response_model=IdentityOut)
async def me(identity: CurrentIdentity, response: Response) -> IdentityOut:
    response.headers["Cache-Control"] = "no-store"
    return identity_out(identity)


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
async def logout(request: Request, db: DbSession) -> Response:
    await service.logout(db, request.cookies.get(settings.session_cookie_name))
    response = Response(status_code=204)
    clear_auth_cookies(response)
    return response


@router.post("/password", response_model=LoginOut, dependencies=[Depends(require_csrf)])
async def password(
    payload: PasswordIn, request: Request, response: Response, db: DbSession
) -> LoginOut:
    identity, token = await service.change_password(
        db,
        request.cookies.get(settings.session_cookie_name),
        payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(),
    )
    return login_out(response, identity, token)
