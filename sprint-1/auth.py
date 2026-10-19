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
    return url_for("admin.dashboard") if user["role"] == "admin" else url_for("booking.my_appointments")


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


# ---------- Login / logout (one login page for both roles) ----------
@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
        else:
            session.clear()  # new session on login
            session["user_id"] = user["id"]
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(home_for(user))
    return render_template("login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You're logged out.", "info")
    return redirect(url_for("auth.login"))
