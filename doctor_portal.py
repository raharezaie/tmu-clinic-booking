"""Doctor accounts: invite links and sign-up from an invite. The dashboard is in doctor_dashboard.py."""
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

from auth import create_user, validate_new_password
from db import get_db

bp = Blueprint("doctor", __name__, url_prefix="/doctor")

INVITE_DAYS = 7
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def cancel_invites(doctor_id):
    """Remove a doctor's unused invite links."""
    get_db().execute("DELETE FROM doctor_invites WHERE doctor_id = ? AND used_at IS NULL", (doctor_id,))


def create_invite(doctor_id, email):
    """Replace any unused invite with a new one. Returns the plain token (only ever shown once)."""
    db = get_db()
    cancel_invites(doctor_id)
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=INVITE_DAYS)).strftime(TIME_FORMAT)
    db.execute(
        "INSERT INTO doctor_invites (doctor_id, email, token_hash, expires_at) VALUES (?, ?, ?, ?)",
        (doctor_id, email, _hash(token), expires),
    )
    db.commit()
    return token


def account_status(doctor):
    """What the admin sees about a doctor's login: (label, css tag, detail)."""
    if doctor["user_id"]:
        user = get_db().execute("SELECT email FROM users WHERE id = ?", (doctor["user_id"],)).fetchone()
        if doctor["active"]:
            return "Active login", "completed", user["email"]
        return "Login disabled", "cancelled", user["email"]
    invite = get_db().execute(
        "SELECT * FROM doctor_invites WHERE doctor_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1",
        (doctor["id"],),
    ).fetchone()
    if invite is None:
        return "No account", "", ""
    expires = datetime.strptime(invite["expires_at"], TIME_FORMAT)
    if expires <= datetime.now():
        return "Invite expired", "no_show", invite["email"]
    return "Invite pending", "", f"{invite['email']}, expires {expires:%b %d}"


def find_invite(token):
    """The invite and doctor for a usable token, or (None, None)."""
    db = get_db()
    invite = db.execute(
        "SELECT * FROM doctor_invites WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
        (_hash(token), datetime.now().strftime(TIME_FORMAT)),
    ).fetchone()
    if invite is None:
        return None, None
    doctor = db.execute(
        "SELECT * FROM doctors WHERE id = ? AND active = 1 AND user_id IS NULL", (invite["doctor_id"],)
    ).fetchone()
    return (invite, doctor) if doctor else (None, None)


@bp.route("/join/<token>", methods=("GET", "POST"))
def join(token):
    invite, doctor = find_invite(token)
    if invite is None:
        return render_template(
            "error.html", title="Invite link not valid",
            message="This invite link has expired or was already used. Ask clinic staff for a new one.",
        ), 404
    if request.method == "POST":
        password, errors = validate_new_password(request.form)
        if not errors:
            user_id = create_user(doctor["full_name"], invite["email"], password, "doctor")
            if user_id is None:
                errors.append("An account with that email already exists. Ask clinic staff for help.")
            else:
                db = get_db()
                db.execute("UPDATE doctors SET user_id = ? WHERE id = ?", (user_id, doctor["id"]))
                db.execute("UPDATE doctor_invites SET used_at = datetime('now') WHERE id = ?", (invite["id"],))
                db.commit()
                flash("Account created. Log in with your email and new password.", "success")
                return redirect(url_for("auth.login"))
        for e in errors:
            flash(e, "error")
    return render_template("doctor_join.html", invite=invite, doctor=doctor)

