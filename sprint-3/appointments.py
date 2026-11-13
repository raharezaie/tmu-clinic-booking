"""3.0 Book Appointment: booking rules, wait list and appointment status logic.

Every page that changes an appointment or the wait list goes through these
functions, so the rules live in one place.

Appointment life cycle:

    booked ──check in──▶ checked_in ──▶ completed
      │                      │
      ├──────────────────────┴──▶ no_show   (after the start time)
      └──▶ cancelled  (by the patient, or by the clinic)

When a booking is cancelled or moved, the freed slot goes straight to the
first eligible patient on that doctor's wait list for that day.
"""
import sqlite3
from datetime import date, datetime, timedelta

from db import get_db
from scheduling import all_slots, bookable_range, open_slots

MAX_UPCOMING = 3                     # active appointments a patient can hold at once
MAX_WAITLISTS = 3                    # wait lists a patient can be on at once
CHANGE_CUTOFF = timedelta(hours=2)   # patients can't cancel/move closer than this,
                                     # and the wait list doesn't fill slots closer than this
ACTIVE = ("booked", "checked_in")    # statuses that still hold a future slot


class BookingError(Exception):
    """A rule was broken. The message is safe to show to the user."""


def starts_at(appt_date, start_time):
    return datetime.strptime(f"{appt_date} {start_time}", "%Y-%m-%d %H:%M")


def get_doctor(doctor_id):
    return get_db().execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()


def get(appt_id):
    """An appointment with doctor and patient names, or None."""
    return get_db().execute(
        """SELECT a.*, d.full_name AS doctor_name, d.specialty, d.department,
                  u.full_name AS patient_name, u.email AS patient_email, u.student_id
           FROM appointments a
           JOIN doctors d ON d.id = a.doctor_id
           JOIN users u ON u.id = a.patient_id
           WHERE a.id = ?""",
        (appt_id,),
    ).fetchone()


def get_for_patient(appt_id, patient_id):
    appt = get(appt_id)
    return appt if appt is not None and appt["patient_id"] == patient_id else None


def notify(user_id, message):
    get_db().execute("INSERT INTO notifications (user_id, message) VALUES (?, ?)", (user_id, message))


def upcoming_count(patient_id):
    now = datetime.now()
    rows = get_db().execute(
        "SELECT appt_date, start_time FROM appointments WHERE patient_id = ? AND status IN ('booked', 'checked_in')",
        (patient_id,),
    ).fetchall()
    return sum(1 for r in rows if starts_at(r["appt_date"], r["start_time"]) > now)


# ---------- Booking ----------
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
        "AND status IN ('booked', 'checked_in') AND id != ?",
        (patient_id, day.isoformat(), time, ignore),
    ).fetchone():
        raise BookingError("You already have an appointment at that time.")
    if db.execute(
        "SELECT 1 FROM appointments WHERE patient_id = ? AND doctor_id = ? AND appt_date = ? "
        "AND status IN ('booked', 'checked_in') AND id != ?",
        (patient_id, doctor_id, day.isoformat(), ignore),
    ).fetchone():
        raise BookingError("You already have an appointment with this doctor that day. Reschedule it instead.")


def _insert(patient_id, doctor_id, day, time, reason, source):
    """Insert a booking. Raises sqlite3.IntegrityError if the slot was just taken."""
    cur = get_db().execute(
        "INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time, reason, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (patient_id, doctor_id, day.isoformat(), time, reason or None, source),
    )
    # Booking with a doctor for a day takes the patient off that day's wait list
    get_db().execute(
        "UPDATE waitlist SET status = 'booked', appointment_id = ? "
        "WHERE patient_id = ? AND doctor_id = ? AND wait_date = ? AND status = 'waiting'",
        (cur.lastrowid, patient_id, doctor_id, day.isoformat()),
    )
    return cur.lastrowid


