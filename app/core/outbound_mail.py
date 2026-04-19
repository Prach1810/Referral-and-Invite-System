"""
Synchronous outbound email helpers for RQ workers.

Uses only the standard library for transport (SMTP or SendGrid HTTPS).
If no provider is configured, logs the payload (local/dev).
"""
from __future__ import annotations

import json
import logging
import smtplib
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def _display_inviter(inviter_name: str) -> str:
    name = (inviter_name or "").strip()
    return name if name else "Someone"


def _build_invite_copy(invitee_email: str, inviter_name: str, shareable_link: str) -> tuple[str, str, str]:
    who = _display_inviter(inviter_name)
    subject = f"{who} invited you to join Flik"
    text = (
        f"{who} invited you to sign up using their referral link.\n\n"
        f"Join here:\n{shareable_link}\n\n"
        "If you did not expect this message, you can ignore it.\n"
    )
    btn_style = (
        "display:inline-block;padding:10px 16px;background:#111;color:#fff;"
        "text-decoration:none;border-radius:6px;"
    )
    html = f"""<!DOCTYPE html>
<html>
  <body style="font-family: system-ui, sans-serif; line-height: 1.5; color: #111;">
    <p><strong>{who}</strong> invited you to join Flik.</p>
    <p>
      <a href="{shareable_link}" style="{btn_style}">Accept invitation</a>
    </p>
    <p style="font-size: 14px; color: #444;">Or copy this link:<br>
      <span style="word-break: break-all;">{shareable_link}</span>
    </p>
    <p style="font-size: 12px; color: #666;">Sent to {invitee_email}. If this was not you, you can ignore this email.</p>
  </body>
</html>
"""
    return subject, text, html


def _send_sendgrid(invitee_email: str, subject: str, text: str, html: str) -> None:
    if not settings.MAIL_FROM_EMAIL:
        raise ValueError("MAIL_FROM_EMAIL is required when SENDGRID_API_KEY is set")

    payload = {
        "personalizations": [{"to": [{"email": invitee_email}]}],
        "from": {"email": settings.MAIL_FROM_EMAIL, "name": settings.MAIL_FROM_NAME},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text},
            {"type": "text/html", "value": html},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SENDGRID_API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.getcode()
            if code not in (200, 202):
                raise RuntimeError(f"SendGrid unexpected status {code}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        logger.error("SendGrid HTTP error %s: %s", e.code, detail)
        raise RuntimeError(f"SendGrid request failed: {e.code}") from e
    except urllib.error.URLError as e:
        logger.error("SendGrid network error: %s", e)
        raise


def _send_smtp(invitee_email: str, subject: str, text: str, html: str) -> None:
    if not settings.MAIL_FROM_EMAIL:
        raise ValueError("MAIL_FROM_EMAIL is required when SMTP_HOST is set")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM_EMAIL}>"
    msg["To"] = invitee_email
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        user = (settings.SMTP_USER or "").strip()
        password = (settings.SMTP_PASSWORD or "").strip()
        if user and password:
            server.login(user, password)
        server.sendmail(settings.MAIL_FROM_EMAIL, [invitee_email], msg.as_string())


def send_invite_email_sync(invitee_email: str, inviter_name: str, shareable_link: str) -> None:
    """
    Deliver an invitation email. Raises on provider failure so RQ can retry.

    Resolution order:
    1. ``SENDGRID_API_KEY`` — SendGrid v3 Mail Send API
    2. ``SMTP_HOST`` — SMTP with optional TLS and auth
    3. Neither — log only (development)
    """
    subject, text, html = _build_invite_copy(invitee_email, inviter_name, shareable_link)

    if settings.SENDGRID_API_KEY:
        logger.info("Sending invite email to %s via SendGrid", invitee_email)
        _send_sendgrid(invitee_email, subject, text, html)
        return

    if settings.SMTP_HOST:
        logger.info("Sending invite email to %s via SMTP %s", invitee_email, settings.SMTP_HOST)
        _send_smtp(invitee_email, subject, text, html)
        return

    logger.warning(
        "[invite-email] no SENDGRID_API_KEY or SMTP_HOST — email not sent (configure a provider in .env). "
        "to=%s inviter=%r link=%s",
        invitee_email,
        inviter_name,
        shareable_link,
    )
