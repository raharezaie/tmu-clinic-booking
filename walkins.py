"""Walk-in queue: check-in from the clinic tablet, one first-come-first-served line per
specialty, and calling people into free slots. A called walk-in becomes an ordinary
appointment (source = 'walk_in'), so day views, notes and reports treat it like any visit."""
import sqlite3
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from appointments import REASON_MAX, REASON_MIN, now_text
from auth import STUDENT_ID, TMU_EMAIL, login_required
from db import get_db
from scheduling import slot_ranges

bp = Blueprint("walkins", __name__, url_prefix="/admin")

END_LABELS = {"left": "marked as left without being seen", "removed": "removed from the queue"}
GUEST_PASSWORD = "!"   # not a valid hash, so a guest can never log in


def _now_hm():
    return datetime.now().strftime("%H:%M")


def _doctors(specialty=None):
    sql, params = "SELECT * FROM doctors WHERE active = 1", []
    if specialty:
        sql += " AND specialty = ?"
        params.append(specialty)
    return get_db().execute(sql + " ORDER BY full_name", params).fetchall()


def _taken(doctor_id, day):
    """Start times already holding a booked or completed visit."""
    return {
        r["start_time"]
        for r in get_db().execute(
            "SELECT start_time FROM appointments WHERE doctor_id = ? AND appt_date = ? "
            "AND status IN ('booked', 'completed')",
            (doctor_id, day.isoformat()),
        )
    }


# ---------- Slots ----------
def current_slot(doctor_id):
    """(start, end) of the doctor's slot running right now, or None."""
    now = _now_hm()
    for start, end in slot_ranges(doctor_id, date.today()):
        if start <= now < end:
            return start, end
    return None


def doctor_free_slots(doctor_id):
    """Today's free start times for one doctor: the slot running now (if free) and later ones."""
    today, now = date.today(), _now_hm()
    taken = _taken(doctor_id, today)
    return [start for start, end in slot_ranges(doctor_id, today) if end > now and start not in taken]


def free_slots(specialty):
    """Sorted (start, doctor_id) pairs of every free slot left today in a specialty."""
    return sorted((t, d["id"]) for d in _doctors(specialty) for t in doctor_free_slots(d["id"]))


def has_slots_left(specialty):
    """True if any doctor in the specialty still has a slot (free or not) running or to come today."""
    now = _now_hm()
    return any(end > now for d in _doctors(specialty) for _s, end in slot_ranges(d["id"], date.today()))


def walk_in_specialties():
    """Specialties with at least one doctor working the rest of today."""
    return sorted({d["specialty"] for d in _doctors() if has_slots_left(d["specialty"])})


# ---------- Queue ----------
def close_stale():
    """Close entries nobody can see any more: earlier days, or a specialty with no slots left today."""
    db = get_db()
    today = date.today().isoformat()
    db.execute(
        "UPDATE walk_ins SET status = 'closed', ended_at = ?, end_reason = 'The clinic closed for the day.' "
        "WHERE status = 'waiting' AND visit_date < ?",
        (now_text(), today),
    )
    for r in db.execute("SELECT DISTINCT specialty FROM walk_ins WHERE status = 'waiting'").fetchall():
        if not has_slots_left(r["specialty"]):
            db.execute(
                "UPDATE walk_ins SET status = 'closed', ended_at = ?, "
                "end_reason = 'No more doctors for this specialty today.' "
                "WHERE status = 'waiting' AND specialty = ?",
                (now_text(), r["specialty"]),
            )
    db.commit()


def waiting(specialty):
    return get_db().execute(
        """SELECT w.*, u.full_name, u.student_id, COALESCE(u.email, u.guest_email) AS email, u.role AS person_role
           FROM walk_ins w JOIN users u ON u.id = w.user_id
           WHERE w.status = 'waiting' AND w.specialty = ?
           ORDER BY w.checked_in_at, w.id""",
        (specialty,),
    ).fetchall()


