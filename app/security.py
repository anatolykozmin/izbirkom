import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.config import Settings, get_settings

MAX_OTP_ATTEMPTS = 8

def normalize_email(email: str) -> str:
    return email.strip().lower()


def generate_otp(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def _otp_hmac(email: str, code: str, settings: Settings) -> str:
    msg = f"{normalize_email(email)}:{code}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


def hash_otp(email: str, code: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return _otp_hmac(email, code, s)


def verify_otp(email: str, plain_code: str, stored_hex: str, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    expected = _otp_hmac(email, plain_code, s)
    return hmac.compare_digest(expected, stored_hex)


def create_access_token(email: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=s.access_token_expire_minutes)
    payload = {"sub": email, "exp": expire}
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_access_token(token: str, settings: Settings | None = None) -> str | None:
    s = settings or get_settings()
    try:
        data = jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
        sub = data.get("sub")
        if isinstance(sub, str):
            return sub
    except jwt.PyJWTError:
        return None
    return None
