"""Slot logic for 2.0 Search Availability and 3.0 Book Appointment."""
import sqlite3
from datetime import date, datetime, timedelta

from db import get_db

BOOKING_WINDOW_DAYS = 30


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def bookable_range():
    today = date.today()
    return today, today + timedelta(days=BOOKING_WINDOW_DAYS)


def _times_between(start, end, minutes):
    t = datetime.strptime(start, "%H:%M")
    stop = datetime.strptime(end, "%H:%M")
    while t + timedelta(minutes=minutes) <= stop:
        yield t.strftime("%H:%M")
        t += timedelta(minutes=minutes)


def is_working(doctor_id, day):
    """False if the doctor is inactive or has that day off."""
    row = get_db().execute(
        """SELECT d.active, EXISTS (SELECT 1 FROM doctor_time_off t
                                    WHERE t.doctor_id = d.id AND t.off_date = ?) AS off
           FROM doctors d WHERE d.id = ?""",
        (day.isoformat(), doctor_id),
    ).fetchone()
    return row is not None and row["active"] and not row["off"]


def slot_ranges(doctor_id, day):
    """(start, end) of every slot in a doctor's schedule for that day, booked or not."""
    if not is_working(doctor_id, day):
        return []
    rows = get_db().execute(
        "SELECT start_time, end_time, slot_minutes FROM doctor_schedules WHERE doctor_id = ? AND weekday = ?",
        (doctor_id, day.weekday()),
    ).fetchall()
    ranges = []
    for r in rows:
        for t in _times_between(r["start_time"], r["end_time"], r["slot_minutes"]):
            end = datetime.strptime(t, "%H:%M") + timedelta(minutes=r["slot_minutes"])
            ranges.append((t, end.strftime("%H:%M")))
    return sorted(ranges)


def all_slots(doctor_id, day):
    """Every slot in a doctor's schedule for that day, booked or not."""
    return [start for start, _end in slot_ranges(doctor_id, day)]


def open_slots(doctor_id, day):
    """Slots that are still free and not already in the past."""
    taken = {
        r["start_time"]
        for r in get_db().execute(
            "SELECT start_time FROM appointments WHERE doctor_id = ? AND appt_date = ? AND status = 'booked'",
            (doctor_id, day.isoformat()),
        )
    }
    now = datetime.now()
    result = []
    for s in all_slots(doctor_id, day):
        if s in taken:
            continue
        if day == now.date() and s <= now.strftime("%H:%M"):
            continue
        result.append(s)
    return result


def search_availability(day, specialty=None):
    """Doctors working that day (optionally one specialty) with their open slots."""
    sql = """SELECT DISTINCT d.* FROM doctors d
             JOIN doctor_schedules s ON s.doctor_id = d.id
             WHERE s.weekday = ? AND d.active = 1
               AND NOT EXISTS (SELECT 1 FROM doctor_time_off t WHERE t.doctor_id = d.id AND t.off_date = ?)"""
    params = [day.weekday(), day.isoformat()]
    if specialty:
        sql += " AND d.specialty = ?"
        params.append(specialty)
    sql += " ORDER BY d.specialty, d.full_name"
    return [
        {"doctor": d, "slots": open_slots(d["id"], day)}
        for d in get_db().execute(sql, params).fetchall()
    ]


def specialties():
    return [r["specialty"] for r in get_db().execute(
        "SELECT DISTINCT specialty FROM doctors WHERE active = 1 ORDER BY specialty")]


def book_slot(patient_id, doctor_id, day, time, reason=None, by_staff=False):
    """Check a booking request and save it. Returns an error message, or None if it was booked.

    Used by both the patient booking page and staff booking on a patient's behalf,
    so the server-side checks are the same either way."""
    db = get_db()
    first, last = bookable_range()
    doctor = db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    if doctor is None or day is None or not first <= day <= last or time not in all_slots(doctor["id"], day):
        return "That time isn't available. Choose another slot."
    if datetime.combine(day, datetime.strptime(time, "%H:%M").time()) <= datetime.now():
        return "That time has already passed. Choose a later slot."
    clash = db.execute(
        "SELECT 1 FROM appointments WHERE patient_id = ? AND appt_date = ? AND start_time = ? AND status = 'booked'",
        (patient_id, day.isoformat(), time),
    ).fetchone()
    if clash:
        return ("This patient already has" if by_staff else "You already have") + " an appointment at that time."
    try:
        db.execute(
            "INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time, reason) VALUES (?, ?, ?, ?, ?)",
            (patient_id, doctor["id"], day.isoformat(), time, reason or None),
        )
        db.commit()
    except sqlite3.IntegrityError:  # someone booked the same slot a moment earlier
        return "Someone just booked that slot. Choose another time."
    return None


def future_bookings(doctor_id, weekday=None, day=None, start=None, end=None):
    """Upcoming booked appointments for a doctor, optionally limited to one weekday,
    one date, or a time range. Used to stop schedule changes from stranding patients."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = get_db().execute(
        """SELECT a.*, u.full_name AS patient_name FROM appointments a
           JOIN users u ON u.id = a.patient_id
           WHERE a.doctor_id = ? AND a.status = 'booked'
           ORDER BY a.appt_date, a.start_time""",
        (doctor_id,),
    ).fetchall()
    result = []
    for r in rows:
        when = parse_date(r["appt_date"])
        if f"{r['appt_date']} {r['start_time']}" <= now:
            continue
        if weekday is not None and when.weekday() != weekday:
            continue
        if day is not None and when != day:
            continue
        if start is not None and not start <= r["start_time"] < end:
            continue
        result.append(r)
    return result
