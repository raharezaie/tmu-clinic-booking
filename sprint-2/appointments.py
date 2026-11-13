"""3.0 Book Appointment: the rules for booking, rescheduling and cancelling.

Every page that changes an appointment goes through these functions, so the
rules live in one place and can't drift apart between pages.
"""
import sqlite3
from datetime import datetime, timedelta

from db import get_db
from scheduling import all_slots, bookable_range

MAX_UPCOMING = 3                     # booked appointments a patient can hold at once
CHANGE_CUTOFF = timedelta(hours=2)   # no cancelling/rescheduling closer than this


class BookingError(Exception):
    """A rule was broken. The message is safe to show to the patient."""


def starts_at(appt_date, start_time):
    return datetime.strptime(f"{appt_date} {start_time}", "%Y-%m-%d %H:%M")


def get_doctor(doctor_id):
    return get_db().execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()


def upcoming_count(patient_id):
    now = datetime.now()
    rows = get_db().execute(
        "SELECT appt_date, start_time FROM appointments WHERE patient_id = ? AND status = 'booked'",
        (patient_id,),
    ).fetchall()
    return sum(1 for r in rows if starts_at(r["appt_date"], r["start_time"]) > now)


def check_slot(patient_id, doctor_id, day, time, ignore_appt_id=None):
    """Raise BookingError unless this patient may take this slot.

    ignore_appt_id is the appointment being rescheduled, so it doesn't clash with itself.
    """
    first, last = bookable_range()
    if get_doctor(doctor_id) is None or day is None:
        raise BookingError("That doctor or date doesn't exist. Choose another slot.")
    if not first <= day <= last:
        raise BookingError(f"Choose a date between {first:%b %d} and {last:%b %d}.")
    if time not in all_slots(doctor_id, day):
        raise BookingError("That time isn't in the doctor's schedule. Choose another slot.")
    if starts_at(day.isoformat(), time) <= datetime.now():
        raise BookingError("That time has already passed. Choose a later slot.")

    ignore = ignore_appt_id or 0
    db = get_db()
    if db.execute(
        "SELECT 1 FROM appointments WHERE patient_id = ? AND appt_date = ? AND start_time = ? "
        "AND status = 'booked' AND id != ?",
        (patient_id, day.isoformat(), time, ignore),
    ).fetchone():
        raise BookingError("You already have an appointment at that time.")
    if db.execute(
        "SELECT 1 FROM appointments WHERE patient_id = ? AND doctor_id = ? AND appt_date = ? "
        "AND status = 'booked' AND id != ?",
        (patient_id, doctor_id, day.isoformat(), ignore),
    ).fetchone():
        raise BookingError("You already have an appointment with this doctor that day. Reschedule it instead.")


def book(patient_id, doctor_id, day, time, reason=None):
    """Create a booking and return its id, or raise BookingError."""
    check_slot(patient_id, doctor_id, day, time)
    if upcoming_count(patient_id) >= MAX_UPCOMING:
        raise BookingError(f"You can have up to {MAX_UPCOMING} upcoming appointments. "
                           "Cancel one before booking another.")
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time, reason) VALUES (?, ?, ?, ?, ?)",
            (patient_id, doctor_id, day.isoformat(), time, reason or None),
        )
        db.commit()
    except sqlite3.IntegrityError:  # someone took the slot a moment earlier
        db.rollback()
        raise BookingError("Someone just booked that slot. Choose another time.")
    return cur.lastrowid


def get_for_patient(appt_id, patient_id):
    return get_db().execute(
        """SELECT a.*, d.full_name AS doctor_name, d.specialty, d.department
           FROM appointments a JOIN doctors d ON d.id = a.doctor_id
           WHERE a.id = ? AND a.patient_id = ?""",
        (appt_id, patient_id),
    ).fetchone()


def can_change(appt):
    """Booked appointments can be cancelled or moved until 2 hours before they start."""
    return (appt["status"] == "booked"
            and starts_at(appt["appt_date"], appt["start_time"]) - datetime.now() >= CHANGE_CUTOFF)


def cancel(appt):
    if not can_change(appt):
        raise BookingError("Appointments can't be cancelled less than 2 hours before they start. "
                           "Call the clinic instead.")
    db = get_db()
    db.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ? AND status = 'booked'", (appt["id"],))
    db.commit()


def reschedule(appt, day, time):
    """Move a booking to a new slot with the same doctor."""
    if not can_change(appt):
        raise BookingError("Appointments can't be moved less than 2 hours before they start.")
    check_slot(appt["patient_id"], appt["doctor_id"], day, time, ignore_appt_id=appt["id"])
    db = get_db()
    try:
        db.execute(
            "UPDATE appointments SET appt_date = ?, start_time = ? WHERE id = ? AND status = 'booked'",
            (day.isoformat(), time, appt["id"]),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise BookingError("Someone just booked that slot. Choose another time.")
