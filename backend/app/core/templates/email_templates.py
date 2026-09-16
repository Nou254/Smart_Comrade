"""
Email templates.

Each function returns (subject, html_body, text_body).

Templates are inline HTML strings, styled for email client compatibility
(inline CSS, no external stylesheets, no JS, min-width 320px).
"""
from __future__ import annotations


BRAND_COLOR = "#00d4c8"
BRAND_DARK = "#0f172a"
BRAND_MUTED = "#64748b"


def _wrapper(title: str, body_html: str, footer_note: str = "") -> str:
    return f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f4f7f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:{BRAND_DARK};">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f4f7f8;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(15,23,42,0.06);">
          <tr>
            <td style="padding:24px 32px 8px;border-bottom:1px solid #eef2f5;">
              <div style="font-size:20px;font-weight:700;color:{BRAND_COLOR};letter-spacing:0.3px;">Smart Comrade</div>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 32px 8px;">
              <h1 style="margin:0 0 16px;font-size:20px;font-weight:700;color:{BRAND_DARK};">{title}</h1>
              {body_html}
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 32px;">
              <p style="margin:0;font-size:12px;color:{BRAND_MUTED};line-height:1.5;">{footer_note or "You received this email because you have a Smart Comrade account."}</p>
            </td>
          </tr>
        </table>
        <p style="margin:16px 0 0;font-size:12px;color:{BRAND_MUTED};">© Smart Comrade · N.O.U. Digital Systems</p>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _button(label: str, url: str) -> str:
    return (
        f'<p style="margin:24px 0;">'
        f'<a href="{url}" style="display:inline-block;background:{BRAND_COLOR};color:#ffffff;'
        f'padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">'
        f'{label}</a></p>'
    )


def _code_box(code: str) -> str:
    return (
        f'<div style="margin:24px 0;padding:16px;background:#f1f5f9;border-radius:8px;text-align:center;">'
        f'<div style="font-size:32px;font-weight:700;letter-spacing:8px;color:{BRAND_DARK};font-family:\'Courier New\',monospace;">{code}</div>'
        f'</div>'
    )


# ── Templates ──────────────────────────────────────────────

def welcome(name: str) -> tuple[str, str, str]:
    subject = "Welcome to Smart Comrade"
    html = _wrapper(
        f"Welcome, {name}!",
        "<p style='margin:0 0 12px;font-size:14px;line-height:1.6;'>Your Smart Comrade account is ready. "
        "Verify your email to unlock the full platform: study groups, timetable uploads, "
        "unit coordination, and everything else.</p>"
        "<p style='margin:0;font-size:14px;line-height:1.6;color:#64748b;'>"
        "If you didn't sign up, you can safely ignore this email.</p>",
    )
    text = f"Welcome to Smart Comrade, {name}.\nVerify your email to get started."
    return subject, html, text


def verify_email(name: str, code: str, expires_minutes: int = 15) -> tuple[str, str, str]:
    subject = "Verify your Smart Comrade email"
    html = _wrapper(
        "Verify your email",
        f"<p style='margin:0 0 8px;font-size:14px;line-height:1.6;'>Hi {name}, enter this code to verify your email:</p>"
        f"{_code_box(code)}"
        f"<p style='margin:0;font-size:13px;color:{BRAND_MUTED};'>This code expires in {expires_minutes} minutes.</p>",
    )
    text = f"Hi {name}, your Smart Comrade verification code is {code}. Expires in {expires_minutes} minutes."
    return subject, html, text


def verify_phone(name: str, code: str, expires_minutes: int = 10) -> tuple[str, str, str]:
    subject = "Your Smart Comrade phone verification code"
    html = _wrapper(
        "Verify your phone",
        f"<p style='margin:0 0 8px;font-size:14px;line-height:1.6;'>Hi {name}, enter this code to verify your phone number:</p>"
        f"{_code_box(code)}"
        f"<p style='margin:0;font-size:13px;color:{BRAND_MUTED};'>This code expires in {expires_minutes} minutes.</p>",
    )
    text = f"Hi {name}, your Smart Comrade phone verification code is {code}. Expires in {expires_minutes} minutes."
    return subject, html, text


def password_reset(name: str, reset_url: str, expires_minutes: int = 60) -> tuple[str, str, str]:
    subject = "Reset your Smart Comrade password"
    html = _wrapper(
        "Reset your password",
        f"<p style='margin:0 0 8px;font-size:14px;line-height:1.6;'>Hi {name}, we received a request to reset your password.</p>"
        f"{_button('Reset password', reset_url)}"
        f"<p style='margin:0;font-size:13px;color:{BRAND_MUTED};'>This link expires in {expires_minutes} minutes. "
        f"If you didn't request this, ignore this email — your password will not change.</p>",
    )
    text = f"Hi {name}, reset your Smart Comrade password: {reset_url} (expires in {expires_minutes} minutes)."
    return subject, html, text


