"""Clinic doctor dashboard (Sprint 3): the doctor's day, walk-ins and weekly hours."""
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import appointments
import walkins
from appointments import BookingError
from auth import login_required
from db import get_db
from scheduling import WEEKDAYS, ShiftError, add_shift, all_slots, parse_date, remove_shift, shifts

bp = Blueprint("doctor", __name__, url_prefix="/doctor")


def my_profile():
    """The doctors row linked to the logged-in doctor's account."""
    profile = get_db().execute("SELECT * FROM doctors WHERE user_id = ?", (g.user["id"],)).fetchone()
    if profile is None:
        abort(403)
    return profile


def day_appointments(doctor_id, day):
    return get_db().execute(
        """SELECT a.*, u.full_name AS patient_name, u.email AS patient_email, u.student_id
           FROM appointments a JOIN users u ON u.id = a.patient_id
           WHERE a.doctor_id = ? AND a.appt_date = ?
           ORDER BY a.start_time, a.status = 'cancelled'""",
        (doctor_id, day.isoformat()),
    ).fetchall()


def day_waitlist(doctor_id, day):
    return get_db().execute(
        """SELECT w.*, u.full_name AS patient_name FROM waitlist w JOIN users u ON u.id = w.patient_id
           WHERE w.doctor_id = ? AND w.wait_date = ? AND w.status = 'waiting' ORDER BY w.created_at, w.id""",
        (doctor_id, day.isoformat()),
    ).fetchall()


@bp.route("/dashboard")
@login_required(role="doctor")
def dashboard():
    doctor = my_profile()
    day = parse_date(request.args.get("date")) or date.today()
    appts = day_appointments(doctor["id"], day)
    active = [a for a in appts if a["status"] != "cancelled"]
    now = datetime.now()
    summary = {
        "slots": len(all_slots(doctor["id"], day)),
        "booked": len(active),
        "checked_in": sum(a["status"] == "checked_in" for a in active),
        "completed": sum(a["status"] == "completed" for a in active),
        "no_show": sum(a["status"] == "no_show" for a in active),
    }
    is_today = day == date.today()
    walk = None
    if is_today:
        q = walkins.todays_queue()
        walk = {
            "with_me": [w for w in q["with_doctor"] if w["assigned_doctor_id"] == doctor["id"]],
            "waiting": walkins.waiting_for_doctor(doctor["id"]),
        }
    return render_template(
        "doctor_dashboard.html", doctor=doctor, day=day, appts=appts, summary=summary,
        waitlist=day_waitlist(doctor["id"], day), walk=walk, is_today=is_today,
        started=lambda a: appointments.starts_at(a["appt_date"], a["start_time"]) <= now,
        prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1),
    )


def _my_appointment(appt_id, doctor):
    appt = appointments.get(appt_id)
    if appt is None or appt["doctor_id"] != doctor["id"]:
        abort(404)
    return appt


@bp.route("/appointments/<int:appt_id>/<action>", methods=("POST",))
@login_required(role="doctor")
def appointment_action(appt_id, action):
    doctor = my_profile()
    appt = _my_appointment(appt_id, doctor)
    try:
        if action == "complete":
            appointments.complete(appt, request.form.get("notes"))
            flash(f"Visit with {appt['patient_name']} marked complete.", "success")
        elif action == "no-show":
            appointments.no_show(appt)
            flash(f"{appt['patient_name']} marked as no-show.", "success")
        elif action == "cancel":
            filled = appointments.cancel(appt, by="clinic")
            flash(f"Appointment cancelled and {appt['patient_name']} notified."
                  + (f" The slot went to {filled['full_name']} from the wait list." if filled else ""), "success")
        else:
            abort(404)
    except BookingError as e:
        flash(str(e), "error")
    return redirect(url_for("doctor.dashboard", date=appt["appt_date"]))


@bp.route("/walk-ins/call-next", methods=("POST",))
@login_required(role="doctor")
def call_next():
    doctor = my_profile()
    entry = walkins.next_for_doctor(doctor["id"])
    if entry is None:
        flash("No walk-ins are waiting for you.", "info")
    else:
        try:
            walkins.call(entry, doctor["id"])
            flash(f"Called in {entry['patient_name']}{' (urgent)' if entry['urgency'] == 'urgent' else ''}.",
                  "success")
        except walkins.WalkInError as e:
            flash(str(e), "error")
    return redirect(url_for("doctor.dashboard"))


@bp.route("/walk-ins/<int:entry_id>/done", methods=("POST",))
@login_required(role="doctor")
def walkin_done(entry_id):
    doctor = my_profile()
    entry = walkins.get(entry_id)
    if entry is None or entry["assigned_doctor_id"] != doctor["id"]:
        abort(404)
    try:
        walkins.finish(entry, "done")
        flash(f"Finished with {entry['patient_name']}.", "success")
    except walkins.WalkInError as e:
        flash(str(e), "error")
    return redirect(url_for("doctor.dashboard"))


# ---------- Weekly hours (shared with the admin's doctor management) ----------
def handle_hours(doctor, back_endpoint, **back_args):
    """GET shows the doctor's shifts; POST adds or removes one."""
    if request.method == "POST":
        try:
            if request.form.get("action") == "remove":
                remove_shift(doctor["id"], request.form.get("shift_id", type=int))
                flash("Shift removed.", "success")
            else:
                add_shift(doctor["id"], request.form.get("weekday", type=int),
                          request.form.get("start_time", ""), request.form.get("end_time", ""))
                filled = appointments.fill_new_slots(doctor["id"])
                flash("Shift added. Patients can book it now."
                      + (f" {filled} patient(s) from the wait list were booked into it." if filled else ""), "success")
        except ShiftError as e:
            flash(str(e), "error")
        return redirect(url_for(back_endpoint, **back_args))
    times = [f"{h:02d}:{m:02d}" for h in range(7, 21) for m in (0, 30)]
    return render_template("hours.html", doctor=doctor, shifts=shifts(doctor["id"]), weekdays=WEEKDAYS, times=times)


@bp.route("/hours", methods=("GET", "POST"))
@login_required(role="doctor")
def hours():
    return handle_hours(my_profile(), "doctor.hours")