def book(patient_id, doctor_id, day, time, reason=None):
    """Create a booking and return its id, or raise BookingError."""
    check_slot(patient_id, doctor_id, day, time)
    if upcoming_count(patient_id) >= MAX_UPCOMING:
        raise BookingError(f"You can have up to {MAX_UPCOMING} upcoming appointments. "
                           "Cancel one before booking another.")
    db = get_db()
    try:
        appt_id = _insert(patient_id, doctor_id, day, time, reason, "online")
        db.commit()
    except sqlite3.IntegrityError:  # someone took the slot a moment earlier
        db.rollback()
        raise BookingError("Someone just booked that slot. Choose another time.")
    return appt_id


def can_change(appt):
    """Patients can cancel or move a booking until 2 hours before it starts."""
    return (appt["status"] == "booked"
            and starts_at(appt["appt_date"], appt["start_time"]) - datetime.now() >= CHANGE_CUTOFF)


def cancel(appt, by="patient"):
    """Cancel a booking. Patients are held to the 2-hour cutoff; the clinic isn't.

    Returns the patient who got the slot from the wait list, or None.
    """
    if by == "patient" and not can_change(appt):
        raise BookingError("Appointments can't be cancelled less than 2 hours before they start. "
                           "Call the clinic instead.")
    if appt["status"] not in ACTIVE:
        raise BookingError("Only booked appointments can be cancelled.")
    db = get_db()
    db.execute("UPDATE appointments SET status = 'cancelled', cancelled_by = ? WHERE id = ?", (by, appt["id"]))
    if by == "clinic":
        notify(appt["patient_id"], f"The clinic cancelled your appointment with {appt['doctor_name']} on "
                                   f"{appt['appt_date']} at {appt['start_time']}. Please book a new time.")
    db.commit()
    return promote_waitlist(appt["doctor_id"], appt["appt_date"], appt["start_time"])


def reschedule(appt, day, time):
    """Move a booking to a new slot with the same doctor. The old slot goes to the wait list."""
    if not can_change(appt):
        raise BookingError("Appointments can't be moved less than 2 hours before they start.")
    check_slot(appt["patient_id"], appt["doctor_id"], day, time, ignore_appt_id=appt["id"])
    db = get_db()
    try:
        db.execute("UPDATE appointments SET appt_date = ?, start_time = ? WHERE id = ? AND status = 'booked'",
                   (day.isoformat(), time, appt["id"]))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise BookingError("Someone just booked that slot. Choose another time.")
    promote_waitlist(appt["doctor_id"], appt["appt_date"], appt["start_time"])


# ---------- Wait list ----------
def expire_old_waitlist():
    """Entries for days that have passed are closed."""
    db = get_db()
    db.execute("UPDATE waitlist SET status = 'expired' WHERE status = 'waiting' AND wait_date < ?",
               (date.today().isoformat(),))
    db.commit()


def join_waitlist(patient_id, doctor_id, day):
    """Put a patient on the wait list for a doctor's fully booked day."""
    first, last = bookable_range()
    if get_doctor(doctor_id) is None or day is None or not first <= day <= last:
        raise BookingError("Choose a doctor and a date within the next 30 days.")
    if not all_slots(doctor_id, day):
        raise BookingError("The doctor doesn't work that day.")
    if open_slots(doctor_id, day):
        raise BookingError("There are still open times that day, so you can book one directly.")
    db = get_db()
    if db.execute(
        "SELECT 1 FROM appointments WHERE patient_id = ? AND doctor_id = ? AND appt_date = ? "
        "AND status IN ('booked', 'checked_in')",
        (patient_id, doctor_id, day.isoformat()),
    ).fetchone():
        raise BookingError("You already have an appointment with this doctor that day.")
    expire_old_waitlist()
    waiting = db.execute("SELECT COUNT(*) FROM waitlist WHERE patient_id = ? AND status = 'waiting'",
                         (patient_id,)).fetchone()[0]
    if waiting >= MAX_WAITLISTS:
        raise BookingError(f"You can be on up to {MAX_WAITLISTS} wait lists at once. Leave one first.")
    try:
        db.execute("INSERT INTO waitlist (patient_id, doctor_id, wait_date) VALUES (?, ?, ?)",
                   (patient_id, doctor_id, day.isoformat()))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise BookingError("You're already on the wait list for that day.")


