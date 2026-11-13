"""4.0 Admin Dashboard: daily clinic summary for staff (simple version)."""
from datetime import date, timedelta

from flask import Blueprint, render_template, request

from auth import login_required
from db import get_db
from scheduling import all_slots, parse_date

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/dashboard")
@login_required(role="admin")
def dashboard():
    db = get_db()
    day = parse_date(request.args.get("date")) or date.today()

    appts = db.execute(
        """SELECT a.*, u.full_name AS patient_name, u.email AS patient_email, u.student_id,
                  d.full_name AS doctor_name, d.specialty
           FROM appointments a
           JOIN users u ON u.id = a.patient_id
           JOIN doctors d ON d.id = a.doctor_id
           WHERE a.appt_date = ?
           ORDER BY a.start_time, d.full_name""",
        (day.isoformat(),),
    ).fetchall()
    booked = [a for a in appts if a["status"] == "booked"]

    doctors = []
    for d in db.execute("SELECT * FROM doctors ORDER BY full_name"):
        capacity = len(all_slots(d["id"], day))
        if capacity == 0:
            continue
        count = sum(1 for a in booked if a["doctor_id"] == d["id"])
        doctors.append({"doctor": d, "capacity": capacity, "booked": count,
                        "pct": round(100 * count / capacity)})

    capacity = sum(x["capacity"] for x in doctors)
    summary = {
        "booked": len(booked),
        "cancelled": sum(1 for a in appts if a["status"] == "cancelled"),
        "patients": len({a["patient_id"] for a in booked}),
        "capacity": capacity,
        "pct": round(100 * len(booked) / capacity) if capacity else 0,
    }
    return render_template(
        "dashboard.html", day=day, summary=summary, doctors=doctors, appts=appts,
        prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1),
    )
