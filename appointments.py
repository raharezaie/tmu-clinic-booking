"""Rules for changing an appointment's status and for visit notes, shared by staff and doctors."""
import sqlite3
from datetime import date, datetime, timedelta

from flask import current_app

from db import get_db

PAST_ONLY = {"completed", "no_show"}   # only once the start time has passed
FUTURE_ONLY = {"cancelled"}            # only before it starts
STATUS_DONE = {"completed": "marked completed", "no_show": "marked as a no-show",
               "cancelled": "cancelled", "booked": "set back to booked"}
REASON_MIN, REASON_MAX = 3, 200
NOTE_MAX = 2000
NOTE_EDIT_DAYS = 7


def has_started(appt):
    return f"{appt['appt_date']} {appt['start_time']}" <= datetime.now().strftime("%Y-%m-%d %H:%M")


def can_revert(appt):
    """Doctors can undo completed / no-show until midnight on the visit date."""
    return appt["status"] in PAST_ONLY and appt["appt_date"] == date.today().isoformat()


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def slot_taken_by_other(appt):
    """True if another, still-active appointment now sits in this one's slot (e.g. a walk-in)."""
    return get_db().execute(
        """SELECT 1 FROM appointments WHERE doctor_id = ? AND appt_date = ? AND start_time = ?
           AND id != ? AND status != 'cancelled' AND slot_released_at IS NULL""",
        (appt["doctor_id"], appt["appt_date"], appt["start_time"], appt["id"]),
    ).fetchone() is not None


def change_status(appt, new_status, actor, reason=None):
    """Apply a status change made by clinic staff ("admin") or the doctor ("doctor").
    Returns an error message, or None if the change was saved."""
    old = appt["status"]
    if new_status not in STATUS_DONE:
        return "Unknown status."

    if new_status == "booked":
        if actor != "doctor" or old not in PAST_ONLY:
            return "That visit can't be set back to booked."
        if not can_revert(appt):
            return "Visits can only be set back to booked on the day of the visit."
        if appt["slot_released_at"] and slot_taken_by_other(appt):
            return "That slot has since been given to a walk-in."
    elif new_status in FUTURE_ONLY and has_started(appt):
        return "That appointment has already started. Mark it completed or a no-show instead."
    elif old != "booked":
        return "That appointment was already updated."
    elif new_status in PAST_ONLY and not has_started(appt):
        return "You can only mark a visit completed or a no-show once its start time has passed."
    elif new_status in FUTURE_ONLY:
        reason = (reason or "").strip()
        if not REASON_MIN <= len(reason) <= REASON_MAX:
            return f"Give the patient a reason for cancelling ({REASON_MIN}–{REASON_MAX} characters)."

    db = get_db()
    if new_status == "cancelled":
        cur = db.execute(
            "UPDATE appointments SET status = 'cancelled', cancelled_by = 'clinic', cancel_reason = ? "
            "WHERE id = ? AND status = ?",
            (reason, appt["id"], old),
        )
    elif new_status == "booked":
        # Undo also takes back a released slot (refused above if someone else has it now)
        try:
            cur = db.execute(
                "UPDATE appointments SET status = 'booked', slot_released_at = NULL WHERE id = ? AND status = ?",
                (appt["id"], old),
            )
        except sqlite3.IntegrityError:  # a walk-in was booked into the slot a moment ago
            db.rollback()
            return "That slot has since been given to a walk-in."
    else:
        cur = db.execute("UPDATE appointments SET status = ? WHERE id = ? AND status = ?",
                         (new_status, appt["id"], old))
    db.commit()
    return None if cur.rowcount else "That appointment was already updated."


# ---------- Arrival and late release (booked visits) ----------
def is_today(appt):
    return appt["appt_date"] == date.today().isoformat()


def can_arrive(appt):
    return appt["status"] == "booked" and is_today(appt) and not appt["arrived_at"]


def release_time(appt):
    """When a late, not-arrived booking may be released to walk-ins."""
    start = datetime.strptime(f"{appt['appt_date']} {appt['start_time']}", "%Y-%m-%d %H:%M")
    return start + timedelta(minutes=current_app.config["LATE_GRACE_MINUTES"])


def can_release(appt):
    """Only today's slots: releasing a slot that's already over frees nothing."""
    return (appt["status"] == "booked" and is_today(appt) and not appt["arrived_at"]
            and datetime.now() >= release_time(appt))


def mark_arrived(appt):
    """Record that a booked patient checked in. Returns an error message, or None."""
    if not can_arrive(appt):
        if appt["arrived_at"]:
            return "That patient is already checked in."
        return "Only today's booked visits can be checked in."
    db = get_db()
    cur = db.execute(
        "UPDATE appointments SET arrived_at = ? WHERE id = ? AND status = 'booked' AND arrived_at IS NULL",
        (now_text(), appt["id"]),
    )
    db.commit()
    return None if cur.rowcount else "That appointment was already updated."


def release_slot(appt):
    """Mark a late booking a no-show and free its slot for walk-ins. Returns an error message, or None."""
    if appt["status"] != "booked":
        return "Only booked visits can be released."
    if appt["arrived_at"]:
        return "That patient has checked in, so the slot can't be released."
    if not is_today(appt):
        return "Only today's slots can be released."
    if datetime.now() < release_time(appt):
        return f"The slot can be released from {release_time(appt):%H:%M} if the patient hasn't arrived."
    db = get_db()
    cur = db.execute(
        """UPDATE appointments SET status = 'no_show', slot_released_at = ?
           WHERE id = ? AND status = 'booked' AND arrived_at IS NULL""",
        (now_text(), appt["id"]),
    )
    db.commit()
    return None if cur.rowcount else "That appointment was already updated."


# ---------- Visit notes ----------
def notes_lock_date(appt):
    return datetime.strptime(appt["appt_date"], "%Y-%m-%d").date() + timedelta(days=NOTE_EDIT_DAYS)


def notes_editable(appt):
    """Notes can be written on completed visits, for 7 days after the visit date."""
    return appt["status"] == "completed" and date.today() <= notes_lock_date(appt)


def get_notes(appt_id):
    return get_db().execute("SELECT * FROM visit_notes WHERE appointment_id = ?", (appt_id,)).fetchone()


def save_notes(appt_id, private_note, shared_note):
    def clean(text):
        return (text or "").strip()[:NOTE_MAX] or None

    db = get_db()
    db.execute(
        """INSERT INTO visit_notes (appointment_id, private_note, shared_note) VALUES (?, ?, ?)
           ON CONFLICT (appointment_id) DO UPDATE SET
               private_note = excluded.private_note, shared_note = excluded.shared_note,
               updated_at = datetime('now')""",
        (appt_id, clean(private_note), clean(shared_note)),
    )
    db.commit()
