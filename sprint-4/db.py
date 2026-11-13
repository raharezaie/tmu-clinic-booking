"""Database connection, setup, and sample data (D1 User DB, D2 Doctor Sched DB, D3 Appointments DB)."""
import os
import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA_VERSION = 6  # matches PRAGMA user_version in schema.sql

SAMPLE_DOCTORS = [
    # (name, email, specialty, department, [(weekday, start, end), ...])
    # A doctor who registers with one of these emails takes over that profile.
    ("Dr. Priya Raman", "priya.raman@torontomu.ca", "General Practice", "Primary Care",
     [(0, "09:00", "12:00"), (2, "09:00", "12:00"), (4, "13:00", "16:00")]),
    ("Dr. Marcus Chen", "marcus.chen@torontomu.ca", "General Practice", "Primary Care",
     [(1, "10:00", "15:00"), (3, "10:00", "15:00")]),
    ("Dr. Aisha Bello", "aisha.bello@torontomu.ca", "Mental Health", "Counselling",
     [(0, "13:00", "17:00"), (1, "09:00", "12:00"), (3, "13:00", "17:00")]),
    ("Dr. Daniel Okafor", "daniel.okafor@torontomu.ca", "Sexual Health", "Primary Care",
     [(2, "13:00", "16:00"), (4, "09:00", "12:00")]),
    ("Dr. Sofia Marino", "sofia.marino@torontomu.ca", "Physiotherapy", "Sports Medicine",
     [(1, "13:00", "17:00"), (4, "09:00", "13:00")]),
]


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))
    for name, email, specialty, dept, shifts in SAMPLE_DOCTORS:
        cur = db.execute(
            "INSERT INTO doctors (full_name, email, specialty, department) VALUES (?, ?, ?, ?)",
            (name, email, specialty, dept),
        )
        db.executemany(
            "INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
            [(cur.lastrowid, d, s, e) for d, s, e in shifts],
        )
    db.commit()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Delete the database and recreate it with sample doctors."""
    path = current_app.config["DATABASE"]
    if os.path.exists(path):
        os.remove(path)
    init_db()
    click.echo("Database created with sample doctors.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    # Create the database automatically the first time the app runs
    if not os.path.exists(app.config["DATABASE"]):
        with app.app_context():
            init_db()

    # An old clinic.db (from Sprint 1 or 2) is missing the new tables. Instead of
    # crashing on some random page, every page explains how to fix it.
    @app.before_request
    def check_schema_version():
        con = sqlite3.connect(app.config["DATABASE"])
        try:
            version = con.execute("PRAGMA user_version").fetchone()[0]
        finally:
            con.close()
        if version != SCHEMA_VERSION:
            return (
                "<h1>Database needs to be rebuilt</h1>"
                f"<p>clinic.db was made by an older version of the app (schema {version}, need {SCHEMA_VERSION}).</p>"
                "<p>Stop the server and run <code>flask --app app init-db</code>, then start it again. "
                "This deletes existing test accounts and bookings.</p>", 500)