def leave_waitlist(entry_id, patient_id):
    db = get_db()
    cur = db.execute("UPDATE waitlist SET status = 'left' WHERE id = ? AND patient_id = ? AND status = 'waiting'",
                     (entry_id, patient_id))
    db.commit()
    return cur.rowcount == 1


def waitlist_position(entry):
    return get_db().execute(
        "SELECT COUNT(*) FROM waitlist WHERE doctor_id = ? AND wait_date = ? AND status = 'waiting' "
        "AND created_at <= ?",
        (entry["doctor_id"], entry["wait_date"], entry["created_at"]),
    ).fetchone()[0]


def promote_waitlist(doctor_id, appt_date, start_time):
    """Give a freed slot to the first eligible patient waiting for that doctor and day.

    Patients who can't take it (they have a clash, or are at their booking limit)
    are skipped but stay on the list. Returns the patient's user row, or None.
    """
    day = datetime.strptime(appt_date, "%Y-%m-%d").date()
    if starts_at(appt_date, start_time) - datetime.now() < CHANGE_CUTOFF:
        return None  # too late to hand the slot to someone who may not see the message
    if start_time not in open_slots(doctor_id, day):
        return None  # already taken again
    db = get_db()
    doctor = get_doctor(doctor_id)
    queue = db.execute(
        "SELECT w.*, u.full_name FROM waitlist w JOIN users u ON u.id = w.patient_id "
        "WHERE w.doctor_id = ? AND w.wait_date = ? AND w.status = 'waiting' ORDER BY w.created_at, w.id",
        (doctor_id, appt_date),
    ).fetchall()
    for entry in queue:
        try:
            check_slot(entry["patient_id"], doctor_id, day, start_time)
        except BookingError:
            continue
        if upcoming_count(entry["patient_id"]) >= MAX_UPCOMING:
            continue
        try:
            _insert(entry["patient_id"], doctor_id, day, start_time, None, "waitlist")
        except sqlite3.IntegrityError:
            db.rollback()
            return None
        notify(entry["patient_id"], f"Good news: a spot opened up and you're booked with {doctor['full_name']} "
                                    f"on {day:%A, %B %d} at {start_time}. Cancel it if you can't make it.")
        db.commit()
        return entry
    return None


# ---------- Clinic actions: check in, complete, no-show ----------
def check_in(appt):
    if appt["status"] != "booked":
        raise BookingError("Only booked appointments can be checked in.")
    if appt["appt_date"] != date.today().isoformat():
        raise BookingError("Patients can only be checked in on the day of their appointment.")
    _set_status(appt, "checked_in")


def complete(appt, notes=None):
    if appt["status"] not in ACTIVE:
        raise BookingError("Only booked or checked-in appointments can be completed.")
    if appt["appt_date"] > date.today().isoformat():
        raise BookingError("You can't complete an appointment that's on a future day.")
    db = get_db()
    db.execute("UPDATE appointments SET status = 'completed', visit_notes = ? WHERE id = ?",
               ((notes or "").strip()[:2000] or None, appt["id"]))
    db.commit()


def no_show(appt):
    if appt["status"] != "booked":
        raise BookingError("Only booked appointments can be marked as no-show.")
    if starts_at(appt["appt_date"], appt["start_time"]) > datetime.now():
        raise BookingError("You can only mark a no-show after the appointment's start time.")
    _set_status(appt, "no_show")


def _set_status(appt, status):
    db = get_db()
    db.execute("UPDATE appointments SET status = ? WHERE id = ?", (status, appt["id"]))
    db.commit()
