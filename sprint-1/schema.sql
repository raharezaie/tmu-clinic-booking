-- D1: User DB
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    student_id    TEXT,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('patient', 'admin')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- D2: Doctor Sched DB
CREATE TABLE doctors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name  TEXT NOT NULL,
    specialty  TEXT NOT NULL,
    department TEXT NOT NULL
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
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES users(id),
    doctor_id  INTEGER NOT NULL REFERENCES doctors(id),
    appt_date  TEXT    NOT NULL,   -- 'YYYY-MM-DD'
    start_time TEXT    NOT NULL,   -- 'HH:MM'
    reason     TEXT,
    status     TEXT    NOT NULL DEFAULT 'booked'
               CHECK (status IN ('booked', 'cancelled', 'completed')),
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- A slot can only hold one active booking (stops double-booking at the database level)
CREATE UNIQUE INDEX one_booking_per_slot
    ON appointments (doctor_id, appt_date, start_time)
    WHERE status = 'booked';
