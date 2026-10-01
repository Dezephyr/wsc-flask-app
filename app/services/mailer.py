"""
Outbound email via Resend (HTTPS API — works on any network).
Falls back to terminal logging when RESEND_API_KEY isn't set.
"""
import os
import requests


def _config():
    return {
        "api_key": os.environ.get("RESEND_API_KEY", "").strip(),
        "sender": os.environ.get(
            "RESEND_FROM",
            "Wall Street Capital <noreply@wallstreetcapital.com>"
        ),
    }


def is_configured() -> bool:
    return bool(_config()["api_key"])


def send_email(to_address: str, subject: str,
               text_body: str, html_body: str = None) -> bool:
    """Send an email via Resend. Returns True on success. Never raises."""
    cfg = _config()

    if not cfg["api_key"]:
        print("\n" + "=" * 60)
        print(f"[mailer] RESEND_API_KEY not set — would have sent to {to_address}")
        print(f"[mailer] Subject: {subject}")
        print("-" * 60)
        print(text_body)
        print("=" * 60 + "\n")
        return False

    payload = {
        "from": cfg["sender"],
        "to": [to_address],
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body

    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        if r.status_code >= 400:
            print(f"[mailer] Resend {r.status_code}: {r.text[:300]}")
            return False
        return True
    except Exception as err:
        print(f"[mailer] Resend request failed: {err}")
        return False


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


def send_welcome(to_address: str, name: str = "there") -> bool:
    """
    Welcome email sent once, on signup only.

    Called from routes/auth_routes.py inside the signup flow, wrapped in
    try/except so a mail failure never blocks account creation.
    """
    subject = "Welcome to Wall Street Capital"

    text = (
        f"Hi {name},\n\n"
        f"Welcome to Wall Street Capital. Your account is ready.\n\n"
        f"Here is what to do next:\n\n"
        f"  1. Complete identity verification (KYC) to unlock deposits,\n"
        f"     withdrawals, and full trading.\n\n"
        f"  2. Link a crypto wallet for faster withdrawals.\n\n"
        f"  3. Fund your account to start trading crypto, stocks,\n"
        f"     and copy strategies.\n\n"
        f"Sign in any time at https://wallstreetcapital.com/login.html\n\n"
        f"If you have questions, reply to this email and our team will help.\n\n"
        f"— Wall Street Capital"
    )

    html = f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0a1220;padding:40px 20px;">
      <div style="max-width:560px;margin:0 auto;background:#0f1a30;
                  border:1px solid rgba(255,255,255,0.08);border-radius:16px;
                  padding:36px 32px;color:#e5ecf7;">

        <h1 style="font-family:Georgia,serif;font-weight:500;margin:0 0 8px;
                   color:#ffffff;font-size:26px;line-height:1.2;">
          Welcome to Wall Street Capital
        </h1>
        <p style="color:#9DA9C0;line-height:1.7;margin:0 0 26px;font-size:15px;">
          Hi {name}, your account is ready. Here is how to get started.
        </p>

        <div style="margin-bottom:16px;padding:16px 18px;
                    background:rgba(96,165,250,0.06);
                    border:1px solid rgba(96,165,250,0.2);border-radius:12px;">
          <div style="font-weight:600;color:#ffffff;margin-bottom:4px;font-size:14px;">
            1. Verify your identity
          </div>
          <div style="color:#9DA9C0;font-size:13.5px;line-height:1.6;">
            Complete KYC to unlock deposits, withdrawals, and full trading.
          </div>
        </div>

        <div style="margin-bottom:16px;padding:16px 18px;
                    background:rgba(96,165,250,0.06);
                    border:1px solid rgba(96,165,250,0.2);border-radius:12px;">
          <div style="font-weight:600;color:#ffffff;margin-bottom:4px;font-size:14px;">
            2. Fund Your Account
          </div>
          <div style="color:#9DA9C0;font-size:13.5px;line-height:1.6;">
            Add funds to start trading crypto, stocks, and copy strategies.
          </div>
        </div>

        <div style="margin-bottom:28px;padding:16px 18px;
                    background:rgba(96,165,250,0.06);
                    border:1px solid rgba(96,165,250,0.2);border-radius:12px;">
          <div style="font-weight:600;color:#ffffff;margin-bottom:4px;font-size:14px;">
            3. Start Trading
          </div>
          <div style="color:#9DA9C0;font-size:13.5px;line-height:1.6;">
            Start trading crypto, stocks, and copy strategies.
          </div>
        </div>

        <a href="https://wallstreetscapital.com/login.html"
           style="display:inline-block;padding:13px 26px;border-radius:10px;
                  background:linear-gradient(135deg,#60A5FA,#1D4ED8);
                  color:#ffffff;text-decoration:none;font-weight:600;
                  font-size:14.5px;">
          Sign in to your account
        </a>

        <p style="color:#7a869a;font-size:12.5px;line-height:1.6;margin:28px 0 0;">
          Questions? Just reply to this email and our team will get back to you.
        </p>

      </div>
    </div>
    """

    return send_email(to_address, subject, text, html)