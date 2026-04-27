import re

from pydantic import BaseModel, EmailStr, Field, field_validator

# Допустимые форматы: 123456@edu.fa.ru или 1234567@edu.fa.ru
_ALLOWED_EMAIL_RE = re.compile(r"^\d{6,7}@edu\.fa\.ru$", re.IGNORECASE)


def _validate_corp_email(value: str) -> str:
    if not _ALLOWED_EMAIL_RE.match(value.strip()):
        raise ValueError(
            "Принимаются только корпоративные адреса вида 123456@edu.fa.ru или 1234567@edu.fa.ru"
        )
    return value.strip().lower()


class RequestCodeBody(BaseModel):
    email: EmailStr

    @field_validator("email", mode="after")
    @classmethod
    def check_corp_email(cls, v: str) -> str:
        return _validate_corp_email(v)


class VerifyBody(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)

    @field_validator("email", mode="after")
    @classmethod
    def check_corp_email(cls, v: str) -> str:
        return _validate_corp_email(v)


class VoteBody(BaseModel):
    candidate_id: int = Field(ge=1, le=100)
