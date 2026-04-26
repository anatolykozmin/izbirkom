import logging
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings

log = logging.getLogger(__name__)


async def send_otp_email(to_addr: str, code: str) -> None:
    settings = get_settings()
    body = (
        "Здравствуйте!\n\n"
        f"Ваш код подтверждения для голосования в студенческом совете: {code}\n\n"
        "Код действителен ограниченное время. Если вы не запрашивали код, проигнорируйте это письмо.\n"
    )
    if settings.email_debug:
        # SMTP не вызывается — код только в логах терминала (удобно для отладки).
        log.warning("EMAIL_DEBUG: OTP для %s: %s", to_addr, code)
        print(
            "\n=== IZBIRKOM: EMAIL_DEBUG — SMTP отключён, смотрите код ниже ===\n"
            f"Кому: {to_addr}\n"
            f"Код:  {code}\n"
            "================================================================\n",
            flush=True,
        )
        return

    msg = EmailMessage()
    msg["Subject"] = "Код подтверждения — студенческий совет"
    msg["From"] = settings.smtp_from
    msg["To"] = to_addr
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=settings.smtp_use_tls,
    )
