"""Database connection, setup, and sample data (D1 User DB, D2 Doctor Sched DB, D3 Appointments DB)."""
import os
import sqlite3

import click
from flask import current_app, g


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


SAMPLE_DOCTORS = [
    # (name, specialty, department, [(weekday, start, end), ...])
    ("Dr. Priya Raman", "General Practice", "Primary Care", [(0, "09:00", "12:00"), (2, "09:00", "12:00"), (4, "13:00", "16:00")]),
    ("Dr. Marcus Chen", "General Practice", "Primary Care", [(1, "10:00", "15:00"), (3, "10:00", "15:00")]),
    ("Dr. Aisha Bello", "Mental Health", "Counselling", [(0, "13:00", "17:00"), (1, "09:00", "12:00"), (3, "13:00", "17:00")]),
    ("Dr. Daniel Okafor", "Sexual Health", "Primary Care", [(2, "13:00", "16:00"), (4, "09:00", "12:00")]),
    ("Dr. Sofia Marino", "Physiotherapy", "Sports Medicine", [(1, "13:00", "17:00"), (4, "09:00", "13:00")]),
]


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))
    for name, specialty, dept, shifts in SAMPLE_DOCTORS:
        cur = db.execute(
            "INSERT INTO doctors (full_name, specialty, department) VALUES (?, ?, ?)",
            (name, specialty, dept),
        )
        db.executemany(
            "INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
            [(cur.lastrowid, d, s, e) for d, s, e in shifts],
        )
    db.commit()


@click.command("init-db")
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
