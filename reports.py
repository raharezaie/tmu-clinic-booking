"""Staff tools: patient lookup and visit reports over a date range."""
from datetime import date, timedelta

from flask import Blueprint, abort, flash, render_template, request

from auth import login_required
from db import get_db
from scheduling import all_slots, parse_date

bp = Blueprint("reports", __name__, url_prefix="/admin")

MAX_REPORT_DAYS = 92
STATUSES = ("booked", "completed", "no_show", "cancelled")


# ---------- Patients ----------
@bp.route("/patients")
@login_required(role="admin")
def patients():
    q = request.args.get("q", "").strip()
    rows = []
    if q:
        like = f"%{q}%"
        rows = get_db().execute(
            """SELECT u.*, (SELECT COUNT(*) FROM appointments a WHERE a.patient_id = u.id) AS visits
               FROM users u
               WHERE u.role = 'patient' AND (u.full_name LIKE ? OR u.email LIKE ? OR u.student_id LIKE ?)
               ORDER BY u.full_name LIMIT 50""",
            (like, like, like),
        ).fetchall()
    return render_template("patients.html", q=q, rows=rows)


@bp.route("/patients/<int:patient_id>")
@login_required(role="admin")
def patient(patient_id):
    db = get_db()
    person = db.execute("SELECT * FROM users WHERE id = ? AND role = 'patient'", (patient_id,)).fetchone()
    if person is None:
        abort(404)
    appts = db.execute(
        """SELECT a.*, d.full_name AS doctor_name, d.specialty
           FROM appointments a JOIN doctors d ON d.id = a.doctor_id
           WHERE a.patient_id = ?
           ORDER BY a.appt_date DESC, a.start_time DESC""",
        (patient_id,),
    ).fetchall()
    counts = {s: sum(1 for a in appts if a["status"] == s) for s in STATUSES}
    return render_template("patient.html", person=person, appts=appts, counts=counts)


# ---------- Reports ----------
def empty_counts():
    return dict.fromkeys(STATUSES + ("capacity",), 0)


def finish(row):
    used = row["booked"] + row["completed"] + row["no_show"]
    row["used"] = used
    row["pct"] = round(100 * used / row["capacity"]) if row["capacity"] else 0
    attended = row["completed"] + row["no_show"]
    row["no_show_pct"] = round(100 * row["no_show"] / attended) if attended else 0
    return row


@bp.route("/reports")
@login_required(role="admin")
def report():
    db = get_db()
    end = parse_date(request.args.get("end")) or date.today()
    start = parse_date(request.args.get("start")) or end - timedelta(days=6)
    if start > end:
        start, end = end, start
    if (end - start).days + 1 > MAX_REPORT_DAYS:
        flash(f"Reports cover up to {MAX_REPORT_DAYS} days, so the start date was moved.", "info")
        start = end - timedelta(days=MAX_REPORT_DAYS - 1)

    doctors = db.execute("SELECT * FROM doctors ORDER BY specialty, full_name").fetchall()
    by_doctor = {d["id"]: dict(empty_counts(), doctor=d) for d in doctors}

    day = start
    while day <= end:
        for d in doctors:
            by_doctor[d["id"]]["capacity"] += len(all_slots(d["id"], day))
        day += timedelta(days=1)

    for r in db.execute(
        """SELECT doctor_id, status, COUNT(*) AS n FROM appointments
           WHERE appt_date BETWEEN ? AND ? GROUP BY doctor_id, status""",
        (start.isoformat(), end.isoformat()),
    ):
        by_doctor[r["doctor_id"]][r["status"]] += r["n"]

    by_specialty = {}
    for row in by_doctor.values():
        spec = by_specialty.setdefault(row["doctor"]["specialty"], dict(empty_counts(), name=row["doctor"]["specialty"]))
        for k in empty_counts():
            spec[k] += row[k]

    totals = empty_counts()
    for row in by_doctor.values():
        for k in totals:
            totals[k] += row[k]

    doctor_rows = [finish(r) for r in by_doctor.values() if r["capacity"] or any(r[s] for s in STATUSES)]
    return render_template(
        "reports.html", start=start, end=end, totals=finish(totals),
        doctor_rows=doctor_rows, specialty_rows=[finish(r) for r in by_specialty.values()],
    )