def queue(specialty):
    """Waiting people in order, each with position, minutes waited, and an estimated slot.
    The i-th person is matched with the i-th free slot left today."""
    close_stale()
    slots = free_slots(specialty)
    now = datetime.now()
    rows = []
    for i, w in enumerate(waiting(specialty)):
        slot = slots[i][0] if i < len(slots) else None
        rows.append(dict(
            w, position=i + 1,
            waited=int((now - datetime.strptime(w["checked_in_at"], "%Y-%m-%d %H:%M:%S")).total_seconds() // 60),
            estimate=None if slot is None else ("now" if slot <= now.strftime("%H:%M") else slot),
        ))
    return rows


def waiting_count(specialty):
    close_stale()
    return len(waiting(specialty))


# ---------- People ----------
def find_or_create_person(name, student_id, email):
    """The patient account matching BOTH student number and email, else a guest record."""
    db = get_db()
    person = db.execute(
        "SELECT id FROM users WHERE role = 'patient' AND email = ? AND student_id = ?", (email, student_id)
    ).fetchone() or db.execute(
        "SELECT id FROM users WHERE role = 'guest' AND guest_email = ? AND student_id = ?", (email, student_id)
    ).fetchone()
    if person:
        return person["id"]
    cur = db.execute(
        "INSERT INTO users (full_name, student_id, guest_email, password_hash, role) VALUES (?, ?, ?, ?, 'guest')",
        (name, student_id, email, GUEST_PASSWORD),
    )
    return cur.lastrowid


def merge_guest(guest_id, patient_id):
    """Move a guest's visits and queue entries onto a patient account. Returns an error message, or None."""
    db = get_db()
    try:
        db.execute("UPDATE appointments SET patient_id = ? WHERE patient_id = ?", (patient_id, guest_id))
        db.execute("UPDATE walk_ins SET user_id = ? WHERE user_id = ?", (patient_id, guest_id))
        db.execute("DELETE FROM users WHERE id = ? AND role = 'guest'", (guest_id,))
        db.commit()
    except sqlite3.IntegrityError:  # both are waiting in the queue right now
        db.rollback()
        return "Both records are waiting in the queue right now. Try again once one has been called."
    return None


def auto_merge(user_id, email, student_id):
    """After sign-up: take over guest records with the same student number AND email."""
    for g in get_db().execute(
        "SELECT id FROM users WHERE role = 'guest' AND student_id = ? AND guest_email = ?", (student_id, email)
    ).fetchall():
        merge_guest(g["id"], user_id)


# ---------- Lifecycle ----------
def check_in(name, student_id, email, specialty, reason):
    """Add someone to a specialty's queue from the tablet. Returns (error, info).
    The answer is the same whether or not an account matched, so the tablet reveals nothing."""
    name, student_id, email = name.strip()[:100], student_id.strip(), email.strip().lower()
    reason = (reason or "").strip()[:300] or None
    errors = []
    if not name:
        errors.append("Enter your full name.")
    if not STUDENT_ID.match(student_id):
        errors.append("Student number must be 9 digits.")
    if not TMU_EMAIL.match(email):
        errors.append("Use your @torontomu.ca email address.")
    if specialty not in walk_in_specialties():
        errors.append("Choose a service that's open for walk-ins today.")
    if errors:
        return " ".join(errors), None
    close_stale()
    if len(waiting(specialty)) >= len(free_slots(specialty)):
        return f"No walk-in spots left today for {specialty}. Please see the front desk.", None

    db = get_db()
    try:
        person = find_or_create_person(name, student_id, email)
        db.execute(
            "INSERT INTO walk_ins (user_id, specialty, reason, visit_date, checked_in_at) VALUES (?, ?, ?, ?, ?)",
            (person, specialty, reason, date.today().isoformat(), now_text()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return "You're already in the queue. Please see the front desk if you need to change anything.", None
    mine = next(r for r in queue(specialty) if r["user_id"] == person)
    return None, {"specialty": specialty, "position": mine["position"], "estimate": mine["estimate"]}


def call(walk_in, doctor_id, slot_time):
    """Turn a waiting entry into a walk-in appointment in a free slot today. Returns an error message, or None."""
    db = get_db()
    today = date.today().isoformat()
    try:
        cur = db.execute(
            "UPDATE walk_ins SET status = 'called', ended_at = ? WHERE id = ? AND status = 'waiting'",
            (now_text(), walk_in["id"]),
        )
        if not cur.rowcount:
            db.rollback()
            return "That person was just called or taken out of the queue."
        # A no-show already in this slot is now released: the walk-in takes its place
        db.execute(
            "UPDATE appointments SET slot_released_at = ? WHERE doctor_id = ? AND appt_date = ? "
            "AND start_time = ? AND status = 'no_show' AND slot_released_at IS NULL",
            (now_text(), doctor_id, today, slot_time),
        )
        appt = db.execute(
            "INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time, reason, source, arrived_at) "
            "VALUES (?, ?, ?, ?, ?, 'walk_in', ?)",
            (walk_in["user_id"], doctor_id, today, slot_time, walk_in["reason"], now_text()),
        )
        db.execute("UPDATE walk_ins SET appointment_id = ? WHERE id = ?", (appt.lastrowid, walk_in["id"]))
        db.commit()
    except sqlite3.IntegrityError:  # someone booked or called into the slot a moment earlier
        db.rollback()
        return "That slot was just taken. Try again."
    return None


def call_next(doctor):
    """A doctor calls the next person in their specialty into the slot running now.
    Returns (error, the called walk-in's name)."""
    slot = current_slot(doctor["id"])
    if slot is None:
        return "You don't have a slot running right now.", None
    if slot[0] in _taken(doctor["id"], date.today()):
        return f"Your current slot ({slot[0]}) already has a patient.", None
    close_stale()
    line = waiting(doctor["specialty"])
    if not line:
        return f"Nobody is waiting for {doctor['specialty']}.", None
    error = call(line[0], doctor["id"], slot[0])
    return error, None if error else line[0]["full_name"]


def get_walk_in(walk_in_id):
    row = get_db().execute(
        "SELECT w.*, u.full_name FROM walk_ins w JOIN users u ON u.id = w.user_id WHERE w.id = ?", (walk_in_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


def assign(walk_in, doctor_id):
    """Staff send a waiting person to a doctor: the slot running now if free, else that doctor's next
    free slot today (the person then waits until it starts). Returns (error, slot time)."""
    doctor = get_db().execute("SELECT * FROM doctors WHERE id = ? AND active = 1", (doctor_id,)).fetchone()
    if doctor is None:
        return "Choose an active doctor.", None
    if walk_in["status"] != "waiting":
        return "That person is no longer waiting.", None
    slots = doctor_free_slots(doctor["id"])
    if not slots:
        return f"{doctor['full_name']} has no free slot left today.", None
    error = call(walk_in, doctor["id"], slots[0])
    return error, None if error else (doctor["full_name"], slots[0])


def end(walk_in, status, reason=None):
    """Staff take someone out of the queue. Returns an error message, or None."""
    if status not in END_LABELS:
        return "Unknown queue action."
    reason = (reason or "").strip()
    if status == "removed" and not REASON_MIN <= len(reason) <= REASON_MAX:
        return f"Give a reason for removing this entry ({REASON_MIN}–{REASON_MAX} characters)."
    db = get_db()
    cur = db.execute(
        "UPDATE walk_ins SET status = ?, ended_at = ?, end_reason = ? WHERE id = ? AND status = 'waiting'",
        (status, now_text(), reason or None, walk_in["id"]),
    )
    db.commit()
    return None if cur.rowcount else "That person is no longer waiting."


# ---------- Admin queue page ----------
def doctors_working_now():
    """Active doctors with a slot running or to come today, for the assign menu."""
    now = _now_hm()
    return [d for d in _doctors() if any(end > now for _s, end in slot_ranges(d["id"], date.today()))]


@bp.route("/walk-ins")
@login_required(role="admin")
def queue_page():
    close_stale()
    specialties = sorted(set(walk_in_specialties()) | {
        r["specialty"] for r in get_db().execute("SELECT DISTINCT specialty FROM walk_ins WHERE status = 'waiting'")
    })
    queues = [{"specialty": s, "rows": queue(s), "free": len(free_slots(s))} for s in specialties]
    ended = get_db().execute(
        """SELECT w.*, u.full_name, a.start_time, d.full_name AS doctor_name
           FROM walk_ins w JOIN users u ON u.id = w.user_id
           LEFT JOIN appointments a ON a.id = w.appointment_id
           LEFT JOIN doctors d ON d.id = a.doctor_id
           WHERE w.visit_date = ? AND w.status != 'waiting'
           ORDER BY w.ended_at DESC""",
        (date.today().isoformat(),),
    ).fetchall()
    return render_template("walk_ins.html", queues=queues, ended=ended, doctors=doctors_working_now())


@bp.route("/walk-ins/<int:walk_in_id>/assign", methods=("POST",))
@login_required(role="admin")
def assign_route(walk_in_id):
    walk_in = get_walk_in(walk_in_id)
    error, result = assign(walk_in, request.form.get("doctor_id"))
    if error:
        flash(error, "error")
    else:
        flash(f"{walk_in['full_name']} is booked with {result[0]} at {result[1]}.", "success")
    return redirect(url_for("walkins.queue_page"))


@bp.route("/walk-ins/<int:walk_in_id>/end", methods=("POST",))
@login_required(role="admin")
def end_route(walk_in_id):
    walk_in = get_walk_in(walk_in_id)
    status = request.form.get("status")
    error = end(walk_in, status, request.form.get("reason"))
    if error:
        flash(error, "error")
    else:
        flash(f"{walk_in['full_name']} {END_LABELS[status]}.", "success")
    return redirect(url_for("walkins.queue_page"))
