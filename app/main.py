import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import Base, engine, get_session
from app.email_service import send_otp_email
from app.models import OTPChallenge, Vote
from app.schemas import RequestCodeBody, VerifyBody, VoteBody
from app.security import (
    MAX_OTP_ATTEMPTS,
    create_access_token,
    decode_access_token,
    generate_otp,
    hash_otp,
    normalize_email,
    verify_otp,
)

log = logging.getLogger(__name__)

CANDIDATES = (
    {"id": 1, "name": "Фёдор Жаркевич", "note": ""},
    {"id": 2, "name": "Против всех", "note": ""},
)

COOKIE_NAME = "session"
BASE_DIR = Path(__file__).resolve().parent

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Студенческий совет — голосование", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    return response

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def get_token_from_request(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


async def require_voter(request: Request) -> str:
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Требуется вход")
    email = decode_access_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="Сессия недействительна")
    return email


@app.get("/", response_class=HTMLResponse)
async def page_home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "candidates": CANDIDATES},
    )


@app.get("/verify", response_class=HTMLResponse)
async def page_verify(request: Request):
    return templates.TemplateResponse("verify.html", {"request": request})


@app.get("/ballot", response_class=HTMLResponse)
async def page_ballot(request: Request, session: AsyncSession = Depends(get_session)):
    token = get_token_from_request(request)
    email = decode_access_token(token) if token else None
    if not email:
        return RedirectResponse(url="/", status_code=302)
    result = await session.execute(select(Vote).where(Vote.email == email))
    existing = result.scalar_one_or_none()
    return templates.TemplateResponse(
        "ballot.html",
        {
            "request": request,
            "candidates": CANDIDATES,
            "already_voted": existing is not None,
            "voted_for": existing.candidate_id if existing else None,
        },
    )


@app.post("/api/request-code")
@limiter.limit("5/minute")
async def api_request_code(
    request: Request,
    body: RequestCodeBody,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    email = normalize_email(str(body.email))
    code = generate_otp(settings.otp_length)
    code_hash = hash_otp(email, code, settings)
    expires = datetime.now(UTC) + timedelta(minutes=settings.otp_expire_minutes)

    

    result = await session.execute(select(OTPChallenge).where(OTPChallenge.email == email))
    row = result.scalar_one_or_none()
    if row:
        row.code_hash = code_hash
        row.expires_at = expires
        row.attempts = 0
    else:
        session.add(OTPChallenge(email=email, code_hash=code_hash, expires_at=expires))
    await session.commit()

    background_tasks.add_task(send_otp_email, email, code)
    return {"ok": True, "message": "Код отправлен на указанный адрес."}


@app.post("/api/verify")
@limiter.limit("20/minute")
async def api_verify(
    request: Request,
    response: Response,
    body: VerifyBody,
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    email = normalize_email(str(body.email))
    code = body.code.strip().replace(" ", "")

    result = await session.execute(select(OTPChallenge).where(OTPChallenge.email == email))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=400, detail="Сначала запросите код")

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        await session.delete(row)
        await session.commit()
        raise HTTPException(status_code=400, detail="Код истёк, запросите новый")

    if row.attempts >= MAX_OTP_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Слишком много попыток, запросите новый код")

    row.attempts += 1
    await session.commit()

    if not verify_otp(email, code, row.code_hash, settings):
        raise HTTPException(status_code=400, detail="Неверный код")

    await session.delete(row)
    await session.commit()

    token = create_access_token(email, settings)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return {"ok": True}


@app.post("/api/vote")
@limiter.limit("30/minute")
async def api_vote(
    request: Request,
    body: VoteBody,
    session: AsyncSession = Depends(get_session),
    voter_email: str = Depends(require_voter),
):
    if body.candidate_id not in {c["id"] for c in CANDIDATES}:
        raise HTTPException(status_code=400, detail="Некорректный кандидат")

    result = await session.execute(select(Vote).where(Vote.email == voter_email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Вы уже голосовали")

    session.add(Vote(email=voter_email, candidate_id=body.candidate_id))
    await session.commit()
    return {"ok": True}


@app.post("/api/logout")
async def api_logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


# ── Admin ────────────────────────────────────────────────────────────────────

ADMIN_COOKIE = "admin_session"


def _check_admin(request: Request) -> bool:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return False
    settings = get_settings()
    expected = hmac.new(
        settings.secret_key.encode(), b"admin", hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(token, expected)


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if _check_admin(request):
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": None})


@app.post("/admin/login", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def admin_login_post(request: Request, response: Response, password: str = Form(...)):
    settings = get_settings()
    if hmac.compare_digest(password, settings.admin_password):
        token = hmac.new(settings.secret_key.encode(), b"admin", hashlib.sha256).hexdigest()
        response = RedirectResponse(url="/admin", status_code=302)
        response.set_cookie(
            ADMIN_COOKIE,
            token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=3600,
        )
        return response
    return templates.TemplateResponse(
        "admin_login.html", {"request": request, "error": "Неверный пароль"}, status_code=401
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, session: AsyncSession = Depends(get_session)):
    if not _check_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)

    total = await session.scalar(select(func.count()).select_from(Vote))
    rows = await session.execute(
        select(Vote.candidate_id, func.count(Vote.id).label("cnt"))
        .group_by(Vote.candidate_id)
    )
    counts = {row.candidate_id: row.cnt for row in rows}

    def votes_label(n: int) -> str:
        if 11 <= n % 100 <= 14:
            return "голосов"
        r = n % 10
        if r == 1:
            return "голос"
        if 2 <= r <= 4:
            return "голоса"
        return "голосов"

    results = [
        {
            "id": c["id"],
            "name": c["name"],
            "votes": counts.get(c["id"], 0),
            "pct": round(counts.get(c["id"], 0) / total * 100) if total else 0,
            "votes_label": votes_label(counts.get(c["id"], 0)),
        }
        for c in CANDIDATES
    ]
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "results": results, "total": total},
    )


@app.post("/admin/logout")
async def admin_logout(response: Response):
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return RedirectResponse(url="/admin/login", status_code=302)
