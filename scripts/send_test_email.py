import os
import sys
import smtplib
from email.message import EmailMessage


def _get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def main() -> int:
    to_email = _get("SMTP_TEST_TO") or (sys.argv[1].strip() if len(sys.argv) > 1 else "")
    if not to_email:
        print("Missing recipient. Set SMTP_TEST_TO or pass as argv[1].", file=sys.stderr)
        return 2

    provider = _get("SMTP_PROVIDER").lower()
    host = _get("SMTP_HOST")
    port_raw = _get("SMTP_PORT", "")
    user = _get("SMTP_USER")
    password = _get("SMTP_PASS")
    from_email = _get("SMTP_FROM") or user

    if not host and provider in ("gmail", "google"):
        host = "smtp.gmail.com"
    elif not host and provider in ("outlook", "office365", "microsoft"):
        host = "smtp.office365.com"
    elif not host and provider in ("sendgrid",):
        host = "smtp.sendgrid.net"
        if not user:
            user = "apikey"
            if not from_email:
                from_email = user

    try:
        port = int(port_raw or "587")
    except Exception:
        port = 587

    if not host or not from_email:
        print("SMTP is not configured. Set SMTP_HOST and SMTP_FROM (and usually SMTP_USER/SMTP_PASS).", file=sys.stderr)
        return 2

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = "LinkUp SMTP test"
    msg.set_content("This is a test email from LinkUp. If you received this, SMTP is working.\n")

    try:
        print(f"Connecting to {host}:{port} ...")
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
                print("STARTTLS: enabled")
            except Exception:
                print("STARTTLS: not available (continuing)")

            if user and password:
                print("Authenticating ...")
                server.login(user, password)

            print("Sending ...")
            server.send_message(msg)

        print("OK: sent")
        return 0
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
