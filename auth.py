"""1.0 Authenticate User: registration, login, sessions, and role checks."""
import functools
import hmac
import re
import secrets
import sqlite3

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db

bp = Blueprint("auth", __name__)

TMU_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@torontomu\.ca$")
STUDENT_ID = re.compile(r"^\d{9}$")
MIN_PASSWORD = 8


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
        if g.user and not can_log_in(g.user):  # doctor deactivated mid-session
            session.clear()
            g.user = None


def doctor_for_user(user):
    """The doctors row linked to a doctor login, or None."""
    return get_db().execute("SELECT * FROM doctors WHERE user_id = ?", (user["id"],)).fetchone()


def can_log_in(user):
    """Doctors can only log in while their doctor record is active."""
    if user["role"] != "doctor":
        return True
    doctor = doctor_for_user(user)
    return doctor is not None and bool(doctor["active"])


def login_required(role=None):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(**kwargs):
            if g.user is None:
                flash("Log in to continue.", "info")
                return redirect(url_for("auth.login", next=request.path))
            if role and g.user["role"] != role:
                abort(403)
            return view(**kwargs)
        return wrapped
    return decorator


def home_for(user):
    return {
        "admin": url_for("admin.dashboard"),
        "doctor": url_for("doctor.home"),
    }.get(user["role"], url_for("booking.my_appointments"))


# ---------- Shared validation ----------
def validate_common(form):
    errors = []
    name = form.get("full_name", "").strip()
    email = form.get("email", "").strip().lower()
    if not name:
        errors.append("Enter your full name.")
    if not TMU_EMAIL.match(email):
        errors.append("Use your @torontomu.ca email address.")
    password, password_errors = validate_new_password(form)
    return name, email, password, errors + password_errors


def create_user(name, email, password, role, student_id=None):
    """Returns the new user's id, or None if the email is already taken."""
    try:
        cur = get_db().execute(
            "INSERT INTO users (full_name, email, student_id, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            (name, email, student_id, generate_password_hash(password), role),
        )
        get_db().commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def validate_new_password(form):
    password = form.get("password", "")
    errors = []
    if len(password) < MIN_PASSWORD:
        errors.append(f"Password must be at least {MIN_PASSWORD} characters.")
    if password != form.get("confirm", ""):
        errors.append("Passwords don't match.")
    return password, errors


# ---------- Patient registration ----------
@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        name, email, password, errors = validate_common(request.form)
        student_id = request.form.get("student_id", "").strip()
        if not STUDENT_ID.match(student_id):
            errors.append("Student number must be 9 digits.")
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


# ---------- Login / logout (one login page for every role) ----------
@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
        elif not can_log_in(user):
            flash("Your doctor account is disabled. Contact clinic staff.", "error")
        else:
            session.clear()  # new session on login
            session["user_id"] = user["id"]
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(home_for(user))
    return render_template("login.html")


# ---------- Change own password (doctors) ----------
@bp.route("/account/password", methods=("GET", "POST"))
@login_required(role="doctor")
def change_password():
    if request.method == "POST":
        password, errors = validate_new_password(request.form)
        if not check_password_hash(g.user["password_hash"], request.form.get("current", "")):
            errors.insert(0, "Current password is incorrect.")
        if not errors:
            get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?",
                             (generate_password_hash(password), g.user["id"]))
            get_db().commit()
            flash("Password changed.", "success")
            return redirect(home_for(g.user))
        for e in errors:
            flash(e, "error")
    return render_template("change_password.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You're logged out.", "info")
    return redirect(url_for("auth.login"))
