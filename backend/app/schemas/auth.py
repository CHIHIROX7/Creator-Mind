from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.core.security import normalize_username, validate_password


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str


class SessionOut(BaseModel):
    expires_at: datetime


class IdentityOut(BaseModel):
    user: UserOut
    session: SessionOut


class CsrfOut(BaseModel):
    csrf_token: str
    expires_at: datetime


class LoginOut(IdentityOut):
    csrf_token: str
    csrf_expires_at: datetime


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_login(cls, value: str) -> str:
        return normalize_username(value)


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=15, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: SecretStr) -> SecretStr:
        validate_password(value.get_secret_value())
        return value
