"""Walk-in queue (Sprint 3): the front desk adds walk-in patients, doctors call them in.

Queue order: urgent walk-ins first, then everyone else by arrival time.
A walk-in can ask for a specific doctor or take the first one available.
"""
import re
from datetime import date, datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from auth import login_required
from db import get_db
from scheduling import all_slots

bp = Blueprint("walkins", __name__, url_prefix="/walk-ins")

STUDENT_ID = re.compile(r"^\d{9}$")
NOW_FMT = "%Y-%m-%d %H:%M:%S"


class WalkInError(Exception):
    """A queue change was refused. The message is safe to show."""


def _now():
    return datetime.now().strftime(NOW_FMT)


def doctors_working_today():
    today = date.today()
    return [d for d in get_db().execute("SELECT * FROM doctors ORDER BY full_name") if all_slots(d["id"], today)]


def get(entry_id):
    return get_db().execute("SELECT * FROM walk_ins WHERE id = ?", (entry_id,)).fetchone()


def todays_queue():
    """Today's walk-ins, with wait time and queue position for those still waiting."""
    rows = get_db().execute(
        """SELECT w.*, p.full_name AS preferred_name, a.full_name AS assigned_name
           FROM walk_ins w
           LEFT JOIN doctors p ON p.id = w.preferred_doctor_id
           LEFT JOIN doctors a ON a.id = w.assigned_doctor_id
           WHERE substr(w.arrived_at, 1, 10) = ?
           ORDER BY CASE w.urgency WHEN 'urgent' THEN 0 ELSE 1 END, w.arrived_at, w.id""",
        (date.today().isoformat(),),
    ).fetchall()
    now = datetime.now()
    queue, position = [], 0
    for r in rows:
        item = dict(r)
        item["wait_minutes"] = int((now - datetime.strptime(r["arrived_at"], NOW_FMT)).total_seconds() // 60)
        if r["status"] == "waiting":
            position += 1
            item["position"] = position
        queue.append(item)
    return {
        "waiting": [q for q in queue if q["status"] == "waiting"],
        "with_doctor": [q for q in queue if q["status"] == "with_doctor"],
        "finished": [q for q in queue if q["status"] in ("done", "left")],
    }


def add(form, added_by):
    """Validate the front desk form and add the walk-in. Returns the new id."""
    name = form.get("patient_name", "").strip()[:80]
    reason = form.get("reason", "").strip()[:300]
    student_id = form.get("student_id", "").strip()
    urgency = form.get("urgency", "normal")
    preferred = form.get("preferred_doctor_id", type=int)

    errors = []
    if not name:
        errors.append("Enter the patient's name.")
    if not reason:
        errors.append("Enter the reason for the visit.")
    if student_id and not STUDENT_ID.match(student_id):
        errors.append("Student number must be 9 digits, or leave it blank.")
    if urgency not in ("normal", "urgent"):
        errors.append("Choose normal or urgent.")
    if preferred and preferred not in {d["id"] for d in doctors_working_today()}:
        errors.append("That doctor isn't working today. Choose another or 'First available'.")
    if errors:
        raise WalkInError(" ".join(errors))

    db = get_db()
    account = None
    if student_id:
        account = db.execute("SELECT id FROM users WHERE student_id = ? AND role = 'patient'",
                             (student_id,)).fetchone()
    cur = db.execute(
        "INSERT INTO walk_ins (patient_name, student_id, patient_id, reason, urgency, preferred_doctor_id, "
        "added_by, arrived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, student_id or None, account["id"] if account else None, reason, urgency, preferred or None,
         added_by, _now()),
    )
    db.commit()
    return cur.lastrowid


def call(entry, doctor_id):
    """Send a waiting walk-in to a doctor."""
    if entry["status"] != "waiting":
        raise WalkInError("That patient isn't waiting anymore.")
    if entry["preferred_doctor_id"] and entry["preferred_doctor_id"] != doctor_id:
        raise WalkInError("That patient asked for a different doctor.")
    db = get_db()
    db.execute("UPDATE walk_ins SET status = 'with_doctor', assigned_doctor_id = ?, called_at = ? WHERE id = ?",
               (doctor_id, _now(), entry["id"]))
    db.commit()


def next_for_doctor(doctor_id):
    """The walk-in this doctor should see next: urgent first, then longest waiting."""
    return get_db().execute(
        """SELECT * FROM walk_ins
           WHERE status = 'waiting' AND substr(arrived_at, 1, 10) = ?
             AND (preferred_doctor_id IS NULL OR preferred_doctor_id = ?)
           ORDER BY CASE urgency WHEN 'urgent' THEN 0 ELSE 1 END, arrived_at, id LIMIT 1""",
        (date.today().isoformat(), doctor_id),
    ).fetchone()


def waiting_for_doctor(doctor_id):
    return get_db().execute(
        """SELECT COUNT(*) FROM walk_ins WHERE status = 'waiting' AND substr(arrived_at, 1, 10) = ?
           AND (preferred_doctor_id IS NULL OR preferred_doctor_id = ?)""",
        (date.today().isoformat(), doctor_id),
    ).fetchone()[0]


def finish(entry, status="done"):
    if status == "left" and entry["status"] != "waiting":
        raise WalkInError("Only patients who are still waiting can be marked as left.")
    if status == "done" and entry["status"] != "with_doctor":
        raise WalkInError("Only patients who are with a doctor can be marked as done.")
    db = get_db()
    db.execute("UPDATE walk_ins SET status = ?, finished_at = ? WHERE id = ?", (status, _now(), entry["id"]))
    db.commit()


# ---------- Front desk pages (clinic admin) ----------
def _entry_or_404(entry_id):
    entry = get(entry_id)
    if entry is None:
        abort(404)
    return entry


@bp.route("/", methods=("GET", "POST"))
@login_required(role="admin")
def queue():
    if request.method == "POST":
        try:
            add(request.form, g.user["id"])
            flash(f"{request.form.get('patient_name', '').strip()} added to the walk-in queue.", "success")
            return redirect(url_for("walkins.queue"))
        except WalkInError as e:
            flash(str(e), "error")
    return render_template("walkins.html", q=todays_queue(), doctors=doctors_working_today())


@bp.route("/<int:entry_id>/assign", methods=("POST",))
@login_required(role="admin")
def assign(entry_id):
    entry = _entry_or_404(entry_id)
    doctor_id = request.form.get("doctor_id", type=int)
    try:
        if doctor_id not in {d["id"] for d in doctors_working_today()}:
            raise WalkInError("Choose a doctor who is working today.")
        call(entry, doctor_id)
        flash(f"{entry['patient_name']} sent in to see the doctor.", "success")
    except WalkInError as e:
        flash(str(e), "error")
    return redirect(url_for("walkins.queue"))


@bp.route("/<int:entry_id>/status", methods=("POST",))
@login_required(role="admin")
def set_status(entry_id):
    entry = _entry_or_404(entry_id)
    status = request.form.get("status")
    try:
        if status not in ("done", "left"):
            raise WalkInError("Unknown status.")
        finish(entry, status)
        flash(f"{entry['patient_name']} marked as {'left' if status == 'left' else 'done'}.", "success")
    except WalkInError as e:
        flash(str(e), "error")
    return redirect(url_for("walkins.queue"))
