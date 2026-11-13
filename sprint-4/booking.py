"""2.0 Search Availability and 3.0 Book Appointment (patient pages).

The rules themselves live in appointments.py; this file handles the pages.
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import appointments
from appointments import BookingError
from auth import login_required
from db import get_db
from scheduling import (availability_week, bookable_range, parse_date,
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


@bp.route("/book/review")
@login_required(role="patient")
def review():
    """Confirmation step for a slot picked on a doctor's availability page."""
    doctor = appointments.get_doctor(request.args.get("doctor_id"))
    day = parse_date(request.args.get("date"))
    time = request.args.get("time", "")
    try:
        if doctor is None:
            raise BookingError("That doctor doesn't exist.")
        appointments.check_slot(g.user["id"], doctor["id"], day, time)
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("doctors.detail", doctor_id=doctor["id"]) if doctor else url_for("doctors.index"))
    return render_template("review.html", doctor=doctor, day=day, time=time)


@bp.route("/book", methods=("POST",))
@login_required(role="patient")
def confirm():
    day = parse_date(request.form.get("date"))
    time = request.form.get("time", "")
    reason = request.form.get("reason", "").strip()[:300]
    doctor_id = request.form.get("doctor_id", type=int)
    try:
        appt_id = appointments.book(g.user["id"], doctor_id, day, time, reason)
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("booking.book", date=day.isoformat() if day else None))
    doctor = appointments.get_doctor(doctor_id)
    flash(f"Booked with {doctor['full_name']} on {day:%A, %B %d} at {time}.", "success")
    return redirect(url_for("booking.detail", appt_id=appt_id))


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
    now = datetime.now()
    upcoming = [r for r in rows
                if r["status"] == "booked" and appointments.starts_at(r["appt_date"], r["start_time"]) > now]
    history = [r for r in rows if r not in upcoming][::-1]
    db = get_db()
    appointments.expire_old_waitlist()
    waits = db.execute(
        """SELECT w.*, d.full_name AS doctor_name, d.specialty FROM waitlist w JOIN doctors d ON d.id = w.doctor_id
           WHERE w.patient_id = ? AND w.status = 'waiting' ORDER BY w.wait_date""",
        (g.user["id"],),
    ).fetchall()
    return render_template("appointments.html", upcoming=upcoming, history=history,
                           can_change=appointments.can_change, limit=appointments.MAX_UPCOMING,
                           waits=[{"w": w, "position": appointments.waitlist_position(w)} for w in waits])


def _own_appointment(appt_id):
    appt = appointments.get_for_patient(appt_id, g.user["id"])
    if appt is None:
        abort(404)
    return appt


@bp.route("/appointments/<int:appt_id>")
@login_required(role="patient")
def detail(appt_id):
    appt = _own_appointment(appt_id)
    return render_template("appointment_detail.html", a=appt, can_change=appointments.can_change(appt))


@bp.route("/appointments/<int:appt_id>/cancel", methods=("POST",))
@login_required(role="patient")
def cancel(appt_id):
    appt = _own_appointment(appt_id)
    try:
        appointments.cancel(appt)
        flash("Appointment cancelled.", "success")
    except BookingError as e:
        flash(str(e), "error")
    return redirect(url_for("booking.my_appointments"))


@bp.route("/appointments/<int:appt_id>/reschedule", methods=("GET", "POST"))
@login_required(role="patient")
def reschedule(appt_id):
    appt = _own_appointment(appt_id)
    if not appointments.can_change(appt):
        flash("This appointment can't be moved anymore. Call the clinic if you need help.", "error")
        return redirect(url_for("booking.detail", appt_id=appt_id))

    if request.method == "POST":
        day = parse_date(request.form.get("date"))
        time = request.form.get("time", "")
        try:
            appointments.reschedule(appt, day, time)
            flash(f"Moved to {day:%A, %B %d} at {time}.", "success")
            return redirect(url_for("booking.detail", appt_id=appt_id))
        except BookingError as e:
            flash(str(e), "error")

    first, last = bookable_range()
    start = parse_date(request.args.get("start")) or first
    start = min(max(start, first), last)
    return render_template(
        "reschedule.html", a=appt, days=availability_week(appt["doctor_id"], start), today=date.today(),
        prev_start=max(first, start - timedelta(days=7)) if start > first else None,
        next_start=start + timedelta(days=7) if start + timedelta(days=7) <= last else None,
    )



# ---------- Sprint 3: wait list and notifications ----------
@bp.route("/waitlist", methods=("POST",))
@login_required(role="patient")
def join_waitlist():
    day = parse_date(request.form.get("date"))
    doctor_id = request.form.get("doctor_id", type=int)
    try:
        appointments.join_waitlist(g.user["id"], doctor_id, day)
        flash(f"You're on the wait list for {day:%A, %B %d}. If a time opens up, "
              "you'll be booked automatically and see a message here.", "success")
        return redirect(url_for("booking.my_appointments"))
    except BookingError as e:
        flash(str(e), "error")
        return redirect(request.referrer if _same_site(request.referrer) else url_for("booking.book"))


def _same_site(url):
    return bool(url) and url.startswith(request.host_url)


@bp.route("/waitlist/<int:entry_id>/leave", methods=("POST",))
@login_required(role="patient")
def leave_waitlist(entry_id):
    if appointments.leave_waitlist(entry_id, g.user["id"]):
        flash("You've left the wait list.", "success")
    else:
        flash("You're not on that wait list anymore.", "error")
    return redirect(url_for("booking.my_appointments"))


# ---------- Sprint 4: patient message center ----------
@bp.route("/messages")
@login_required(role="patient")
def messages():
    """Every notification the patient has had: reminders, wait-list bookings, cancellations.

    New ones are highlighted this time, then counted as read.
    """
    db = get_db()
    rows = db.execute(
        """SELECT n.*, a.appt_date, a.start_time, a.status AS appt_status
           FROM notifications n LEFT JOIN appointments a ON a.id = n.appointment_id
           WHERE n.user_id = ? ORDER BY n.id DESC""",
        (g.user["id"],),
    ).fetchall()
    db.execute("UPDATE notifications SET read_at = datetime('now', 'localtime') WHERE user_id = ? AND read_at IS NULL",
               (g.user["id"],))
    db.commit()
    return render_template("messages.html", messages=rows, unread=0,
                           new_count=sum(1 for r in rows if r["read_at"] is None))


@bp.app_context_processor
def unread_count():
    """Lets base.html show a badge when a patient has new messages."""
    if g.get("user") is None or g.user["role"] != "patient":
        return {"unread": 0}
    n = get_db().execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
                         (g.user["id"],)).fetchone()[0]
    return {"unread": n}
