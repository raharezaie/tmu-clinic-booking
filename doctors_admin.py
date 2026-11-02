"""Staff tools for D2 Doctor Sched DB: doctors, weekly shifts, and time off."""
import re
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from auth import login_required
from db import get_db
from scheduling import future_bookings, parse_date

bp = Blueprint("doctors_admin", __name__, url_prefix="/admin")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HALF_HOUR = re.compile(r"^([01]\d|2[0-3]):(00|30)$")


def get_doctor(doctor_id):
    doctor = get_db().execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    if doctor is None:
        abort(404)
    return doctor


def doctor_fields(form):
    """Name, specialty, department from a form, plus any errors."""
    values = {k: form.get(k, "").strip()[:100] for k in ("full_name", "specialty", "department")}
    errors = [f"Enter the doctor's {k.replace('_', ' ')}." for k, v in values.items() if not v]
    return values, errors


def refuse_if_booked(bookings, action):
    """Flash the appointments a change would strand. Returns True if there are any."""
    if not bookings:
        return False
    listed = ", ".join(f"{b['appt_date']} {b['start_time']} ({b['patient_name']})" for b in bookings[:5])
    more = f" and {len(bookings) - 5} more" if len(bookings) > 5 else ""
    flash(f"Can't {action}: {len(bookings)} upcoming appointment(s) would be left without a doctor: "
          f"{listed}{more}. Cancel or rebook them from the dashboard first.", "error")
    return True


# ---------- Doctors ----------
@bp.route("/doctors")
@login_required(role="admin")
def doctors():
    db = get_db()
    rows = []
    for d in db.execute("SELECT * FROM doctors ORDER BY active DESC, full_name"):
        shifts = db.execute(
            "SELECT * FROM doctor_schedules WHERE doctor_id = ? ORDER BY weekday, start_time", (d["id"],)
        ).fetchall()
        minutes = sum(
            (datetime.strptime(s["end_time"], "%H:%M") - datetime.strptime(s["start_time"], "%H:%M")).seconds // 60
            for s in shifts
        )
        days = sorted({s["weekday"] for s in shifts})
        rows.append({"doctor": d, "hours": minutes / 60, "days": ", ".join(WEEKDAYS[w][:3] for w in days)})
    return render_template("doctors.html", rows=rows)


@bp.route("/doctors", methods=("POST",))
@login_required(role="admin")
def add_doctor():
    values, errors = doctor_fields(request.form)
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("doctors_admin.doctors"))
    db = get_db()
    cur = db.execute(
        "INSERT INTO doctors (full_name, specialty, department) VALUES (?, ?, ?)",
        (values["full_name"], values["specialty"], values["department"]),
    )
    db.commit()
    flash(f"Added {values['full_name']}. Add their weekly shifts below so patients can book them.", "success")
    return redirect(url_for("doctors_admin.edit_doctor", doctor_id=cur.lastrowid))


@bp.route("/doctors/<int:doctor_id>", methods=("GET", "POST"))
@login_required(role="admin")
def edit_doctor(doctor_id):
    db = get_db()
    doctor = get_doctor(doctor_id)
    if request.method == "POST":
        values, errors = doctor_fields(request.form)
        for e in errors:
            flash(e, "error")
        if not errors:
            db.execute(
                "UPDATE doctors SET full_name = ?, specialty = ?, department = ? WHERE id = ?",
                (values["full_name"], values["specialty"], values["department"], doctor_id),
            )
            db.commit()
            flash("Doctor details saved.", "success")
        return redirect(url_for("doctors_admin.edit_doctor", doctor_id=doctor_id))

    shifts = db.execute(
        "SELECT * FROM doctor_schedules WHERE doctor_id = ? ORDER BY weekday, start_time", (doctor_id,)
    ).fetchall()
    time_off = db.execute(
        "SELECT * FROM doctor_time_off WHERE doctor_id = ? AND off_date >= ? ORDER BY off_date",
        (doctor_id, date.today().isoformat()),
    ).fetchall()
    return render_template(
        "doctor_edit.html", doctor=doctor, shifts=shifts, time_off=time_off,
        weekdays=WEEKDAYS, today=date.today(),
        times=[f"{h:02d}:{m:02d}" for h in range(7, 22) for m in (0, 30)],
    )


