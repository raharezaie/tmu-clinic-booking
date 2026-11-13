"""Doctor availability pages (Sprint 2): browse doctors and see their open times."""
from datetime import date, timedelta

from flask import Blueprint, abort, render_template, request

from appointments import get_doctor
from auth import login_required
from scheduling import (availability_week, bookable_range, list_doctors,
                        next_open_slot, parse_date, specialties, weekly_hours)

bp = Blueprint("doctors", __name__, url_prefix="/doctors")


@bp.route("/")
@login_required()
def index():
    specialty = request.args.get("specialty") or None
    doctors = [
        {"doctor": d, "hours": weekly_hours(d["id"]), "next": next_open_slot(d["id"])}
        for d in list_doctors(specialty)
    ]
    return render_template("doctors.html", doctors=doctors, specialty=specialty, specialties=specialties())


@bp.route("/<int:doctor_id>")
@login_required()
def detail(doctor_id):
    doctor = get_doctor(doctor_id)
    if doctor is None:
        abort(404)
    first, last = bookable_range()
    start = parse_date(request.args.get("start")) or first
    start = min(max(start, first), last)
    return render_template(
        "doctor_detail.html", doctor=doctor, hours=weekly_hours(doctor_id),
        days=availability_week(doctor_id, start), today=date.today(),
        prev_start=max(first, start - timedelta(days=7)) if start > first else None,
        next_start=start + timedelta(days=7) if start + timedelta(days=7) <= last else None,
    )
