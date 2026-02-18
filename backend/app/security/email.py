"""
Email service — Brevo (Sendinblue) transactional API.

Sends HTML emails via the Brevo REST API using httpx.
No SDK dependency — raw HTTP calls keep the footprint minimal.

Brevo docs: https://developers.brevo.com/reference/sendtransacemail
"""
from __future__ import annotations

import logging

import httpx

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def _verification_html(name: str, verify_url: str) -> str:
    """Return the HTML body for the email-verification email."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Verify your SentinelAI account</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0f;font-family:'Segoe UI',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:48px 16px;">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0"
               style="background:#111827;border-radius:14px;border:1px solid #1e293b;overflow:hidden;max-width:560px;">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);
                        padding:36px 40px;text-align:center;">
              <h1 style="margin:0;font-size:30px;font-weight:800;letter-spacing:-0.5px;">
                <span style="color:#3b82f6;">Sentinel</span><span style="color:#f8fafc;">AI</span>
              </h1>
              <p style="margin:6px 0 0;color:#64748b;font-size:13px;letter-spacing:0.5px;
                         text-transform:uppercase;">
                Geopolitical Market Intelligence
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="margin:0 0 12px;font-size:22px;color:#f1f5f9;font-weight:700;">
                Welcome, {name}!
              </h2>
              <p style="margin:0 0 28px;color:#94a3b8;font-size:15px;line-height:1.7;">
                Thank you for creating your SentinelAI account. To activate your access
                to real-time geopolitical market intelligence, please confirm your email
                address by clicking the button below.
              </p>

              <!-- CTA button -->
              <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td align="center" style="padding:0 0 32px;">
                    <a href="{verify_url}"
                       style="display:inline-block;padding:15px 36px;
                              background:linear-gradient(135deg,#3b82f6 0%,#2563eb 100%);
                              color:#ffffff;text-decoration:none;border-radius:8px;
                              font-weight:700;font-size:15px;letter-spacing:0.3px;
                              box-shadow:0 4px 14px rgba(59,130,246,0.4);">
                      Verify Email Address
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 8px;color:#475569;font-size:13px;">
                Or paste this link into your browser:
              </p>
              <p style="margin:0 0 28px;padding:12px 16px;background:#1e293b;
                         border-radius:6px;border-left:3px solid #3b82f6;
                         font-size:12px;color:#7dd3fc;word-break:break-all;
                         font-family:monospace;">
                {verify_url}
              </p>

              <p style="margin:0;color:#475569;font-size:13px;line-height:1.7;
                         border-top:1px solid #1e293b;padding-top:24px;">
                This link expires in <strong style="color:#94a3b8;">24 hours</strong>.
                If you did not create a SentinelAI account, you can safely ignore this email.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#0f172a;padding:20px 40px;
                        border-top:1px solid #1e293b;text-align:center;">
              <p style="margin:0;color:#374151;font-size:12px;line-height:1.6;">
                &copy; 2026 SentinelAI &mdash; All rights reserved<br />
                <span style="color:#1e293b;">
                  This is an automated security email. Please do not reply.
                </span>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _password_reset_html(name: str, reset_url: str) -> str:
    """Return the HTML body for a password-reset email (future use)."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Reset your SentinelAI password</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0f;font-family:'Segoe UI',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:48px 16px;">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0"
               style="background:#111827;border-radius:14px;border:1px solid #1e293b;
                      overflow:hidden;max-width:560px;">
          <tr>
            <td style="background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);
                        padding:36px 40px;text-align:center;">
              <h1 style="margin:0;font-size:30px;font-weight:800;">
                <span style="color:#3b82f6;">Sentinel</span><span style="color:#f8fafc;">AI</span>
              </h1>
            </td>
          </tr>
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="margin:0 0 12px;font-size:22px;color:#f1f5f9;">
                Password Reset Request
              </h2>
              <p style="margin:0 0 28px;color:#94a3b8;font-size:15px;line-height:1.7;">
                Hi {name}, we received a request to reset the password for your SentinelAI
                account. Click the button below to choose a new password.
              </p>
              <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td align="center" style="padding:0 0 32px;">
                    <a href="{reset_url}"
                       style="display:inline-block;padding:15px 36px;
                              background:linear-gradient(135deg,#dc2626,#b91c1c);
                              color:#ffffff;text-decoration:none;border-radius:8px;
                              font-weight:700;font-size:15px;">
                      Reset Password
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0;color:#475569;font-size:13px;line-height:1.7;
                         border-top:1px solid #1e293b;padding-top:24px;">
                This link expires in <strong style="color:#94a3b8;">1 hour</strong>.
                If you did not request a password reset, please ignore this email —
                your account remains secure.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:#0f172a;padding:20px 40px;border-top:1px solid #1e293b;
                        text-align:center;">
              <p style="margin:0;color:#374151;font-size:12px;">
                &copy; 2026 SentinelAI &mdash; All rights reserved
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


async def _send(to_email: str, to_name: str, subject: str, html: str) -> None:
    """Low-level Brevo transactional email send."""
    settings = get_settings()
    payload = {
        "sender": {
            "name":  settings.brevo_sender_name,
            "email": settings.brevo_sender_email,
        },
        "to": [{"email": to_email, "name": to_name}],
        "subject": subject,
        "htmlContent": html,
    }
    headers = {
        "api-key":      settings.brevo_api_key,
        "Content-Type": "application/json",
        "Accept":       "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(_BREVO_URL, headers=headers, json=payload)

    if resp.status_code not in (200, 201):
        logger.error(
            "Brevo send failed status=%d body=%s",
            resp.status_code,
            resp.text[:300],
        )
        raise RuntimeError(
            f"Failed to send email via Brevo (HTTP {resp.status_code}): {resp.text[:200]}"
        )

    logger.info("Brevo email sent to=%s subject=%r", to_email, subject)


async def send_verification_email(to_email: str, to_name: str, raw_token: str) -> None:
    """
    Send the email-verification email.

    The verification link points to the FRONTEND, which will then call
    POST /api/v1/auth/verify-email with the token in the JSON body.
    """
    settings = get_settings()
    verify_url = f"{settings.frontend_url}/verify-email?token={raw_token}"
    html = _verification_html(to_name, verify_url)
    await _send(
        to_email=to_email,
        to_name=to_name,
        subject="Verify your SentinelAI account",
        html=html,
    )


async def send_password_reset_email(
    to_email: str, to_name: str, raw_token: str
) -> None:
    """Send the password-reset email (ready for future /auth/forgot-password)."""
    settings = get_settings()
    reset_url = f"{settings.frontend_url}/reset-password?token={raw_token}"
    html = _password_reset_html(to_name, reset_url)
    await _send(
        to_email=to_email,
        to_name=to_name,
        subject="Reset your SentinelAI password",
        html=html,
    )