@bp.route("/doctors/<int:doctor_id>/active", methods=("POST",))
@login_required(role="admin")
def toggle_active(doctor_id):
    db = get_db()
    doctor = get_doctor(doctor_id)
    back = redirect(url_for("doctors_admin.edit_doctor", doctor_id=doctor_id))
    if doctor["active"]:
        if refuse_if_booked(future_bookings(doctor_id), "deactivate this doctor"):
            return back
        db.execute("UPDATE doctors SET active = 0 WHERE id = ?", (doctor_id,))
        flash(f"{doctor['full_name']} is deactivated and no longer bookable.", "success")
    else:
        db.execute("UPDATE doctors SET active = 1 WHERE id = ?", (doctor_id,))
        flash(f"{doctor['full_name']} is active again.", "success")
    db.commit()
    return back


# ---------- Weekly shifts ----------
@bp.route("/doctors/<int:doctor_id>/shifts", methods=("POST",))
@login_required(role="admin")
def add_shift(doctor_id):
    db = get_db()
    get_doctor(doctor_id)
    back = redirect(url_for("doctors_admin.edit_doctor", doctor_id=doctor_id))
    weekday = request.form.get("weekday", "")
    start, end = request.form.get("start_time", ""), request.form.get("end_time", "")
    if not weekday.isdigit() or not 0 <= int(weekday) <= 6:
        flash("Choose a day of the week.", "error")
        return back
    if not HALF_HOUR.match(start) or not HALF_HOUR.match(end):
        flash("Shift times must be on the hour or half hour (for example 09:00 or 13:30).", "error")
        return back
    if start >= end:
        flash("The shift has to end after it starts.", "error")
        return back
    overlap = db.execute(
        "SELECT start_time, end_time FROM doctor_schedules WHERE doctor_id = ? AND weekday = ? AND start_time < ? AND end_time > ?",
        (doctor_id, int(weekday), end, start),
    ).fetchone()
    if overlap:
        flash(f"That overlaps the existing {WEEKDAYS[int(weekday)]} shift "
              f"{overlap['start_time']}–{overlap['end_time']}.", "error")
        return back
    db.execute(
        "INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
        (doctor_id, int(weekday), start, end),
    )
    db.commit()
    flash(f"Added {WEEKDAYS[int(weekday)]} {start}–{end}.", "success")
    return back


@bp.route("/shifts/<int:shift_id>/delete", methods=("POST",))
@login_required(role="admin")
def delete_shift(shift_id):
    db = get_db()
    shift = db.execute("SELECT * FROM doctor_schedules WHERE id = ?", (shift_id,)).fetchone()
    if shift is None:
        abort(404)
    back = redirect(url_for("doctors_admin.edit_doctor", doctor_id=shift["doctor_id"]))
    booked = future_bookings(shift["doctor_id"], weekday=shift["weekday"],
                             start=shift["start_time"], end=shift["end_time"])
    if refuse_if_booked(booked, "remove this shift"):
        return back
    db.execute("DELETE FROM doctor_schedules WHERE id = ?", (shift_id,))
    db.commit()
    flash(f"Removed {WEEKDAYS[shift['weekday']]} {shift['start_time']}–{shift['end_time']}.", "success")
    return back


# ---------- Time off ----------
@bp.route("/doctors/<int:doctor_id>/time-off", methods=("POST",))
@login_required(role="admin")
def add_time_off(doctor_id):
    db = get_db()
    get_doctor(doctor_id)
    back = redirect(url_for("doctors_admin.edit_doctor", doctor_id=doctor_id))
    day = parse_date(request.form.get("off_date"))
    reason = request.form.get("reason", "").strip()[:100]
    if day is None or day < date.today():
        flash("Choose today or a future date for time off.", "error")
        return back
    if refuse_if_booked(future_bookings(doctor_id, day=day), f"add time off on {day:%b %d}"):
        return back
    exists = db.execute(
        "SELECT 1 FROM doctor_time_off WHERE doctor_id = ? AND off_date = ?", (doctor_id, day.isoformat())
    ).fetchone()
    if exists:
        flash(f"{day:%A, %B %d} is already marked as time off.", "error")
        return back
    db.execute(
        "INSERT INTO doctor_time_off (doctor_id, off_date, reason) VALUES (?, ?, ?)",
        (doctor_id, day.isoformat(), reason or None),
    )
    db.commit()
    flash(f"Marked {day:%A, %B %d} as time off.", "success")
    return back


@bp.route("/time-off/<int:off_id>/delete", methods=("POST",))
@login_required(role="admin")
def delete_time_off(off_id):
    db = get_db()
    off = db.execute("SELECT * FROM doctor_time_off WHERE id = ?", (off_id,)).fetchone()
    if off is None:
        abort(404)
    db.execute("DELETE FROM doctor_time_off WHERE id = ?", (off_id,))
    db.commit()
    flash(f"Removed time off on {off['off_date']}. Those slots are bookable again.", "success")
    return redirect(url_for("doctors_admin.edit_doctor", doctor_id=off["doctor_id"]))
