from pydantic import BaseModel, EmailStr, Field


class RequestCodeBody(BaseModel):
    email: EmailStr


class VerifyBody(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)


class VoteBody(BaseModel):
    candidate_id: int = Field(ge=1, le=2)
