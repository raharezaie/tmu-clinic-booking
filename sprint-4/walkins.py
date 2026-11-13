"""Walk-in queue (Sprint 3): the front desk adds walk-in patients, doctors call them in.

Queue order: urgent walk-ins first, then everyone else by arrival time.
A walk-in can ask for a specific doctor or take the first one available.
"""
import re
from datetime import date, datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import mailer
from auth import login_required
from db import get_db
from scheduling import all_slots

bp = Blueprint("walkins", __name__, url_prefix="/walk-ins")

STUDENT_ID = re.compile(r"^\d{9}$")
ANY_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NEAR_TURN = 3   # email stepped-out walk-ins once they're this close to the front (2 people ahead)
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
    email = form.get("email", "").strip().lower()[:120]
    stepped_out = form.get("stepped_out") == "1"

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
    if email and not ANY_EMAIL.match(email):
        errors.append("That email address doesn't look right.")

    db = get_db()
    account = None
    if student_id:
        account = db.execute("SELECT id, email FROM users WHERE student_id = ? AND role = 'patient'",
                             (student_id,)).fetchone()
    if not email and account:
        email = account["email"]  # use the email on their account
    if stepped_out and not email:
        errors.append("Add an email address so we can tell them when their turn is coming.")
    if errors:
        raise WalkInError(" ".join(errors))

    cur = db.execute(
        "INSERT INTO walk_ins (patient_name, student_id, patient_id, reason, urgency, preferred_doctor_id, "
        "added_by, arrived_at, email, stepped_out) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, student_id or None, account["id"] if account else None, reason, urgency, preferred or None,
         added_by, _now(), email or None, int(stepped_out)),
    )
    db.commit()
    send_near_turn_emails()
    return cur.lastrowid


# ---------- Sprint 4: emails for walk-ins who stepped out ----------
def _first(name):
    return name.split()[0]


def send_near_turn_emails():
    """Email stepped-out walk-ins who are now close to the front. Run after every queue change."""
    db = get_db()
    for item in todays_queue()["waiting"]:
        if not (item["stepped_out"] and item["email"]) or item["near_turn_sent_at"]:
            continue
        if item["position"] > NEAR_TURN:
            continue
        ahead = item["position"] - 1
        news = ("You're next in line." if ahead == 0 else
                f"There {'is' if ahead == 1 else 'are'} {ahead} {'person' if ahead == 1 else 'people'} ahead of you.")
        body = (f"Hi {_first(item['patient_name'])},\n\n{news} Please head back to the TMU Health "
                "front desk now so you don't miss your turn.\n\nIf you've decided not to wait, please call "
                "the front desk so we can let the next person in.")
        if mailer.send(item["email"], "Your turn at TMU Health is coming up", body, "walkin_near",
                       walk_in_id=item["id"]) != "failed":
            db.execute("UPDATE walk_ins SET near_turn_sent_at = ? WHERE id = ?", (_now(), item["id"]))
            db.commit()


def send_called_email(entry, doctor_id):
    """Tell a stepped-out walk-in that a doctor is ready for them."""
    if not (entry["stepped_out"] and entry["email"]) or entry["called_sent_at"]:
        return
    doctor = get_db().execute("SELECT full_name FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    body = (f"Hi {_first(entry['patient_name'])},\n\nIt's your turn. {doctor['full_name']} is ready to see you. "
            "Please come to the TMU Health front desk right away.")
    if mailer.send(entry["email"], "It's your turn at TMU Health", body, "walkin_called",
                   walk_in_id=entry["id"]) != "failed":
        db = get_db()
        db.execute("UPDATE walk_ins SET called_sent_at = ? WHERE id = ?", (_now(), entry["id"]))
        db.commit()


def set_stepped_out(entry, stepped_out, email=None):
    """Front desk marks a waiting walk-in as stepped out (with an email) or back in the waiting room."""
    if entry["status"] != "waiting":
        raise WalkInError("Only patients who are still waiting can be marked as stepped out.")
    email = (email or "").strip().lower() or entry["email"]
    if stepped_out and not email:
        raise WalkInError("Add an email address so we can tell them when their turn is coming.")
    if email and not ANY_EMAIL.match(email):
        raise WalkInError("That email address doesn't look right.")
    db = get_db()
    db.execute("UPDATE walk_ins SET stepped_out = ?, email = ? WHERE id = ?", (int(stepped_out), email, entry["id"]))
    db.commit()
    send_near_turn_emails()


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
    send_called_email(get(entry["id"]), doctor_id)
    send_near_turn_emails()  # everyone behind just moved up


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
    if status == "left":
        send_near_turn_emails()  # everyone behind just moved up


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


@bp.route("/<int:entry_id>/stepped-out", methods=("POST",))
@login_required(role="admin")
def stepped_out(entry_id):
    entry = _entry_or_404(entry_id)
    out = request.form.get("stepped_out") == "1"
    try:
        set_stepped_out(entry, out, request.form.get("email"))
        flash(f"{entry['patient_name']} marked as {'stepped out. They will be emailed when their turn is close' if out else 'back in the waiting room'}.",
              "success")
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
