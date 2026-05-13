import re

from pydantic import BaseModel, EmailStr, Field, field_validator

# Допустимые форматы: что-угодно@edu.fa.ru или что-угодно@fa.ru
_ALLOWED_EMAIL_RE = re.compile(r"^.+@(edu\.fa\.ru|fa\.ru)$", re.IGNORECASE)


def _validate_corp_email(value: str) -> str:
    if not _ALLOWED_EMAIL_RE.match(value.strip()):
        raise ValueError(
            "Принимаются только адреса @edu.fa.ru или @fa.ru"
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
