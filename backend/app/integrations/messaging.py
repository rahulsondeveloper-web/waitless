"""SMS, WhatsApp and e-mail behind one interface (PRD §25, decision D28).

Providers (set in .env):
- SMS: `console` (log only, development) · `msg91` (India; OTP API with a DLT-approved template) · `twilio`
- WhatsApp: `console` · `twilio` · `meta` (WhatsApp Cloud API)
- E-mail: `console` · `smtp`

Sending never raises into the caller: a failed message is logged with the provider's answer, and the
request that caused it (a booking, an order) still succeeds. OTP sending is the exception — the caller needs
to know, so `send_otp` raises a friendly 503.
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import get_settings
from app.core.errors import AppError

log = logging.getLogger("waitless.messaging")
_transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def _mask(phone: str) -> str:
    return phone[:-4] + "****" if len(phone) > 4 else "****"


def _client(**kw) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(timeout=10, transport=_transport, **kw)


# ---------- SMS ----------


async def send_otp(phone: str, code: str) -> None:
    """Sign-in code by SMS. Raises 503 when the provider refuses (the guest can retry)."""
    s = get_settings()
    text = f"{code} is your WaitLess code. It expires in {s.otp_ttl_seconds // 60} minutes. Never share it."
    if s.sms_provider == "console":
        log.info("SMS (console) to %s: one-time code", _mask(phone))
        return
    try:
        if s.sms_provider == "msg91":
            async with _client() as c:
                r = await c.post(
                    "https://control.msg91.com/api/v5/otp",
                    params={"template_id": s.msg91_otp_template_id, "mobile": phone.lstrip("+"), "otp": code},
                    headers={"authkey": s.msg91_auth_key},
                )
        else:
            r = await _twilio_message(phone, text, whatsapp=False)
        r.raise_for_status()
        log.info("OTP sent via %s to %s", s.sms_provider, _mask(phone))
    except Exception as exc:
        log.error("OTP via %s failed for %s: %s", s.sms_provider, _mask(phone), exc)
        raise AppError(
            "We could not send the code right now. Please try again.", code="SMS_FAILED", status_code=503
        ) from exc


async def _twilio_message(phone: str, text: str, *, whatsapp: bool) -> httpx.Response:
    s = get_settings()
    sender = s.twilio_whatsapp_from if whatsapp else s.twilio_sms_from
    to = f"whatsapp:{phone}" if whatsapp else phone
    async with _client(auth=(s.twilio_account_sid, s.twilio_auth_token)) as c:
        return await c.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
            data={"From": sender, "To": to, "Body": text},
        )


async def send_text(phone: str, text: str) -> str:
    """A notification to a phone: WhatsApp when configured, else SMS (Twilio), else the log.

    Returns the channel used. MSG91 generic SMS needs a DLT template per message in India,
    so with MSG91 notifications go to WhatsApp or the log; OTPs still go by SMS.
    """
    s = get_settings()
    try:
        if s.whatsapp_provider == "meta":
            async with _client(headers={"Authorization": f"Bearer {s.meta_whatsapp_token}"}) as c:
                r = await c.post(
                    f"https://graph.facebook.com/v20.0/{s.meta_whatsapp_phone_id}/messages",
                    json={
                        "messaging_product": "whatsapp",
                        "to": phone.lstrip("+"),
                        "type": "text",
                        "text": {"body": text},
                    },
                )
            r.raise_for_status()
            return "whatsapp"
        if s.whatsapp_provider == "twilio":
            (await _twilio_message(phone, text, whatsapp=True)).raise_for_status()
            return "whatsapp"
        if s.sms_provider == "twilio":
            (await _twilio_message(phone, text, whatsapp=False)).raise_for_status()
            return "sms"
    except Exception as exc:  # never break the caller
        log.error("message to %s failed: %s", _mask(phone), exc)
        return "failed"
    log.info("message (console) to %s: %s", _mask(phone), text)
    return "console"


# ---------- e-mail ----------


def _smtp_send(msg: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
        if s.smtp_starttls:
            smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> str:
    s = get_settings()
    if s.email_provider == "console" or not to:
        log.info("e-mail (console) to %s: %s", to.split("@")[-1] if to else "-", subject)
        return "console"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    try:
        await asyncio.to_thread(_smtp_send, msg)
        return "email"
    except Exception as exc:
        log.error("e-mail to %s failed: %s", to.split("@")[-1], exc)
        return "failed"


def fire(coro) -> None:  # type: ignore[no-untyped-def]
    """Send in the background: notifications must never slow down or fail the request."""
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:  # pragma: no cover - no loop
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)


_pending: set[asyncio.Task] = set()  # type: ignore[type-arg]
