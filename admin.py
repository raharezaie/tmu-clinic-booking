"""4.0 Admin Dashboard: daily clinic summary, appointment actions, and booking for patients."""
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from appointments import (STATUS_DONE, can_arrive, can_release, change_status, has_started,
                          mark_arrived, release_slot)
from auth import login_required
from db import get_db
from scheduling import (all_slots, book_slot, bookable_range, parse_date,
                        search_availability, specialties)

bp = Blueprint("admin", __name__, url_prefix="/admin")

@bp.route("/dashboard")
@login_required(role="admin")
def dashboard():
    db = get_db()
    day = parse_date(request.args.get("date")) or date.today()

    appts = [
        dict(a, started=has_started(a), arrivable=can_arrive(a), releasable=can_release(a))
        for a in db.execute(
            """SELECT a.*, u.full_name AS patient_name, COALESCE(u.email, u.guest_email) AS patient_email,
                      u.student_id, u.role AS patient_role,
                      d.full_name AS doctor_name, d.specialty,
                      (n.private_note IS NOT NULL OR n.shared_note IS NOT NULL) AS has_note
               FROM appointments a
               JOIN users u ON u.id = a.patient_id
               JOIN doctors d ON d.id = a.doctor_id
               LEFT JOIN visit_notes n ON n.appointment_id = a.id
               WHERE a.appt_date = ?
               ORDER BY a.start_time, d.full_name""",
            (day.isoformat(),),
        )
    ]
    # Booked, completed or no-show; a released no-show gave its slot away, so it isn't counted twice
    used = [a for a in appts if a["status"] != "cancelled" and not a["slot_released_at"]]

    doctors = []
    for d in db.execute("SELECT * FROM doctors ORDER BY full_name"):
        capacity = len(all_slots(d["id"], day))
        if capacity == 0:
            continue
        count = sum(1 for a in used if a["doctor_id"] == d["id"])
        doctors.append({"doctor": d, "capacity": capacity, "booked": count,
                        "pct": round(100 * count / capacity)})

    capacity = sum(x["capacity"] for x in doctors)

    def count(status):
        return sum(1 for a in appts if a["status"] == status)

    summary = {
        "booked": len(used),
        "cancelled": count("cancelled"),
        "completed": count("completed"),
        "no_show": count("no_show"),
        "patients": len({a["patient_id"] for a in used}),
        "capacity": capacity,
        "pct": round(100 * len(used) / capacity) if capacity else 0,
        "walk_ins": sum(1 for a in used if a["source"] == "walk_in"),
    }
    queue = {r["status"]: r["n"] for r in db.execute(
        "SELECT status, COUNT(*) AS n FROM walk_ins WHERE visit_date = ? GROUP BY status", (day.isoformat(),))}
    summary["waiting"] = queue.get("waiting", 0)
    summary["left"] = queue.get("left", 0) + queue.get("closed", 0)
    return render_template(
        "dashboard.html", day=day, summary=summary, doctors=doctors, appts=appts,
        prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1),
    )


@bp.route("/appointments/<int:appt_id>/status", methods=("POST",))
@login_required(role="admin")
def set_status(appt_id):
    db = get_db()
    appt = db.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if appt is None:
        abort(404)
    status = request.form.get("status")
    if status not in STATUS_DONE:
        abort(400, "Unknown status.")
    error = change_status(appt, status, "admin", request.form.get("reason"))
    if error:
        flash(error, "error")
    else:
        flash(f"Appointment at {appt['start_time']} {STATUS_DONE[status]}.", "success")
    return redirect(url_for("admin.dashboard", date=appt["appt_date"]))


def _appt_or_404(appt_id):
    appt = get_db().execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if appt is None:
        abort(404)
    return appt


@bp.route("/appointments/<int:appt_id>/arrive", methods=("POST",))
@login_required(role="admin")
def arrive(appt_id):
    appt = _appt_or_404(appt_id)
    error = mark_arrived(appt)
    flash(error or f"Checked in the {appt['start_time']} appointment.", "error" if error else "success")
    return redirect(url_for("admin.dashboard", date=appt["appt_date"]))


@bp.route("/appointments/<int:appt_id>/release", methods=("POST",))
@login_required(role="admin")
def release(appt_id):
    appt = _appt_or_404(appt_id)
    error = release_slot(appt)
    flash(error or f"The {appt['start_time']} slot was released and the patient marked a no-show.",
          "error" if error else "success")
    return redirect(url_for("admin.dashboard", date=appt["appt_date"]))


# ---------- Book on a patient's behalf (same checks as the patient page) ----------
def get_patient(patient_id):
    return get_db().execute(
        "SELECT * FROM users WHERE id = ? AND role = 'patient'", (patient_id,)
    ).fetchone()


@bp.route("/book")
@login_required(role="admin")
def book():
    patient = get_patient(request.args.get("patient_id"))
    if patient is None:
        flash("Find the patient first, then choose Book.", "info")
        return redirect(url_for("reports.patients"))
    first, last = bookable_range()
    day = parse_date(request.args.get("date")) or first
    if not first <= day <= last:
        flash(f"Pick a date between {first:%b %d} and {last:%b %d}.", "error")
        day = first
    specialty = request.args.get("specialty") or None
    return render_template(
        "book.html", endpoint="admin.book", patient=patient,
        day=day, prev_day=max(first, day - timedelta(days=1)), next_day=min(last, day + timedelta(days=1)),
        first=first, last=last,
        specialty=specialty, specialties=specialties(),
        results=search_availability(day, specialty),
    )


@bp.route("/book", methods=("POST",))
@login_required(role="admin")
def confirm():
    patient = get_patient(request.form.get("patient_id"))
    if patient is None:
        abort(400, "Choose a patient to book for.")
    day = parse_date(request.form.get("date"))
    time = request.form.get("time", "")
    reason = request.form.get("reason", "").strip()[:300]
    error = book_slot(patient["id"], request.form.get("doctor_id"), day, time, reason, by_staff=True)
    if error:
        flash(error, "error")
        return redirect(url_for("admin.book", patient_id=patient["id"], date=day.isoformat() if day else None))
    flash(f"Booked {patient['full_name']} on {day:%A, %B %d} at {time}.", "success")
    return redirect(url_for("admin.dashboard", date=day.isoformat()))
