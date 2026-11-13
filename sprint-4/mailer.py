"""Email notifications (Sprint 4).

If MAIL_SERVER is set, emails go out through that mail server (for example
Gmail with an app password, see README). If not, which is the default for
development and demos, each email is printed in the terminal instead.

Either way every email is saved in the `emails` table, so staff can see what
was sent and when (the admin "Emails" page).
"""
import smtplib
from email.message import EmailMessage

from flask import current_app

from db import get_db


def app_url(path=""):
    """Links in emails need the full address, even when sent from a terminal command."""
    return current_app.config["APP_URL"].rstrip("/") + path


def send(to, subject, body, kind, appointment_id=None, walk_in_id=None):
    """Send (or print) one email and log it. Returns 'sent', 'printed' or 'failed'.

    Never raises: a mail problem must not break a page.
    """
    cfg = current_app.config
    status, error = "printed", None
    if cfg.get("MAIL_SERVER"):
        try:
            msg = EmailMessage()
            msg["From"] = cfg["MAIL_FROM"]
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body + "\n\nTMU Health Booking\n" + app_url())
            with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=10) as smtp:
                if cfg["MAIL_USE_TLS"]:
                    smtp.starttls()
                if cfg.get("MAIL_USERNAME"):
                    smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
                smtp.send_message(msg)
            status = "sent"
        except (OSError, smtplib.SMTPException) as e:
            status, error = "failed", str(e)[:300]
            current_app.logger.warning("Email to %s failed: %s", to, e)
    elif not current_app.testing:
        print(f"\n----- EMAIL (not sent: no MAIL_SERVER set) -----\nTo: {to}\nSubject: {subject}\n\n{body}\n"
              "------------------------------------------------\n", flush=True)

    db = get_db()
    db.execute(
        "INSERT INTO emails (to_address, subject, body, kind, appointment_id, walk_in_id, status, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (to, subject, body, kind, appointment_id, walk_in_id, status, error),
    )
    db.commit()
    return status

