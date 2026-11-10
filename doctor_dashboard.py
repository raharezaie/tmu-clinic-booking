"""Doctor dashboard: the doctor's own day, visits, notes, patients, and schedule."""
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from appointments import (STATUS_DONE, can_release, can_revert, change_status, get_notes, has_started,
                          notes_editable, notes_lock_date, release_slot, save_notes)
from auth import doctor_for_user, login_required
from db import get_db
from doctors_admin import WEEKDAYS
from reports import doctor_counts
from scheduling import all_slots, open_slots, parse_date
import walkins

bp = Blueprint("doctor_dashboard", __name__, url_prefix="/doctor")

STATS_DAYS = 30


def current_doctor():
    doctor = doctor_for_user(g.user)
    if doctor is None:
        abort(403)
    return doctor


def my_appointment(appt_id, doctor):
    """One of this doctor's appointments with patient details, or 404 (other doctors' ids don't leak)."""
    appt = get_db().execute(
        """SELECT a.*, u.full_name AS patient_name, COALESCE(u.email, u.guest_email) AS patient_email,
                  u.student_id, u.role AS patient_role
           FROM appointments a JOIN users u ON u.id = a.patient_id
           WHERE a.id = ? AND a.doctor_id = ?""",
        (appt_id, doctor["id"]),
    ).fetchone()
    if appt is None:
        abort(404)
    return appt


def with_flags(appt):
    return dict(appt, started=has_started(appt), revertable=can_revert(appt), releasable=can_release(appt))


@bp.route("/home")
@login_required(role="doctor")
def home():
    doctor = current_doctor()
    db = get_db()
    today = date.today()
    day = parse_date(request.args.get("date")) or today

    appts = [
        with_flags(a)
        for a in db.execute(
            """SELECT a.*, u.full_name AS patient_name, u.student_id,
                      (n.private_note IS NOT NULL OR n.shared_note IS NOT NULL) AS has_note
               FROM appointments a
               JOIN users u ON u.id = a.patient_id
               LEFT JOIN visit_notes n ON n.appointment_id = a.id
               WHERE a.doctor_id = ? AND a.appt_date = ?
               ORDER BY a.start_time""",
            (doctor["id"], day.isoformat()),
        )
    ]
    # A released no-show gave its slot to a walk-in, so it's listed below with the cancelled ones
    active = {a["start_time"]: a for a in appts if a["status"] != "cancelled" and not a["slot_released_at"]}
    slots = all_slots(doctor["id"], day)
    # Every slot in the schedule, plus any visit outside it (e.g. booked before a shift changed)
    times = sorted(set(slots) | set(active))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = [{"time": t, "appt": active.get(t), "passed": f"{day.isoformat()} {t}" <= now} for t in times]

    def count(status):
        return sum(1 for a in appts if a["status"] == status)

    summary = {"booked": count("booked"), "completed": count("completed"),
               "no_show": count("no_show"), "open": len(open_slots(doctor["id"], day)),
               "walk_ins": sum(1 for a in active.values() if a["source"] == "walk_in")}
    time_off = db.execute(
        "SELECT * FROM doctor_time_off WHERE doctor_id = ? AND off_date = ?", (doctor["id"], day.isoformat())
    ).fetchone()
    return render_template(
        "doctor_day.html", doctor=doctor, day=day, today=today, rows=rows, summary=summary,
        cancelled=[a for a in appts if a["status"] == "cancelled" or a["slot_released_at"]], time_off=time_off,
        walk_in=walk_in_panel(doctor) if day == today else None,
        month=doctor_counts(doctor["id"], today - timedelta(days=STATS_DAYS - 1), today),
        stats_days=STATS_DAYS,
        prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1),
    )


def walk_in_panel(doctor):
    """How many are waiting in the doctor's specialty, and whether Call next can be used now."""
    waiting = walkins.waiting_count(doctor["specialty"])
    slot = walkins.current_slot(doctor["id"])
    if not waiting:
        why = None
    elif slot is None:
        why = "You don't have a slot running right now."
    elif slot[0] not in walkins.doctor_free_slots(doctor["id"]):
        why = f"Your current slot ({slot[0]}) already has a patient."
    else:
        why = None
    return {"waiting": waiting, "can_call": bool(waiting) and slot is not None and why is None, "why": why}


