"""Clinic check-in tablet: walk-ins join a queue, booked patients mark themselves arrived.
The tablet logs in with its own kiosk account and can open nothing else. Its answers never
say whether an account exists for the details someone typed."""
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from appointments import mark_arrived
from auth import login_required
from db import get_db
from walkins import check_in, close_stale, walk_in_specialties

bp = Blueprint("kiosk", __name__, url_prefix="/kiosk")

NOT_FOUND = "We couldn't find a booking for today with those details. Please see the front desk."


@bp.route("")
@login_required(role="kiosk")
def home():
    close_stale()
    return render_template("kiosk.html", specialties=walk_in_specialties())


@bp.route("/walk-in", methods=("POST",))
@login_required(role="kiosk")
def walk_in():
    f = request.form
    error, info = check_in(f.get("full_name", ""), f.get("student_id", ""), f.get("email", ""),
                           f.get("specialty", ""), f.get("reason"))
    if error:
        flash(error, "error")
    else:
        when = "you should be seen shortly" if info["estimate"] == "now" else (
            f"your estimated time is {info['estimate']}" if info["estimate"] else "please see the front desk")
        flash(f"You're #{info['position']} in line for {info['specialty']}; {when}. Please take a seat.", "success")
    return redirect(url_for("kiosk.home"))


@bp.route("/arrive", methods=("POST",))
@login_required(role="kiosk")
def arrive():
    email = request.form.get("email", "").strip().lower()
    student_id = request.form.get("student_id", "").strip()
    appt = get_db().execute(
        """SELECT a.*, d.full_name AS doctor_name FROM appointments a
           JOIN users u ON u.id = a.patient_id JOIN doctors d ON d.id = a.doctor_id
           WHERE u.role = 'patient' AND u.email = ? AND u.student_id = ?
             AND a.appt_date = ? AND a.status = 'booked'
           ORDER BY a.arrived_at IS NOT NULL, a.start_time LIMIT 1""",
        (email, student_id, date.today().isoformat()),
    ).fetchone() if email and student_id else None
    if appt is None:
        flash(NOT_FOUND, "error")
    elif appt["arrived_at"]:
        flash(f"You're already checked in for {appt['start_time']} with {appt['doctor_name']}.", "info")
    elif mark_arrived(appt) is None:
        flash(f"You're checked in for {appt['start_time']} with {appt['doctor_name']}. Please take a seat.", "success")
    else:
        flash(NOT_FOUND, "error")
    return redirect(url_for("kiosk.home"))
