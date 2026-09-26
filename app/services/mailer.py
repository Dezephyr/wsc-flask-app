"""
Outbound email. Uses SMTP from .env.

If SMTP_HOST / SMTP_USER / SMTP_PASSWORD are not set, sends are logged
instead of delivered — the app still runs, and the password-reset flow
still generates codes. Useful for local development.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _smtp_config():
    return {
        "host":     os.environ.get("SMTP_HOST", "").strip(),
        "port":     int(os.environ.get("SMTP_PORT", "587")),
        "user":     os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", "").strip(),
        "sender":   os.environ.get(
            "SMTP_FROM",
            "Wall Street Capital <no-reply@wallstreetcapital.app>"
        ),
    }


def is_configured() -> bool:
    cfg = _smtp_config()
    return bool(cfg["host"] and cfg["user"] and cfg["password"])


def send_email(to_address: str, subject: str, text_body: str, html_body: str = None) -> bool:
    """
    Send an email. Returns True on success, False on failure.
    Never raises — a logging failure must not break the request.
    """
    cfg = _smtp_config()

    if not cfg["host"]:
        # Dev mode: print the whole body so the code is visible in the terminal.
        print("\n" + "=" * 60)
        print(f"[mailer] SMTP not configured — would have sent to {to_address}")
        print(f"[mailer] Subject: {subject}")
        print("-" * 60)
        print(text_body)
        print("=" * 60 + "\n")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = cfg["sender"]
    msg["To"]      = to_address

    msg.attach(MIMEText(text_body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["sender"], [to_address], msg.as_string())
        return True
    except Exception as err:
        print(f"[mailer] send to {to_address} failed: {err}")
        return False


# ------------------------------------------------------------
# Templates
# ------------------------------------------------------------

def send_password_reset(to_address: str, code: str, name: str = "there") -> bool:
    subject = "Your password reset code — Wall Street Capital"

    text = (
        f"Hi {name},\n\n"
        f"Someone requested a password reset for your Wall Street Capital account.\n\n"
        f"Your 6-digit code is: {code}\n\n"
        f"This code expires in 10 minutes. If you didn't request it, ignore this email.\n\n"
        f"— Wall Street Capital"
    )

    html = f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0a1220;padding:40px 20px;">
      <div style="max-width:520px;margin:0 auto;background:#0f1a30;
                  border:1px solid rgba(255,255,255,0.08);border-radius:16px;
                  padding:32px;color:#e5ecf7;">
        <h2 style="font-family:Georgia,serif;font-weight:500;margin:0 0 16px;color:#ffffff;">
          Password reset
        </h2>
        <p style="color:#9DA9C0;line-height:1.6;margin:0 0 22px;">
          Hi {name}, use the code below to reset your Wall Street Capital password.
        </p>
        <div style="font-family:ui-monospace,monospace;font-size:34px;letter-spacing:10px;
                    text-align:center;padding:18px;background:rgba(96,165,250,0.08);
                    border:1px solid rgba(96,165,250,0.3);border-radius:12px;
                    color:#60A5FA;font-weight:700;margin-bottom:22px;">
          {code}
        </div>
        <p style="color:#9DA9C0;font-size:13px;line-height:1.6;margin:0;">
          This code expires in 10 minutes. If you didn't request this,
          you can safely ignore this email.
        </p>
      </div>
    </div>
    """

    return send_email(to_address, subject, text, html)