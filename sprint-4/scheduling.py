"""Slot logic for 2.0 Search Availability, plus doctors' weekly hours."""
from datetime import date, datetime, timedelta

from db import get_db

BOOKING_WINDOW_DAYS = 30
CHANGE_CUTOFF = timedelta(hours=2)   # patients can't cancel/move closer than this,
                                     # and the wait list doesn't fill slots closer than this


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


def all_slots(doctor_id, day):
    """Every slot in a doctor's schedule for that day, booked or not."""
    rows = get_db().execute(
        "SELECT start_time, end_time, slot_minutes FROM doctor_schedules WHERE doctor_id = ? AND weekday = ?",
        (doctor_id, day.weekday()),
    ).fetchall()
    slots = []
    for r in rows:
        slots.extend(_times_between(r["start_time"], r["end_time"], r["slot_minutes"]))
    return sorted(slots)


def open_slots(doctor_id, day):
    """Slots that are still free and not already in the past."""
    taken = {
        r["start_time"]
        for r in get_db().execute(
            "SELECT start_time FROM appointments WHERE doctor_id = ? AND appt_date = ? AND status != 'cancelled'",
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
             WHERE s.weekday = ?"""
    params = [day.weekday()]
    if specialty:
        sql += " AND d.specialty = ?"
        params.append(specialty)
    sql += " ORDER BY d.specialty, d.full_name"
    results = []
    for d in get_db().execute(sql, params).fetchall():
        slots = open_slots(d["id"], day)
        results.append({"doctor": d, "slots": slots,
                        "can_wait": not slots and time_left_to_fill(d["id"], day)})
    return results


def specialties():
    return [r["specialty"] for r in get_db().execute("SELECT DISTINCT specialty FROM doctors ORDER BY specialty")]


# ---------- Sprint 2: doctor availability page ----------
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def weekly_hours(doctor_id):
    """A doctor's regular shifts, e.g. [("Monday", "09:00", "12:00"), ...]."""
    return [(WEEKDAYS[r["weekday"]], r["start_time"], r["end_time"]) for r in shifts(doctor_id)]


def shifts(doctor_id):
    return get_db().execute(
        "SELECT * FROM doctor_schedules WHERE doctor_id = ? ORDER BY weekday, start_time", (doctor_id,)
    ).fetchall()


def next_open_slot(doctor_id):
    """The earliest free slot in the booking window, as (date, "HH:MM"), or None."""
    first, last = bookable_range()
    day = first
    while day <= last:
        slots = open_slots(doctor_id, day)
        if slots:
            return day, slots[0]
        day += timedelta(days=1)
    return None


def time_left_to_fill(doctor_id, day):
    """True if the doctor still has a slot that day far enough ahead for the wait list to fill.

    Sprint 4 fix: patients could join the wait list for a day whose hours were already over.
    """
    soonest = datetime.now() + CHANGE_CUTOFF
    return any(datetime.combine(day, datetime.strptime(t, "%H:%M").time()) >= soonest
               for t in all_slots(doctor_id, day))


def availability_week(doctor_id, start):
    """Seven days from `start` (clipped to the booking window) with each day's open slots."""
    first, last = bookable_range()
    days = []
    for i in range(7):
        day = start + timedelta(days=i)
        if first <= day <= last:
            slots = open_slots(doctor_id, day)
            days.append({"date": day, "working": bool(all_slots(doctor_id, day)), "slots": slots,
                         "can_wait": not slots and time_left_to_fill(doctor_id, day)})
    return days


def list_doctors(specialty=None):
    sql, params = "SELECT * FROM doctors", []
    if specialty:
        sql += " WHERE specialty = ?"
        params.append(specialty)
    return get_db().execute(sql + " ORDER BY specialty, full_name", params).fetchall()



# ---------- Sprint 3: doctors (and admins) edit weekly hours ----------
class ShiftError(Exception):
    """A shift change was refused. The message is safe to show."""


def _valid_time(t):
    try:
        parsed = datetime.strptime(t, "%H:%M")
    except (TypeError, ValueError):
        return False
    return parsed.minute in (0, 30)


def add_shift(doctor_id, weekday, start, end):
    if weekday not in range(7):
        raise ShiftError("Choose a day of the week.")
    if not (_valid_time(start) and _valid_time(end)):
        raise ShiftError("Times must be on the hour or half hour, like 09:00 or 13:30.")
    if start >= end:
        raise ShiftError("The shift must end after it starts.")
    for s in shifts(doctor_id):
        if s["weekday"] == weekday and start < s["end_time"] and s["start_time"] < end:
            raise ShiftError(f"That overlaps an existing {WEEKDAYS[weekday]} shift "
                             f"({s['start_time']}–{s['end_time']}).")
    db = get_db()
    db.execute("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
               (doctor_id, weekday, start, end))
    db.commit()


def remove_shift(doctor_id, shift_id):
    """Delete a shift, unless patients are already booked into it."""
    db = get_db()
    shift = db.execute("SELECT * FROM doctor_schedules WHERE id = ? AND doctor_id = ?",
                       (shift_id, doctor_id)).fetchone()
    if shift is None:
        raise ShiftError("That shift doesn't exist.")
    today = date.today().isoformat()
    booked = [
        r for r in db.execute(
            "SELECT appt_date, start_time FROM appointments WHERE doctor_id = ? AND status = 'booked' AND appt_date >= ?",
            (doctor_id, today))
        if datetime.strptime(r["appt_date"], "%Y-%m-%d").weekday() == shift["weekday"]
        and shift["start_time"] <= r["start_time"] < shift["end_time"]
    ]
    if booked:
        raise ShiftError(f"{len(booked)} upcoming appointment(s) fall in this shift. "
                         "Cancel or move them before removing it.")
    db.execute("DELETE FROM doctor_schedules WHERE id = ?", (shift_id,))
    db.commit()
