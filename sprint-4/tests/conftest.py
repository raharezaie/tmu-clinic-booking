"""Shared test setup.

Every test gets its own fresh database, so tests never affect each other or
your real clinic.db. Run all tests from the project folder with:  pytest
"""
import os
import re
import sys
from datetime import date, datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

PASSWORD = "password123"


@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})


class Browser:
    """A logged-in (or anonymous) visitor. Handles the CSRF token on every form."""

    def __init__(self, app):
        self.client = app.test_client()

    def get(self, path, **kw):
        return self.client.get(path, **kw)

    def page(self, path):
        return self.client.get(path, follow_redirects=True).get_data(as_text=True)

    def post(self, path, data=None, from_page=None, follow=True):
        """Submit a form. from_page is where the form lives (to read its CSRF token)."""
        html = self.client.get(from_page or path).get_data(as_text=True)
        token = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
        return self.client.post(path, data=dict(data or {}, csrf=token), follow_redirects=follow)

    def text(self, path, data=None, from_page=None):
        return self.post(path, data, from_page).get_data(as_text=True)

    def login(self, email, password=PASSWORD):
        return self.text("/login", dict(email=email, password=password))


class Site:
    """Helpers for setting up accounts and data directly in the test database."""

    def __init__(self, app):
        self.app = app

    def sql(self, query, args=()):
        with self.app.app_context():
            from db import get_db
            db = get_db()
            cur = db.execute(query, args)
            rows = cur.fetchall()
            db.commit()
            return rows if rows else cur.lastrowid

    def one(self, query, args=()):
        rows = self.sql(query, args)
        return rows[0] if isinstance(rows, list) and rows else None

    def make_user(self, name, email, role="patient", student_id=None):
        return self.sql("INSERT INTO users (full_name, email, student_id, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                        (name, email, student_id, generate_password_hash(PASSWORD), role))

    def browser(self, email=None):
        b = Browser(self.app)
        if email:
            b.login(email)
        return b

    def patient(self, n=1):
        """A logged-in patient browser; n makes each patient unique."""
        email = f"patient{n}@torontomu.ca"
        if not self.one("SELECT id FROM users WHERE email = ?", (email,)):
            self.make_user(f"Patient {n}", email, "patient", f"5000000{n:02d}")
        b = self.browser(email)
        b.user_id = self.one("SELECT id FROM users WHERE email = ?", (email,))["id"]
        return b

    def admin(self):
        if not self.one("SELECT id FROM users WHERE email = 'desk@torontomu.ca'"):
            self.make_user("Front Desk", "desk@torontomu.ca", "admin")
        return self.browser("desk@torontomu.ca")

    def doctor(self, doctor_id=1):
        """Log in as one of the sample doctors (1 = Dr. Priya Raman)."""
        doc = self.one("SELECT * FROM doctors WHERE id = ?", (doctor_id,))
        if doc["user_id"] is None:
            uid = self.make_user(doc["full_name"], doc["email"], "doctor")
            self.sql("UPDATE doctors SET user_id = ? WHERE id = ?", (uid, doctor_id))
        return self.browser(doc["email"])

    def new_doctor(self, slots_on=None, start="09:00", end="10:00"):
        """A doctor with exactly one shift, so it's easy to fill their day. Returns doctor id."""
        did = self.sql("INSERT INTO doctors (full_name, email, specialty, department) VALUES "
                       "('Dr. Test Doctor', 'test.doctor@torontomu.ca', 'Testing', 'QA')")
        if slots_on is not None:
            self.sql("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
                     (did, slots_on.weekday(), start, end))
        return did

    def appointment(self, patient_id, doctor_id, day, time, status="booked", **extra):
        cols = ["patient_id", "doctor_id", "appt_date", "start_time", "status"] + list(extra)
        vals = [patient_id, doctor_id, day.isoformat() if hasattr(day, "isoformat") else day, time, status]
        vals += list(extra.values())
        return self.sql(f"INSERT INTO appointments ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)


@pytest.fixture
def site(app):
    return Site(app)


def weekday_ahead(weekday, min_days=3):
    """The first date at least min_days from today that falls on weekday (0 = Monday)."""
    d = date.today() + timedelta(days=min_days)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


@pytest.fixture
def monday():
    """A Monday at least 3 days away. Dr. Raman (1) works 09:00-12:00, Dr. Bello (3) 13:00-17:00."""
    return weekday_ahead(0)


def in_minutes(minutes):
    t = datetime.now() + timedelta(minutes=minutes)
    return t.date(), t.strftime("%H:%M")
