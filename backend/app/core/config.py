from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_prefix="CREATORMIND_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "CreatorMind API"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "change-me-in-production"
    cors_origins: str = "http://localhost:5173"
    auth_secret_key: SecretStr = SecretStr("")
    auth_session_ttl_seconds: int = Field(default=28800, ge=60)
    auth_csrf_ttl_seconds: int = Field(default=1800, ge=60)
    auth_trusted_origins: str = "http://localhost:5173"
    auth_trusted_hosts: str = "localhost,127.0.0.1,[::1]"
    auth_login_ip_limit: int = Field(default=10, ge=1)
    auth_login_ip_window: int = Field(default=600, ge=1)
    auth_login_failure_limit: int = Field(default=5, ge=1)
    auth_login_failure_window: int = Field(default=900, ge=1)

    @property
    def auth_origin_list(self) -> list[str]:
        return [item.strip() for item in self.auth_trusted_origins.split(",") if item.strip()]

    @property
    def auth_host_list(self) -> list[str]:
        return [item.strip() for item in self.auth_trusted_hosts.split(",") if item.strip()]

    @property
    def auth_cookie_secure(self) -> bool:
        return self.environment == "production"

    @property
    def session_cookie_name(self) -> str:
        return "__Host-cm_session" if self.auth_cookie_secure else "cm_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "__Host-cm_csrf" if self.auth_cookie_secure else "cm_csrf"

    def validate_auth(self) -> None:
        key = self.auth_secret_key.get_secret_value()
        if len(key.encode("utf-8")) < 32 or len(set(key)) < 12:
            raise ValueError("CREATORMIND_AUTH_SECRET_KEY 必须是至少 32 字节的随机密钥")
        if not self.auth_origin_list or set(self.auth_origin_list) != set(self.cors_origin_list):
            raise ValueError("认证来源必须非空且与 CORS 来源一致")
        for origin in self.auth_origin_list:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
            ):
                raise ValueError("认证来源必须是明确的 HTTP/HTTPS Origin，不支持通配符")
            if self.environment == "production" and parsed.scheme != "https":
                raise ValueError("生产认证来源必须使用 HTTPS")
        if not self.auth_host_list or any("*" in host for host in self.auth_host_list):
            raise ValueError("认证 Host 必须明确配置，不支持通配符")
        if self.environment == "production" and self.debug:
            raise ValueError("生产环境禁止启用 debug")

    database_url: str = (
        "postgresql+asyncpg://creatormind:creatormind_dev@localhost:5433/creatormind"
    )
    redis_url: str = "redis://localhost:6382/0"
    celery_broker_url: str = "redis://localhost:6382/1"
    celery_result_backend: str = "redis://localhost:6382/2"

    s3_endpoint_url: str = "http://localhost:19000"
    s3_access_key: str = "creatormind"
    s3_secret_key: str = "creatormind_dev_secret"
    s3_bucket: str = "creatormind"

    llm_provider: str = "openai-compatible"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen3"
    llm_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
