from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.errors import ApiError
from app.core.middleware import PrivateResponseMiddleware
from app.core.security import verify_dummy_password
from app.db.session import engine
from app.services.auth_rate_limit import redis_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.validate_auth()
    await verify_dummy_password("startup-prewarm")
    try:
        yield
    finally:
        await redis_client.aclose()
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="面向知识型内容创作者的个性化可信多智能体创作平台 API",
    debug=settings.debug,
    lifespan=lifespan,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None if settings.environment == "production" else "/redoc",
    openapi_url=None if settings.environment == "production" else "/openapi.json",
)

app.add_middleware(PrivateResponseMiddleware, api_prefix=settings.api_v1_prefix)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.auth_host_list)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
        headers={"Cache-Control": "no-store", **exc.headers},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = []
    for error in exc.errors():
        location = error.get("loc", ())
        field = location[1] if len(location) > 1 else "request"
        safe_field = (
            field
            if field
            in {
                "username",
                "password",
                "current_password",
                "new_password",
                "title",
                "content",
                "role",
                "conversation_id",
            }
            else "request"
        )
        fields.append({"field": safe_field, "message": "字段格式不正确或存在不允许的字段"})
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "请求格式不正确", "details": fields},
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_: Request, __: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "code": "AUTH_DEPENDENCY_UNAVAILABLE",
            "message": "数据服务暂时不可用",
            "details": [],
        },
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    codes = {404: "RESOURCE_NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": codes.get(exc.status_code, "REQUEST_FAILED"),
            "message": exc.detail if isinstance(exc.detail, str) else "请求失败",
            "details": [],
        },
        headers=exc.headers,
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health",
    }
