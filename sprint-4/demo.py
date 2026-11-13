"""Demo data for presentations (Sprint 4).

    flask --app app seed-demo

Rebuilds clinic.db and fills it with patients, doctor and admin accounts,
today's appointments in every status, a week of history, a fully booked day
with a wait list, and a walk-in queue. Every demo account uses the password
"password123".
"""
import os
from datetime import date, datetime, timedelta

import click
from flask import current_app
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from db import get_db, init_db
from scheduling import all_slots

DEMO_PASSWORD = "password123"

PATIENTS = [
    ("Sam Lee", "sam.lee@torontomu.ca", "501234567"),
    ("Jo Park", "jo.park@torontomu.ca", "501111111"),
    ("Maya Singh", "maya.singh@torontomu.ca", "502222222"),
    ("Leo Tran", "leo.tran@torontomu.ca", "503333333"),
    ("Ava Brooks", "ava.brooks@torontomu.ca", "504444444"),
    ("Omar Haddad", "omar.haddad@torontomu.ca", "505555555"),
    ("Nia Clarke", "nia.clarke@torontomu.ca", "506666666"),
    ("Ben Ortiz", "ben.ortiz@torontomu.ca", "507777777"),
]
DOCTOR_LOGINS = ["priya.raman@torontomu.ca", "aisha.bello@torontomu.ca"]


