-- Schema version, checked at startup so an old database gives a clear message
PRAGMA user_version = 3;

-- D1: User DB (patients, clinic admins and, from Sprint 3, doctors)
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    student_id    TEXT,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('patient', 'admin', 'doctor')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- D2: Doctor Sched DB
CREATE TABLE doctors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name  TEXT NOT NULL,
    specialty  TEXT NOT NULL,
    department TEXT NOT NULL,
    email      TEXT UNIQUE,                            -- lets a doctor claim this profile when registering
    user_id    INTEGER UNIQUE REFERENCES users(id)     -- set once the doctor has a login
);

CREATE TABLE doctor_schedules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id    INTEGER NOT NULL REFERENCES doctors(id),
    weekday      INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),  -- 0 = Monday
    start_time   TEXT    NOT NULL,                                   -- 'HH:MM'
    end_time     TEXT    NOT NULL,
    slot_minutes INTEGER NOT NULL DEFAULT 30
);

-- D3: Appointments DB
CREATE TABLE appointments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL REFERENCES users(id),
    doctor_id    INTEGER NOT NULL REFERENCES doctors(id),
    appt_date    TEXT    NOT NULL,   -- 'YYYY-MM-DD'
    start_time   TEXT    NOT NULL,   -- 'HH:MM'
    reason       TEXT,
    status       TEXT    NOT NULL DEFAULT 'booked'
                 CHECK (status IN ('booked', 'checked_in', 'completed', 'no_show', 'cancelled')),
    source       TEXT    NOT NULL DEFAULT 'online' CHECK (source IN ('online', 'waitlist')),
    cancelled_by TEXT    CHECK (cancelled_by IN ('patient', 'clinic')),
    visit_notes  TEXT,               -- written by the doctor, only shown to clinic staff
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- A slot holds at most one appointment that isn't cancelled (stops double-booking)
CREATE UNIQUE INDEX one_booking_per_slot
    ON appointments (doctor_id, appt_date, start_time)
    WHERE status != 'cancelled';

-- Wait list: patients waiting for any opening with a doctor on a given day
CREATE TABLE waitlist (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL REFERENCES users(id),
    doctor_id      INTEGER NOT NULL REFERENCES doctors(id),
    wait_date      TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'waiting'
                   CHECK (status IN ('waiting', 'booked', 'left', 'expired')),
    appointment_id INTEGER REFERENCES appointments(id),
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime'))
);
CREATE UNIQUE INDEX one_wait_per_day
    ON waitlist (patient_id, doctor_id, wait_date)
    WHERE status = 'waiting';

-- Walk-in queue, filled in by the front desk
CREATE TABLE walk_ins (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_name        TEXT    NOT NULL,
    student_id          TEXT,
    patient_id          INTEGER REFERENCES users(id),     -- linked if they have an account
    reason              TEXT    NOT NULL,
    urgency             TEXT    NOT NULL DEFAULT 'normal' CHECK (urgency IN ('normal', 'urgent')),
    preferred_doctor_id INTEGER REFERENCES doctors(id),   -- NULL = first available doctor
    assigned_doctor_id  INTEGER REFERENCES doctors(id),
    status              TEXT    NOT NULL DEFAULT 'waiting'
                        CHECK (status IN ('waiting', 'with_doctor', 'done', 'left')),
    added_by            INTEGER REFERENCES users(id),
    arrived_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    called_at           TEXT,
    finished_at         TEXT
);

-- Messages shown to patients, e.g. "You were booked from the wait list"
CREATE TABLE notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    message    TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    read_at    TEXT
);