@bp.route("/call-next", methods=("POST",))
@login_required(role="doctor")
def call_next():
    error, name = walkins.call_next(current_doctor())
    flash(error or f"{name} has been called in for a walk-in visit.", "error" if error else "success")
    return redirect(url_for("doctor_dashboard.home"))


@bp.route("/appointments/<int:appt_id>/release", methods=("POST",))
@login_required(role="doctor")
def release(appt_id):
    appt = my_appointment(appt_id, current_doctor())
    error = release_slot(appt)
    flash(error or f"The {appt['start_time']} slot was released and {appt['patient_name']} marked a no-show.",
          "error" if error else "success")
    return redirect(url_for("doctor_dashboard.home", date=appt["appt_date"]))


@bp.route("/appointments/<int:appt_id>/status", methods=("POST",))
@login_required(role="doctor")
def set_status(appt_id):
    appt = my_appointment(appt_id, current_doctor())
    status = request.form.get("status")
    if status not in STATUS_DONE:
        abort(400, "Unknown status.")
    error = change_status(appt, status, "doctor", request.form.get("reason"))
    if error:
        flash(error, "error")
    else:
        flash(f"Visit at {appt['start_time']} with {appt['patient_name']} {STATUS_DONE[status]}.", "success")
    if request.form.get("back") == "visit":
        return redirect(url_for("doctor_dashboard.visit", appt_id=appt_id))
    return redirect(url_for("doctor_dashboard.home", date=appt["appt_date"]))


@bp.route("/appointments/<int:appt_id>", methods=("GET", "POST"))
@login_required(role="doctor")
def visit(appt_id):
    doctor = current_doctor()
    appt = my_appointment(appt_id, doctor)
    editable = notes_editable(appt)
    if request.method == "POST":
        if not editable:
            flash("Notes can only be written on completed visits, up to "
                  "7 days after the visit.", "error")
        else:
            save_notes(appt_id, request.form.get("private_note"), request.form.get("shared_note"))
            flash("Notes saved.", "success")
        return redirect(url_for("doctor_dashboard.visit", appt_id=appt_id))
    return render_template(
        "doctor_visit.html", doctor=doctor, appt=with_flags(appt), notes=get_notes(appt_id),
        editable=editable, lock_date=notes_lock_date(appt),
    )


@bp.route("/patients/<int:patient_id>")
@login_required(role="doctor")
def patient(patient_id):
    doctor = current_doctor()
    db = get_db()
    appts = db.execute(
        """SELECT a.*, (n.private_note IS NOT NULL OR n.shared_note IS NOT NULL) AS has_note
           FROM appointments a LEFT JOIN visit_notes n ON n.appointment_id = a.id
           WHERE a.patient_id = ? AND a.doctor_id = ?
           ORDER BY a.appt_date DESC, a.start_time DESC""",
        (patient_id, doctor["id"]),
    ).fetchall()
    if not appts:  # only patients who have booked with this doctor
        abort(404)
    person = db.execute("SELECT * FROM users WHERE id = ?", (patient_id,)).fetchone()
    return render_template("doctor_patient.html", person=person, appts=appts)


@bp.route("/schedule")
@login_required(role="doctor")
def schedule():
    doctor = current_doctor()
    db = get_db()
    shifts = db.execute(
        "SELECT * FROM doctor_schedules WHERE doctor_id = ? ORDER BY weekday, start_time", (doctor["id"],)
    ).fetchall()
    time_off = db.execute(
        "SELECT * FROM doctor_time_off WHERE doctor_id = ? AND off_date >= ? ORDER BY off_date",
        (doctor["id"], date.today().isoformat()),
    ).fetchall()
    return render_template("doctor_schedule.html", doctor=doctor, shifts=shifts,
                           time_off=time_off, weekdays=WEEKDAYS)