def password_changed(name: str, ip: str | None = None) -> tuple[str, str, str]:
    subject = "Your Smart Comrade password was changed"
    ip_line = f"<p style='margin:0 0 8px;font-size:13px;color:{BRAND_MUTED};'>IP: {ip}</p>" if ip else ""
    html = _wrapper(
        "Password changed",
        f"<p style='margin:0 0 12px;font-size:14px;line-height:1.6;'>Hi {name}, your password was just changed.</p>"
        f"{ip_line}"
        "<p style='margin:0;font-size:13px;color:#dc2626;'>"
        "If this wasn't you, reset your password immediately and contact support.</p>",
    )
    text = f"Hi {name}, your Smart Comrade password was changed. If this wasn't you, act immediately."
    return subject, html, text


def new_device_login(
    name: str,
    device: str,
    ip: str | None = None,
    when: str | None = None,
) -> tuple[str, str, str]:
    subject = "New device signed in to Smart Comrade"
    rows = "".join([
        f"<tr><td style='padding:4px 12px 4px 0;color:{BRAND_MUTED};font-size:13px;'>Device</td>"
        f"<td style='padding:4px 0;font-size:13px;'>{device}</td></tr>",
        f"<tr><td style='padding:4px 12px 4px 0;color:{BRAND_MUTED};font-size:13px;'>IP</td>"
        f"<td style='padding:4px 0;font-size:13px;'>{ip or 'unknown'}</td></tr>" if ip else "",
        f"<tr><td style='padding:4px 12px 4px 0;color:{BRAND_MUTED};font-size:13px;'>When</td>"
        f"<td style='padding:4px 0;font-size:13px;'>{when or 'just now'}</td></tr>" if when else "",
    ])
    html = _wrapper(
        "New device signed in",
        f"<p style='margin:0 0 16px;font-size:14px;line-height:1.6;'>Hi {name}, a new device just signed in to your account.</p>"
        f"<table role='presentation' cellpadding='0' cellspacing='0' border='0' style='margin:0 0 16px;'>{rows}</table>"
        f"<p style='margin:0;font-size:13px;color:{BRAND_MUTED};'>"
        "If this was you, no action is needed. If not, change your password and review active sessions.</p>",
    )
    text = f"Hi {name}, a new device signed in. Device: {device}. IP: {ip or 'unknown'}. If this wasn't you, act now."
    return subject, html, text


def account_approved(name: str) -> tuple[str, str, str]:
    subject = "Your Smart Comrade account has been approved"
    html = _wrapper(
        "Account approved",
        f"<p style='margin:0;font-size:14px;line-height:1.6;'>Hi {name}, your account has been approved. "
        "You can now sign in and access all features available to your role.</p>",
    )
    text = f"Hi {name}, your Smart Comrade account has been approved."
    return subject, html, text


def account_rejected(name: str, reason: str | None = None) -> tuple[str, str, str]:
    subject = "Your Smart Comrade registration was not approved"
    reason_html = f"<p style='margin:12px 0 0;font-size:13px;'><strong>Reason:</strong> {reason}</p>" if reason else ""
    html = _wrapper(
        "Registration not approved",
        f"<p style='margin:0;font-size:14px;line-height:1.6;'>Hi {name}, we're unable to approve your Smart Comrade registration.</p>"
        f"{reason_html}"
        "<p style='margin:16px 0 0;font-size:13px;color:#64748b;'>You may contact support if you believe this was a mistake.</p>",
    )
    text = f"Hi {name}, your Smart Comrade registration was not approved." + (f" Reason: {reason}" if reason else "")
    return subject, html, text


def account_suspended(name: str, reason: str | None = None) -> tuple[str, str, str]:
    subject = "Your Smart Comrade account has been suspended"
    reason_html = f"<p style='margin:12px 0 0;font-size:13px;'><strong>Reason:</strong> {reason}</p>" if reason else ""
    html = _wrapper(
        "Account suspended",
        f"<p style='margin:0;font-size:14px;line-height:1.6;'>Hi {name}, your Smart Comrade account has been suspended.</p>"
        f"{reason_html}"
        "<p style='margin:16px 0 0;font-size:13px;color:#64748b;'>Contact support if you wish to appeal.</p>",
    )
    text = f"Hi {name}, your Smart Comrade account was suspended." + (f" Reason: {reason}" if reason else "")
    return subject, html, text


def admin_invitation(role_code: str, activation_url: str) -> tuple[str, str, str]:
    subject = "You're invited to Smart Comrade as an administrator"
    html = _wrapper(
        "Admin invitation",
        f"<p style='margin:0 0 12px;font-size:14px;line-height:1.6;'>You've been invited as <strong>{role_code}</strong>.</p>"
        f"{_button('Activate account', activation_url)}"
        "<p style='margin:0;font-size:13px;color:#64748b;'>This link expires in 7 days.</p>",
    )
    text = f"You're invited to Smart Comrade as {role_code}. Activate: {activation_url}"
    return subject, html, text