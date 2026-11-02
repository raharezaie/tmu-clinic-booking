"""4.0 Admin Dashboard: daily clinic summary, appointment actions, and booking for patients."""
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from auth import login_required
from db import get_db
from scheduling import (all_slots, book_slot, bookable_range, parse_date,
                        search_availability, specialties)

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Which status changes staff can make, and when
PAST_ONLY = {"completed", "no_show"}   # only once the start time has passed
FUTURE_ONLY = {"cancelled"}            # only before it starts
STATUS_DONE = {"completed": "marked completed", "no_show": "marked as a no-show", "cancelled": "cancelled"}


def has_started(appt):
    return f"{appt['appt_date']} {appt['start_time']}" <= datetime.now().strftime("%Y-%m-%d %H:%M")


@bp.route("/dashboard")
@login_required(role="admin")
def dashboard():
    db = get_db()
    day = parse_date(request.args.get("date")) or date.today()

    appts = [
        dict(a, started=has_started(a))
        for a in db.execute(
            """SELECT a.*, u.full_name AS patient_name, u.email AS patient_email, u.student_id,
                      d.full_name AS doctor_name, d.specialty
               FROM appointments a
               JOIN users u ON u.id = a.patient_id
               JOIN doctors d ON d.id = a.doctor_id
               WHERE a.appt_date = ?
               ORDER BY a.start_time, d.full_name""",
            (day.isoformat(),),
        )
    ]
    used = [a for a in appts if a["status"] != "cancelled"]  # booked, completed or no-show

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
    }
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
    back = redirect(url_for("admin.dashboard", date=appt["appt_date"]))
    if status not in STATUS_DONE:
        abort(400, "Unknown status.")
    if status in PAST_ONLY and not has_started(appt):
        flash("You can only mark a visit completed or a no-show once its start time has passed.", "error")
        return back
    if status in FUTURE_ONLY and has_started(appt):
        flash("That appointment has already started. Mark it completed or a no-show instead.", "error")
        return back
    cur = db.execute("UPDATE appointments SET status = ? WHERE id = ? AND status = 'booked'", (status, appt_id))
    db.commit()
    if cur.rowcount:
        flash(f"Appointment at {appt['start_time']} {STATUS_DONE[status]}.", "success")
    else:
        flash("That appointment was already updated.", "error")
    return back


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