def seed():
    db = get_db()
    today = date.today()
    pw = generate_password_hash(DEMO_PASSWORD)

    def user(name, email, role, student_id=None):
        return db.execute(
            "INSERT INTO users (full_name, email, student_id, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            (name, email, student_id, pw, role)).lastrowid

    user("Front Desk", "frontdesk@torontomu.ca", "admin")
    p = [user(n, e, "patient", s) for n, e, s in PATIENTS]
    for email in DOCTOR_LOGINS:
        name = db.execute("SELECT full_name FROM doctors WHERE email = ?", (email,)).fetchone()[0]
        db.execute("UPDATE doctors SET user_id = ? WHERE email = ?", (user(name, email, "doctor"), email))

    # Dr. Raman (1) and Dr. Bello (3) work today in the demo, whatever day it is
    for doctor_id, start, end in ((1, "09:00", "12:00"), (3, "13:00", "16:00")):
        if not all_slots(doctor_id, today):
            db.execute("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
                       (doctor_id, today.weekday(), start, end))

    def appt(patient, doctor, day, time, status="booked", reason=None, source="online", notes=None, by=None):
        db.execute(
            "INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time, reason, status, source, "
            "visit_notes, cancelled_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (patient, doctor, day.isoformat(), time, reason, status, source, notes, by))

    # Today at Dr. Raman's: one appointment in each status
    raman = all_slots(1, today)
    todays = [
        (p[0], "completed", "Flu symptoms", "Rest and fluids. Follow up if the fever lasts past Friday.", None, "online"),
        (p[1], "no_show", "Prescription renewal", None, None, "online"),
        (p[2], "checked_in", "Sprained ankle follow-up", None, None, "online"),
        (p[3], "booked", "Vaccination", None, None, "online"),
        (p[4], "cancelled", "Check-up", None, "patient", "online"),
        (p[5], "booked", "Ear pain", None, None, "waitlist"),
    ]
    for slot, (patient, status, reason, notes, by, source) in zip(raman, todays):
        appt(patient, 1, today, slot, status, reason, source, notes, by)
    appt(p[6], 3, today, all_slots(3, today)[0], "completed", "Exam stress", notes="Referred to group sessions.")

    # The past 6 days, for the dashboard's 7-day trend
    outcomes = ["completed", "completed", "no_show", "completed", "cancelled"]
    for back in range(1, 7):
        day = today - timedelta(days=back)
        k = 0
        for doctor_id in range(1, 6):
            for slot in all_slots(doctor_id, day)[: 1 + (back + doctor_id) % 3]:
                appt(p[k % len(p)], doctor_id, day, slot, outcomes[(k + back) % len(outcomes)], "Follow-up")
                k += 1

    # A fully booked day for Dr. Okafor (4), with two patients on the wait list
    full = today + timedelta(days=3)
    while not all_slots(4, full):
        full += timedelta(days=1)
    for i, slot in enumerate(all_slots(4, full)):
        appt(p[1 + i % 6] if i < 6 else p[7], 4, full, slot, reason="Consultation")
    for patient in (p[0], p[7]):
        db.execute("INSERT INTO waitlist (patient_id, doctor_id, wait_date) VALUES (?, 4, ?)", (patient, full.isoformat()))

    # Sam has an upcoming visit that he got from a wait list, and a message about it
    nxt = today + timedelta(days=1)
    while not all_slots(3, nxt):
        nxt += timedelta(days=1)
    slot = all_slots(3, nxt)[1]
    appt(p[0], 3, nxt, slot, reason="Counselling intake", source="waitlist")
    sam_appt = db.execute("SELECT id FROM appointments WHERE patient_id = ? AND appt_date = ?",
                          (p[0], nxt.isoformat())).fetchone()[0]
    earlier = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    yesterday = (datetime.now() - timedelta(days=1)).replace(hour=8, minute=0).strftime("%Y-%m-%d %H:%M")
    sam_today = db.execute("SELECT id, start_time FROM appointments WHERE patient_id = ? AND appt_date = ?",
                           (p[0], today.isoformat())).fetchone()
    # His message center: an older, already-read reminder, and a new wait-list message
    db.execute(
        "INSERT INTO notifications (user_id, kind, subject, message, appointment_id, email_status, emailed_at, "
        "created_at, read_at) VALUES (?, 'reminder', ?, ?, ?, 'printed', ?, ?, ?)",
        (p[0], f"Reminder: appointment tomorrow at {sam_today[1]}",
         f"Reminder: you have an appointment tomorrow, {today:%A, %B %d}, at {sam_today[1]} with Dr. Priya Raman "
         "(Primary Care). Please arrive 5 minutes early and bring your student card. Can't make it? Cancel at "
         "least 2 hours before so someone on the wait list can have the time.",
         sam_today[0], yesterday, yesterday, yesterday))
    db.execute(
        "INSERT INTO notifications (user_id, kind, subject, message, appointment_id, email_status, emailed_at, "
        "created_at) VALUES (?, 'waitlist', ?, ?, ?, 'printed', ?, ?)",
        (p[0], f"You're booked: {nxt:%a %b %d} at {slot}",
         f"Good news: a spot opened up and you're booked with Dr. Aisha Bello on {nxt:%A, %B %d} at {slot}. "
         "Cancel it if you can't make it.", sam_appt, earlier, earlier))

    # This morning's walk-ins. Dan and Lucy stepped out and left an email address.
    now = datetime.now()
    for name, reason, urgency, preferred, status, minutes_ago, assigned, email in [
        ("Kai Morgan", "Cut on hand", "normal", None, "done", 140, 1, None),
        ("Rosa Diaz", "Fever", "normal", None, "with_doctor", 50, 1, None),
        ("Dan Wu", "Sore throat", "normal", None, "waiting", 34, None, "dan.wu@torontomu.ca"),
        ("Ken Ito", "Prescription question", "normal", 3, "waiting", 21, None, None),
        ("Lucy Fox", "Twisted knee", "normal", None, "waiting", 12, None, "lucy.fox@torontomu.ca"),
        ("Elle Moreau", "Allergic reaction, hives", "urgent", None, "waiting", 6, None, None),
    ]:
        arrived = now - timedelta(minutes=minutes_ago)
        db.execute(
            "INSERT INTO walk_ins (patient_name, reason, urgency, preferred_doctor_id, assigned_doctor_id, status, "
            "arrived_at, called_at, finished_at, email, stepped_out) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, reason, urgency, preferred, assigned, status, arrived.strftime("%Y-%m-%d %H:%M:%S"),
             (arrived + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S") if assigned else None,
             (arrived + timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S") if status == "done" else None,
             email, int(bool(email))))

    # Tomorrow's appointments, so the day-before reminders have something to send
    tomorrow = today + timedelta(days=1)
    k = 0
    for doctor_id in range(1, 6):
        for slot in all_slots(doctor_id, tomorrow)[:2]:
            if not db.execute("SELECT 1 FROM appointments WHERE doctor_id = ? AND appt_date = ? AND start_time = ?",
                              (doctor_id, tomorrow.isoformat(), slot)).fetchone():
                appt(p[2 + k % 6], doctor_id, tomorrow, slot, reason="Follow-up")
                k += 1
    db.commit()

    # Send the emails a real morning would have produced (printed in the terminal without a mail server)
    import reminders
    import walkins
    walkins.send_near_turn_emails()   # Dan is #2 in line, so he's told his turn is coming
    reminders.send_due()              # day-before reminders for tomorrow


@click.command("seed-demo")
@with_appcontext
def seed_demo_command():
    """Rebuild the database with demo data for presentations."""
    path = current_app.config["DATABASE"]
    if os.path.exists(path):
        os.remove(path)
    init_db()
    seed()
    click.echo("Demo data loaded. Every account's password is: " + DEMO_PASSWORD)
    click.echo("  Clinic admin:  frontdesk@torontomu.ca")
    click.echo("  Doctors:       priya.raman@torontomu.ca, aisha.bello@torontomu.ca")
    click.echo("  Patients:      sam.lee@torontomu.ca, jo.park@torontomu.ca, and 6 more")
    click.echo("The emails printed above are logged on the admin's Emails page.")
