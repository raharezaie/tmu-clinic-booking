"""4.0 Admin Dashboard (full version, Sprint 3).

Daily clinic summary, appointment actions (check in, cancel, no-show), the
day's wait lists, walk-in queue summary, a 7-day trend, and doctor management.
"""
import csv
import io
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for

import appointments
import reminders
import walkins
from appointments import BookingError
from auth import login_required
from db import get_db
from doctor_portal import handle_hours
from scheduling import all_slots, parse_date, weekly_hours

bp = Blueprint("admin", __name__, url_prefix="/admin")


def week_trend(end_day):
    """Counts per day for the 7 days ending on end_day."""
    start = end_day - timedelta(days=6)
    rows = get_db().execute(
        "SELECT appt_date, status, COUNT(*) AS n FROM appointments WHERE appt_date BETWEEN ? AND ? "
        "GROUP BY appt_date, status",
        (start.isoformat(), end_day.isoformat()),
    ).fetchall()
    counts = {}
    for r in rows:
        counts.setdefault(r["appt_date"], {})[r["status"]] = r["n"]
    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        c = counts.get(d.isoformat(), {})
        days.append({
            "date": d,
            "booked": sum(v for k, v in c.items() if k != "cancelled"),
            "completed": c.get("completed", 0),
            "no_show": c.get("no_show", 0),
            "cancelled": c.get("cancelled", 0),
        })
    peak = max([x["booked"] for x in days] + [1])
    for x in days:
        x["pct"] = round(100 * x["booked"] / peak)
    return days


@bp.route("/dashboard")
@login_required(role="admin")
def dashboard():
    db = get_db()
    day = parse_date(request.args.get("date")) or date.today()
    appointments.expire_old_waitlist()

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
    active = [a for a in appts if a["status"] != "cancelled"]

    doctors = []
    for d in db.execute("SELECT * FROM doctors ORDER BY full_name"):
        capacity = len(all_slots(d["id"], day))
        if capacity == 0:
            continue
        count = sum(1 for a in active if a["doctor_id"] == d["id"])
        doctors.append({"doctor": d, "capacity": capacity, "booked": count,
                        "pct": round(100 * count / capacity)})

    waitlist = db.execute(
        """SELECT w.*, u.full_name AS patient_name, d.full_name AS doctor_name
           FROM waitlist w JOIN users u ON u.id = w.patient_id JOIN doctors d ON d.id = w.doctor_id
           WHERE w.wait_date = ? AND w.status = 'waiting' ORDER BY d.full_name, w.created_at, w.id""",
        (day.isoformat(),),
    ).fetchall()

    capacity = sum(x["capacity"] for x in doctors)
    summary = {
        "booked": len(active),
        "capacity": capacity,
        "pct": round(100 * len(active) / capacity) if capacity else 0,
        "checked_in": sum(a["status"] == "checked_in" for a in active),
        "completed": sum(a["status"] == "completed" for a in active),
        "no_show": sum(a["status"] == "no_show" for a in active),
        "cancelled": sum(a["status"] == "cancelled" for a in appts),
        "from_waitlist": sum(a["source"] == "waitlist" for a in active),
        "waiting": len(waitlist),
    }
    is_today = day == date.today()
    now = datetime.now()
    due = reminders.due_tomorrow()
    reminder_status = {"total": len(due), "sent": sum(1 for a in due if a["reminder_sent_at"])}
    return render_template(
        "dashboard.html", day=day, summary=summary, doctors=doctors, appts=appts, waitlist=waitlist,
        reminder_status=reminder_status,
        walk=walkins.todays_queue() if is_today else None, is_today=is_today, trend=week_trend(day),
        started=lambda a: appointments.starts_at(a["appt_date"], a["start_time"]) <= now,
        prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1),
    )


@bp.route("/dashboard.csv")
@login_required(role="admin")
def dashboard_csv():
    """Sprint 4: download the day's appointments as a spreadsheet."""
    day = parse_date(request.args.get("date")) or date.today()
    rows = get_db().execute(
        """SELECT a.start_time, u.full_name, u.student_id, u.email, d.full_name AS doctor, d.specialty,
                  a.reason, a.status, a.source, a.cancelled_by
           FROM appointments a JOIN users u ON u.id = a.patient_id JOIN doctors d ON d.id = a.doctor_id
           WHERE a.appt_date = ? ORDER BY a.start_time, d.full_name""",
        (day.isoformat(),),
    ).fetchall()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Time", "Patient", "Student number", "Email", "Doctor", "Specialty",
                     "Reason", "Status", "Booked via", "Cancelled by"])
    for r in rows:
        writer.writerow([day.isoformat(), r["start_time"], r["full_name"], r["student_id"] or "", r["email"],
                         r["doctor"], r["specialty"], _safe_cell(r["reason"]), r["status"].replace("_", "-"),
                         "wait list" if r["source"] == "waitlist" else "online", r["cancelled_by"] or ""])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=appointments-{day.isoformat()}.csv"})


def _safe_cell(text):
    """Stop spreadsheet apps from running a patient-typed reason like '=HYPERLINK(...)' as a formula."""
    text = text or ""
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@bp.route("/appointments/<int:appt_id>/<action>", methods=("POST",))
@login_required(role="admin")
def appointment_action(appt_id, action):
    appt = appointments.get(appt_id)
    if appt is None:
        abort(404)
    try:
        if action == "check-in":
            appointments.check_in(appt)
            flash(f"{appt['patient_name']} checked in.", "success")
        elif action == "no-show":
            appointments.no_show(appt)
            flash(f"{appt['patient_name']} marked as no-show.", "success")
        elif action == "cancel":
            filled = appointments.cancel(appt, by="clinic")
            flash(f"Appointment cancelled and {appt['patient_name']} notified."
                  + (f" The slot went to {filled['full_name']} from the wait list." if filled else ""), "success")
        else:
            abort(404)
    except BookingError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.dashboard", date=appt["appt_date"]))


# ---------- Sprint 4: email reminders and the email log ----------
@bp.route("/reminders/send", methods=("POST",))
@login_required(role="admin")
def send_reminders():
    n = reminders.send_due()
    flash(f"{n} reminder email(s) sent for tomorrow's appointments." if n
          else "All of tomorrow's reminders have already been sent.", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/emails")
@login_required(role="admin")
def emails():
    rows = get_db().execute("SELECT * FROM emails ORDER BY id DESC LIMIT 200").fetchall()
    return render_template("emails.html", emails=rows, mail_server=bool(current_app.config.get("MAIL_SERVER")))


# ---------- Doctor management ----------
@bp.route("/doctors")
@login_required(role="admin")
def doctors():
    rows = get_db().execute(
        """SELECT d.*, u.email AS account_email,
                  (SELECT COUNT(*) FROM appointments a WHERE a.doctor_id = d.id AND a.status = 'booked'
                     AND a.appt_date >= date('now', 'localtime')) AS upcoming
           FROM doctors d LEFT JOIN users u ON u.id = d.user_id ORDER BY d.full_name"""
    ).fetchall()
    return render_template("admin_doctors.html",
                           doctors=[{"doctor": d, "hours": weekly_hours(d["id"])} for d in rows])


@bp.route("/doctors/<int:doctor_id>/hours", methods=("GET", "POST"))
@login_required(role="admin")
def doctor_hours(doctor_id):
    doctor = appointments.get_doctor(doctor_id)
    if doctor is None:
        abort(404)
    return handle_hours(doctor, "admin.doctor_hours", doctor_id=doctor_id)
