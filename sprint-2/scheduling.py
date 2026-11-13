"""Slot logic for 2.0 Search Availability."""
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
             WHERE s.weekday = ?"""
    params = [day.weekday()]
    if specialty:
        sql += " AND d.specialty = ?"
        params.append(specialty)
    sql += " ORDER BY d.specialty, d.full_name"
    return [
        {"doctor": d, "slots": open_slots(d["id"], day)}
        for d in get_db().execute(sql, params).fetchall()
    ]


def specialties():
    return [r["specialty"] for r in get_db().execute("SELECT DISTINCT specialty FROM doctors ORDER BY specialty")]


# ---------- Sprint 2: doctor availability page ----------
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def weekly_hours(doctor_id):
    """A doctor's regular shifts, e.g. [("Monday", "09:00", "12:00"), ...]."""
    rows = get_db().execute(
        "SELECT weekday, start_time, end_time FROM doctor_schedules WHERE doctor_id = ? ORDER BY weekday, start_time",
        (doctor_id,),
    ).fetchall()
    return [(WEEKDAYS[r["weekday"]], r["start_time"], r["end_time"]) for r in rows]


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


def availability_week(doctor_id, start):
    """Seven days from `start` (clipped to the booking window) with each day's open slots."""
    first, last = bookable_range()
    days = []
    for i in range(7):
        day = start + timedelta(days=i)
        if first <= day <= last:
            days.append({"date": day, "working": bool(all_slots(doctor_id, day)), "slots": open_slots(doctor_id, day)})
    return days


def list_doctors(specialty=None):
    sql, params = "SELECT * FROM doctors", []
    if specialty:
        sql += " WHERE specialty = ?"
        params.append(specialty)
    return get_db().execute(sql + " ORDER BY specialty, full_name", params).fetchall()
