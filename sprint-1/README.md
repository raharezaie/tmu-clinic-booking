# TMU Health Booking: Sprint 1

A Flask + SQLite web app for the TMU clinic. Sprint 1 covers the five cards on the board:

| Sprint 1 card | Where it lives | DFD link |
|---|---|---|
| Authentication (backend) | `auth.py`: password hashing, sessions, role checks, CSRF protection | 1.0 Authenticate User, D1 User DB |
| Patient registration and login | `/register`, `/login` (requires an @torontomu.ca email and a 9-digit student number) | E1, 1.0, D1 |
| Clinic admin registration and login | `/admin/register` (requires the staff invite code), `/login` | E2, 1.0, D1 |
| Appointment booking (simple version) | `/book`, `/appointments` in `booking.py`, slot logic in `scheduling.py` | 2.0 Search Availability, 3.0 Book Appointment, D2, D3 |
| Clinic admin dashboard (simple version) | `/admin/dashboard` in `admin.py` | 4.0 Admin Dashboard, D3 |

## Run it

You need Python 3.10 or newer.

```bash
cd tmu_clinic
python -m venv venv
# Windows: venv\Scripts\activate    Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Open http://127.0.0.1:5000. The database file `clinic.db` is created on first run with five sample doctors and their weekly shifts.

To wipe all accounts and bookings and start fresh:

```bash
flask --app app init-db
```

## Try it out

1. **Patient:** Go to "Create account", register with any `name@torontomu.ca` email and a 9-digit student number, log in, then book a time on the Book page. Doctors work Monday to Friday only, so pick a weekday.
2. **Clinic admin:** Go to `/admin/register` (also linked from the login page). The staff invite code for development is `TMU-STAFF-2026`. Log in and the dashboard shows the day's bookings, slots filled per doctor, and cancellations.

## Project structure

```
app.py          App setup, routes registered, error pages
auth.py         1.0 Authenticate User (register, login, logout, role checks, CSRF)
booking.py      2.0 Search Availability + 3.0 Book Appointment (patient pages)
admin.py        4.0 Admin Dashboard
scheduling.py   Turns doctor shifts into 30-minute slots, removes booked/past ones
db.py           Database connection, init-db command, sample doctors
schema.sql      Tables: users (D1), doctors + doctor_schedules (D2), appointments (D3)
templates/      HTML pages (Jinja)
static/         style.css
```

## What Sprint 1 already handles

- Passwords are stored hashed, never in plain text.
- Patients can't open the admin dashboard and admins can't book (returns "No access").
- A slot can only be booked once, enforced by a unique index in the database, so two students clicking the same time at once can't both get it.
- The server re-checks every booking: the slot must exist in the doctor's schedule, be in the future, and be within the next 30 days.
- Patients can cancel their own upcoming appointments, and the slot reopens.
- Every form has a CSRF token.

## Settings

| Variable | Default | Change before deploying |
|---|---|---|
| `SECRET_KEY` | `dev-only-change-me` | Yes, set a long random value |
| `ADMIN_INVITE_CODE` | `TMU-STAFF-2026` | Yes |

## Left for later sprints

- Email verification of @torontomu.ca addresses (Sprint 1 checks the format only)
- Admin tools to add doctors and edit schedules (Sprint 1 uses the sample doctors in `db.py`)
- Rescheduling, reminders, marking visits completed, and richer dashboard reports
- Automated test suite (Sprint 4: Testing)
