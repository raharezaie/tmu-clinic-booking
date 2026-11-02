"""2.0 Search Availability and 3.0 Book Appointment (patients)."""
from datetime import datetime, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from auth import login_required
from db import get_db
from scheduling import (book_slot, bookable_range, parse_date,
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
    day = parse_date(request.form.get("date"))
    time = request.form.get("time", "")
    reason = request.form.get("reason", "").strip()[:300]
    error = book_slot(g.user["id"], request.form.get("doctor_id"), day, time, reason)
    if error:
        flash(error, "error")
        return redirect(url_for("booking.book", date=day.isoformat() if day else None))
    doctor = get_db().execute("SELECT full_name FROM doctors WHERE id = ?", (request.form.get("doctor_id"),)).fetchone()
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
