"""Day-before appointment reminders (Sprint 4).

Every booked appointment gets one reminder email on the day before it. They
go out three ways, so nothing depends on a single one:

  * automatically while the app is running (checked at most every 10 minutes),
  * from a terminal or a scheduled job:  flask --app app send-reminders
  * from the "Send now" button on the admin dashboard.

Each reminder is also posted to the patient's Messages page. The
appointment's reminder_sent_at records when it was emailed, so nobody gets
two, and staff and patients can see that it was sent.
"""
import time
from datetime import date, datetime, timedelta

import click
from flask.cli import with_appcontext

import appointments
from db import get_db

SWEEP_EVERY_SECONDS = 600
_last_sweep = {"at": 0.0}


def due_tomorrow():
    """Tomorrow's booked appointments, with whether their reminder has gone out."""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    return get_db().execute(
        """SELECT a.*, u.full_name AS patient_name, u.email AS patient_email,
                  d.full_name AS doctor_name, d.department
           FROM appointments a JOIN users u ON u.id = a.patient_id JOIN doctors d ON d.id = a.doctor_id
           WHERE a.appt_date = ? AND a.status = 'booked' ORDER BY a.start_time""",
        (tomorrow,),
    ).fetchall()


def send_due():
    """Remind every patient with an appointment tomorrow. Returns how many reminders were emailed.

    Each reminder is posted to the patient's message center and emailed. If the
    email fails, the message stays posted and only the email is tried again later.
    """
    db = get_db()
    sent = 0
    for a in due_tomorrow():
        if a["reminder_sent_at"]:
            continue
        existing = db.execute(
            "SELECT id FROM notifications WHERE appointment_id = ? AND kind = 'reminder'", (a["id"],)
        ).fetchone()
        if existing:
            emailed = appointments.email_notification(existing["id"])
        else:
            day = datetime.strptime(a["appt_date"], "%Y-%m-%d")
            message = (f"Reminder: you have an appointment tomorrow, {day:%A, %B %d}, at {a['start_time']} "
                       f"with {a['doctor_name']} ({a['department']}). Please arrive 5 minutes early and bring "
                       "your student card. Can't make it? Cancel at least 2 hours before so someone on the "
                       "wait list can have the time.")
            note_id = appointments.notify(a["patient_id"], message,
                                          subject=f"Reminder: appointment tomorrow at {a['start_time']}",
                                          appointment_id=a["id"], kind="reminder")
            emailed = db.execute("SELECT email_status FROM notifications WHERE id = ?",
                                 (note_id,)).fetchone()["email_status"] != "failed"
        if emailed:
            db.execute("UPDATE appointments SET reminder_sent_at = ? WHERE id = ?",
                       (datetime.now().strftime("%Y-%m-%d %H:%M"), a["id"]))
            db.commit()
            sent += 1
    return sent


@click.command("send-reminders")
@with_appcontext
def send_reminders_command():
    """Email tomorrow's appointment reminders (safe to run as often as you like)."""
    click.echo(f"{send_due()} reminder(s) sent.")


def init_app(app):
    app.cli.add_command(send_reminders_command)

    @app.before_request
    def automatic_sweep():
        if not app.config["AUTO_REMINDERS"] or app.testing:
            return
        if time.monotonic() - _last_sweep["at"] < SWEEP_EVERY_SECONDS:
            return
        _last_sweep["at"] = time.monotonic()
        try:
            send_due()
        except Exception:  # a reminder problem must never stop someone using the site
            app.logger.exception("Reminder sweep failed")
