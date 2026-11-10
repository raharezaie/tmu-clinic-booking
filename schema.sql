-- D1: User DB
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    UNIQUE,   -- login email; NULL only for walk-in guests
    student_id    TEXT,
    password_hash TEXT    NOT NULL, -- '!' for guests, which never matches a password
    role          TEXT    NOT NULL CHECK (role IN ('patient', 'admin', 'doctor', 'kiosk', 'guest')),
    guest_email   TEXT,             -- the email a walk-in guest typed in (not unique, not a login)
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (email IS NOT NULL OR role = 'guest')
);

-- D2: Doctor Sched DB
CREATE TABLE doctors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name  TEXT NOT NULL,
    specialty  TEXT NOT NULL,
    department TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    user_id    INTEGER UNIQUE REFERENCES users(id)   -- the doctor's login, if they have one
);

-- One-time sign-up links staff send to doctors (only a hash of the token is stored)
CREATE TABLE doctor_invites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id  INTEGER NOT NULL REFERENCES doctors(id),
    email      TEXT    NOT NULL,
    token_hash TEXT    NOT NULL UNIQUE,
    expires_at TEXT    NOT NULL,   -- 'YYYY-MM-DD HH:MM:SS'
    used_at    TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE doctor_schedules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id    INTEGER NOT NULL REFERENCES doctors(id),
    weekday      INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),  -- 0 = Monday
    start_time   TEXT    NOT NULL,                                   -- 'HH:MM'
    end_time     TEXT    NOT NULL,
    slot_minutes INTEGER NOT NULL DEFAULT 30
);

-- Days a doctor is away (vacation, sick day); no slots are offered that day
CREATE TABLE doctor_time_off (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    off_date  TEXT    NOT NULL,   -- 'YYYY-MM-DD'
    reason    TEXT,
    UNIQUE (doctor_id, off_date)
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
               CHECK (status IN ('booked', 'cancelled', 'completed', 'no_show')),
    cancelled_by  TEXT CHECK (cancelled_by IN ('patient', 'clinic')),
    cancel_reason TEXT,   -- required when the clinic cancels; shown to the patient
    source     TEXT    NOT NULL DEFAULT 'booked' CHECK (source IN ('booked', 'walk_in')),
    arrived_at TEXT,      -- when a booked patient checked in (walk-ins: when they were called)
    slot_released_at TEXT, -- a late no-show whose slot was given to someone else
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Doctor's notes on a completed visit. Kept apart from appointments so only the pages
-- that need them ever read them. private_note is doctor-only; shared_note is shown to the patient.
CREATE TABLE visit_notes (
    appointment_id INTEGER PRIMARY KEY REFERENCES appointments(id),
    private_note   TEXT,
    shared_note    TEXT,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Walk-in queue: one line per specialty, first come first served. Being called turns
-- the entry into an appointment (source = 'walk_in') in a free slot.
CREATE TABLE walk_ins (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),   -- a patient or a guest
    specialty      TEXT    NOT NULL,
    reason         TEXT,
    visit_date     TEXT    NOT NULL,   -- 'YYYY-MM-DD'
    checked_in_at  TEXT    NOT NULL,   -- 'YYYY-MM-DD HH:MM:SS'
    status         TEXT    NOT NULL DEFAULT 'waiting'
                   CHECK (status IN ('waiting', 'called', 'left', 'removed', 'closed')),
    appointment_id INTEGER REFERENCES appointments(id),
    ended_at       TEXT,
    end_reason     TEXT
);

-- Someone can only be waiting in one queue at a time
CREATE UNIQUE INDEX one_wait_per_person ON walk_ins (user_id) WHERE status = 'waiting';

-- A slot can only hold one active booking (stops double-booking at the database level)
CREATE UNIQUE INDEX one_booking_per_slot
    ON appointments (doctor_id, appt_date, start_time)
    WHERE status = 'booked';
