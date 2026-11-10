"""2.0 Search Availability and 3.0 Book Appointment (patients)."""
import sqlite3
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from auth import login_required
from db import get_db
from scheduling import (all_slots, bookable_range, parse_date,
                        search_availability, specialties)

bp = Blueprint("booking", __name__)


@bp.route("/book")
@login_required(role="patient")
def book():
    first, last = bookable_range()
    day = parse_date(request.args.get("date")) or first
    if not first <= day <= last:
        flash(f"Pick a date between {first:%b %d} and {last:%b %d}.", "error")
        day = first
    specialty = request.args.get("specialty") or None
    return render_template(
        "book.html",
        day=day, prev_day=max(first, day - timedelta(days=1)), next_day=min(last, day + timedelta(days=1)),
        first=first, last=last,
        specialty=specialty, specialties=specialties(),
        results=search_availability(day, specialty),
    )


@bp.route("/book", methods=("POST",))
@login_required(role="patient")
def confirm():
    db = get_db()
    day = parse_date(request.form.get("date"))
    time = request.form.get("time", "")
    reason = request.form.get("reason", "").strip()[:300]
    doctor = db.execute("SELECT * FROM doctors WHERE id = ?", (request.form.get("doctor_id"),)).fetchone()
    first, last = bookable_range()
    back = url_for("booking.book", date=day.isoformat() if day else None)

    # Re-check everything on the server: never trust the form
    if doctor is None or day is None or not first <= day <= last or time not in all_slots(doctor["id"], day):
        flash("That time isn't available. Choose another slot.", "error")
        return redirect(back)
    if datetime.combine(day, datetime.strptime(time, "%H:%M").time()) <= datetime.now():
        flash("That time has already passed. Choose a later slot.", "error")
        return redirect(back)
    clash = db.execute(
        "SELECT 1 FROM appointments WHERE patient_id = ? AND appt_date = ? AND start_time = ? AND status = 'booked'",
        (g.user["id"], day.isoformat(), time),
    ).fetchone()
    if clash:
        flash("You already have an appointment at that time.", "error")
        return redirect(back)

    try:
        db.execute(
            "INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time, reason) VALUES (?, ?, ?, ?, ?)",
            (g.user["id"], doctor["id"], day.isoformat(), time, reason or None),
        )
        db.commit()
    except sqlite3.IntegrityError:  # someone booked the same slot a moment earlier
        flash("Someone just booked that slot. Choose another time.", "error")
        return redirect(back)

    flash(f"Booked with {doctor['full_name']} on {day:%A, %B %d} at {time}.", "success")
    return redirect(url_for("booking.my_appointments"))


@bp.route("/appointments")
@login_required(role="patient")
def my_appointments():
    rows = get_db().execute(
        """SELECT a.*, d.full_name AS doctor_name, d.specialty
           FROM appointments a JOIN doctors d ON d.id = a.doctor_id
           WHERE a.patient_id = ?
           ORDER BY a.appt_date, a.start_time""",
        (g.user["id"],),
    ).fetchall()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    upcoming = [r for r in rows if r["status"] == "booked" and f"{r['appt_date']} {r['start_time']}" > now]
    history = [r for r in rows if r not in upcoming][::-1]
    return render_template("appointments.html", upcoming=upcoming, history=history)


@bp.route("/appointments/<int:appt_id>/cancel", methods=("POST",))
@login_required(role="patient")
def cancel(appt_id):
    db = get_db()
    cur = db.execute(
        "UPDATE appointments SET status = 'cancelled' WHERE id = ? AND patient_id = ? AND status = 'booked'",
        (appt_id, g.user["id"]),
    )
    db.commit()
    flash("Appointment cancelled." if cur.rowcount else "That appointment can't be cancelled.",
          "success" if cur.rowcount else "error")
    return redirect(url_for("booking.my_appointments"))
