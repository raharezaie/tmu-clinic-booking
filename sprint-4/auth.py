"""1.0 Authenticate User: registration, login, sessions, and role checks."""
import functools
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db

bp = Blueprint("auth", __name__)

TMU_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@torontomu\.ca$")
STUDENT_ID = re.compile(r"^\d{9}$")
MIN_PASSWORD = 8
MAX_FAILED_LOGINS = 5                     # Sprint 4: wrong passwords allowed in a row...
LOCKOUT = timedelta(minutes=15)           # ...before the account is locked for this long


# ---------- CSRF protection for every form ----------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not hmac.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Form expired. Go back, refresh the page, and try again.")


# ---------- Who is logged in ----------
@bp.before_app_request
def load_user():
    check_csrf()
    uid = session.get("user_id")
    g.user = None
    if uid is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(role=None):
    """Protect a page. role can be one role ("admin") or several (("admin", "doctor"))."""
    allowed = (role,) if isinstance(role, str) else role

    def decorator(view):
        @functools.wraps(view)
        def wrapped(**kwargs):
            if g.user is None:
                flash("Log in to continue.", "info")
                return redirect(url_for("auth.login", next=request.path))
            if allowed and g.user["role"] not in allowed:
                abort(403)
            return view(**kwargs)
        return wrapped
    return decorator


def home_for(user):
    return {
        "admin": url_for("admin.dashboard"),
        "doctor": url_for("doctor.dashboard"),
    }.get(user["role"], url_for("booking.my_appointments"))


# ---------- Shared validation ----------
def validate_common(form):
    errors = []
    name = form.get("full_name", "").strip()
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    if not name:
        errors.append("Enter your full name.")
    if not TMU_EMAIL.match(email):
        errors.append("Use your @torontomu.ca email address.")
    if len(password) < MIN_PASSWORD:
        errors.append(f"Password must be at least {MIN_PASSWORD} characters.")
    if password != form.get("confirm", ""):
        errors.append("Passwords don't match.")
    return name, email, password, errors


def create_user(name, email, password, role, student_id=None):
    try:
        get_db().execute(
            "INSERT INTO users (full_name, email, student_id, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            (name, email, student_id, generate_password_hash(password), role),
        )
        get_db().commit()
        return True
    except sqlite3.IntegrityError:
        return False


# ---------- Patient registration ----------
@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        name, email, password, errors = validate_common(request.form)
        student_id = request.form.get("student_id", "").strip()
        if not STUDENT_ID.match(student_id):
            errors.append("Student number must be 9 digits.")
        elif get_db().execute("SELECT 1 FROM users WHERE student_id = ?", (student_id,)).fetchone():
            # Sprint 4 fix: two accounts could share one student number
            errors.append("That student number already has an account. Log in instead.")
        if not errors:
            if create_user(name, email, password, "patient", student_id):
                flash("Account created. Log in to book an appointment.", "success")
                return redirect(url_for("auth.login"))
            errors.append("An account with that email already exists.")
        for e in errors:
            flash(e, "error")
    return render_template("register.html")


# ---------- Clinic admin registration (needs the staff invite code) ----------
@bp.route("/admin/register", methods=("GET", "POST"))
def admin_register():
    if request.method == "POST":
        name, email, password, errors = validate_common(request.form)
        code = request.form.get("invite_code", "")
        if not hmac.compare_digest(code, current_app.config["ADMIN_INVITE_CODE"]):
            errors.append("Staff invite code is incorrect.")
        if not errors:
            if create_user(name, email, password, "admin"):
                flash("Staff account created. Log in to open the dashboard.", "success")
                return redirect(url_for("auth.login"))
            errors.append("An account with that email already exists.")
        for e in errors:
            flash(e, "error")
    return render_template("admin_register.html")


# ---------- Doctor registration (Sprint 3, needs the doctor invite code) ----------
@bp.route("/doctor/register", methods=("GET", "POST"))
def doctor_register():
    db = get_db()
    if request.method == "POST":
        name, email, password, errors = validate_common(request.form)
        specialty = request.form.get("specialty", "").strip()[:60]
        department = request.form.get("department", "").strip()[:60]
        code = request.form.get("invite_code", "")
        if not hmac.compare_digest(code, current_app.config["DOCTOR_INVITE_CODE"]):
            errors.append("Doctor invite code is incorrect.")

        # A clinic profile with this email may already exist (the sample doctors do):
        # the new account takes it over, keeping its schedule and bookings.
        profile = db.execute("SELECT * FROM doctors WHERE email = ?", (email,)).fetchone()
        if profile is not None and profile["user_id"] is not None:
            errors.append("That doctor profile already has an account. Log in instead.")
        if profile is None and not (specialty and department):
            errors.append("Enter your specialty and department.")

        if not errors:
            if create_user(name, email, password, "doctor"):
                user_id = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
                if profile is not None:
                    db.execute("UPDATE doctors SET user_id = ? WHERE id = ?", (user_id, profile["id"]))
                    msg = f"Account created and linked to your existing profile as {profile['full_name']}."
                else:
                    db.execute("INSERT INTO doctors (full_name, email, specialty, department, user_id) "
                               "VALUES (?, ?, ?, ?, ?)", (name, email, specialty, department, user_id))
                    msg = "Doctor account created. Log in and add your weekly hours so patients can book."
                db.commit()
                flash(msg, "success")
                return redirect(url_for("auth.login"))
            errors.append("An account with that email already exists.")
        for e in errors:
            flash(e, "error")
    specialties = [r["specialty"] for r in db.execute("SELECT DISTINCT specialty FROM doctors ORDER BY specialty")]
    return render_template("doctor_register.html", specialties=specialties)


# ---------- Login / logout (one login page for every role) ----------
@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        db = get_db()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        now = datetime.now()

        # Sprint 4: after 5 wrong passwords in a row the account is locked for 15 minutes,
        # so nobody can guess passwords by trying thousands of them.
        if user is not None and user["locked_until"] and datetime.fromisoformat(user["locked_until"]) > now:
            minutes = int((datetime.fromisoformat(user["locked_until"]) - now).total_seconds() // 60) + 1
            flash(f"Too many wrong passwords. Try again in {minutes} minute{'s' if minutes != 1 else ''}.", "error")
        elif user is None or not check_password_hash(user["password_hash"], password):
            if user is not None:
                failed = user["failed_logins"] + 1
                locked = (now + LOCKOUT).isoformat(timespec="seconds") if failed >= MAX_FAILED_LOGINS else None
                db.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                           (0 if locked else failed, locked, user["id"]))
                db.commit()
            if user is not None and failed >= MAX_FAILED_LOGINS:
                flash("Too many wrong passwords. This account is locked for 15 minutes.", "error")
            else:
                flash("Email or password is incorrect.", "error")
        else:
            db.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (user["id"],))
            db.commit()
            session.clear()  # new session on login
            session["user_id"] = user["id"]
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
                return redirect(nxt)
            return redirect(home_for(user))
    return render_template("login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You're logged out.", "info")
    return redirect(url_for("auth.login"))
