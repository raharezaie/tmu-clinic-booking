"""Staff tools: patient lookup and visit reports over a date range."""
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from auth import login_required
from db import get_db
from scheduling import all_slots, parse_date
from walkins import merge_guest

bp = Blueprint("reports", __name__, url_prefix="/admin")

MAX_REPORT_DAYS = 92
STATUSES = ("booked", "completed", "no_show", "cancelled")
EXTRA_COUNTS = ("walk_in", "released", "left")   # walk-in visits, released late slots, walk-ins never seen


# ---------- Patients ----------
@bp.route("/patients")
@login_required(role="admin")
def patients():
    q = request.args.get("q", "").strip()
    rows = []
    if q:
        like = f"%{q}%"
        rows = get_db().execute(
            """SELECT u.*, COALESCE(u.email, u.guest_email) AS shown_email,
                      (SELECT COUNT(*) FROM appointments a WHERE a.patient_id = u.id) AS visits
               FROM users u
               WHERE u.role IN ('patient', 'guest')
                 AND (u.full_name LIKE ? OR u.email LIKE ? OR u.guest_email LIKE ? OR u.student_id LIKE ?)
               ORDER BY u.full_name LIMIT 50""",
            (like, like, like, like),
        ).fetchall()
    return render_template("patients.html", q=q, rows=rows)


@bp.route("/patients/<int:patient_id>")
@login_required(role="admin")
def patient(patient_id):
    db = get_db()
    person = db.execute(
        "SELECT * FROM users WHERE id = ? AND role IN ('patient', 'guest')", (patient_id,)
    ).fetchone()
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


@bp.route("/patients/<int:guest_id>/merge", methods=("POST",))
@login_required(role="admin")
def merge(guest_id):
    """Attach a walk-in guest's visits to a patient account, found by email or student number."""
    db = get_db()
    guest = db.execute("SELECT * FROM users WHERE id = ? AND role = 'guest'", (guest_id,)).fetchone()
    if guest is None:
        abort(404)
    target = request.form.get("target", "").strip().lower()
    matches = db.execute(
        "SELECT * FROM users WHERE role = 'patient' AND (email = ? OR student_id = ?)", (target, target)
    ).fetchall() if target else []
    if len(matches) != 1:
        flash("No single patient account matches that. Enter their email address." if matches
              else "No patient account has that email or student number.", "error")
        return redirect(url_for("reports.patient", patient_id=guest_id))
    error = merge_guest(guest_id, matches[0]["id"])
    if error:
        flash(error, "error")
        return redirect(url_for("reports.patient", patient_id=guest_id))
    flash(f"Merged the guest record into {matches[0]['full_name']}'s account.", "success")
    return redirect(url_for("reports.patient", patient_id=matches[0]["id"]))


# ---------- Reports ----------
def empty_counts():
    return dict.fromkeys(STATUSES + EXTRA_COUNTS + ("capacity",), 0)


def finish(row):
    # A released no-show handed its slot to a walk-in, so that slot is only counted once
    used = row["booked"] + row["completed"] + row["no_show"] - row["released"]
    row["used"] = used
    row["pct"] = round(100 * used / row["capacity"]) if row["capacity"] else 0
    attended = row["completed"] + row["no_show"]
    row["no_show_pct"] = round(100 * row["no_show"] / attended) if attended else 0
    return row


def doctor_counts(doctor_id, start, end):
    """Slots and visits by status for one doctor over a date range (used by reports and the doctor dashboard)."""
    row = empty_counts()
    day = start
    while day <= end:
        row["capacity"] += len(all_slots(doctor_id, day))
        day += timedelta(days=1)
    for r in get_db().execute(
        """SELECT status, COUNT(*) AS n FROM appointments
           WHERE doctor_id = ? AND appt_date BETWEEN ? AND ? GROUP BY status""",
        (doctor_id, start.isoformat(), end.isoformat()),
    ):
        row[r["status"]] += r["n"]
    extra = get_db().execute(
        """SELECT SUM(source = 'walk_in' AND status != 'cancelled') AS walk_in,
                  SUM(slot_released_at IS NOT NULL) AS released
           FROM appointments WHERE doctor_id = ? AND appt_date BETWEEN ? AND ?""",
        (doctor_id, start.isoformat(), end.isoformat()),
    ).fetchone()
    row["walk_in"], row["released"] = extra["walk_in"] or 0, extra["released"] or 0
    return finish(row)


def left_counts(start, end):
    """Walk-ins who left or were still waiting at closing, by specialty."""
    return {r["specialty"]: r["n"] for r in get_db().execute(
        """SELECT specialty, COUNT(*) AS n FROM walk_ins
           WHERE status IN ('left', 'closed') AND visit_date BETWEEN ? AND ? GROUP BY specialty""",
        (start.isoformat(), end.isoformat()),
    )}


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
    by_doctor = {d["id"]: dict(doctor_counts(d["id"], start, end), doctor=d) for d in doctors}

    by_specialty = {}
    for row in by_doctor.values():
        spec = by_specialty.setdefault(row["doctor"]["specialty"], dict(empty_counts(), name=row["doctor"]["specialty"]))
        for k in empty_counts():
            spec[k] += row[k]

    for name, n in left_counts(start, end).items():
        by_specialty.setdefault(name, dict(empty_counts(), name=name))["left"] = n

    totals = empty_counts()
    for row in by_specialty.values():
        for k in totals:
            totals[k] += row[k]

    doctor_rows = [r for r in by_doctor.values() if r["capacity"] or any(r[s] for s in STATUSES)]
    return render_template(
        "reports.html", start=start, end=end, totals=finish(totals),
        doctor_rows=doctor_rows, specialty_rows=[finish(r) for r in by_specialty.values()],
    )
