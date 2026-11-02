# TMU Health Booking

A Flask + SQLite web app for the TMU clinic. Sprint 1 covered the five cards on the board:

| Sprint 1 card | Where it lives | DFD link |
|---|---|---|
| Authentication (backend) | `auth.py`: password hashing, sessions, role checks, CSRF protection | 1.0 Authenticate User, D1 User DB |
| Patient registration and login | `/register`, `/login` (requires an @torontomu.ca email and a 9-digit student number) | E1, 1.0, D1 |
| Clinic admin registration and login | `/admin/register` (requires the staff invite code), `/login` | E2, 1.0, D1 |
| Appointment booking (simple version) | `/book`, `/appointments` in `booking.py`, slot logic in `scheduling.py` | 2.0 Search Availability, 3.0 Book Appointment, D2, D3 |
| Clinic admin dashboard (simple version) | `/admin/dashboard` in `admin.py` | 4.0 Admin Dashboard, D3 |

Since then, the **full clinic admin dashboard** has been added:

| Feature | Where it lives |
|---|---|
| Manage appointments: mark completed / no-show, cancel, book for a patient | `/admin/dashboard`, `/admin/book` in `admin.py` |
| Manage doctors: add, edit, deactivate | `/admin/doctors` in `doctors_admin.py` |
| Edit schedules: weekly shifts and days off | `/admin/doctors/<id>` in `doctors_admin.py` |
| Patient lookup and visit history | `/admin/patients` in `reports.py` |
| Reports over a date range, by doctor and specialty | `/admin/reports` in `reports.py` |

Staff can't make a schedule change that would leave a booked patient without a doctor (deactivating, removing a shift, or adding time off). The app lists the affected appointments so staff can cancel or rebook them first.

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

To wipe all accounts and bookings and start fresh (also needed once if your `clinic.db` was created before the full admin dashboard, since the tables changed):

```bash
flask --app app init-db
```

## Try it out

1. **Patient:** Go to "Create account", register with any `name@torontomu.ca` email and a 9-digit student number, log in, then book a time on the Book page. Doctors work Monday to Friday only, so pick a weekday.
2. **Clinic admin:** Go to `/admin/register` (also linked from the login page). The staff invite code for development is `TMU-STAFF-2026`. Log in and the dashboard shows the day's bookings, slots filled per doctor, and cancellations. From there:
   - Mark past visits **Completed** or **No-show**, or **Cancel** upcoming ones.
   - **Doctors**: add a doctor, give them weekly shifts, book days off, or deactivate them.
   - **Patients**: search by name, email or student number, see their history, and **Book** on their behalf.
   - **Reports**: pick a date range to see slots filled, completed visits, no-shows and cancellations by doctor and specialty.

## Project structure

```
app.py          App setup, routes registered, error pages
auth.py         1.0 Authenticate User (register, login, logout, role checks, CSRF)
booking.py      2.0 Search Availability + 3.0 Book Appointment (patient pages)
admin.py        4.0 Admin Dashboard: daily summary, appointment status changes, booking for patients
doctors_admin.py  Staff management of doctors, weekly shifts, and time off (D2)
reports.py      Patient lookup and date-range reports
scheduling.py   Turns doctor shifts into 30-minute slots, removes booked/past/time-off ones; shared booking checks
db.py           Database connection, init-db command, sample doctors
schema.sql      Tables: users (D1), doctors + doctor_schedules + doctor_time_off (D2), appointments (D3)
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
- Doctor accounts and a doctor dashboard
- Walk-in queue
- Rescheduling in one step (today: cancel and rebook) and reminders
- Automated test suite (Sprint 4: Testing)
